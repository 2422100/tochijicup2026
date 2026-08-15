# -*- coding: utf-8 -*-
"""
子連れ避難の到達性

  stage=shelters   東京都防災マップの避難所CSV → 23区分をEPSG:6677に投影して保存
  stage=access     区ごとに「最寄り避難所までの所要時間」を全ノードについて計算
  stage=report     区別サマリ + 都全体の調査結果パネル用のJSON

考え方
  避難所を「多始点」にして道路網を逆向きに探索すると、1回のダイクストラで
  全ノードの最寄り避難所と到達コストが得られる。個別の経路探索を繰り返すより
  桁違いに速く、面としての到達性（どこが取り残されるか）が見える。

  経路の選び方（重み）と、その経路を歩いたときの所要時間は別物なので、
  重み cost_stroller* で木を作り、その木に沿って time_min_child を積み上げる。

出力: 03_network/access_{区}.parquet, reports/child_access.csv, reports/child_access.json
"""
import argparse, glob, json, os
import numpy as np
import pandas as pd
import geopandas as gpd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "02_processed")
NET = os.path.join(ROOT, "03_network")
EXT = os.path.join(ROOT, "20_external", "tokyo_child")
REP = os.path.join(ROOT, "reports")
os.makedirs(REP, exist_ok=True)

CRS = 6677
SNAP_MAX_M = 300.0      # これより遠い避難所はネットワークに接続しない


# ------------------------------------------------------------------ 避難所

def stage_shelters():
    """避難所一覧CSV → 23区分のGeoDataFrame

    元CSVは1行目が空で2行目がヘッダ、以降に100万行超の空行が続く
    （Excel書き出しの残骸）。dropna(how='all') で落とす。
    """
    p = os.path.join(EXT, "130001_evacuation_center.csv")
    df = pd.read_csv(p, encoding="cp932", dtype=str, header=1).dropna(how="all")
    df.columns = ["name", "code", "pref", "ward", "addr", "lat", "lon",
                  "ev1f", "slope", "braille", "wc_toilet", "other"]
    df = df[df["ward"].str.endswith("区", na=False)].copy()

    for c in ("ev1f", "slope", "braille", "wc_toilet"):
        df[c] = df[c].notna()

    # ベビーカーで入れるか（バリアフリー属性からの推定）
    #   スロープがある、または避難スペースが1階／エレベータがある、を可とする。
    #   ※元データは「避難所のバリアフリー対応」であって乳幼児対応ではない。
    #     授乳室・おむつ交換台の有無は公開データに無い（§限界）。
    df["stroller_ok"] = df["slope"] | df["ev1f"]

    g = gpd.GeoDataFrame(
        df, geometry=gpd.points_from_xy(df["lon"].astype(float),
                                        df["lat"].astype(float)),
        crs=4326).to_crs(CRS)
    g["sid"] = np.arange(len(g))
    out = os.path.join(PROC, "shelters23.parquet")
    g.to_parquet(out)
    print(f"避難所 {len(g):,} / {g['ward'].nunique()}区  "
          f"スロープ等 {g['slope'].mean()*100:.1f}%  "
          f"EV・1階 {g['ev1f'].mean()*100:.1f}%  "
          f"ベビーカー可(推定) {g['stroller_ok'].mean()*100:.1f}%")
    print("->", out)


# ------------------------------------------------------------------ 到達性

def _accumulate(pred, order, edge_val, n):
    """最短経路木に沿って値を積み上げる（距離の小さい順に1回なめる）"""
    acc = np.full(n, np.inf)
    acc[pred < 0] = 0.0          # 始点（＝避難所ノード）
    for i in order:
        p = pred[i]
        if p < 0:
            continue
        acc[i] = acc[p] + edge_val.get((p, i), edge_val.get((i, p), 0.0))
    return acc


