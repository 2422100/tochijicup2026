# -*- coding: utf-8 -*-
"""
可視化

  stage=overview  23区の俯瞰図（道幅・倒壊閉塞リスク・勾配のコロプレス）→ PNG
  stage=ward      1区の道路網を属性で色分け → PNG
  stage=web       1区の道路網を単一HTMLの地図に → ブラウザで開ける

出力: reports/maps/
"""
import argparse, glob, json, os
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize, LinearSegmentedColormap
from matplotlib import font_manager

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "02_processed")
NET = os.path.join(ROOT, "03_network")
OUT = os.path.join(ROOT, "reports", "maps")
os.makedirs(OUT, exist_ok=True)

# 日本語ラベルのためCJKフォントを明示的に指定する
for cand in ("Noto Sans CJK JP", "Noto Serif CJK JP", "IPAGothic"):
    if any(f.name == cand for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = cand
        break
plt.rcParams["axes.unicode_minus"] = False


def ward_stats():
    """区ごとの代表値をエッジから集計（延長重み付き）"""
    rows = []
    for f in sorted(glob.glob(os.path.join(NET, "edges_final_*.parquet"))):
        w = os.path.basename(f)[12:-8]
        e = pd.read_parquet(f, columns=["length_m", "width_m", "blockage_risk",
                                        "slope_pct", "elev_m"])
        L = e["length_m"].to_numpy()
        tot = L.sum()
        rows.append(dict(
            ward=w,
            length_km=tot / 1000,
            width_med=float(np.median(e["width_m"])),
            narrow_pct=100 * L[e["width_m"] < 4].sum() / tot,     # 4m未満の延長割合
            blockage=float(np.average(e["blockage_risk"], weights=L)),
            slope5=100 * L[e["slope_pct"] > 5].sum() / tot,
            elev=float(np.nanmedian(e["elev_m"])),
        ))
    return pd.DataFrame(rows)


def stage_overview():
    wards = gpd.read_parquet(os.path.join(PROC, "wards23.parquet"))
    st = ward_stats()
    g = wards.merge(st, on="ward")

    panels = [
        ("width_med", "道幅の中央値 (m)", "viridis_r", None),
        ("narrow_pct", "4m未満の道路が占める延長割合 (%)", "OrRd", None),
        ("blockage", "地震時の倒壊閉塞リスク (0-1)", "OrRd", None),
        ("slope5", "勾配5%超の延長割合 (%)", "PuBu", None),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(17, 17))
    for ax, (col, title, cmap, _) in zip(axes.ravel(), panels):
        g.plot(column=col, cmap=cmap, ax=ax, edgecolor="white", linewidth=0.8,
               legend=True, legend_kwds={"shrink": 0.6})
        ax.set_title(title, fontsize=15, pad=12)
        ax.set_axis_off()
        # 上位3区と下位1区だけラベルを置く（全部書くと潰れる）
        top = g.nlargest(3, col)
        bot = g.nsmallest(1, col)
        for _, r in pd.concat([top, bot]).iterrows():
            c = r.geometry.representative_point()
            ax.annotate(f"{r['ward']}\n{r[col]:.2f}", (c.x, c.y), ha="center",
                        fontsize=8.5, color="black",
                        bbox=dict(fc="white", ec="none", alpha=0.75, pad=1.5))
    fig.suptitle("東京23区 避難ルーティング基盤データ 俯瞰",
                 fontsize=19, y=0.955)
    p = os.path.join(OUT, "overview_23ku.png")
    fig.savefig(p, dpi=115, bbox_inches="tight")
    plt.close(fig)
    print("->", p, flush=True)

    st.sort_values("blockage", ascending=False).round(2).to_csv(
        os.path.join(ROOT, "reports", "ward_summary.csv"), index=False)
    print(st.sort_values("blockage", ascending=False).round(2).to_string(index=False))


def stage_ward(ward):
    e = gpd.read_parquet(os.path.join(NET, f"edges_final_{ward}.parquet"))
    wards = gpd.read_parquet(os.path.join(PROC, "wards23.parquet"))
    wg = wards[wards["ward"] == ward]

    # 白背景に淡色だと道路網が見えないので暗背景にする。
    # 低い値も必ず色が付く連続カラーマップを使うこと（白始まりは線が消える）。
    specs = [
        ("width_m", "道幅 (m)", "turbo", 2, 18),
        ("blockage_risk", "倒壊閉塞リスク（地震時）", "inferno", 0, 0.9),
        ("slope_pct", "勾配 (%)", "cool", 0, 8),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(26, 9.5), facecolor="#111318")
    for ax, (col, title, cmap, vmin, vmax) in zip(axes, specs):
        ax.set_facecolor("#111318")
        wg.plot(ax=ax, color="#1c2029", edgecolor="#4a5163", linewidth=1.0)
        e.sort_values(col).plot(          # 高い値を上に描いて埋もれさせない
            ax=ax, column=col, cmap=cmap, linewidth=0.75,
            norm=Normalize(vmin, vmax), legend=True,
            legend_kwds={"shrink": 0.55})
        cb = ax.get_figure().axes[-1]
        cb.tick_params(colors="#dddddd")
        ax.set_title(f"{ward} — {title}", fontsize=15, color="white", pad=10)
        ax.set_axis_off()
        ax.set_aspect("equal")
    fig.patch.set_facecolor("#111318")
    p = os.path.join(OUT, f"ward_{ward}.png")
    fig.savefig(p, dpi=110, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print("->", p, flush=True)


WEB_TEMPLATE = """<!DOCTYPE html>
<meta charset="utf-8"><title>__WARD__ 避難ルーティング基盤</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 html,body{margin:0;height:100%;background:#111318;
   font-family:"Noto Sans JP",system-ui,sans-serif}
 #map{height:100%}
 .panel{position:absolute;top:12px;right:12px;z-index:1000;background:#1c2029ee;
   color:#e8eaf0;padding:14px 16px;border-radius:10px;font-size:13px;
   box-shadow:0 4px 18px #0008;min-width:210px}
 .panel h3{margin:0 0 10px;font-size:15px}
 .panel label{display:block;margin:5px 0;cursor:pointer}
 .bar{height:11px;border-radius:3px;margin:7px 0 3px}
 .ticks{display:flex;justify-content:space-between;font-size:11px;color:#9aa3b5}
 .stat{margin-top:12px;padding-top:10px;border-top:1px solid #3a4051;
   font-size:12px;color:#b8c0d0;line-height:1.7}
 .leaflet-popup-content-wrapper{background:#1c2029;color:#e8eaf0}
 .leaflet-popup-tip{background:#1c2029}
</style>
<div id="map"></div>
<div class="panel">
  <h3>__WARD__</h3>
  <label><input type="radio" name="m" value="width" checked> 道幅</label>
  <label><input type="radio" name="m" value="blockage"> 倒壊閉塞リスク（地震時）</label>
  <label><input type="radio" name="m" value="slope"> 勾配</label>
  <div class="bar" id="bar"></div>
  <div class="ticks"><span id="t0"></span><span id="t1"></span></div>
  <div class="stat" id="stat"></div>
</div>
<script>
const DATA = __DATA__;
const STATS = __STATS__;
// [色] 低い値も必ず見えるよう、白始まりの配色は使わない
const RAMPS = {
  width:    {stops:["#3b1f6b","#2f6fd0","#28c1a8","#c9e04a","#e83a2a"], lo:2, hi:18,
             unit:"m", label:"道幅"},
  blockage: {stops:["#0b0b1a","#5b1a5e","#b83654","#f07d24","#f7e05a"], lo:0, hi:0.9,
             unit:"", label:"倒壊閉塞リスク"},
  slope:    {stops:["#12e6e6","#4aa8f0","#8f6ce8","#d94ad2","#ff2fa8"], lo:0, hi:8,
             unit:"%", label:"勾配"}
};
function lerp(a,b,t){return a+(b-a)*t}
function hex2rgb(h){return [1,3,5].map(i=>parseInt(h.slice(i,i+2),16))}
function ramp(name,v){
  const r=RAMPS[name]; let t=(v-r.lo)/(r.hi-r.lo); t=Math.max(0,Math.min(1,t));
  const s=r.stops, x=t*(s.length-1), i=Math.min(s.length-2,Math.floor(x)), f=x-i;
  const a=hex2rgb(s[i]), b=hex2rgb(s[i+1]);
  return `rgb(${a.map((c,k)=>Math.round(lerp(c,b[k],f))).join(",")})`;
}
const map=L.map("map",{preferCanvas:true});
L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
  {attribution:"&copy; OpenStreetMap, &copy; CARTO / 国土地理院 基盤地図情報",
   maxZoom:20}).addTo(map);
let mode="width";
function style(f){
  const p=f.properties;
  const v = mode==="width"?p.w : mode==="blockage"?p.b : p.s;
  return {color:ramp(mode,v), weight: mode==="width"? Math.max(1,Math.min(6,p.w/2.5)) : 2,
          opacity:0.9};
}
const layer=L.geoJSON(DATA,{style:style,
  onEachFeature:(f,l)=>{const p=f.properties;
    l.bindPopup(`道幅 <b>${p.w} m</b><br>倒壊閉塞リスク <b>${p.b}</b><br>`+
                `勾配 <b>${p.s} %</b><br>延長 ${p.l} m`);}
}).addTo(map);
map.fitBounds(layer.getBounds());
function refresh(){
  layer.setStyle(style);
  const r=RAMPS[mode];
  document.getElementById("bar").style.background =
    `linear-gradient(90deg,${r.stops.join(",")})`;
  document.getElementById("t0").textContent = r.lo+r.unit;
  document.getElementById("t1").textContent = r.hi+r.unit+"以上";
  document.getElementById("stat").innerHTML = STATS[mode];
}
document.querySelectorAll("input[name=m]").forEach(el=>
  el.addEventListener("change",e=>{mode=e.target.value;refresh();}));
refresh();
</script>
"""


def stage_web(ward, simplify_m=3.0, min_len=0.0):
    e = gpd.read_parquet(os.path.join(NET, f"edges_final_{ward}.parquet"))
    if min_len:
        e = e[e["length_m"] >= min_len]
    g = e.to_crs(4326)
    geom = g.geometry.simplify(simplify_m / 111000)   # 度に換算した許容誤差

    feats = []
    for w, b, s, L, gm in zip(e["width_m"], e["blockage_risk"], e["slope_pct"],
                              e["length_m"], geom):
        if gm.is_empty:
            continue
        cs = [[round(x, 6), round(y, 6)] for x, y in gm.coords] \
            if gm.geom_type == "LineString" else None
        if not cs or len(cs) < 2:
            continue
        feats.append({"type": "Feature",
                      "properties": {"w": float(w), "b": float(b),
                                     "s": float(s), "l": round(float(L))},
                      "geometry": {"type": "LineString", "coordinates": cs}})
    fc = {"type": "FeatureCollection", "features": feats}

    Ls = e["length_m"].to_numpy()
    tot = Ls.sum()
    stats = {
        "width": (f"総延長 {tot/1000:,.0f} km<br>中央値 {np.median(e['width_m']):.1f} m<br>"
                  f"4m未満 {100*Ls[e['width_m']<4].sum()/tot:.1f}%"),
        "blockage": (f"延長加重平均 {np.average(e['blockage_risk'],weights=Ls):.2f}<br>"
                     f"リスク0.5超 {100*Ls[e['blockage_risk']>0.5].sum()/tot:.1f}%"),
        "slope": (f"5%超 {100*Ls[e['slope_pct']>5].sum()/tot:.1f}%<br>"
                  f"8%超 {100*Ls[e['slope_pct']>8].sum()/tot:.1f}%"),
    }
    html = (WEB_TEMPLATE.replace("__WARD__", ward)
            .replace("__DATA__", json.dumps(fc, ensure_ascii=False,
                                            separators=(",", ":")))
            .replace("__STATS__", json.dumps(stats, ensure_ascii=False)))
    p = os.path.join(OUT, f"map_{ward}.html")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(html)
    os.replace(tmp, p)
    print(f"-> {p}  ({len(feats):,} 本 / {os.path.getsize(p)/1e6:.1f} MB)", flush=True)


def stage_index():
    """区別マップへの索引ページ。俯瞰PNGと主要指標の表を載せる"""
    st = ward_stats().sort_values("blockage", ascending=False)
    rows = "\n".join(
        f'<tr><td><a href="map_{r.ward}.html">{r.ward}</a>'
        f'<a class="png" href="ward_{r.ward}.png" title="静止画">▦</a></td>'
        f'<td>{r.length_km:,.0f}</td><td>{r.width_med:.1f}</td>'
        f'<td>{r.narrow_pct:.1f}</td><td>{r.blockage:.2f}</td>'
        f'<td>{r.slope5:.1f}</td><td>{r.elev:.1f}</td></tr>'
        for r in st.itertuples())
    html = f"""<!DOCTYPE html><meta charset="utf-8">
<title>東京23区 避難ルーティング基盤</title>
<style>
 body{{background:#111318;color:#e8eaf0;font-family:"Noto Sans JP",system-ui,sans-serif;
   margin:0 auto;max-width:1180px;padding:28px 22px 60px}}
 h1{{font-size:23px;margin:0 0 6px}} h2{{font-size:17px;margin:32px 0 10px}}
 p{{color:#aab2c4;line-height:1.75;font-size:14px}}
 img{{width:100%;border-radius:10px;margin-top:8px}}
 table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}}
 th,td{{padding:7px 9px;border-bottom:1px solid #2c3140;text-align:right}}
 th{{color:#9aa3b5;font-weight:600;text-align:right;position:sticky;top:0;
   background:#111318}}
 td:first-child,th:first-child{{text-align:left}}
 a{{color:#6fb5ff;text-decoration:none}} a:hover{{text-decoration:underline}}
 .png{{margin-left:7px;color:#7a8399;font-size:12px}}
 .note{{background:#1c2029;border-left:3px solid #f0a24a;padding:11px 14px;
   border-radius:5px;font-size:13px;color:#c9d0de;margin-top:10px}}
</style>
<h1>東京23区 避難ルーティング基盤データ</h1>
<p>国土地理院「基盤地図情報」から生成。694,712エッジ / 総延長19,586km。
区名をクリックすると道路網の対話地図が開きます（道幅・倒壊閉塞リスク・勾配を切替）。</p>

<h2>23区の俯瞰</h2>
<img src="overview_23ku.png" alt="23区俯瞰">

<h2>区別の指標</h2>
<p>倒壊閉塞リスクの高い順。いずれも延長で重み付けした値です。</p>
<table>
<tr><th>区</th><th>総延長 km</th><th>道幅中央値 m</th><th>4m未満 %</th>
<th>閉塞リスク</th><th>勾配5%超 %</th><th>標高中央値 m</th></tr>
{rows}
</table>
<div class="note">
倒壊閉塞リスクは建蔽率を建物高さの代理変数とした<b>未較正の推定値</b>です。
勾配が0の区間が多いのはDEM誤差を除去しているためで、平坦という意味ではありません。
江戸川区は道路網の連結性に未解明の問題があります（最大連結成分53.4%）。
詳細は <code>reports/qc.md</code> を参照してください。
</div>
"""
    p = os.path.join(OUT, "index.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write(html)
    print("->", p, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="overview",
                    choices=["overview","ward","web","index","web_all","ward_all"])
    ap.add_argument("--min-len", type=float, default=0.0,
                    help="この長さ未満のエッジを地図から省く（ファイル軽量化）")
    ap.add_argument("--ward", default="荒川区")
    a = ap.parse_args()
    if a.stage == "overview":
        stage_overview()
    elif a.stage == "index":
        stage_index()
    elif a.stage == "ward_all":
        wards = gpd.read_parquet(os.path.join(PROC, "wards23.parquet"))["ward"]
        for w in wards:
            out = os.path.join(OUT, f"ward_{w}.png")
            if os.path.exists(out) and os.path.getsize(out) > 10000:
                continue
            stage_ward(w)
    elif a.stage == "web_all":
        wards = gpd.read_parquet(os.path.join(PROC, "wards23.parquet"))["ward"]
        for w in wards:
            out = os.path.join(OUT, f"map_{w}.html")
            if os.path.exists(out) and os.path.getsize(out) > 10000:
                continue          # 生成済みは飛ばす（中断・再開できるように）
            stage_web(w, min_len=a.min_len)
    elif a.stage == "web":
        stage_web(a.ward, min_len=a.min_len)
    else:
        stage_ward(a.ward)
