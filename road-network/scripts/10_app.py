# -*- coding: utf-8 -*-
"""
統合UI — 1ページで全部見る

  reports/child_mesh.json    250mメッシュ（到達時間・道幅・倒壊閉塞・勾配）
  reports/child_access.csv   区別サマリ
  reports/child_survey.json  福祉局調査（都全体）
  02_processed/shelters23.parquet   避難所 1,538
  02_processed/evac_areas23.parquet 広域避難場所 764
  data/roads_{区}.json       道路線（ズーム時に区単位で遅延読み込み）
    ↓
  index.html （GitHub Pages の入口）

設計
  - 俯瞰（zoom<13）は250mメッシュ。ズームすると道路線に切り替わる。
    23区の道路を全部載せると100MB級になるため、表示中の区のファイルだけ取る。
  - 指標は1つだけ画面に出す。連続量なので単一色相ランプ（blue 600→100）。
    「明るいほど悪い」で統一するため、道幅だけランプを反転させる。
  - 避難所（丸・橙）と広域避難場所（四角・緑）は役割が違うので形で分ける。
    色だけに意味を持たせない。
"""
import csv, json, os
import geopandas as gpd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "02_processed")
REP = os.path.join(ROOT, "reports")

RAMP = ["#184f95", "#256abf", "#2a78d6", "#3987e5", "#5598e7",
        "#6da7ec", "#86b6ef", "#9ec5f4", "#b7d3f6", "#cde2fb"]
C_SHELTER = "#d95926"     # categorical slot2 (dark)
C_AREA = "#199e70"        # categorical slot3 (dark)
S1 = "#3987e5"
SURFACE = "#1a1a19"

METRICS = [
    ("tn", "子連れ到達時間・平常時", 2, [4, 6, 8, 10, 12, 15, 18, 22, 28], "分", None, 0),
    ("tq", "子連れ到達時間・地震時", 3, [4, 6, 8, 10, 12, 15, 18, 22, 28], "分", None, 0),
    ("w",  "道幅",                  5, [3, 3.5, 4, 4.5, 5, 6, 8, 10, 14], "m", 0, 1),
    ("b",  "倒壊閉塞リスク",         6, [.1, .2, .3, .4, .5, .6, .7, .8, .9], "", 1, 0),
    ("s",  "勾配",                  7, [1, 2, 3, 4, 5, 7, 9, 12, 15], "%", 2, 0),
]