def access_one(ward, shelters):
    ep = os.path.join(NET, f"edges_final_{ward}.parquet")
    npth = os.path.join(NET, f"nodes_{ward}.parquet")
    if not (os.path.exists(ep) and os.path.exists(npth)):
        return None
    e = gpd.read_parquet(ep)
    nd = gpd.read_parquet(npth)
    if "cost_stroller" not in e.columns:
        raise SystemExit(f"[{ward}] cost_stroller が無い。"
                         "先に 05_network.py --stage recost を実行すること")

    nid = nd["node_id"].to_numpy()
    idx = {int(v): i for i, v in enumerate(nid)}
    n = len(nid)

    u = e["u"].map(idx).to_numpy()
    v = e["v"].map(idx).to_numpy()
    ok = ~(pd.isna(u) | pd.isna(v))
    u = u[ok].astype(np.int64); v = v[ok].astype(np.int64)
    t = e["time_min_child"].to_numpy()[ok]

    # 避難所を最寄りノードにスナップ
    s = shelters[shelters["ward"] == ward]
    if not len(s):
        return None
    nn = gpd.sjoin_nearest(s[["sid", "geometry"]], nd[["node_id", "geometry"]],
                           how="inner", max_distance=SNAP_MAX_M,
                           distance_col="snap_m")
    src = np.unique([idx[int(x)] for x in nn["node_id"] if int(x) in idx])
    if not len(src):
        return None

    res = {"ward": ward, "n_nodes": n, "n_shelter": len(s),
           "n_snapped": len(nn), "snap_med_m": float(nn["snap_m"].median())}

    for tag, wcol in (("normal", "cost_stroller"), ("quake", "cost_stroller_quake")):
        w = e[wcol].to_numpy()[ok]
        M = coo_matrix((w, (u, v)), shape=(n, n)).tocsr()
        M = M.maximum(M.T)                      # 無向グラフ
        # min_only=True は (距離, 直前ノード, その点にとっての最寄り始点) を返す
        d, pred, srcof = dijkstra(M, directed=False, indices=src, min_only=True,
                                  return_predecessors=True)
        order = np.argsort(d, kind="stable")
        order = order[np.isfinite(d[order])]
        ev = {}
        for a, b, x in zip(u, v, t):
            k = (a, b)
            if k not in ev or x < ev[k]:
                ev[k] = float(x)
        tmin = _accumulate(pred, order, ev, n)
        nd[f"cost_{tag}"] = d
        nd[f"tmin_{tag}"] = tmin
        nd[f"src_{tag}"] = srcof          # 最寄り避難所のノード番号
        fin = np.isfinite(tmin)
        res[f"cover_{tag}"] = float(100 * fin.mean())
        res[f"tmed_{tag}"] = float(np.median(tmin[fin]))
        res[f"t90_{tag}"] = float(np.percentile(tmin[fin], 90))

    nd["ward"] = ward
    nd.to_parquet(os.path.join(NET, f"access_{ward}.parquet"))
    res["worsen_pct"] = 100 * (res["tmed_quake"] / res["tmed_normal"] - 1)
    print(f"[{ward}] ノード{n:,} 避難所{len(s)}({len(nn)}接続) "
          f"到達率{res['cover_normal']:.1f}% "
          f"中央値 平常{res['tmed_normal']:.1f}分 → 地震{res['tmed_quake']:.1f}分 "
          f"({res['worsen_pct']:+.1f}%)", flush=True)
    return res


def stage_access(wards=None):
    sh = gpd.read_parquet(os.path.join(PROC, "shelters23.parquet"))
    targets = wards or list(gpd.read_parquet(
        os.path.join(PROC, "wards23.parquet"))["ward"])
    rows = [r for r in (access_one(w, sh) for w in targets) if r]
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(REP, "child_access.csv"), index=False)
    print("\n->", os.path.join(REP, "child_access.csv"))
    return df


# ------------------------------------------------------------------ 調査結果

def _read(name):
    return pd.read_csv(os.path.join(EXT, name), encoding="cp932", dtype=str)


