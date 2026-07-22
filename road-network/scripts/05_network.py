# -*- coding: utf-8 -*-
"""
避難ルーティング用ネットワーク構築

入力: 03_network/centerlines_{区}.parquet
  中心線は1m格子上の2点線分の集合で、位相を持たない（1区あたり数十万〜180万本）。

処理:
  stage=topology
    線分の端点を格子座標の整数キーに符号化してノード化し、次数を数える。
    次数2のノード（通過点）だけからなる連結成分＝1本の街路とみなし、
    その両端の交差点ノードを結ぶ1本のエッジに縮約する。
    → length_m（総延長）、width_m（長さ重み付き平均）を持つエッジ集合になる。
    ※ networkxに全線分を入れるとメモリが足りないため、
      scipy.sparse.csgraph の連結成分でベクトル化して処理する。

  stage=cost
    dist_to_bld    エッジ中点から最近傍建物までの距離（沿道の張り出し余地）
    barrier_cross  水涯線・軌道と交差するエッジ（橋・踏切の情報が無いため要注意）
    slope_pct      DEM未投入のため 0.0 のプレースホルダ
    cost_general / cost_wheelchair を config_weights.json の重みで合成

出力:
  03_network/edges_{区}.parquet   u, v, length_m, width_m, geometry, cost_*
  03_network/nodes_{区}.parquet   node_id, geometry
  03_network/network_{区}.graphml （--graphml 指定時のみ。大きい区は重い）

使い方:
  python 05_network.py --stage topology --skip-done
  python 05_network.py --stage cost --skip-done
"""
import argparse, json, os
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from scipy import sparse
from scipy.sparse import csgraph

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "02_processed")
NET = os.path.join(ROOT, "03_network")
CFG = os.path.join(ROOT, "scripts", "config_weights.json")

GRID = 2          # 座標を 1/GRID m 単位の整数に量子化（中心線は0.5mオフセットの1m格子）
SHIFT = 1_000_000  # 負座標を正にするオフセット
MUL = 10_000_000   # キー化の桁


# ---------------------------------------------------------------- 共通

def _readable(path):
    if not os.path.exists(path):
        return False
    try:
        import pyarrow.parquet as pq
        pq.ParquetFile(path)
        return True
    except Exception:
        return False


def _atomic_to_parquet(gdf, path):
    tmp = path + ".tmp"
    gdf.to_parquet(tmp)
    os.replace(tmp, path)


# ---------------------------------------------------------------- 位相構築

