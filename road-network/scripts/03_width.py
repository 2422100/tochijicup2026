# -*- coding: utf-8 -*-
"""
道幅推定（ラスター細線化方式）

考え方（QCで確認済み）:
  基盤地図情報の道路縁(RdEdg)をpolygonizeすると得られるのは「街区」であり、
  道路はその隙間である。したがって
      道路空間 = 区ポリゴン − 街区ポリゴン群
  として道路空間を作り、それをラスタライズして
      - 距離変換(EDT)      → 各画素の道路中心までの距離 = 局所半幅
      - skeletonize        → 中心線
  から中心線ベクトルと局所道幅を得る。

非道路（河川・鉄道敷地・大規模敷地の隙間）の除去:
  1) 水部ポリゴン(WA)を差し引く
  2) 道路縁から ROAD_NEAR_M 以内の画素のみ道路とみなす
  3) 局所道幅が MAX_WIDTH_M を超える画素は非道路として除外

出力:
  02_processed/road_space{suffix}.parquet   道路空間ポリゴン（可視化用）
  03_network/centerlines{suffix}.parquet    中心線（width_m 付き, ルーティング元データ）

使い方:
  python 03_width.py --ward 荒川区     # 1区（検証）
  python 03_width.py                   # 23区すべて（区ごとに逐次・再開可）
"""
import argparse, os, glob
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, box
from shapely.ops import polygonize, unary_union, linemerge
from scipy import ndimage as ndi
from skimage.morphology import skeletonize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "02_processed")
NET = os.path.join(ROOT, "03_network")
os.makedirs(NET, exist_ok=True)

PX = 1.0              # ラスター解像度 [m/px]
                      # 0.5mでも動くが23区分では中心線が1千万本規模になり非実用。
                      # 距離変換は実数を返すため、1m格子でも道幅の分解能は保たれる。
ROAD_NEAR_M = 25.0    # 道路縁からこの距離以内のみ道路とみなす
BRIDGE_KEEP_M = 6.0   # 水部でも道路縁のこの距離以内は残す（橋の分断防止）
TILE_VERSION = 2      # タイルキャッシュの世代。処理を変えたら上げること
                      #   v2: 橋の保護(BRIDGE_KEEP_M)を追加
TAG = ""              # --tag で指定。タイルキャッシュの識別子
FORCE = False         # --force で立てる。特定の区だけ作り直したいとき用
                      # （区界を更新した区は、世代を上げずにここで無効化する）
MAX_WIDTH_M = 50.0    # これを超える幅の空間は非道路（河川敷・広場等）
MIN_AREA_M2 = 20.0    # 極小の道路空間は除去
TILE_M = 2000.0       # ラスター処理のタイル幅 [m]
TILE_PAD_M = 60.0     # タイル境界の重なり（細線化の端効果対策）


# ---------------------------------------------------------------- 道路空間

def build_road_space(edges, ward_geom, water=None):
    """区ポリゴンから街区を差し引いて道路空間ポリゴンを作る"""
    lines = unary_union(edges.geometry.values)
    blocks = [p for p in polygonize(lines) if not p.is_empty]
    print(f"  街区ポリゴン: {len(blocks)}  面積 {sum(p.area for p in blocks)/1e6:.2f} km2",
          flush=True)
    build_road_space.blocks = blocks       # 呼び出し側でラスター処理に再利用
    space = ward_geom.difference(unary_union(blocks).buffer(0))
    if water is not None and len(water):
        space = space.difference(unary_union(water.geometry.values).buffer(0))
    # ※「道路縁近傍のみ採用」はタイル内のラスター処理で行う（巨大バッファ回避）
    parts = [g for g in getattr(space, "geoms", [space])
             if g.geom_type == "Polygon" and g.area >= MIN_AREA_M2]
    gdf = gpd.GeoDataFrame(geometry=parts, crs=edges.crs)
    print(f"  道路空間: {len(gdf)} parts  面積 {gdf.area.sum()/1e6:.2f} km2", flush=True)
    return gdf


# ---------------------------------------------------------------- ラスター

def _rasterize(geoms, minx, miny, nx, ny):
    """shapelyポリゴン群を bool 配列へ（matplotlib非依存の単純スキャン）"""
    from rasterio.features import rasterize as rio_rasterize
    from rasterio.transform import from_origin
    tr = from_origin(minx, miny + ny * PX, PX, PX)
    arr = rio_rasterize(((g, 1) for g in geoms), out_shape=(ny, nx),
                        transform=tr, fill=0, dtype="uint8")
    return arr.astype(bool), tr


