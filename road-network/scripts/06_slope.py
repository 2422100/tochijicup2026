# -*- coding: utf-8 -*-
"""
DEM（基盤地図情報 数値標高モデル）から道路エッジの勾配を算出する

DEMは基本項目とは構造が違う。地物の集合ではなく格子で、
2次メッシュzipの中に3次メッシュ単位のXMLが100枚入っている。
各XMLは
  gml:Envelope        緯度経度の範囲
  gml:GridEnvelope    low/high（例 "0 0" / "224 149" → 225×150セル）
  gml:startPoint      データが途中から始まる場合の開始セル（欠けることがある）
  gml:tupleList       "地表面,12.89" の行が北西から東へ、行単位で南下する順に並ぶ
という構成。欠測は -9999。

  stage=dem    DEM zip → 2次メッシュ単位の .npy（標高ラスタ）
  stage=slope  エッジ両端の標高差から slope_pct を計算し edges_final に書き戻す

使い方:
  python 06_slope.py --stage dem   --skip-done
  python 06_slope.py --stage slope --skip-done
  python 05_network.py --stage recost      # 勾配をコストに反映
"""
import argparse, glob, io, json, os, re, zipfile
import numpy as np
import geopandas as gpd
from lxml import etree

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "02_processed")
NET = os.path.join(ROOT, "03_network")
EXT = os.path.join(ROOT, "20_external")
DEM_DIR = os.path.join(PROC, "_dem")
NS_GML = "http://www.opengis.net/gml/3.2"

NODATA = -9999.0
SUB = 10          # 2次メッシュあたりの3次メッシュ数（縦横とも）

# --- 短いエッジの勾配ノイズ対策
#   DEMは5mメッシュで鉛直方向に数十cmの誤差がある。2mのスタブの両端で
#   0.2mの差が出ただけで勾配10%になってしまい、実測では「勾配5%超」の
#   76.5%が長さ10m未満のエッジだった（江東区。埋立地で本来ほぼ平坦）。
#   歩行者が受ける負荷という意味でも、数mの区間の傾きは効いてこない。
#   そこで最低15mの基線で測り、DEM誤差相当の標高差は切り捨てる。
SLOPE_BASELINE_M = 15.0
ELEV_NOISE_M = 0.25


def find_dem_zips():
    """DEMを含むZIPを中身で判定して探す（置き場所に依存しない）"""
    cands = sorted(set(glob.glob(os.path.join(os.path.dirname(ROOT), "*.zip")) +
                       glob.glob(os.path.join(EXT, "*.zip"))))
    out = []
    for p in cands:
        try:
            with zipfile.ZipFile(p) as zf:
                if any(re.search(r"-DEM\d[A-C]-", n) for n in zf.namelist()):
                    out.append(p)
        except zipfile.BadZipFile:
            pass
    return out


def parse_dem_xml(fileobj):
    """1枚の3次メッシュXML → (values, nx, ny, lat0, lon0, lat1, lon1)"""
    tree = etree.parse(fileobj)
    r = tree.getroot()
    low = r.find(f".//{{{NS_GML}}}lowerCorner").text.split()
    up = r.find(f".//{{{NS_GML}}}upperCorner").text.split()
    lat0, lon0 = float(low[0]), float(low[1])
    lat1, lon1 = float(up[0]), float(up[1])
    hi = r.find(f".//{{{NS_GML}}}high").text.split()
    nx, ny = int(hi[0]) + 1, int(hi[1]) + 1

    sp = r.find(f".//{{{NS_GML}}}startPoint")
    start = 0
    if sp is not None and sp.text:
        sx, sy = (int(v) for v in sp.text.split())
        start = sy * nx + sx           # 途中から始まるデータがある

    tl = r.find(f".//{{{NS_GML}}}tupleList")
    grid = np.full(nx * ny, np.nan, dtype=np.float32)
    if tl is not None and tl.text:
        body = tl.text.strip()
        if body:
            # "種別,値" の行。種別は地表面/表層面/海水面など複数あるので
            # 最後のカンマ以降を取る。100万行規模になるので内包表記で回す。
            vals = np.fromiter(
                (float(s[s.rfind(",") + 1:]) for s in body.split("\n") if s),
                dtype=np.float32)
            end = min(start + len(vals), grid.size)
            grid[start:end] = vals[:end - start]
    grid[grid == NODATA] = np.nan
    return grid.reshape(ny, nx), nx, ny, lat0, lon0, lat1, lon1


