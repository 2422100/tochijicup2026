# -*- coding: utf-8 -*-
"""
01_interim/{ftype}_{mesh}.parquet をftype別に結合 → EPSG:6677投影 → 23区でクリップ
出力: 02_processed/{layer}.parquet
"""
import glob, os
import geopandas as gpd
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTERIM = os.path.join(ROOT, "01_interim")
PROC = os.path.join(ROOT, "02_processed")
os.makedirs(PROC, exist_ok=True)

# 建物は分割parquetのディレクトリとして保持する（単一ファイルにしない理由は
# clip_buildings のコメントを参照）
BLD_DIR = os.path.join(PROC, "_bld")

WARDS_23 = ["千代田区","中央区","港区","新宿区","文京区","台東区","墨田区","江東区",
            "品川区","目黒区","大田区","世田谷区","渋谷区","中野区","杉並区","豊島区",
            "北区","荒川区","板橋区","練馬区","足立区","葛飾区","江戸川区"]


def load_ftype(ftype):
    files = sorted(glob.glob(os.path.join(INTERIM, f"{ftype}_*.parquet")))
    if not files:
        return None
    gdf = pd.concat([gpd.read_parquet(f) for f in files], ignore_index=True)
    return gpd.GeoDataFrame(gdf, geometry="geometry", crs="EPSG:6668").to_crs(6677)


def build_wards():
    """23区ポリゴン（区名でdissolve）を返す"""
    cached = os.path.join(PROC, "wards23.parquet")
    if os.path.exists(cached):
        w = gpd.read_parquet(cached)
        print(f"wards: {len(w)}/23 (キャッシュ)")
        return w
    adm = load_ftype("AdmArea")
    assert adm is not None, "AdmArea が見つからない"
    print("AdmArea columns:", list(adm.columns))
    assert "name" in adm.columns, "AdmArea に name 列が無い"
    w = adm[adm["name"].isin(WARDS_23)].copy()
    w = w[w.geometry.notna()]
    w["geometry"] = w.geometry.buffer(0)          # 自己交差の修復
    wards = w.dissolve(by="name")[["geometry"]].reset_index()
    wards = wards.rename(columns={"name": "ward"})
    wards.to_parquet(os.path.join(PROC, "wards23.parquet"))
    missing = sorted(set(WARDS_23) - set(wards["ward"]))
    print(f"wards: {len(wards)}/23" + (f"  ※不足: {missing}" if missing else ""))
    return wards


def _readable(path):
    """中断で切れたparquetを『無い』扱いにするための健全性チェック"""
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


def clip_chunked(wards, ftype, dirname):
    """大きなレイヤ（建物286万件・道路縁70万件）を入力ファイル単位で区クリップする。

    一括処理は実行時間制限に収まらない。途中で止まっても次回の実行で続きから進む。
    """
    # 出力先は「分割parquetのディレクトリ」。単一ファイルにまとめない。
    #   マウント先の書き込みが約5MB/秒しか出ず、230MBの単一ファイルは
    #   1回の実行時間制限(45秒)内に書き切れないため。
    #   読み込みは gpd.read_parquet(BLD_DIR) でディレクトリごと指定できる。
    tmpdir = os.path.join(PROC, dirname)
    os.makedirs(tmpdir, exist_ok=True)
    srcs = sorted(glob.glob(os.path.join(INTERIM, f"{ftype}_*.parquet")))
    outs, made = [], 0
    for s in srcs:
        o = os.path.join(tmpdir, os.path.basename(s))
        outs.append(o)
        if _readable(o):
            continue
        g = gpd.read_parquet(s).to_crs(6677)
        g = g[g.geometry.notna()].reset_index(drop=True)
        j = gpd.sjoin(g, wards, how="inner", predicate="intersects")
        j = j[~j.index.duplicated(keep="first")].drop(columns=["index_right"])
        tmp = o + ".tmp"
        j.to_parquet(tmp)
        os.replace(tmp, o)
        made += 1
        print(f"  {ftype} {os.path.basename(s)}: {len(g)} -> {len(j)}", flush=True)
    if made:
        print(f"{ftype} {made} ファイル処理 / 全 {len(outs)}", flush=True)
    if any(not _readable(o) for o in outs):
        print(f"{ftype} クリップ未完 → 再実行で続行", flush=True)
        return
    import pyarrow.parquet as pq
    n = sum(pq.read_metadata(o).num_rows for o in outs)
    print(f"{ftype} -> {dirname}/ : {n} 件 / {len(outs)} ファイル", flush=True)


def main():
    wards = build_wards()
    clip_chunked(wards, "BldA", "_bld")
    clip_chunked(wards, "RdEdg", "_rdedg")
    layers = {
        "RdCompt": "road_compt",
        "WL": "water_lines", "WA": "water_areas",
        "RailCL": "rail_lines", "CommBdry": "chocho_bdry", "CommPt": "chocho_pt",
        "SBBdry": "gaiku_bdry", "SBAPt": "gaiku_pt",
        "AdmBdry": "adm_bdry", "AdmPt": "adm_pt",
    }
    for ftype, out in layers.items():
        dst = os.path.join(PROC, f"{out}.parquet")
        # os.path.exists ではなく中身で判定する。マウントの書き込みが遅く、
        # 実行時間制限で切れた不完全なファイルが残ることがあるため。
        if _readable(dst):
            print(f"skip {ftype} (exists)", flush=True); continue
        gdf = load_ftype(ftype)
        if gdf is None:
            print(f"skip {ftype} (not found)"); continue
        gdf = gdf[gdf.geometry.notna()].reset_index(drop=True)
        # 空間インデックス利用のsjoinでクリップ＋区名付与（重複は最初の区に寄せる）
        j = gpd.sjoin(gdf, wards, how="inner", predicate="intersects")
        j = j[~j.index.duplicated(keep="first")].drop(columns=["index_right"])
        _atomic_to_parquet(j, dst)
        print(f"{ftype} -> {out}: {len(gdf)} -> {len(j)}", flush=True)


if __name__ == "__main__":
    main()