def skeleton_to_lines(skel, width_px, ox, oy_top, core_bounds):
    """細線化ラスター → width_m 付き線分。numpyで一括処理（ループ禁物）"""
    if not skel.any():
        return None
    w_m = width_px * (2 * PX)          # 画素ごとの推定道幅[m]
    pieces = []
    # 重複を避けるため 4方向のみ（右・下・右下・左下）
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        a = skel
        b = np.roll(np.roll(skel, -dy, axis=0), -dx, axis=1)
        # ロールの巻き込みを無効化
        if dy: b[-dy:, :] = False
        if dx > 0: b[:, -dx:] = False
        elif dx < 0: b[:, :(-dx)] = False
        yy, xx = np.nonzero(a & b)
        if len(yy) == 0:
            continue
        wa = w_m[yy, xx]
        wb = w_m[yy + dy, xx + dx]
        pieces.append((yy, xx, np.full(len(yy), dy), np.full(len(yy), dx),
                       (wa + wb) / 2.0))
    if not pieces:
        return None
    yy = np.concatenate([p[0] for p in pieces])
    xx = np.concatenate([p[1] for p in pieces])
    dys = np.concatenate([p[2] for p in pieces])
    dxs = np.concatenate([p[3] for p in pieces])
    ww = np.concatenate([p[4] for p in pieces])

    x0 = ox + (xx + 0.5) * PX
    y0 = oy_top - (yy + 0.5) * PX
    x1 = ox + (xx + dxs + 0.5) * PX
    y1 = oy_top - (yy + dys + 0.5) * PX

    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    bx0, by0, bx1, by1 = core_bounds
    keep = (ww <= MAX_WIDTH_M) & (cx >= bx0) & (cx < bx1) & (cy >= by0) & (cy < by1)
    if not keep.any():
        return None
    from shapely import linestrings
    n = int(keep.sum())
    coords = np.empty((n * 2, 2))
    coords[0::2, 0] = x0[keep]; coords[0::2, 1] = y0[keep]
    coords[1::2, 0] = x1[keep]; coords[1::2, 1] = y1[keep]
    geoms = linestrings(coords, indices=np.repeat(np.arange(n), 2))
    return geoms, np.round(ww[keep], 1)


def _readable(path):
    """途中終了で切れたparquetを『無い』扱いにするための健全性チェック"""
    if not os.path.exists(path):
        return False
    try:
        import pyarrow.parquet as pq
        pq.ParquetFile(path)     # フッタだけ読む（軽い）
        return True
    except Exception:
        return False


def _atomic_to_parquet(gdf, path):
    """一時ファイルへ書いてからrenameし、中断による破損を防ぐ"""
    tmp = path + ".tmp"
    gdf.to_parquet(tmp)
    os.replace(tmp, path)


def _empty(crs):
    return gpd.GeoDataFrame({"width_m": np.array([], dtype=float)},
                            geometry=[], crs=crs)