def build_mesh_raster(zf, inner_name):
    """2次メッシュのDEM zip → (raster, meta)。3次メッシュ100枚を並べる"""
    data = zf.read(inner_name)
    tiles = {}
    meta = None
    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        for xn in sorted(zin.namelist()):
            if not xn.endswith(".xml") or xn.startswith("fmdid"):
                continue
            # FG-GML-5339-25-00-DEM5A-... の "00" が3次メッシュ番号(行列)
            m = re.search(r"FG-GML-\d{4}-\d{2}-(\d)(\d)-DEM", xn)
            if not m:
                continue
            row3, col3 = int(m.group(1)), int(m.group(2))
            with zin.open(xn) as f:
                g, nx, ny, la0, lo0, la1, lo1 = parse_dem_xml(f)
            tiles[(row3, col3)] = g
            if meta is None:
                meta = dict(nx=nx, ny=ny, dlat=(la1 - la0), dlon=(lo1 - lo0),
                            lat0=la0 - row3 * (la1 - la0),
                            lon0=lo0 - col3 * (lo1 - lo0))
    if meta is None:
        return None, None
    nx, ny = meta["nx"], meta["ny"]
    ras = np.full((ny * SUB, nx * SUB), np.nan, dtype=np.float32)
    for (r3, c3), g in tiles.items():
        # 3次メッシュ番号は南西原点。ラスタは北が上なので行を反転して配置
        r_from_top = (SUB - 1 - r3)
        ras[r_from_top * ny:(r_from_top + 1) * ny, c3 * nx:(c3 + 1) * nx] = g
    meta.update(lat_span=meta["dlat"] * SUB, lon_span=meta["dlon"] * SUB,
                rows=ny * SUB, cols=nx * SUB)
    return ras, meta


def stage_dem(skip_done):
    os.makedirs(DEM_DIR, exist_ok=True)
    zips = find_dem_zips()
    if not zips:
        raise SystemExit("DEMを含むZIPが見つからない")
    seen = set()
    for zp in zips:
        with zipfile.ZipFile(zp) as zf:
            for n in sorted(zf.namelist()):
                m = re.match(r"FG-GML-(\d+)-(DEM\d[A-C])-", os.path.basename(n))
                if not m or not n.endswith(".zip"):
                    continue
                mesh, kind = m.group(1), m.group(2)
                key = (mesh, kind)
                if key in seen:
                    continue
                seen.add(key)
                out = os.path.join(DEM_DIR, f"{mesh}_{kind}.npy")
                if skip_done and os.path.exists(out):
                    continue
                ras, meta = build_mesh_raster(zf, n)
                if ras is None:
                    continue
                np.save(out + ".tmp.npy", ras)
                os.replace(out + ".tmp.npy", out)
                json.dump(meta, open(os.path.join(DEM_DIR, f"{mesh}_{kind}.json"),
                                     "w"))
                ok = np.isfinite(ras)
                print(f"[{mesh} {kind}] {ras.shape}  有効 {100*ok.mean():.1f}%  "
                      f"標高 {np.nanmin(ras):.1f}〜{np.nanmax(ras):.1f}m", flush=True)


# ---------------------------------------------------------------- 標高サンプリング