def build_topology(cl):
    """1m格子の線分集合 → (nodes_gdf, edges_gdf)"""
    coords = shapely.get_coordinates(cl.geometry.values)      # (2N, 2)
    n_seg = len(cl)
    assert len(coords) == 2 * n_seg, "全て2点線分である前提"

    # 端点を整数キーに（浮動小数の誤差でノードが割れないように量子化する）
    xi = np.rint(coords[:, 0] * GRID).astype(np.int64) + SHIFT
    yi = np.rint(coords[:, 1] * GRID).astype(np.int64) + SHIFT
    key = xi * MUL + yi

    uniq, inv = np.unique(key, return_inverse=True)
    n_node = len(uniq)
    u = inv[0::2]
    v = inv[1::2]

    seg_len = shapely.length(cl.geometry.values)
    width = cl["width_m"].to_numpy(dtype=float)

    # --- 対角ショートカットの除去
    # ラスター細線化の階段状パターンでは、斜めの線が
    #   (x,y)-(x,y+1)-(x+1,y+1) という直角の並びと (x,y)-(x+1,y+1) の対角線の
    # 両方を持ち、三角形ができてしまう。すると通過点のはずの画素が次数3〜4に
    # なり、街路がすべて1画素刻みに分断される（実測: エッジ中央値1.4m）。
    # 直角の迂回路が存在する対角線は冗長なので落とす。
    ux, uy = xi[0::2], yi[0::2]
    vx, vy = xi[1::2], yi[1::2]
    is_diag = (np.abs(ux - vx) > 0) & (np.abs(uy - vy) > 0)
    corner_a = ux * MUL + vy          # (u.x, v.y)
    corner_b = vx * MUL + uy          # (v.x, u.y)
    has_corner = np.isin(corner_a, uniq) | np.isin(corner_b, uniq)
    drop_diag = is_diag & has_corner

    # 自己ループ（同一ノードに戻る線分）と冗長な対角線を捨てる
    ok = (u != v) & ~drop_diag
    u, v, seg_len, width = u[ok], v[ok], seg_len[ok], width[ok]
    seg_idx = np.nonzero(ok)[0]
    print(f"    対角ショートカット除去: {int(drop_diag.sum()):,} / {n_seg:,}",
          flush=True)

    # 次数（無向）
    deg = np.bincount(u, minlength=n_node) + np.bincount(v, minlength=n_node)
    is_chain = deg == 2                       # 通過点
    is_junc = ~is_chain                       # 交差点・行き止まり

    # --- 通過点だけの部分グラフで連結成分 = 街路1本の内部
    both_chain = is_chain[u] & is_chain[v]
    if both_chain.any():
        g = sparse.coo_matrix(
            (np.ones(both_chain.sum(), np.int8), (u[both_chain], v[both_chain])),
            shape=(n_node, n_node)).tocsr()
        ncomp, labels = csgraph.connected_components(g, directed=False)
    else:
        labels = np.full(n_node, -1, np.int64)

    # --- 各線分を街路(chain)に割り当てる
    chain = np.full(len(u), -1, np.int64)
    chain[is_chain[u]] = labels[u[is_chain[u]]]
    m = (chain < 0) & is_chain[v]
    chain[m] = labels[v[m]]
    # 交差点同士を直結する線分は、それ自体で1本の街路
    solo = chain < 0
    if solo.any():
        chain[solo] = labels.max() + 1 + np.arange(solo.sum())

    # --- 街路ごとに集計
    order = np.argsort(chain, kind="stable")
    cs = chain[order]
    starts = np.searchsorted(cs, np.unique(cs))
    lengths = np.add.reduceat(seg_len[order], starts)
    wsum = np.add.reduceat((seg_len * width)[order], starts)
    widths = wsum / np.maximum(lengths, 1e-9)

    # --- 街路の端点（交差点ノード）を拾う
    ju = np.where(is_junc[u], u, -1)
    jv = np.where(is_junc[v], v, -1)
    # 端点候補を (chain, node) の組にして重複を除く
    pairs = np.concatenate([
        np.stack([chain, ju], 1)[ju >= 0],
        np.stack([chain, jv], 1)[jv >= 0]])
    pairs = np.unique(pairs, axis=0)
    # chainごとに最大2つ取る
    ends = {}
    for c, nd in pairs:
        ends.setdefault(c, []).append(nd)

    uniq_chain = np.unique(cs)
    us, vs, keep = [], [], []
    for i, c in enumerate(uniq_chain):
        e = ends.get(c)
        if not e or len(e) < 2:
            continue          # 閉ループ等（交差点に接続しない）は落とす
        us.append(e[0]); vs.append(e[1]); keep.append(i)
    keep = np.array(keep, dtype=np.int64)
    if len(keep) == 0:
        return None, None

    # --- ジオメトリ（街路ごとの線分をまとめてline_mergeで1本にする）
    seg_geom = cl.geometry.values[seg_idx][order]
    grp = np.searchsorted(np.unique(cs), cs)
    mls = shapely.multilinestrings(seg_geom, indices=grp)
    merged = shapely.line_merge(mls)
    merged = shapely.simplify(merged, 0.5)

    edges = gpd.GeoDataFrame({
        "u": np.array(us, np.int64),
        "v": np.array(vs, np.int64),
        "length_m": np.round(lengths[keep], 2),
        "width_m": np.round(widths[keep], 1),
    }, geometry=merged[keep], crs=cl.crs)

    node_x = (uniq // MUL - SHIFT) / GRID
    node_y = (uniq % MUL - SHIFT) / GRID
    used = np.unique(np.concatenate([edges["u"].values, edges["v"].values]))
    nodes = gpd.GeoDataFrame({"node_id": used},
                             geometry=shapely.points(node_x[used], node_y[used]),
                             crs=cl.crs)
    return nodes, edges


# ---------------------------------------------------------------- コスト

def narrow_penalty(width_m, wheelchair=False):
    """4m未満で急増する狭隘ペナルティ (0〜)"""
    w = np.where(np.isnan(width_m), 4.0, width_m)   # 欠損は4m仮定
    base = np.clip((4.0 - w) / 4.0, 0, 1) ** 2 * 3.0
    if wheelchair:
        base = base * 2.5 + np.where(w < 1.5, 10.0, 0.0)
    return base


def blockage_risk(width_m, bld_density, cfg):
    """地震時の倒壊閉塞リスク (0〜1)

    考え方: 沿道建物が倒壊すると道路に瓦礫が出る。瓦礫の到達幅より道路幅が
    狭ければ閉塞する。瓦礫の到達幅は建物の高さに比例するが高さデータが無いため、
    建蔽率(250mメッシュ建物密度)を代理変数として使う。

    ※ DEBRIS_MAX_M と DENSITY_REF は**キャリブレーションされていない仮定値**。
      実務で使うなら東京都の地域危険度調査などで較正すること。
    """
    dmax = float(cfg.get("debris_max_m", 12.0))
    dref = float(cfg.get("density_ref", 0.45))
    dens = np.nan_to_num(np.asarray(bld_density, dtype=float), nan=0.0)
    debris = dmax * np.clip(dens / dref, 0.0, 1.5)      # 瓦礫の到達幅[m]
    w = np.where(np.isnan(width_m), 4.0, width_m)
    with np.errstate(divide="ignore", invalid="ignore"):
        risk = np.where(debris > 0, (debris - w) / debris, 0.0)
    return np.clip(risk, 0.0, 1.0)


def compute_costs(edges, cfg):
    """空間結合はやり直さず、重みだけからコスト列を作り直す。
    config_weights.json をいじって再評価する用途にも使う（--stage recost）。"""
    L = edges["length_m"].to_numpy(dtype=float)
    w = edges["width_m"].to_numpy(dtype=float)
    slope = edges["slope_pct"].to_numpy(dtype=float)
    dens = edges["bld_density"].to_numpy(dtype=float) \
        if "bld_density" in edges.columns else np.zeros(len(edges))
    edges["blockage_risk"] = np.round(blockage_risk(w, dens, cfg), 3)
    blk = edges["blockage_risk"].to_numpy(dtype=float)
    # --- 平常時（倒壊閉塞は含めない）
    edges["cost_general"] = L * (
        1
        + cfg["w1"] * narrow_penalty(w)
        + cfg["w2"] * slope / 10.0
        + cfg["w4"] * 0.0)       # 混雑: 人口データ未取得のため未実装
    edges["cost_wheelchair"] = L * (
        1
        + cfg["w1_wc"] * narrow_penalty(w, wheelchair=True)
        + cfg["w2_wc"] * slope / 10.0)

    # --- 地震時（倒壊閉塞を加算）
    #   平常時のコストに混ぜると「橋を罰して細街路に迂回させた」のと同じ失敗を
    #   繰り返しかねないので、シナリオ別の列として分ける。
    edges["cost_quake"] = L * (
        1
        + cfg["w1"] * narrow_penalty(w)
        + cfg["w2"] * slope / 10.0
        + cfg["w3"] * blk)
    edges["cost_quake_wc"] = L * (
        1
        + cfg["w1_wc"] * narrow_penalty(w, wheelchair=True)
        + cfg["w2_wc"] * slope / 10.0
        + cfg["w3"] * blk)
    # barrier_cross は「平常時のペナルティ」ではなく「橋梁・踏切のフラグ」として扱う。
    #   水部や軌道を横断している道路は定義上そこに橋（または踏切）が架かっており、
    #   むしろ幅の広い幹線であることが多い。当初これを×50で罰したところ、
    #   一般モードの経路が裏の細街路に押し出され、最短距離経路よりも
    #   4m未満を通る距離が増えるという逆効果が実測された（137m→216m）。
    #   橋梁の被災を想定したい場合は bridge_penalty を設定して重み付けする。
    bp = float(cfg.get("bridge_penalty", 0.0))
    if bp:
        edges.loc[edges["barrier_cross"],
                  ["cost_general", "cost_wheelchair",
                   "cost_quake", "cost_quake_wc"]] *= (1.0 + bp)
    return edges


def add_costs(edges, bld, barriers, cfg, dens=None):
    edges = edges.copy()
    edges["slope_pct"] = 0.0        # DEM未投入（§残作業1）

    mid = gpd.GeoDataFrame(
        geometry=edges.geometry.interpolate(0.5, normalized=True), crs=edges.crs)
    if bld is not None and len(bld):
        near = gpd.sjoin_nearest(mid, bld[["geometry"]], how="left",
                                 max_distance=50, distance_col="dist_to_bld")
        near = near[~near.index.duplicated(keep="first")]
        edges["dist_to_bld"] = near["dist_to_bld"].fillna(50.0).values
    else:
        edges["dist_to_bld"] = 50.0

    # 沿道の建蔽率（250mメッシュ）をエッジ中点から取る。倒壊閉塞の推定に使う
    if dens is not None and len(dens):
        j = gpd.sjoin(mid, dens[["bld_density", "geometry"]],
                      how="left", predicate="within")
        j = j[~j.index.duplicated(keep="first")]
        edges["bld_density"] = j["bld_density"].fillna(0.0).values
    else:
        edges["bld_density"] = 0.0

    if barriers is not None and len(barriers):
        j = gpd.sjoin(edges[["geometry"]], barriers[["geometry"]],
                      how="inner", predicate="intersects")
        hit = np.zeros(len(edges), bool)
        hit[np.unique(j.index.values)] = True
        edges["barrier_cross"] = hit
    else:
        edges["barrier_cross"] = False

    return compute_costs(edges, cfg)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ward", default=None)
    ap.add_argument("--stage", default="topology",
                    choices=["topology", "cost", "recost"],
                    help="recost=空間結合をやり直さず重みだけ再計算する")
    ap.add_argument("--skip-done", action="store_true")
    args = ap.parse_args()

    wards = gpd.read_parquet(os.path.join(PROC, "wards23.parquet"))
    targets = [args.ward] if args.ward else list(wards["ward"])

    cfg = bld = barriers = dens = None
    if args.stage == "recost":
        cfg = json.load(open(CFG, encoding="utf-8"))
        for ward in targets:
            fp = os.path.join(NET, f"edges_final_{ward}.parquet")
            if not _readable(fp):
                continue
            e = gpd.read_parquet(fp)
            _atomic_to_parquet(compute_costs(e, cfg), fp)
            print(f"[{ward}] コスト再計算 {len(e):,}", flush=True)
        return

    if args.stage == "cost":
        cfg = json.load(open(CFG, encoding="utf-8"))
        bp = os.path.join(PROC, "barriers.parquet")
        barriers = gpd.read_parquet(bp) if os.path.exists(bp) else None
        dp = os.path.join(PROC, "mesh250_bld_density.parquet")
        dens = gpd.read_parquet(dp) if os.path.exists(dp) else None

    for ward in targets:
        ep = os.path.join(NET, f"edges_{ward}.parquet")
        npth = os.path.join(NET, f"nodes_{ward}.parquet")
        fp = os.path.join(NET, f"edges_final_{ward}.parquet")

        if args.stage == "topology":
            if args.skip_done and os.path.exists(os.path.join(NET,"_topo_v2",ward+".ok")) and _readable(ep):
                continue
            cp = os.path.join(NET, f"centerlines_{ward}.parquet")
            if not _readable(cp):
                print(f"[{ward}] 中心線が無い → skip", flush=True); continue
            cl = gpd.read_parquet(cp)
            nodes, edges = build_topology(cl)
            if edges is None:
                print(f"[{ward}] エッジ0", flush=True); continue
            _atomic_to_parquet(nodes, npth)
            _atomic_to_parquet(edges, ep)
            os.makedirs(os.path.join(NET, "_topo_v2"), exist_ok=True)
            open(os.path.join(NET, "_topo_v2", ward + ".ok"), "w").close()
            print(f"[{ward}] 線分 {len(cl):,} → エッジ {len(edges):,} / "
                  f"ノード {len(nodes):,}  中央値 長さ{edges['length_m'].median():.1f}m "
                  f"幅{edges['width_m'].median():.1f}m", flush=True)

        else:
            if args.skip_done and os.path.exists(os.path.join(NET,"_topo_v2",ward+".cost4")) and _readable(fp):
                continue
            if not _readable(ep):
                print(f"[{ward}] 位相が未作成 → skip", flush=True); continue
            edges = gpd.read_parquet(ep)
            # 建物は区ごとに絞ってから最近傍を取る（全件だと重い）
            bdir = os.path.join(PROC, "_bld")
            b = gpd.read_parquet(bdir, filters=[("ward", "==", ward)]) \
                if os.path.exists(bdir) else None
            out = add_costs(edges, b, barriers, cfg, dens=dens)
            _atomic_to_parquet(out, fp)
            os.makedirs(os.path.join(NET, "_topo_v2"), exist_ok=True)
            open(os.path.join(NET, "_topo_v2", ward + ".cost4"), "w").close()
            print(f"[{ward}] コスト付与 {len(out):,}  "
                  f"障壁交差 {int(out['barrier_cross'].sum()):,}  "
                  f"建物まで中央値 {out['dist_to_bld'].median():.1f}m", flush=True)


if __name__ == "__main__":
    main()