def _one_tile(x0, y0, blocks_gdf, sidx, edges, eidx, crs, water=None, widx=None):
    """1タイル分の中心線を返す（空なら空のGeoDataFrame）

    道路空間そのものは巨大な少数ポリゴンなので、タイルごとにラスタライズすると
    毎回全頂点を走査して非常に遅い。代わりに『街区』（小さく数が多い＝空間索引が
    効く）をラスタライズして反転させ、道路空間マスクを得る。
    """
    tile = box(x0 - TILE_PAD_M, y0 - TILE_PAD_M,
               x0 + TILE_M + TILE_PAD_M, y0 + TILE_M + TILE_PAD_M)
    bx0, by0 = x0 - TILE_PAD_M, y0 - TILE_PAD_M
    nx = ny = int((TILE_M + 2 * TILE_PAD_M) / PX)

    # 道路縁が無いタイルは道路なし
    ecand = edges.iloc[list(eidx.intersection(tile.bounds))]
    if not len(ecand):
        return _empty(crs)
    # 距離変換より、バッファ済みジオメトリのラスタライズの方が速い
    near, _ = _rasterize(list(ecand.geometry.buffer(ROAD_NEAR_M)), bx0, by0, nx, ny)

    bcand = blocks_gdf.iloc[list(sidx.intersection(tile.bounds))]
    bmask, _ = _rasterize(list(bcand.geometry), bx0, by0, nx, ny) if len(bcand) \
        else (np.zeros((ny, nx), bool), None)

    mask = (~bmask) & near                       # 街区でない かつ 道路縁近傍
    if water is not None and widx is not None:
        wcand = water.iloc[list(widx.intersection(tile.bounds))]
        if len(wcand):
            wmask, _ = _rasterize(list(wcand.geometry), bx0, by0, nx, ny)
            # 橋を消さないための保護。基盤地図情報では橋の上にも道路縁が引かれて
            # いるので、道路縁のごく近傍(BRIDGE_KEEP_M)は水部でも道路として残す。
            # これをしないと運河・河川のたびにネットワークが分断され、
            # 江東区では最大連結成分が全ノードの21%まで落ちる。
            keep, _ = _rasterize(
                list(ecand.geometry.buffer(BRIDGE_KEEP_M)), bx0, by0, nx, ny)
            mask &= ~(wmask & ~keep)
    if not mask.any():
        return _empty(crs)
    dist = ndi.distance_transform_edt(mask)      # px 単位の内接半径
    skel = skeletonize(mask)
    res = skeleton_to_lines(skel, dist, bx0, by0 + ny * PX,
                            (x0, y0, x0 + TILE_M, y0 + TILE_M))
    if res is None:
        return _empty(crs)
    geoms_out, widths = res
    return gpd.GeoDataFrame({"width_m": widths}, geometry=geoms_out, crs=crs)


