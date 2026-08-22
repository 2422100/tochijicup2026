# -*- coding: utf-8 -*-
"""
統合UI — 1ページで全部見る

  reports/child_mesh.json    250mメッシュ（到達時間・道幅・倒壊閉塞・勾配）
  reports/child_access.csv   区別サマリ
  reports/child_survey.json  福祉局調査（都全体）
  02_processed/shelters23.parquet   避難所 1,538
  02_processed/evac_areas23.parquet 広域避難場所 764
  02_processed/wards23.parquet      区境界（GeoJSON化して境界線として描画）
  data/roads_{区}.json       道路線（ズーム時に区単位で遅延読み込み）
    ↓
  index.html （GitHub Pages の入口）
"""
import csv, json, os
import geopandas as gpd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "02_processed")
REP = os.path.join(ROOT, "reports")

# 指標ごとの固有カラーランプを定義
RAMP_TIME = ["#3288bd", "#66c2a5", "#abdda4", "#e6f598", "#ffffbf", "#fee08b", "#fdae61", "#f46d43", "#d53e4f", "#9e0142"]
RAMP_WIDTH = ["#d73027", "#f46d43", "#fdae61", "#fee08b", "#ffffbf", "#d9ef8b", "#a6d96a", "#66bd63", "#1a9850", "#006837"]
RAMP_RISK = ["#ffffcc", "#ffeda0", "#fed976", "#feb24c", "#fd8d3c", "#fc4e2a", "#e31a1c", "#bd0026", "#800026", "#50001a"]
RAMP_SLOPE = ["#fcfbfd", "#efedf5", "#dadaeb", "#bcbddc", "#9e9ac8", "#807dba", "#6a51a3", "#54278f", "#3f007d", "#20003f"]

C_SHELTER = "#d95926"     
C_AREA = "#199e70"        
S1 = "#1a73e8"
SURFACE = "#f8f9fa"

METRICS = [
    ("tn", "子連れ到達時間・平常時", 2, [3.5, 5.5, 7.0, 8.5, 10.0, 12.0, 13.5, 16.0, 20.5], "分", None, 0, RAMP_TIME),
    ("tq", "子連れ到達時間・地震時", 3, [3.5, 5.5, 7.5, 9.0, 10.5, 12.0, 14.0, 17.0, 21.5], "分", None, 0, RAMP_TIME),
    ("w",  "道幅",                  5, [4.1, 4.5, 5.0, 5.7, 6.2, 6.6, 7.7, 9.2, 16.4], "m", 0, 1, RAMP_WIDTH),
    ("b",  "倒壊閉塞リスク",         6, [0.001, 0.16, 0.26, 0.32, 0.4, 0.46, 0.52, 0.58, 0.64], "", 1, 0, RAMP_RISK),
    ("s",  "勾配",                  7, [0.001, 0.3, 0.6, 1.0, 1.5, 2.5, 4.0, 6.0, 9.0], "%", 2, 0, RAMP_SLOPE),
]

