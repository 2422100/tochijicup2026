# -*- coding: utf-8 -*-
"""
FGD基本項目 (JPGIS GML) → ftype別 GeoParquet
ディスク節約のため: 大ZIPから内側ZIPを1つずつ取り出し → XMLパース → 即削除。
出力: project/01_interim/{ftype}_{mesh}.parquet (後で結合)

使い方: python 01_parse_fgd.py [--mesh 533945]   # 省略時は全メッシュ
"""
import argparse, glob, io, os, re, sys, zipfile, tempfile
from lxml import etree
from shapely.geometry import LineString, Point, Polygon
import geopandas as gpd
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project/
SRC_DIR = os.path.dirname(ROOT)          # tokyoHackthon/ 直下を見る


def find_zips():
    """基本項目ZIPを探す。

    置き場所ではなく**中身**で判定する（DEMと基本項目は取り違えやすいため）。
    tokyoHackthon/ 直下と project/20_external/ の両方を見て、
    内部に FG-GML-{メッシュ}-{項目番号}- 形式のzipを含むものだけ返す。
    DEMは FG-GML-{メッシュ}-DEM5A- 形式なのでここでは除外される。

    ※ZIPは展開しないこと。中の項目zip→XMLをストリームで読む。
      一括展開するとサンドボックスのディスクが溢れる。
    """
    cands = sorted(glob.glob(os.path.join(SRC_DIR, "*.zip")) +
                   glob.glob(os.path.join(ROOT, "20_external", "*.zip")))
    zs = []
    for p in cands:
        try:
            with zipfile.ZipFile(p) as zf:
                if any(re.match(r"FG-GML-\d+-\d+-", n) for n in zf.namelist()):
                    zs.append(p)
        except zipfile.BadZipFile:
            print(f"  壊れたZIPを無視: {os.path.basename(p)}", flush=True)
    if not zs:
        raise SystemExit(f"基本項目のZIPが見つからない: {SRC_DIR}")
    return zs
OUT_DIR = os.path.join(ROOT, "01_interim")
NS_GML = "http://www.opengis.net/gml/3.2"

# 属性として拾う子要素（存在すれば）
ATTR_TAGS = ["type", "name", "admCode", "admOffice", "orgGILvl", "vis", "fid"]

# パースしない地物ファイル
#   BldL = 建物の外周線。BldA(ポリゴン)と情報が重複し、かつ1ファイル245MBと巨大。
SKIP_FEATURES = {"BldL"}


def _coords(text):
    nums = text.split()
    # FGDは「緯度 経度」→ (lon, lat) に入れ替え
    return [(float(nums[i + 1]), float(nums[i])) for i in range(0, len(nums), 2)]


_SKIP = {"fid", "lfSpanFr", "devDate"}
_ATTRS = set(ATTR_TAGS)
_SURFACE_TAGS = {f"{{{NS_GML}}}Surface", f"{{{NS_GML}}}Polygon"}
_POSLIST = f"{{{NS_GML}}}posList"
_POS = f"{{{NS_GML}}}pos"


def parse_fgd_xml(fileobj):
    """1つのFGD XMLをパースして dictリスト を返す

    地物ごとに el.iter() を1回だけ回して幾何と属性を同時に集める。
    `.//` の部分木検索を地物ごとに4回かけると建物(1ファイル10万棟規模)で
    処理時間が数倍になるため。
    """
    feats = []
    context = etree.iterparse(fileobj, events=("end",))     # iterparseでメモリ節約
    for _, el in context:
        tag = el.tag
        if not isinstance(tag, str) or tag.startswith("{" + NS_GML):
            continue
        parent = el.getparent()
        if parent is None or parent.getparent() is not None:
            continue                                        # ルート直下の地物のみ
        ftype = tag.split("}")[-1]
        if ftype in _SKIP:
            continue

        posl = pos = None
        is_surface = False
        attrs = {}
        for sub in el.iter():
            st = sub.tag
            if not isinstance(st, str):
                continue
            if st in _SURFACE_TAGS:
                is_surface = True
            elif st == _POSLIST:
                if posl is None:
                    posl = sub.text
            elif st == _POS:
                if pos is None:
                    pos = sub.text
            elif sub is not el:
                name = st.split("}")[-1]
                if name in _ATTRS and name not in attrs and sub.text:
                    attrs[name] = sub.text

        geom = None
        try:
            if posl:
                pts = _coords(posl)
                if is_surface and len(pts) >= 4:
                    geom = Polygon(pts)
                elif len(pts) >= 2:
                    geom = LineString(pts)
            elif pos:
                geom = Point(_coords(pos)[0])
        except Exception:
            geom = None
        if geom is not None:
            rec = {"ftype": ftype, "geometry": geom}
            rec.update(attrs)
            feats.append(rec)
        el.clear()
    return feats