def centerlines_for(bounds, crs, blocks_gdf, clip_geom=None, edges=None,
                    water=None, cache_key=None):
    """街区＋道路縁 → 道路中心線(width_m付き)。タイル分割・タイル単位で再開可"""
    minx, miny, maxx, maxy = bounds
    tdir = os.path.join(NET, "_tiles")
    os.makedirs(tdir, exist_ok=True)
    paths, made = [], 0
    nxt = int(np.ceil((maxx - minx) / TILE_M))
    nyt = int(np.ceil((maxy - miny) / TILE_M))
    sidx = blocks_gdf.sindex
    eidx = edges.sindex
    widx = water.sindex if water is not None and len(water) else None
    for ti in range(nxt):
        for tj in range(nyt):
            x0 = minx + ti * TILE_M
            y0 = miny + tj * TILE_M
            tpath = os.path.join(
                tdir, f"{cache_key}_px{PX}v{TILE_VERSION}{TAG}_{ti}_{tj}.parquet")
            paths.append(tpath)
            if _readable(tpath):
                continue                      # 既存タイルはここでは読まない（重いため）
            g = _one_tile(x0, y0, blocks_gdf, sidx, edges, eidx, crs,
                          water=water, widx=widx)
            _atomic_to_parquet(g, tpath)      # 空でも書いて再計算を防ぐ
            made += 1
    if made:
        print(f"  タイル {made} 枚生成 / 全 {len(paths)} 枚", flush=True)
    missing = [p for p in paths if not _readable(p)]
    if missing:
        return None                           # 未完 → 次回の実行で続きから
    # --- 全タイルが揃ったのでまとめる
    recs = [gpd.read_parquet(p) for p in paths]
    recs = [g for g in recs if len(g)]
    if not recs:
        return _empty(crs)
    # 区境での再クリップはしない：道路縁を区+50mで絞っているため、はみ出しは
    # 隣接区との境界道路のみ。数百万件への空間演算はコストに見合わない。
    return gpd.GeoDataFrame(pd.concat(recs, ignore_index=True),
                            crs=crs).reset_index(drop=True)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ward", default=None, help="区名（省略時は23区すべて）")
    ap.add_argument("--stage", default="all",
                    choices=["blocks", "space", "lines", "all"],
                    help="blocks=街区のみ(軽い) / space=道路空間ポリゴン(可視化用) / "
                         "lines=中心線 / all=すべて")
    ap.add_argument("--skip-done", action="store_true", help="出力済みを飛ばす")
    ap.add_argument("--force", action="store_true",
                    help="区ごとのキャッシュ(_edges_*)を作り直す（区界を更新したとき用）")
    ap.add_argument("--tag", default="",
                    help="タイルキャッシュの識別子。区界を更新した区を作り直すとき、"
                         "全体のTILE_VERSIONを上げずにその区だけ無効化できる")
    args = ap.parse_args()
    global FORCE, TAG
    FORCE = args.force
    TAG = args.tag

    wards = gpd.read_parquet(os.path.join(PROC, "wards23.parquet"))
    targets = [args.ward] if args.ward else list(wards["ward"])

    # road_edges は区キャッシュが全部揃っていれば読まない（起動を軽くする）
    need_all = args.stage in ("blocks", "space", "all") or args.force or \
        any(not os.path.exists(os.path.join(PROC, f"_edges_{w}.parquet"))
            for w in targets)
    edges_all = gpd.read_parquet(os.path.join(PROC, "_rdedg")) \
        if need_all else None
    wat_all = None
    if args.stage in ("blocks", "space", "all"):
        wpath = os.path.join(PROC, "water_areas.parquet")
        wat_all = gpd.read_parquet(wpath) if os.path.exists(wpath) else None

    for ward in targets:
        sp = os.path.join(PROC, f"road_space_{ward}.parquet")
        cp = os.path.join(NET, f"centerlines_{ward}.parquet")
        wg = wards[wards["ward"] == ward].geometry.union_all()

        # --- stage 1: 道路空間
        bp = os.path.join(PROC, f"blocks_{ward}.parquet")

        # --- stage 0: 街区のみ（polygonizeだけ。差分演算をしないので軽い）
        if args.stage == "blocks":
            if args.skip_done and os.path.exists(bp):
                print(f"skip {ward} blocks (done)", flush=True); continue
            edges = gpd.clip(edges_all, wg)
            if wat_all is not None:
                gpd.clip(wat_all, wg).to_parquet(
                    os.path.join(PROC, f"_water_{ward}.parquet"))
            lines = unary_union(edges.geometry.values)
            blocks = [p for p in polygonize(lines) if not p.is_empty]
            gpd.GeoDataFrame(geometry=blocks, crs=edges.crs).to_parquet(bp)
            print(f"[{ward}] 街区 {len(blocks)}", flush=True)
            continue

        if args.stage in ("space", "all") and \
                not (args.skip_done and os.path.exists(sp) and os.path.exists(bp)):
            edges = gpd.clip(edges_all, wg)
            water = gpd.clip(wat_all, wg) if wat_all is not None else None
            if water is not None:
                water.to_parquet(os.path.join(PROC, f"_water_{ward}.parquet"))
            print(f"[{ward}] 道路縁 {len(edges)} 本", flush=True)
            space = build_road_space(edges, wg, water)
            space["ward"] = ward
            space.to_parquet(sp)
            gpd.GeoDataFrame(geometry=build_road_space.blocks,
                             crs=space.crs).to_parquet(bp)

        # --- stage 2: 中心線
        if args.stage in ("lines", "all"):
            # 世代マーカで判定する。処理を変えて TILE_VERSION を上げたら、
            # 出力ファイルが残っていても作り直す必要があるため。
            vdir = os.path.join(NET, f"_lines_v{TILE_VERSION}{TAG}")
            os.makedirs(vdir, exist_ok=True)
            vmark = os.path.join(vdir, f"{ward}.ok")
            if args.skip_done and os.path.exists(vmark) and _readable(cp):
                continue
            # 範囲は街区から取る（road_space は可視化専用で、無くても中心線は作れる）
            blocks = gpd.read_parquet(bp)
            # 区ごとの道路縁はキャッシュ（毎回のclipは重い）
            ep = os.path.join(PROC, f"_edges_{ward}.parquet")
            if os.path.exists(ep) and not FORCE:
                edges_w = gpd.read_parquet(ep)
            else:
                edges_w = gpd.clip(edges_all, wg.buffer(50))
                edges_w.to_parquet(ep)
            wp = os.path.join(PROC, f"_water_{ward}.parquet")
            water_w = gpd.read_parquet(wp) if os.path.exists(wp) else None
            cl = centerlines_for(blocks.total_bounds, blocks.crs, blocks,
                                 clip_geom=wg, edges=edges_w, water=water_w,
                                 cache_key=ward)
            if cl is None:
                print(f"[{ward}] タイル未完 → 再実行で続行", flush=True)
                continue
            cl["ward"] = ward
            _atomic_to_parquet(cl, cp)
            open(vmark, "w").close()
            med = cl["width_m"].median() if len(cl) else float("nan")
            print(f"[{ward}] 中心線 {len(cl)} セグメント  道幅中央値 {med:.1f}m",
                  flush=True)


if __name__ == "__main__":
    main()