class DemSampler:
    """2次メッシュ単位の .npy を必要に応じて読み、緯度経度で標高を引く"""

    def __init__(self):
        self.meta = {}
        for j in glob.glob(os.path.join(DEM_DIR, "*.json")):
            mesh, kind = os.path.basename(j)[:-5].split("_")
            self.meta.setdefault(mesh, {})[kind] = json.load(open(j))
        self.cache = {}

    def _get(self, mesh, kind):
        k = (mesh, kind)
        if k not in self.cache:
            p = os.path.join(DEM_DIR, f"{mesh}_{kind}.npy")
            self.cache[k] = np.load(p) if os.path.exists(p) else None
        return self.cache[k]

    def sample(self, lat, lon):
        """緯度経度の配列 → 標高の配列（該当なしは NaN）"""
        out = np.full(len(lat), np.nan, dtype=np.float32)
        for mesh, kinds in self.meta.items():
            mt = kinds.get("DEM5A") or next(iter(kinds.values()))
            la0, lo0 = mt["lat0"], mt["lon0"]
            la1, lo1 = la0 + mt["lat_span"], lo0 + mt["lon_span"]
            sel = (lat >= la0) & (lat < la1) & (lon >= lo0) & (lon < lo1) \
                & ~np.isfinite(out)
            if not sel.any():
                continue
            rows, cols = mt["rows"], mt["cols"]
            r = ((la1 - lat[sel]) / mt["lat_span"] * rows).astype(int)
            c = ((lon[sel] - lo0) / mt["lon_span"] * cols).astype(int)
            np.clip(r, 0, rows - 1, out=r)
            np.clip(c, 0, cols - 1, out=c)
            # DEM5Aを優先し、欠測はDEM5Bで埋める
            v = None
            for kind in ("DEM5A", "DEM5B", "DEM5C"):
                if kind not in kinds:
                    continue
                ras = self._get(mesh, kind)
                if ras is None:
                    continue
                vv = ras[r, c]
                v = vv if v is None else np.where(np.isfinite(v), v, vv)
            if v is not None:
                out[np.nonzero(sel)[0]] = v
        return out


def stage_slope(skip_done, ward_only=None):
    smp = DemSampler()
    if not smp.meta:
        raise SystemExit("DEMラスタが無い。先に --stage dem を実行すること")
    wards = gpd.read_parquet(os.path.join(PROC, "wards23.parquet"))["ward"]
    targets = [ward_only] if ward_only else list(wards)
    for ward in targets:
        fp = os.path.join(NET, f"edges_final_{ward}.parquet")
        if not os.path.exists(fp):
            continue
        mark = os.path.join(NET, "_topo_v2", f"{ward}.slope3")
        if skip_done and os.path.exists(mark):
            continue
        e = gpd.read_parquet(fp)
        g4 = e.geometry.to_crs(4326)
        # エッジの始点・終点の標高差から勾配を出す
        s = g4.apply(lambda x: x.coords[0])
        t = g4.apply(lambda x: x.coords[-1])
        lon0 = np.array([p[0] for p in s]); lat0 = np.array([p[1] for p in s])
        lon1 = np.array([p[0] for p in t]); lat1 = np.array([p[1] for p in t])
        h0 = smp.sample(lat0, lon0)
        h1 = smp.sample(lat1, lon1)
        L = e["length_m"].to_numpy(dtype=float)
        dh = np.abs(h1 - h0)
        dh = np.maximum(dh - ELEV_NOISE_M, 0.0)          # DEM誤差を差し引く
        slope = dh / np.maximum(L, SLOPE_BASELINE_M) * 100.0
        slope = np.where(np.isfinite(slope), slope, 0.0)
        slope = np.clip(slope, 0, 40)     # 階段や誤差による異常値を抑える
        e["slope_pct"] = np.round(slope, 2)
        e["elev_m"] = np.round((h0 + h1) / 2, 1)
        tmp = fp + ".tmp"
        e.to_parquet(tmp); os.replace(tmp, fp)
        cov = 100 * np.isfinite(h0).mean()
        print(f"[{ward}] 勾配付与 {len(e):,}  DEM被覆 {cov:.1f}%  "
              f"勾配中央値 {np.median(slope):.2f}%  "
              f"5%超 {100*(slope>5).mean():.1f}%", flush=True)
        os.makedirs(os.path.dirname(mark), exist_ok=True)
        open(mark, "w").close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["dem", "slope"])
    ap.add_argument("--ward", default=None)
    ap.add_argument("--skip-done", action="store_true")
    a = ap.parse_args()
    if a.stage == "dem":
        stage_dem(a.skip_done)
    else:
        stage_slope(a.skip_done, a.ward)


if __name__ == "__main__":
    main()