def _flush(mesh, feats, seq):
    """ftype別にparquet出力。XMLファイル単位に分けるので再実行しても重複しない
    （建物のように1項目が100MB級のXML数本に分かれる場合、ファイル単位でないと
      実行時間制限のある環境では永久に完了しないため）"""
    gdf = gpd.GeoDataFrame(feats, geometry="geometry", crs="EPSG:6668")
    for ftype, sub in gdf.groupby("ftype"):
        out = os.path.join(OUT_DIR, f"{ftype}_{mesh}_{seq}.parquet")
        tmp = out + ".tmp"
        sub.reset_index(drop=True).to_parquet(tmp)
        os.replace(tmp, out)          # 中断による破損を防ぐ
        print(f"  {mesh} {ftype}: {len(sub)} -> {os.path.basename(out)}", flush=True)


def process_mesh(mesh, inner_names, zf_big, done_dir=None, skip_done=False):
    """XMLファイル単位で処理・出力・完了マーカ記録"""
    for name in inner_names:
        item = re.match(rf"FG-GML-{mesh}-(\d+)-", name).group(1)
        data = zf_big.read(name)
        with zipfile.ZipFile(io.BytesIO(data)) as zin:
            xmls = [x for x in zin.namelist()
                    if x.endswith(".xml") and not x.startswith("fmdid")
                    and not any(f"-{s}-" in x for s in SKIP_FEATURES)]
            for seq, xmlname in enumerate(sorted(xmls)):
                mk = os.path.join(done_dir, f"{mesh}_{item}_{seq}.ok") if done_dir else None
                if skip_done and mk and os.path.exists(mk):
                    continue
                with zin.open(xmlname) as f:
                    feats = parse_fgd_xml(f)
                if feats:
                    _flush(mesh, feats, seq)
                del feats
                if mk:
                    open(mk, "w").close()
        del data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mesh", default=None)
    ap.add_argument("--item", default=None,
                    help="項目番号を1つだけ処理 (05/06/08/10/11/12/13)")
    ap.add_argument("--exclude-item", default="01,11",
                    help="スキップする項目番号(カンマ区切り。GCP=01, 建物=11は既定で除外)")
    ap.add_argument("--skip-done", action="store_true",
                    help="完了マーカがある(mesh,item)をスキップ（再開用）")
    args = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    done_dir = os.path.join(OUT_DIR, "_done")
    os.makedirs(done_dir, exist_ok=True)
    excl = {x for x in args.exclude_item.split(",") if x}
    for zpath in find_zips():
        with zipfile.ZipFile(zpath) as zf:
            # 項目番号が数字のものだけ。同じZIPにDEM(FG-GML-{mesh}-DEM5A-)が
            # 同梱されていることがあるので、ここで確実に除外する。
            names = [n for n in zf.namelist()
                     if n.endswith(".zip") and re.match(r"FG-GML-\d+-\d+-", n)]
            if not names:
                continue      # 基本項目以外のZIP（DEM等）は無視
            meshes = sorted({re.match(r"FG-GML-(\d+)-", n).group(1) for n in names})
            if args.mesh:
                meshes = [m for m in meshes if m == args.mesh]
            print(f"# {os.path.basename(zpath)}: メッシュ {len(meshes)}", flush=True)
            for mesh in meshes:
                for name in sorted(n for n in names
                                   if n.startswith(f"FG-GML-{mesh}-")):
                    item = re.match(rf"FG-GML-{mesh}-(\d+)-", name).group(1)
                    if args.item:
                        if item != args.item:
                            continue
                    elif item in excl:
                        continue
                    marker = os.path.join(done_dir, f"{mesh}_{item}.ok")
                    if args.skip_done and os.path.exists(marker):
                        continue
                    print(f"mesh {mesh} item {item}", flush=True)
                    process_mesh(mesh, [name], zf,
                                 done_dir=done_dir, skip_done=args.skip_done)
                    open(marker, "w").close()


if __name__ == "__main__":
    main()
