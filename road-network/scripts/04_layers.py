# -*- coding: utf-8 -*-
"""
建物・集計単位・障壁レイヤ整備
出力:
  02_processed/buildings.parquet  (footprint + 250mメッシュ建物密度)
  02_processed/chocho.parquet     (町丁目ポリゴン + 代表点名称)
  02_processed/gaiku.parquet      (街区ポリゴン)
  02_processed/barriers.parquet   (水涯線 + 軌道)
"""
import os
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.ops import polygonize, unary_union
from shapely.geometry import box

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "02_processed")


def buildings():
    # 建物は分割parquetのディレクトリ。単一ファイルにまとめるとマウント先の
    # 書き込み速度(約5MB/秒)では実行時間制限に収まらないため。
    b = gpd.read_parquet(os.path.join(PROC, "_bld"))
    b = b[b.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    area = b.geometry.area
    cen = b.geometry.centroid

    # 建物ジオメトリを属性付きで書き直すと230MB級になり、マウントの書き込み速度
    # (約5MB/秒)では実行時間制限に収まらない。建物そのものは _bld/ にあるので
    # 複製せず、集計結果である250mメッシュ密度だけを出力する。
    ORIGIN = 250.0
    mx = np.floor(cen.x / ORIGIN).astype(int)
    my = np.floor(cen.y / ORIGIN).astype(int)
    df = pd.DataFrame({"mesh_x": mx.values, "mesh_y": my.values,
                       "bld_area_m2": area.values})
    agg = df.groupby(["mesh_x", "mesh_y"]).agg(
        bld_count=("bld_area_m2", "size"),
        bld_area_m2=("bld_area_m2", "sum")).reset_index()
    agg["bld_density"] = agg["bld_area_m2"] / (ORIGIN * ORIGIN)   # 建蔽率相当
    cells = [box(x * ORIGIN, y * ORIGIN, (x + 1) * ORIGIN, (y + 1) * ORIGIN)
             for x, y in zip(agg["mesh_x"], agg["mesh_y"])]
    out = gpd.GeoDataFrame(agg, geometry=cells, crs=b.crs)
    out.to_parquet(os.path.join(PROC, "mesh250_bld_density.parquet"))
    print(f"buildings: {len(b)} 棟 / 250mメッシュ {len(out)} セル, "
          f"建蔽率平均={out['bld_density'].mean():.2f}")


def polygonize_bdry(bdry_file, pt_file, out, name_attr="name"):
    bd = gpd.read_parquet(os.path.join(PROC, bdry_file))
    if len(bd) == 0:
        # 街区は元データの収録範囲に23区が含まれず0件になる（欠測ではない）
        print(f"{out}: 入力0件のためスキップ")
        return
    polys = list(polygonize(unary_union(bd.geometry.values)))
    g = gpd.GeoDataFrame(geometry=polys, crs=bd.crs)
    g = g[g.geometry.area > 100]
    pt_path = os.path.join(PROC, pt_file)
    if os.path.exists(pt_path):
        pts = gpd.read_parquet(pt_path)
        keep = [c for c in [name_attr, "admCode", "geometry"] if c in pts.columns]
        j = gpd.sjoin(g, pts[keep], how="left", predicate="contains")
        g = j[~j.index.duplicated(keep="first")].drop(columns=[c for c in ["index_right"] if c in j.columns])
    g.reset_index(drop=True).to_parquet(os.path.join(PROC, out))
    print(f"{out}: {len(g)} polys")


def barriers():
    parts = []
    for f, kind in [("water_lines.parquet", "water"), ("rail_lines.parquet", "rail")]:
        p = os.path.join(PROC, f)
        if os.path.exists(p):
            g = gpd.read_parquet(p)
            g["barrier_type"] = kind
            parts.append(g[["barrier_type", "geometry"]])
    if parts:
        out = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=parts[0].crs)
        out.to_parquet(os.path.join(PROC, "barriers.parquet"))
        print(f"barriers: {len(out)}")


if __name__ == "__main__":
    buildings()
    polygonize_bdry("chocho_bdry.parquet", "chocho_pt.parquet", "chocho.parquet")
    try:
        polygonize_bdry("gaiku_bdry.parquet", "gaiku_pt.parquet", "gaiku.parquet")
    except FileNotFoundError:
        print("gaiku: なし(街区は5メッシュのみ)")
    barriers()