def build():
    mesh = json.load(open(os.path.join(REP, "child_mesh.json"), encoding="utf-8"))
    survey = json.load(open(os.path.join(REP, "child_survey.json"), encoding="utf-8"))
    with open(os.path.join(REP, "child_access.csv"), encoding="utf-8") as f:
        acc = list(csv.DictReader(f))
    acc.sort(key=lambda r: -float(r["tmed_normal"]))

    sh = gpd.read_parquet(os.path.join(PROC, "shelters23.parquet")).to_crs(4326)
    ar = gpd.read_parquet(os.path.join(PROC, "evac_areas23.parquet")).to_crs(4326)
    
    bounds = {}
    ward_geojson = None
    ward_path = os.path.join(PROC, "wards23.parquet")
    
    if os.path.exists(ward_path):
        wd = gpd.read_parquet(ward_path).to_crs(4326)
        ward_geojson = json.loads(wd.to_json())
        for _, r in wd.iterrows():
            x0, y0, x1, y1 = r.geometry.bounds
            bounds[r["ward"]] = [round(y0, 5), round(x0, 5), round(y1, 5), round(x1, 5)]
    else:
        print("注意: wards23.parquetが見つからないため、避難所の座標から代替の区境界を計算する。", flush=True)
        for w in sh["ward"].unique():
            sh_w = sh[sh["ward"] == w]
            if len(sh_w) > 0:
                x0, y0, x1, y1 = sh_w.total_bounds
                bounds[w] = [round(y0-0.01, 5), round(x0-0.01, 5), round(y1+0.01, 5), round(x1+0.01, 5)]

    shelters = [[round(g.y, 5), round(g.x, 5), n, a, int(s), int(e), int(t), w]
                for g, n, a, s, e, t, w in zip(
                    sh.geometry, sh["name"], sh["addr"], sh["slope"],
                    sh["ev1f"], sh["wc_toilet"], sh["ward"])]
    HAZ = [("flood", "洪水"), ("landslide", "崖崩れ・土石流"), ("hightide", "高潮"),
           ("quake", "地震"), ("tsunami", "津波"), ("fire", "大規模な火事"),
           ("inland", "内水氾濫"), ("volcano", "火山現象")]
    areas = [[round(r.geometry.y, 5), round(r.geometry.x, 5), r["name"], r["addr"],
              [lab for k, lab in HAZ if r[k]], r["ward"]]
             for _, r in ar.iterrows()]

    accrows = "\n".join(
        f'<tr data-ward="{r["ward"]}"><td>{r["ward"]}</td>'
        f'<td>{int(r["n_shelter"])}</td>'
        f'<td>{float(r["tmed_normal"]):.1f}</td>'
        f'<td>{float(r["tmed_quake"]):.1f}</td>'
        f'<td>{float(r["worsen_pct"]):+.1f}</td></tr>' for r in acc)

    sup = survey["supplies"]
    bars = "\n".join(
        f'<div class="bar"><span class="bl">{s["label"]}</span>'
        f'<span class="bt"><i style="width:{max(s["pct"],0.8):.1f}%"></i></span>'
        f'<span class="bv">{s["pct"]}%</span></div>' for s in sup)
    ops = [o for o in survey["operation"]
           if any(k in o["label"] for k in ("妊婦", "育児", "子ども", "プライバシー"))]
    opbars = "\n".join(
        f'<div class="bar"><span class="bl">{o["label"]}</span>'
        f'<span class="bt"><i style="width:{max(o["pct"],0.8):.1f}%"></i></span>'
        f'<span class="bv">{o["pct"]}%</span></div>' for o in ops)

    shv = survey["shelter"]
    n_slope = sum(1 for s in shelters if s[4])
    
    wardopts = "".join(f'<option value="{w}">{w}</option>'
                       for w in sorted(bounds))
    
    mbtn = "".join(
        f'<button class="mb" data-m="{k}">{lab}</button>'
        for k, lab, *_ in METRICS)

    supply_html = "".join(
        f'<li>{s["label"]} <b>{s["pct"]}%</b></li>' for s in sup[:6])

    nroad = sum(len(json.load(open(os.path.join(ROOT, "data", f),
                                   encoding="utf-8"))["lines"])
                for f in sorted(os.listdir(os.path.join(ROOT, "data")))
                if f.startswith("roads_"))

    data = {"mesh": mesh, "shelters": shelters, "areas": areas,
            "bounds": bounds, "ward_geojson": ward_geojson}

    html = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>こどもぼうさいナビ — 東京23区</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<link href="https://fonts.googleapis.com/css2?family=Zen+Maru+Gothic:wght@700&display=swap" rel="stylesheet">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 :root{{
   --surface:#f8f9fa;
   --panel:#ffffff;
   --ink:#202124;
   --ink2:#5f6368;
   --ink3:#80868b;
   --line:#dadce0;
   --s1:{S1};
   --sh:{C_SHELTER};
   --ar:{C_AREA};
 }}
 *{{box-sizing:border-box}}
 html,body{{height:100%;margin:0}}
 body{{background:var(--surface);color:var(--ink);
   font-family:"Noto Sans JP",system-ui,sans-serif;font-size:16px;line-height:1.7;
   display:flex;flex-direction:column;overflow:hidden}}
 header{{display:flex;align-items:center;gap:16px;padding:12px 20px;
   border-bottom:1px solid var(--line);flex:none;background:var(--panel)}}
 header h1{{font-family:'Zen Maru Gothic',sans-serif;font-size:26px;color:var(--sh);margin:0;font-weight:700;text-shadow:1px 1px 0px rgba(0,0,0,0.05)}}
 header .main-btn{{background:var(--s1);color:#ffffff;border:none;cursor:pointer;padding:8px 16px;border-radius:24px;margin-left:auto;display:flex;align-items:center;gap:8px;font-size:15px;font-weight:700;box-shadow:0 2px 4px rgba(0,0,0,0.15);transition:all 0.2s}}
 header .main-btn:hover{{background:#1557b0;transform:translateY(-1px);box-shadow:0 4px 8px rgba(0,0,0,0.2)}}
 #wrap{{flex:1;display:flex;min-height:0}}
 #map{{flex:1;background:#e5e3df}}
 #side{{width:400px;flex:none;border-left:1px solid var(--line);
   overflow-y:auto;padding:20px 24px 40px;background:var(--surface)}}
 #side.hide{{display:none}}
 .ctl{{position:absolute;z-index:900;top:12px;left:12px;background:rgba(255,255,255,0.95);
   border:1px solid var(--line);border-radius:12px;padding:16px;
   max-width:360px;backdrop-filter:blur(8px);box-shadow:0 4px 12px rgba(0,0,0,0.1)}}
 .lbl{{color:var(--ink2);font-size:14px;font-weight:600;margin:0 0 8px}}
 .row{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}}
 button,select{{background:#ffffff;color:var(--ink);border:1px solid var(--line);
   border-radius:8px;padding:8px 12px;font-size:14px;cursor:pointer;
   font-family:inherit;transition:all 0.2s ease}}
 button:hover,select:hover{{background:#f1f3f4}}
 button[aria-pressed=true]{{background:var(--s1);color:#ffffff;border-color:var(--s1);font-weight:600}}
 button.sh[aria-pressed=true]{{background:var(--sh);color:#ffffff;border-color:var(--sh)}}
 button.ar[aria-pressed=true]{{background:var(--ar);color:#ffffff;border-color:var(--ar)}}
 select{{padding-right:24px}}
 .filter-cb{{display:flex;align-items:center;gap:6px;color:var(--ink2);font-size:13px;cursor:pointer;user-select:none}}
 .filter-cb input{{margin:0;cursor:pointer;accent-color:var(--sh)}}
 .ramp{{display:flex;height:12px;border-radius:4px;overflow:hidden;margin-top:4px}}
 .ramp i{{flex:1}}
 .ticks{{display:flex;justify-content:space-between;font-size:12px;
   color:var(--ink3);margin-top:6px}}
 .hint{{color:var(--ink2);font-size:13px;margin-top:12px;line-height:1.6;background:#f8f9fa;padding:8px;border-radius:6px;border:1px solid var(--line)}}
 p{{color:var(--ink2);font-size:15px;line-height:1.7;margin:8px 0}}
 .tile{{background:var(--panel);border:1px solid var(--line);border-radius:12px;
   padding:16px;margin-bottom:12px}}
 .tile b{{display:block;font-size:32px;font-weight:700;line-height:1.2;color:var(--ink)}}
 .tile span{{color:var(--ink2);font-size:14px;display:block;margin-top:4px;font-weight:600}}
 .tile em{{color:var(--ink3);font-size:13px;font-style:normal;display:block;
   margin-top:6px;line-height:1.5}}
 table{{border-collapse:collapse;width:100%;font-size:14px}}
 th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right}}
 th{{color:var(--ink3);font-weight:600}}
 td:first-child,th:first-child{{text-align:left}}
 tbody tr{{cursor:pointer;transition:background 0.2s}}
 tbody tr:hover{{background:#f1f3f4}}
 .bar{{display:grid;grid-template-columns:140px 1fr 50px;align-items:center;
   gap:12px;margin:8px 0;font-size:14px}}
 .bl{{color:var(--ink2)}}
 .bt{{background:#e0e0e0;border-radius:6px;height:16px;overflow:hidden}}
 .bt i{{display:block;height:100%;background:var(--s1);border-radius:0 6px 6px 0}}
 .bv{{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}}
 .note{{background:#fef7e0;border-left:4px solid var(--sh);padding:12px 16px;
   border-radius:8px;font-size:14px;color:var(--ink);line-height:1.7}}
 .sq{{background:var(--ar);border:1.5px solid #fff;border-radius:2px;
   position:absolute;transform:translate(-50%,-50%);width:11px;height:11px}}
 .zl .sq{{width:5px;height:5px;border-width:0}}
 .zm .sq{{width:8px;height:8px;border-width:1px}}
 .leaflet-popup-content-wrapper,.leaflet-popup-tip{{background:var(--panel);color:var(--ink)}}
 .leaflet-popup-content{{font-size:14px;line-height:1.7;margin:16px}}
 .pop b{{font-size:16px;display:block;margin-bottom:8px}} 
 .pop dl{{margin:12px 0 0;display:grid;grid-template-columns:auto 1fr;gap:6px 12px}}
 .pop dt{{color:var(--ink3)}} .pop dd{{margin:0;font-weight:600}}
 .pop .ref{{margin-top:12px;padding-top:10px;border-top:1px solid var(--line);
   color:var(--ink3);font-size:12px}}
 .pop .ref ul{{margin:6px 0 0;padding-left:20px}}
 
 details {{ margin-bottom: 24px; border-bottom: 1px solid var(--line); padding-bottom: 16px; }}
 details:last-child {{ border-bottom: none; }}
 details summary {{ cursor: pointer; font-size: 18px; font-weight: 700; margin: 0; outline: none; display: flex; justify-content: space-between; align-items: center; list-style: none; }}
 details summary::-webkit-details-marker {{ display: none; }}
 details summary::after {{ content: '▼'; font-size: 14px; color: var(--ink3); transition: transform 0.2s; }}
 details[open] summary::after {{ transform: rotate(180deg); }}
 details summary:hover {{ color: var(--s1); }}
 .acc-content {{ margin-top: 16px; }}
 
 .ctl-acc summary {{ font-size: 14px; font-weight: 600; color: var(--ink2); padding: 0; margin: 0; }}
 .ctl-acc summary::after {{ font-size: 12px; }}
 .ctl-acc summary:hover {{ color: var(--ink); }}
 
 @media(max-width:860px){{#side{{display:none !important}}}}
</style></head><body>
<header>
 <h1>こどもぼうさいナビ</h1>
 <button id="tg" class="main-btn" title="詳細データを開閉">
   <span id="tg-text">詳細を見る</span>
   <svg viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round">
     <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
     <line x1="15" y1="3" x2="15" y2="21"></line>
   </svg>
 </button>
</header>
<div id="wrap">
 <div id="map">
  <div class="ctl">
   
   <details class="ctl-acc" open>
     <summary>色で見る指標</summary>
     <div style="margin-top:12px">
       <div class="row">{mbtn}</div>
       <div class="ramp" id="ramp"></div>
       <div class="ticks"><span id="t0"></span><span id="t1"></span>
         <span id="t2"></span><span id="t3"></span></div>
     </div>
   </details>
   
   <p class="lbl" style="margin-top:20px">地点の表示</p>
   <div class="row">
    <button class="sh" id="bsh" aria-pressed="true">● 避難所</button>
    <button class="ar" id="bar" aria-pressed="true">■ 広域避難場所</button>
    <select id="wsel"><option value="">区を選択…</option>{wardopts}</select>
   </div>
   <div class="row" style="gap:12px; margin-top:8px; margin-bottom:4px;">
    <label class="filter-cb"><input type="checkbox" id="fslope"> スロープ等</label>
    <label class="filter-cb"><input type="checkbox" id="fev"> EV・1階</label>
    <label class="filter-cb"><input type="checkbox" id="fwc"> 車椅子対応トイレ</label>
   </div>
   <p class="hint" id="hint"></p>
  </div>
 </div>
 <div id="side" class="hide">
  
  <details open>
    <summary>いま分かっていること</summary>
    <div class="acc-content">
      <p style="font-size:13px; color:var(--ink3); margin-top:0; margin-bottom:16px;">
        東京23区 / 避難所{len(shelters):,}・広域避難場所{len(areas):,}・道路{nroad:,}区間（20m以上）
      </p>
      <div class="tile"><b>{shv['pct']}%</b>
        <span>妊産婦・乳幼児を想定した避難所がある自治体</span>
        <em>都内62自治体中{shv['yes']}。残り{shv['no']}は想定なし</em></div>
      <div class="tile"><b>{100*n_slope//len(shelters)}%</b>
        <span>スロープ等がある避難所</span>
        <em>23区{len(shelters):,}か所のうち{n_slope}</em></div>
    </div>
  </details>

  <details open>
    <summary>区別の到達時間</summary>
    <div class="acc-content">
      <p>行をクリックするとその区へ移動し、赤い境界線で強調表示します。</p>
      <table><thead><tr><th>区</th><th>避難所</th><th>平常</th><th>地震</th>
        <th>悪化%</th></tr></thead><tbody id="wtb">{accrows}</tbody></table>
    </div>
  </details>

  <details>
    <summary>避難所に何が置いてあるか</summary>
    <div class="acc-content">
      <p>東京都福祉局の調査（都内62自治体）。<b>施設単位のデータは公開されていない</b>ため、
      ここは都全体の割合です。地図上の個々の避難所と結びつけることはできません。</p>
      {bars}
    </div>
  </details>

  <details>
    <summary>避難所の運営</summary>
    <div class="acc-content">
      <p>「あり」と答えた自治体の割合（62自治体中）。</p>
      {opbars}
    </div>
  </details>

  <details>
    <summary>データに関する限界</summary>
    <div class="acc-content">
      <div class="note">
       避難所の乳幼児対応（授乳室・おむつ交換台）は公開データに存在せず、
       ピンの区別は<b>バリアフリー設備からの推定</b>です。
       所要時間は幼児連れ2.5km/hを道幅と勾配で減速させた粗いモデルで、
       信号待ち・混雑・子どもの疲労を含みません。倒壊閉塞は建蔽率を建物高さの
       代理変数にした未較正の推定値です。避難所・避難場所の基準日は令和3年4月1日。
       広域避難場所は13区分しか収録されていません。
      </div>
      <p style="margin-top:16px;font-size:13px;color:var(--ink3)">
       出典:
       <a href="https://catalog.data.metro.tokyo.lg.jp/dataset/t000003d0000000093" style="color:#8ab4f8">東京都防災マップ 避難所・避難場所一覧</a>（総務局, CC BY） /
       <a href="https://catalog.data.metro.tokyo.lg.jp/dataset/t000054d0000000064" style="color:#8ab4f8">妊婦・乳幼児に関連した防災対策調査</a>（福祉局, CC BY） /
       道路網は<a href="https://fgd.gsi.go.jp/download/menu.php" style="color:#8ab4f8">国土地理院 基盤地図情報</a>より作成。
       <br><a href="data_index.html" style="color:#8ab4f8;display:inline-block;margin-top:8px">道路データ基盤の詳細ページへ戻る</a>
      </p>
    </div>
  </details>

 </div>
</div>

<script>
const D = {json.dumps(data, ensure_ascii=False, separators=(",", ":"))};
const METRICS = {json.dumps({m[0]: {"label": m[1], "idx": m[2], "breaks": m[3],
                                    "unit": m[4], "road": m[5], "inv": m[6], "ramp": m[7]}
                             for m in METRICS}, ensure_ascii=False)};
const SUPPLY = {json.dumps(supply_html, ensure_ascii=False)};
const M = D.mesh, HALF = M.mesh_m/2, ROAD_ZOOM = 13;
let metric = null; 
const FILE_MODE = location.protocol === 'file:';
const failed = {{}};

const map = L.map('map',{{preferCanvas:true, zoomControl:false}})
              .setView([35.702,139.752],11);
L.control.zoom({{position:'topright'}}).addTo(map);

// コントロールパネルのクリックイベントやスクロールが地図に伝播するのを防ぐ
const ctlEl = document.querySelector('.ctl');
L.DomEvent.disableClickPropagation(ctlEl);
L.DomEvent.disableScrollPropagation(ctlEl);

map.createPane('meshPane'); map.getPane('meshPane').style.zIndex = 340;
map.createPane('roadPane'); map.getPane('roadPane').style.zIndex = 360;
map.createPane('wardPane'); map.getPane('wardPane').style.zIndex = 400;
map.createPane('highlightPane'); map.getPane('highlightPane').style.zIndex = 450; 

L.tileLayer("https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png",
  {{maxZoom:19, attribution:'&copy; OpenStreetMap, &copy; CARTO'}}).addTo(map);

const boundaryLayer = L.layerGroup().addTo(map);

function drawBoundary() {{
  boundaryLayer.clearLayers();
  const lineColor = '#444444'; 
  
  if (D.ward_geojson) {{
    L.geoJSON(D.ward_geojson, {{
      style: {{ color: lineColor, weight: 2.5, opacity: 0.9, fillOpacity: 0, dashArray: '4, 4' }},
      interactive: false,
      pane: 'wardPane'
    }}).addTo(boundaryLayer);
  }} else {{
    for (const w in D.bounds) {{
      const bb = D.bounds[w];
      L.rectangle([[bb[0], bb[1]], [bb[2], bb[3]]], {{
        color: lineColor, weight: 2, opacity: 0.6, fillOpacity: 0, dashArray: '4, 4', pane: 'wardPane', interactive: false
      }}).addTo(boundaryLayer);
    }}
  }}
}}

const highlightLayer = L.layerGroup().addTo(map);

function colorOf(v, m){{
  if (v === null || v === undefined) return null;
  const b = m.breaks; let i = b.length;
  for (let k=0;k<b.length;k++) if (v < b[k]) {{ i = k; break; }}
  return m.ramp[m.inv ? m.ramp.length-1-i : i];
}}

function roadsUsable(){{
  if (!metric || FILE_MODE || METRICS[metric].road === null) return false;
  const ws = visibleWards();
  return ws.length > 0 && ws.some(w => cache[w] && cache[w].lines.length > 0);
}}

const meshLayer = L.layerGroup().addTo(map);
function drawMesh(){{
  meshLayer.clearLayers();
  if (!metric) return; 

  const m = METRICS[metric], z = map.getZoom();
  const op = (z >= ROAD_ZOOM && roadsUsable()) ? 0.2 : 0.65; 
  const dLat = HALF/111320;
  const vb = z >= 12 ? map.getBounds().pad(0.2) : null;
  for (const c of M.cells){{
    if (vb && (c[0] < vb.getSouth() || c[0] > vb.getNorth() ||
               c[1] < vb.getWest()  || c[1] > vb.getEast())) continue;
    const col = colorOf(c[m.idx], m); if (!col) continue;
    const dLon = HALF/(111320*Math.cos(c[0]*Math.PI/180));
    L.rectangle([[c[0]-dLat,c[1]-dLon],[c[0]+dLat,c[1]+dLon]],
      {{stroke:false,fillColor:col,fillOpacity:op,pane:'meshPane'}})
     .bindPopup(()=>popMesh(c)).addTo(meshLayer);
  }}
}}
function popMesh(c){{
  return '<div class="pop"><b>'+M.wards[c[4]]+'</b>'
   +'<dl><dt>子連れ到達時間</dt><dd>平常 '+c[2]+'分 / 地震時 '+c[3]+'分</dd>'
   +'<dt>道幅の中央値</dt><dd>'+(c[5]??'—')+' m</dd>'
   +'<dt>倒壊閉塞リスク</dt><dd>'+(c[6]??'—')+'</dd>'
   +'<dt>勾配</dt><dd>'+(c[7]??'—')+' %</dd></dl>'
   +'<div class="ref">250mメッシュの中央値</div></div>';
}}

const roadLayer = L.layerGroup().addTo(map);
const cache = {{}}, loading = {{}};
function visibleWards(){{
  const b = map.getBounds(), out = [];
  for (const [w,bb] of Object.entries(D.bounds))
    if (b.getSouth()<bb[2] && b.getNorth()>bb[0] &&
        b.getWest()<bb[3] && b.getEast()>bb[1]) out.push(w);
  return out;
}}
function decode(d, scale){{
  const pts = []; let x = d[0], y = d[1];
  pts.push([y/scale, x/scale]);
  for (let i=2;i<d.length;i+=2){{ x+=d[i]; y+=d[i+1]; pts.push([y/scale,x/scale]); }}
  return pts;
}}
async function ensureRoads(w){{
  if (FILE_MODE || cache[w] || loading[w] || failed[w]) return;
  loading[w] = true;
  try {{
    const r = await fetch('data/roads_'+encodeURIComponent(w)+'.json');
    if (!r.ok) throw new Error(r.status);
    cache[w] = await r.json();
  }} catch(e) {{
    failed[w] = true;
    console.warn('道路データを取得できません: ' + w, e);
  }}
  loading[w] = false; drawRoads(); drawMesh();
}}
function drawRoads(){{
  roadLayer.clearLayers();
  if (!metric) {{ hint(); return; }} 
  const z = map.getZoom();
  if (z < ROAD_ZOOM) {{ hint(); return; }}
  
  const m = METRICS[metric];
  const wide = z >= 16 ? 3.5 : (z >= 15 ? 2.5 : 1.6);
  const vb = map.getBounds().pad(0.15);
  for (const w of visibleWards()){{
    if (!cache[w]) {{ ensureRoads(w); continue; }}
    const sc = cache[w].scale;
    for (const ln of cache[w].lines){{
      const y0 = ln[3][1]/sc, x0 = ln[3][0]/sc;
      if (y0 < vb.getSouth() || y0 > vb.getNorth() ||
          x0 < vb.getWest()  || x0 > vb.getEast()) continue;
      const val = m.road === null ? null : ln[m.road];
      const col = val === null ? '#cccccc' : colorOf(val, m); 
      L.polyline(decode(ln[3], sc),
        {{color:col, weight:wide, opacity:0.9, pane:'roadPane'}})
       .bindPopup('<div class="pop"><b>道路区間</b><dl>'
         +'<dt>道幅</dt><dd>'+ln[0]+' m</dd>'
         +'<dt>倒壊閉塞リスク</dt><dd>'+ln[1]+'</dd>'
         +'<dt>勾配</dt><dd>'+ln[2]+' %</dd></dl>'
         +'<div class="ref">道幅は1m格子の距離変換から推定（下限2m）</div></div>')
       .addTo(roadLayer);
    }}
  }}
  hint();
}}

const shLayer = L.layerGroup().addTo(map), shMarks = [];
const rad = z => z<=11 ? 2.5 : (z<=13 ? 4 : 7);
for (const s of D.shelters){{
  const mk = L.circleMarker([s[0],s[1]],
    {{radius:rad(11), color:'{C_SHELTER}', weight:1.5,
      fillColor: s[4] ? '{C_SHELTER}' : '{SURFACE}', fillOpacity:1}})
   .bindPopup('<div class="pop"><b>'+s[2]+'</b><br><span style="color:var(--ink2);display:block;margin-top:4px">'
     +(s[3]||'')+'</span><dl>'
     +'<dt>スロープ等</dt><dd>'+(s[4]?'あり':'記載なし')+'</dd>'
     +'<dt>EV・避難スペース1階</dt><dd>'+(s[5]?'あり':'記載なし')+'</dd>'
     +'<dt>車椅子対応トイレ</dt><dd>'+(s[6]?'あり':'記載なし')+'</dd></dl>'
     +'<div class="ref">この施設に何が備蓄されているかは公開されていません。'
     +'都内62自治体のうち備蓄している割合は<ul>'+SUPPLY+'</ul></div></div>');
  mk._ok = !!s[4];             
  mk._s = !!s[4];
  mk._e = !!s[5];
  mk._w = !!s[6];
  mk.addTo(shLayer); shMarks.push(mk);
}}

function updateShelters() {{
  if (document.getElementById('bsh').getAttribute('aria-pressed') !== 'true') return;
  shLayer.clearLayers();
  
  const reqS = document.getElementById('fslope').checked;
  const reqE = document.getElementById('fev').checked;
  const reqW = document.getElementById('fwc').checked;
  
  for (const mk of shMarks) {{
    if (reqS && !mk._s) continue;
    if (reqE && !mk._e) continue;
    if (reqW && !mk._w) continue;
    mk.addTo(shLayer);
  }}
}}

['fslope', 'fev', 'fwc'].forEach(id => {{
  document.getElementById(id).addEventListener('change', updateShelters);
}});

function sizeByZoom(){{
  const z = map.getZoom(), c = map.getContainer();
  c.classList.toggle('zl', z<=11); c.classList.toggle('zm', z>11 && z<=13);
  const r = rad(z), w = z<=11 ? 0 : (z<=13 ? 1 : 1.5);
  
  const offColor = '#b0b0b0'; 
  
  shMarks.forEach(m=>m.setRadius(r).setStyle({{
    weight: w,
    fillColor: (z<=11 || m._ok) ? '{C_SHELTER}' : offColor,
    fillOpacity: z<=11 ? 0.85 : 1
  }}));
}}
map.on('zoomend', sizeByZoom);

const arLayer = L.layerGroup().addTo(map);
for (const a of D.areas){{
  L.marker([a[0],a[1]], {{icon: L.divIcon({{className:'',
     html:'<div class="sq"></div>', iconSize:[0,0], iconAnchor:[0,0]}})}})
   .bindPopup('<div class="pop"><b>'+a[2]+'</b><br><span style="color:var(--ink2);display:block;margin-top:4px">'
     +(a[3]||'')+'</span><dl><dt>対応する災害</dt><dd>'
     +(a[4].length?a[4].join('、'):'記載なし')+'</dd></dl>'
     +'<div class="ref">広域避難場所（一時的に逃げる広い場所）</div></div>')
   .addTo(arLayer);
}}

function legend(){{
  const rampEl = document.getElementById('ramp');
  if (!metric) {{ 
    rampEl.innerHTML = '';
    for (let i=0; i<4; i++) document.getElementById('t'+i).textContent = '';
    return;
  }}
  const m = METRICS[metric], b = m.breaks, u = m.unit;
  const ramp = m.inv ? [...m.ramp].reverse() : m.ramp;
  rampEl.innerHTML = ramp.map(c=>'<i style="background:'+c+'"></i>').join('');
  const n = v => (Math.round(v*10)/10) + u;
  const t = m.inv
    ? ['安全 '+n(b[8])+'〜', n(b[5]), n(b[2]), '〜'+n(b[0])+' 危険']
    : ['安全 〜'+n(b[0]), n(b[2]), n(b[5]), n(b[8])+'〜 危険'];
  for (let i=0;i<4;i++) document.getElementById('t'+i).textContent = t[i];
}}

function hint(){{
  const el = document.getElementById('hint');
  if (FILE_MODE) {{
    el.innerHTML = '<b style="color:#f46d43">ローカルファイルとして開いています。</b>'
      + 'ブラウザの制限で道路データ(data/)を読み込めないため、'
      + '250mメッシュ表示のみになります。道路1本ごとの表示は、'
      + 'GitHub Pages で開くか、ローカルサーバー経由で開いてください。';
    return;
  }}
  if (!metric) {{
    el.textContent = '上のボタンから指標を選択すると、メッシュや道路が色付けされます。';
    return;
  }}
  
  const z = map.getZoom(), m = METRICS[metric];
  const nf = Object.keys(failed).length;
  el.textContent =
    nf > 0 ? ('道路データを取得できませんでした（' + nf + '区）。'
              + 'data/ フォルダが同じ場所にあるか確認してください。')
    : z < ROAD_ZOOM
      ? '250mメッシュ表示。ズームすると道路1本ごとに切り替わります。'
      : (m.road === null
         ? '到達時間は道路単位では持っていないため、メッシュのまま表示しています。'
         : '道路表示。区に入るとその区のデータを読み込みます。');
}}

document.querySelectorAll('.mb').forEach(b=>b.onclick=()=>{{
  const isActive = b.getAttribute('aria-pressed') === 'true';
  document.querySelectorAll('.mb').forEach(x=>x.removeAttribute('aria-pressed'));
  if (isActive) {{
    metric = null; 
  }} else {{
    b.setAttribute('aria-pressed','true');
    metric = b.dataset.m;
  }}
  legend(); drawMesh(); drawRoads();
}});

const bsh=document.getElementById('bsh'), bar=document.getElementById('bar');
bsh.onclick=()=>{{ 
  const on=bsh.ariaPressed!=='true'; 
  bsh.ariaPressed=on?'true':'false';
  if (on) {{ updateShelters(); }} else {{ shLayer.clearLayers(); }}
}};
bar.onclick=()=>{{ const on=bar.ariaPressed!=='true'; bar.ariaPressed=on?'true':'false';
  on?arLayer.addTo(map):map.removeLayer(arLayer); }};

function goWard(w){{
  highlightLayer.clearLayers();
  if(!w) return;
  const b=D.bounds[w];
  if(b) map.fitBounds([[b[0],b[1]],[b[2],b[3]]]);
  
  if (D.ward_geojson) {{
    const features = D.ward_geojson.features.filter(f => f.properties.ward === w);
    if (features.length > 0) {{
      L.geoJSON(features, {{
        style: {{ color: '#ff4444', weight: 4, opacity: 1, fillOpacity: 0.1, fillColor: '#ff4444' }},
        interactive: false,
        pane: 'highlightPane'
      }}).addTo(highlightLayer);
    }}
  }} else if (b) {{
    L.rectangle([[b[0], b[1]], [b[2], b[3]]], {{
      color: '#ff4444', weight: 4, opacity: 1, fillOpacity: 0.1, fillColor: '#ff4444',
      pane: 'highlightPane', interactive: false
    }}).addTo(highlightLayer);
  }}
}}

document.getElementById('wsel').onchange=e=>{{ goWard(e.target.value); }};
document.querySelectorAll('#wtb tr').forEach(tr=>tr.onclick=()=>{{
  const w = tr.dataset.ward;
  document.getElementById('wsel').value = w; 
  goWard(w);
}});

document.getElementById('tg').onclick=e=>{{
  e.preventDefault(); 
  const side = document.getElementById('side');
  side.classList.toggle('hide');
  document.getElementById('tg-text').textContent = side.classList.contains('hide') ? '詳細を見る' : '詳細を閉じる';
  setTimeout(()=>map.invalidateSize(),60); 
}};
  
map.on('moveend zoomend', ()=>{{ drawMesh(); drawRoads(); }});
drawBoundary(); 
legend(); sizeByZoom(); drawMesh(); drawRoads();
</script></body></html>
"""
    p = os.path.join(ROOT, "index.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"-> {p}  ({os.path.getsize(p)/1e6:.2f} MB)  "
          f"避難所{len(shelters):,} 避難場所{len(areas):,} メッシュ{len(mesh['cells']):,}")


if __name__ == "__main__":
    build()