def build():
    mesh = json.load(open(os.path.join(REP, "child_mesh.json"), encoding="utf-8"))
    survey = json.load(open(os.path.join(REP, "child_survey.json"), encoding="utf-8"))
    with open(os.path.join(REP, "child_access.csv"), encoding="utf-8") as f:
        acc = list(csv.DictReader(f))
    acc.sort(key=lambda r: -float(r["tmed_normal"]))

    sh = gpd.read_parquet(os.path.join(PROC, "shelters23.parquet")).to_crs(4326)
    ar = gpd.read_parquet(os.path.join(PROC, "evac_areas23.parquet")).to_crs(4326)
    wd = gpd.read_parquet(os.path.join(PROC, "wards23.parquet")).to_crs(4326)

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

    bounds = {}
    for _, r in wd.iterrows():
        x0, y0, x1, y1 = r.geometry.bounds
        bounds[r["ward"]] = [round(y0, 5), round(x0, 5), round(y1, 5), round(x1, 5)]

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
        f'<button class="mb" data-m="{k}"'
        f'{" aria-pressed=true" if k == "tn" else ""}>{lab}</button>'
        for k, lab, *_ in METRICS)

    supply_html = "".join(
        f'<li>{s["label"]} <b>{s["pct"]}%</b></li>' for s in sup[:6])

    nroad = sum(len(json.load(open(os.path.join(ROOT, "data", f),
                                   encoding="utf-8"))["lines"])
                for f in sorted(os.listdir(os.path.join(ROOT, "data")))
                if f.startswith("roads_"))

    data = {"mesh": mesh, "shelters": shelters, "areas": areas,
            "bounds": bounds}

    html = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>こどもぼうさいナビ — 東京23区</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 :root{{--surface:{SURFACE};--panel:#232322;--ink:#fff;--ink2:#c3c2b7;
   --ink3:#8b8a82;--line:#33332f;--s1:{S1};--sh:{C_SHELTER};--ar:{C_AREA}}}
 *{{box-sizing:border-box}}
 html,body{{height:100%;margin:0}}
 body{{background:var(--surface);color:var(--ink);
   font-family:"Noto Sans JP",system-ui,sans-serif;font-size:14px;
   display:flex;flex-direction:column;overflow:hidden}}
 header{{display:flex;align-items:baseline;gap:14px;padding:11px 16px;
   border-bottom:1px solid var(--line);flex:none}}
 header h1{{font-size:17px;margin:0;letter-spacing:.01em}}
 header span{{color:var(--ink3);font-size:12px}}
 header a{{color:#6fb5ff;font-size:12px;margin-left:auto;text-decoration:none}}
 #wrap{{flex:1;display:flex;min-height:0}}
 #map{{flex:1;background:#111318}}
 #side{{width:352px;flex:none;border-left:1px solid var(--line);
   overflow-y:auto;padding:14px 16px 40px;background:var(--surface)}}
 #side.hide{{display:none}}
 .ctl{{position:absolute;z-index:900;top:10px;left:10px;background:#1a1a19e8;
   border:1px solid var(--line);border-radius:10px;padding:10px 11px;
   max-width:335px;backdrop-filter:blur(3px)}}
 .lbl{{color:var(--ink3);font-size:11px;margin:0 0 5px}}
 .row{{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:9px}}
 button,select{{background:#2b2b29;color:var(--ink2);border:1px solid var(--line);
   border-radius:6px;padding:5px 9px;font-size:12px;cursor:pointer;
   font-family:inherit}}
 button[aria-pressed=true]{{background:var(--s1);color:#fff;border-color:var(--s1)}}
 button.sh[aria-pressed=true]{{background:var(--sh);border-color:var(--sh)}}
 button.ar[aria-pressed=true]{{background:var(--ar);border-color:var(--ar)}}
 .ramp{{display:flex;height:9px;border-radius:3px;overflow:hidden;margin-top:2px}}
 .ramp i{{flex:1}}
 .ticks{{display:flex;justify-content:space-between;font-size:10px;
   color:var(--ink3);margin-top:3px}}
 .hint{{color:var(--ink3);font-size:11px;margin-top:7px;line-height:1.5}}
 h2{{font-size:14px;margin:20px 0 6px}}
 h2:first-child{{margin-top:0}}
 p{{color:var(--ink2);font-size:12.5px;line-height:1.65;margin:5px 0}}
 .tile{{background:var(--panel);border:1px solid var(--line);border-radius:9px;
   padding:11px 13px;margin-bottom:8px}}
 .tile b{{display:block;font-size:25px;font-weight:650;line-height:1.25}}
 .tile span{{color:var(--ink2);font-size:12px}}
 .tile em{{color:var(--ink3);font-size:11px;font-style:normal;display:block;
   margin-top:3px}}
 table{{border-collapse:collapse;width:100%;font-size:12px}}
 th,td{{padding:5px 6px;border-bottom:1px solid var(--line);text-align:right}}
 th{{color:var(--ink3);font-weight:600}}
 td:first-child,th:first-child{{text-align:left}}
 tbody tr{{cursor:pointer}}
 tbody tr:hover{{background:#2b2b29}}
 .bar{{display:grid;grid-template-columns:118px 1fr 44px;align-items:center;
   gap:7px;margin:4px 0;font-size:12px}}
 .bl{{color:var(--ink2)}}
 .bt{{background:#2a2a28;border-radius:4px;height:14px;overflow:hidden}}
 .bt i{{display:block;height:100%;background:var(--s1);border-radius:0 4px 4px 0}}
 .bv{{text-align:right;font-variant-numeric:tabular-nums}}
 .note{{background:#241f1a;border-left:3px solid var(--sh);padding:10px 12px;
   border-radius:6px;font-size:11.5px;color:var(--ink2);line-height:1.65}}
 .sq{{background:var(--ar);border:1.5px solid #fff3;border-radius:2px;
   position:absolute;transform:translate(-50%,-50%);width:11px;height:11px}}
 .zl .sq{{width:5px;height:5px;border-width:1px}}
 .zm .sq{{width:8px;height:8px}}
 .leaflet-popup-content-wrapper,.leaflet-popup-tip{{background:var(--panel);
   color:var(--ink)}}
 .leaflet-popup-content{{font-size:12.5px;line-height:1.6;margin:11px 13px}}
 .pop b{{font-size:13.5px}} .pop dl{{margin:7px 0 0;display:grid;
   grid-template-columns:auto 1fr;gap:2px 9px}}
 .pop dt{{color:var(--ink3)}} .pop dd{{margin:0}}
 .pop .ref{{margin-top:9px;padding-top:7px;border-top:1px solid var(--line);
   color:var(--ink3);font-size:11px}}
 .pop .ref ul{{margin:4px 0 0;padding-left:15px}}
 @media(max-width:860px){{#side{{display:none}}}}
</style></head><body>
<header>
 <h1>こどもぼうさいナビ</h1>
 <span>東京23区 / 避難所{len(shelters):,}・広域避難場所{len(areas):,}・道路{nroad:,}区間（20m以上）</span>
 <a href="#" id="tg">パネル開閉</a>
</header>
<div id="wrap">
 <div id="map">
  <div class="ctl">
   <p class="lbl">色で見る指標</p>
   <div class="row">{mbtn}</div>
   <div class="ramp" id="ramp"></div>
   <div class="ticks"><span id="t0"></span><span id="t1"></span></div>
   <p class="lbl" style="margin-top:11px">地点</p>
   <div class="row">
    <button class="sh" id="bsh" aria-pressed="true">● 避難所</button>
    <button class="ar" id="bar" aria-pressed="true">■ 広域避難場所</button>
    <select id="wsel"><option value="">区へ移動…</option>{wardopts}</select>
   </div>
   <p class="hint" id="hint"></p>
  </div>
 </div>
 <div id="side">
  <h2>いま分かっていること</h2>
  <div class="tile"><b>{shv['pct']}%</b>
    <span>妊産婦・乳幼児を想定した避難所がある自治体</span>
    <em>都内62自治体中{shv['yes']}。残り{shv['no']}は想定なし</em></div>
  <div class="tile"><b>{100*n_slope//len(shelters)}%</b>
    <span>スロープ等がある避難所</span>
    <em>23区{len(shelters):,}か所のうち{n_slope}</em></div>

  <h2>区別の到達時間</h2>
  <p>クリックするとその区へ移動します。単位は分。</p>
  <table><thead><tr><th>区</th><th>避難所</th><th>平常</th><th>地震</th>
    <th>悪化%</th></tr></thead><tbody id="wtb">{accrows}</tbody></table>

  <h2>避難所に何が置いてあるか</h2>
  <p>東京都福祉局の調査（都内62自治体）。<b>施設単位のデータは公開されていない</b>ため、
  ここは都全体の割合です。地図上の個々の避難所と結びつけることはできません。</p>
  {bars}

  <h2>避難所の運営</h2>
  <p>「あり」と答えた自治体の割合（62自治体中）。</p>
  {opbars}

  <h2>限界</h2>
  <div class="note">
   避難所の乳幼児対応（授乳室・おむつ交換台）は公開データに存在せず、
   ピンの区別は<b>バリアフリー設備からの推定</b>です。
   所要時間は幼児連れ2.5km/hを道幅と勾配で減速させた粗いモデルで、
   信号待ち・混雑・子どもの疲労を含みません。倒壊閉塞は建蔽率を建物高さの
   代理変数にした未較正の推定値です。避難所・避難場所の基準日は令和3年4月1日。
   広域避難場所は13区分しか収録されていません。
  </div>
  <p style="margin-top:12px;font-size:11.5px;color:var(--ink3)">
   出典:
   <a href="https://catalog.data.metro.tokyo.lg.jp/dataset/t000003d0000000093">東京都防災マップ 避難所・避難場所一覧</a>（総務局, CC BY） /
   <a href="https://catalog.data.metro.tokyo.lg.jp/dataset/t000054d0000000064">妊婦・乳幼児に関連した防災対策調査</a>（福祉局, CC BY） /
   道路網は<a href="https://fgd.gsi.go.jp/download/menu.php">国土地理院 基盤地図情報</a>より作成。
   <a href="data_index.html">道路データ基盤の詳細ページ</a>
  </p>
 </div>
</div>

<script>
const D = {json.dumps(data, ensure_ascii=False, separators=(",", ":"))};
const RAMP = {json.dumps(RAMP)};
const METRICS = {json.dumps({m[0]: {"label": m[1], "idx": m[2], "breaks": m[3],
                                    "unit": m[4], "road": m[5], "inv": m[6]}
                             for m in METRICS}, ensure_ascii=False)};
const SUPPLY = {json.dumps(supply_html, ensure_ascii=False)};
const M = D.mesh, HALF = M.mesh_m/2, ROAD_ZOOM = 13;
let metric = 'tn';

const map = L.map('map',{{preferCanvas:true, zoomControl:false}})
              .setView([35.702,139.752],11);
L.control.zoom({{position:'topright'}}).addTo(map);
map.createPane('meshPane'); map.getPane('meshPane').style.zIndex = 340;
map.createPane('roadPane'); map.getPane('roadPane').style.zIndex = 360;
L.tileLayer("https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png",
  {{maxZoom:19, attribution:'&copy; OpenStreetMap, &copy; CARTO'}}).addTo(map);

/* 指標の値 → 色。道幅だけは「大きいほど安全」なのでランプを反転する */
function colorOf(v, m){{
  if (v === null || v === undefined) return null;
  const b = m.breaks; let i = b.length;
  for (let k=0;k<b.length;k++) if (v < b[k]) {{ i = k; break; }}
  return RAMP[m.inv ? RAMP.length-1-i : i];
}}

const meshLayer = L.layerGroup().addTo(map);
function drawMesh(){{
  meshLayer.clearLayers();
  if (map.getZoom() >= ROAD_ZOOM && METRICS[metric].road !== null) return;
  const m = METRICS[metric], dLat = HALF/111320;
  for (const c of M.cells){{
    const col = colorOf(c[m.idx], m); if (!col) continue;
    const dLon = HALF/(111320*Math.cos(c[0]*Math.PI/180));
    L.rectangle([[c[0]-dLat,c[1]-dLon],[c[0]+dLat,c[1]+dLon]],
      {{stroke:false,fillColor:col,fillOpacity:0.72,pane:'meshPane'}})
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

/* --- 道路線。区ごとのファイルを、画面に入った区の分だけ取りに行く --- */
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
  if (cache[w] || loading[w]) return;
  loading[w] = true;
  try {{
    const r = await fetch('data/roads_'+encodeURIComponent(w)+'.json');
    cache[w] = await r.json();
  }} catch(e) {{ cache[w] = {{lines:[],scale:1e5}}; }}
  loading[w] = false; drawRoads();
}}
function drawRoads(){{
  roadLayer.clearLayers();
  const z = map.getZoom();
  if (z < ROAD_ZOOM) {{ hint(); return; }}
  const m = METRICS[metric];
  const wide = z >= 16 ? 3.5 : (z >= 15 ? 2.5 : 1.6);
  const vb = map.getBounds().pad(0.15);
  for (const w of visibleWards()){{
    if (!cache[w]) {{ ensureRoads(w); continue; }}
    const sc = cache[w].scale;
    for (const ln of cache[w].lines){{
      // 始点だけで粗く間引く。区の端の線が少し描かれない場合があるが
      // 描画量が数分の一になるので、パディングを取って許容する
      const y0 = ln[3][1]/sc, x0 = ln[3][0]/sc;
      if (y0 < vb.getSouth() || y0 > vb.getNorth() ||
          x0 < vb.getWest()  || x0 > vb.getEast()) continue;
      const val = m.road === null ? null : ln[m.road];
      const col = val === null ? '#4a4a46' : colorOf(val, m);
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

/* --- 地点 --- */
const shLayer = L.layerGroup().addTo(map), shMarks = [];
const rad = z => z<=11 ? 2.5 : (z<=13 ? 4 : 7);
for (const s of D.shelters){{
  const mk = L.circleMarker([s[0],s[1]],
    {{radius:rad(11), color:'{C_SHELTER}', weight:1.5,
      fillColor: s[4] ? '{C_SHELTER}' : '{SURFACE}', fillOpacity:1}})
   .bindPopup('<div class="pop"><b>'+s[2]+'</b><br><span style="color:#8b8a82">'
     +(s[3]||'')+'</span><dl>'
     +'<dt>スロープ等</dt><dd>'+(s[4]?'あり':'記載なし')+'</dd>'
     +'<dt>EV・避難スペース1階</dt><dd>'+(s[5]?'あり':'記載なし')+'</dd>'
     +'<dt>車椅子対応トイレ</dt><dd>'+(s[6]?'あり':'記載なし')+'</dd></dl>'
     +'<div class="ref">この施設に何が備蓄されているかは公開されていません。'
     +'都内62自治体のうち備蓄している割合は<ul>'+SUPPLY+'</ul></div></div>');
  mk.addTo(shLayer); shMarks.push(mk);
}}
function sizeByZoom(){{
  const z = map.getZoom(), c = map.getContainer();
  c.classList.toggle('zl', z<=11); c.classList.toggle('zm', z>11 && z<=13);
  const r = rad(z); shMarks.forEach(m=>m.setRadius(r));
}}
map.on('zoomend', sizeByZoom);

const arLayer = L.layerGroup().addTo(map);
for (const a of D.areas){{
  L.marker([a[0],a[1]], {{icon: L.divIcon({{className:'',
     html:'<div class="sq"></div>', iconSize:[0,0], iconAnchor:[0,0]}})}})
   .bindPopup('<div class="pop"><b>'+a[2]+'</b><br><span style="color:#8b8a82">'
     +(a[3]||'')+'</span><dl><dt>対応する災害</dt><dd>'
     +(a[4].length?a[4].join('、'):'記載なし')+'</dd></dl>'
     +'<div class="ref">広域避難場所（一時的に逃げる広い場所）</div></div>')
   .addTo(arLayer);
}}

/* --- 凡例・ヒント --- */
function legend(){{
  const m = METRICS[metric];
  const ramp = m.inv ? [...RAMP].reverse() : RAMP;
  document.getElementById('ramp').innerHTML =
    ramp.map(c=>'<i style="background:'+c+'"></i>').join('');
  document.getElementById('t0').textContent =
    (m.inv ? '広い' : '小さい') + (m.unit? ' ('+m.unit+')':'');
  document.getElementById('t1').textContent =
    m.inv ? '狭い（危険側）' : '大きい（危険側）';
}}
function hint(){{
  const z = map.getZoom(), m = METRICS[metric];
  document.getElementById('hint').textContent =
    z < ROAD_ZOOM
      ? '250mメッシュ表示。ズームすると道路1本ごとに切り替わります。'
      : (m.road === null
         ? '到達時間は道路単位では持っていないため、メッシュのまま表示しています。'
         : '道路表示。区に入るとその区のデータを読み込みます。');
}}

/* --- 操作 --- */
document.querySelectorAll('.mb').forEach(b=>b.onclick=()=>{{
  document.querySelectorAll('.mb').forEach(x=>x.removeAttribute('aria-pressed'));
  b.setAttribute('aria-pressed','true');
  metric = b.dataset.m; legend(); drawMesh(); drawRoads();
}});
const bsh=document.getElementById('bsh'), bar=document.getElementById('bar');
bsh.onclick=()=>{{ const on=bsh.ariaPressed!=='true'; bsh.ariaPressed=on?'true':'false';
  on?shLayer.addTo(map):map.removeLayer(shLayer); }};
bar.onclick=()=>{{ const on=bar.ariaPressed!=='true'; bar.ariaPressed=on?'true':'false';
  on?arLayer.addTo(map):map.removeLayer(arLayer); }};
function goWard(w){{ const b=D.bounds[w]; if(b) map.fitBounds([[b[0],b[1]],[b[2],b[3]]]); }}
document.getElementById('wsel').onchange=e=>{{ if(e.target.value) goWard(e.target.value); }};
document.querySelectorAll('#wtb tr').forEach(tr=>tr.onclick=()=>goWard(tr.dataset.ward));
document.getElementById('tg').onclick=e=>{{
  e.preventDefault(); document.getElementById('side').classList.toggle('hide');
  setTimeout(()=>map.invalidateSize(),60); }};
map.on('moveend zoomend', ()=>{{ drawMesh(); drawRoads(); }});
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