def stage_report():
    """福祉局調査（62自治体の集計）を、そのまま読める形のJSONにまとめる

    ※この調査は**自治体名を含まない集計値**なので、区別の地図には使えない。
      「東京都全体で何が足りていないか」を示す文脈情報として扱う。
    """
    def pair(fn, label):
        d = _read(fn)
        r = d.iloc[0]
        # 「ミルク用水」だけ選択肢が あり/水の措置はあり になっている
        no_col = "なし" if "なし" in d.columns else d.columns[2]
        return {"label": label, "yes": int(r["あり"]), "no": int(r[no_col]),
                "total": int(r["合計"]),
                "pct": round(100 * int(r["あり"]) / int(r["合計"]), 1)}

    supplies = [
        ("bousai_tyousa_851_1.csv", "粉ミルク"),
        ("bousai_tyousa_852_1.csv", "アレルギー対応ミルク"),
        ("bousai_tyousa_853_1.csv", "ミルク用の水"),
        ("bousai_tyousa_853_2.csv", "離乳食"),
        ("bousai_tyousa_854_2.csv", "おかゆ"),
        ("bousai_tyousa_855_2.csv", "栄養食品等（妊婦）"),
        ("bousai_tyousa_856_2.csv", "ほ乳びん"),
        ("bousai_tyousa_857_2.csv", "ほ乳びん消毒剤"),
        ("bousai_tyousa_858_2.csv", "紙おむつ"),
        ("bousai_tyousa_859_2.csv", "おしりふき"),
        ("bousai_tyousa_860_2.csv", "乳幼児用衣類"),
        ("bousai_tyousa_861_2.csv", "生理用品"),
        ("bousai_tyousa_862_2.csv", "毛布"),
        ("bousai_tyousa_863_1.csv", "乳幼児用毛布"),
        ("bousai_tyousa_864_1.csv", "ベビーベッド"),
    ]
    out = {"supplies": [], "operation": [], "shelter": None}
    for fn, lab in supplies:
        try:
            out["supplies"].append(pair(fn, lab))
        except Exception as ex:
            print("  skip", fn, ex)
    out["supplies"].sort(key=lambda x: x["pct"])

    out["shelter"] = pair("bousai_tyousa_865_1.csv",
                          "妊産婦・乳幼児を想定した避難所")

    d = _read("bousai_tyousa_866_1.csv")
    for _, r in d.iterrows():
        tot = int(r["合計"])
        out["operation"].append({
            "label": str(r["区分"]).strip(),
            "yes": int(r["あり"]), "considering": int(r["検討中"]),
            "no": int(r["なし"]), "total": tot,
            "pct": round(100 * int(r["あり"]) / tot, 1)})
    out["operation"].sort(key=lambda x: x["pct"])

    p = os.path.join(REP, "child_survey.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("->", p)
    print(f"  妊産婦・乳幼児を想定した避難所がある自治体: "
          f"{out['shelter']['yes']}/{out['shelter']['total']} "
          f"({out['shelter']['pct']}%)")
    print("  備蓄率が低い順:",
          ", ".join(f"{s['label']}{s['pct']}%" for s in out["supplies"][:5]))
    return out


# ------------------------------------------------------------------ メッシュ

MESH_M = 250


def stage_mesh():
    """ノード単位の到達時間を250mメッシュに集約して可視化用JSONにする

    ノードは23区で40万点あり、そのままブラウザに渡せない。
    250m格子の中央値にすると1万セル弱まで落ち、Pagesで配れる大きさになる。
    """
    files = sorted(glob.glob(os.path.join(NET, "access_*.parquet")))
    if not files:
        raise SystemExit("先に --stage access を実行すること")
    cells = {}
    for f in files:
        nd = gpd.read_parquet(f)
        x = nd.geometry.x.to_numpy(); y = nd.geometry.y.to_numpy()
        gi = np.floor(x / MESH_M).astype(int)
        gj = np.floor(y / MESH_M).astype(int)
        d = pd.DataFrame({"gi": gi, "gj": gj,
                          "n": nd["tmin_normal"].to_numpy(),
                          "q": nd["tmin_quake"].to_numpy(),
                          "ward": nd["ward"].to_numpy()})
        d = d[np.isfinite(d["n"]) & np.isfinite(d["q"])]
        g = d.groupby(["gi", "gj"]).agg(n=("n", "median"), q=("q", "median"),
                                        c=("n", "size"), ward=("ward", "first"))
        for (i, j), r in g.iterrows():
            k = (i, j)
            if k not in cells or r["c"] > cells[k]["c"]:
                cells[k] = {"n": r["n"], "q": r["q"], "c": r["c"],
                            "ward": r["ward"]}

    # セル中心をWGS84へ
    xs = np.array([(i + 0.5) * MESH_M for i, j in cells])
    ys = np.array([(j + 0.5) * MESH_M for i, j in cells])
    pt = gpd.GeoSeries(gpd.points_from_xy(xs, ys), crs=CRS).to_crs(4326)

    wards = sorted({c["ward"] for c in cells.values()})
    widx = {w: i for i, w in enumerate(wards)}
    out = {"mesh_m": MESH_M, "wards": wards, "cells": []}
    for (k, v), lon, lat in zip(cells.items(), pt.x, pt.y):
        out["cells"].append([round(lat, 5), round(lon, 5),
                             round(float(v["n"]), 1), round(float(v["q"]), 1),
                             widx[v["ward"]]])

    sh = gpd.read_parquet(os.path.join(PROC, "shelters23.parquet")).to_crs(4326)
    out["shelters"] = [[round(g.y, 5), round(g.x, 5), nm,
                        int(sl), int(ev), int(wc)]
                       for g, nm, sl, ev, wc in zip(
                           sh.geometry, sh["name"], sh["slope"],
                           sh["ev1f"], sh["wc_toilet"])]

    p = os.path.join(REP, "child_mesh.json")
    json.dump(out, open(p, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"-> {p}  セル{len(out['cells']):,} / 避難所{len(out['shelters']):,}  "
          f"{os.path.getsize(p)/1e6:.2f} MB")


# ------------------------------------------------------------------ 統合UI用

def stage_areas():
    """広域避難場所（避難場所一覧CSV）→ 23区分。対応災害種別を持つ"""
    p = os.path.join(EXT, "130001_evacuation_area.csv")
    df = pd.read_csv(p, encoding="utf-8-sig", dtype=str).dropna(how="all")
    df.columns = ["code", "ward", "name", "addr", "lat", "lon",
                  "flood", "landslide", "hightide", "quake", "tsunami",
                  "fire", "inland", "volcano", "other",
                  "ev1f", "slope", "braille", "wc_toilet", "other2"]
    df = df[df["ward"].str.endswith("区", na=False)].copy()
    df = df[df["lat"].notna() & df["lon"].notna()]
    haz = ["flood", "landslide", "hightide", "quake", "tsunami",
           "fire", "inland", "volcano"]
    for c in haz + ["slope", "ev1f", "wc_toilet"]:
        df[c] = df[c].notna()
    g = gpd.GeoDataFrame(
        df, geometry=gpd.points_from_xy(df["lon"].astype(float),
                                        df["lat"].astype(float)),
        crs=4326).to_crs(CRS)
    out = os.path.join(PROC, "evac_areas23.parquet")
    g.to_parquet(out)
    print(f"避難場所 {len(g):,} / {g['ward'].nunique()}区  "
          f"地震{g['quake'].sum()} 洪水{g['flood'].sum()} 大規模火事{g['fire'].sum()}")


def stage_roads():
    """統合UI用の道路線データ。区ごとに1ファイルへ書き、ブラウザ側で遅延読み込みする

    23区の全エッジ694,712本をそのまま1ページに載せると100MB級になる。
    - 20m未満のエッジを落とす（半分になる。細かい枝は俯瞰では見えない）
    - 2mの許容誤差で頂点を間引く
    - 座標を1e-5度（約1m）の整数にして、線に沿って差分符号化する
    これで区あたり0.2〜1MB程度に収まる。
    """
    outdir = os.path.join(ROOT, "data")
    os.makedirs(outdir, exist_ok=True)
    tot = 0
    for f in sorted(glob.glob(os.path.join(NET, "edges_final_*.parquet"))):
        ward = os.path.basename(f)[12:-8]
        e = gpd.read_parquet(f)
        e = e[e["length_m"] >= 20].copy()
        g = e.geometry.simplify(2.0).to_crs(4326)
        lines = []
        for geom, w, b, s in zip(g, e["width_m"], e["blockage_risk"],
                                 e["slope_pct"]):
            cs = list(geom.coords)
            if len(cs) < 2:
                continue
            xs = [int(round(c[0] * 1e5)) for c in cs]
            ys = [int(round(c[1] * 1e5)) for c in cs]
            d = [xs[0], ys[0]]
            for i in range(1, len(xs)):
                d += [xs[i] - xs[i-1], ys[i] - ys[i-1]]
            lines.append([round(float(w), 1), round(float(b), 2),
                          round(float(s), 1), d])
        p = os.path.join(outdir, f"roads_{ward}.json")
        json.dump({"ward": ward, "scale": 1e5, "lines": lines},
                  open(p, "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        tot += os.path.getsize(p)
        print(f"[{ward}] {len(lines):,}本  {os.path.getsize(p)/1e6:.2f} MB",
              flush=True)
    print(f"-> {outdir}  合計 {tot/1e6:.1f} MB")


def stage_mesh2():
    """メッシュに道路指標（道幅・倒壊閉塞・勾配）を足す

    統合UIでは俯瞰時にメッシュ、ズーム時に道路線を出す。同じ指標が
    両方に必要なので、エッジ中点を250m格子に落として延長重み付き中央値を取る。
    """
    p = os.path.join(REP, "child_mesh.json")
    mesh = json.load(open(p, encoding="utf-8"))
    key = {}
    for f in sorted(glob.glob(os.path.join(NET, "edges_final_*.parquet"))):
        e = gpd.read_parquet(f)
        mid = e.geometry.interpolate(0.5, normalized=True)
        gi = np.floor(mid.x.to_numpy() / MESH_M).astype(int)
        gj = np.floor(mid.y.to_numpy() / MESH_M).astype(int)
        d = pd.DataFrame({"gi": gi, "gj": gj,
                          "w": e["width_m"].to_numpy(),
                          "b": e["blockage_risk"].to_numpy(),
                          "s": e["slope_pct"].to_numpy()})
        for (i, j), grp in d.groupby(["gi", "gj"]):
            key[(i, j)] = (round(float(grp["w"].median()), 1),
                           round(float(grp["b"].median()), 2),
                           round(float(grp["s"].median()), 1))
    # セル中心の平面直角座標を逆算して突き合わせる
    pt = gpd.GeoSeries(gpd.points_from_xy([c[1] for c in mesh["cells"]],
                                          [c[0] for c in mesh["cells"]]),
                       crs=4326).to_crs(CRS)
    hit = 0
    for c, x, y in zip(mesh["cells"], pt.x, pt.y):
        k = (int(np.floor(x / MESH_M)), int(np.floor(y / MESH_M)))
        v = key.get(k)
        if v is None:
            c += [None, None, None]
        else:
            c += list(v); hit += 1
    mesh["fields"] = ["lat", "lon", "tmin_normal", "tmin_quake", "ward",
                      "width_m", "blockage", "slope_pct"]
    json.dump(mesh, open(p, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"-> {p}  道路指標を付与 {hit:,}/{len(mesh['cells']):,} セル  "
          f"{os.path.getsize(p)/1e6:.2f} MB")



if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="shelters",
                    choices=["shelters", "access", "report", "mesh",
                             "areas", "roads", "mesh2"])
    ap.add_argument("--ward", default=None)
    a = ap.parse_args()
    if a.stage == "shelters":
        stage_shelters()
    elif a.stage == "access":
        stage_access([a.ward] if a.ward else None)
    elif a.stage == "mesh":
        stage_mesh()
    elif a.stage == "areas":
        stage_areas()
    elif a.stage == "roads":
        stage_roads()
    elif a.stage == "mesh2":
        stage_mesh2()
    else:
        stage_report()