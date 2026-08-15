# -*- coding: utf-8 -*-
"""
こどもぼうさいナビ — 単一HTMLの可視化

  reports/child_mesh.json   250mメッシュの到達時間 + 避難所
  reports/child_access.csv  区別サマリ
  reports/child_survey.json 福祉局調査（都全体の集計）
    ↓
  child_nav.html （リポジトリ直下。GitHub Pages でそのまま開ける）

配色の方針
  - 到達時間は連続量なので **単一色相の連続ランプ**（blue 600→100）。
    暗い地図の上で「近い＝暗い」が背景に沈まないよう、下端は step600 で止める。
  - 避難所は「識別」なのでカテゴリ色（orange）。ベビーカー可否は
    塗りつぶし／中抜きの形で区別し、色だけに意味を持たせない。
  - 備蓄率のバーは1系列なので1色（blue slot1）。
"""
import csv, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REP = os.path.join(ROOT, "reports")

# --- 単一色相の連続ランプ（暗背景用に 600→100 で使う）
RAMP = ["#184f95", "#256abf", "#2a78d6", "#3987e5", "#5598e7",
        "#6da7ec", "#86b6ef", "#9ec5f4", "#b7d3f6", "#cde2fb"]
BREAKS = [4, 6, 8, 10, 12, 15, 18, 22, 28]     # 分。RAMPは1つ多い
SERIES1 = "#3987e5"      # categorical slot1 (dark)
SERIES2 = "#d95926"      # categorical slot2 (dark) — 避難所
SURFACE = "#1a1a19"


def load():
    mesh = json.load(open(os.path.join(REP, "child_mesh.json"), encoding="utf-8"))
    survey = json.load(open(os.path.join(REP, "child_survey.json"), encoding="utf-8"))
    with open(os.path.join(REP, "child_access.csv"), encoding="utf-8") as f:
        acc = list(csv.DictReader(f))
    return mesh, survey, acc


def build():
    mesh, survey, acc = load()
    acc.sort(key=lambda r: -float(r["tmed_normal"]))

    rows = "\n".join(
        f'<tr><td>{r["ward"]}</td><td>{int(r["n_shelter"])}</td>'
        f'<td>{float(r["tmed_normal"]):.1f}</td>'
        f'<td>{float(r["t90_normal"]):.1f}</td>'
        f'<td>{float(r["tmed_quake"]):.1f}</td>'
        f'<td>{float(r["worsen_pct"]):+.1f}</td></tr>'
        for r in acc)

    sup = survey["supplies"]
    bars = "\n".join(
        f'<div class="bar"><span class="bl">{s["label"]}</span>'
        f'<span class="bt"><i style="width:{max(s["pct"],0.6):.1f}%"></i></span>'
        f'<span class="bv">{s["pct"]}%</span></div>' for s in sup)

    ops = [o for o in survey["operation"]
           if any(k in o["label"] for k in ("妊婦", "育児", "子ども", "プライバシー"))]
    oprows = "\n".join(
        f'<div class="bar"><span class="bl">{o["label"]}</span>'
        f'<span class="bt"><i style="width:{max(o["pct"],0.6):.1f}%"></i></span>'
        f'<span class="bv">{o["pct"]}%</span></div>' for o in ops)

    sh = survey["shelter"]
    n_sh = len(mesh["shelters"])
    n_slope = sum(1 for s in mesh["shelters"] if s[3])
    tmed_all = sorted(float(r["tmed_normal"]) for r in acc)
    med = tmed_all[len(tmed_all)//2]

    # 連続量なので階級ごとにラベルを打たず、色は連続バー、目盛りだけ間引いて出す
    swatches = "".join(f'<i style="background:{c}"></i>' for c in RAMP)
    ticks = "".join(
        f'<span style="flex:1;text-align:{"left" if i==0 else "center"}">{t}</span>'
        for i, t in enumerate(["近い", str(BREAKS[3]) + "分",
                               str(BREAKS[6]) + "分", str(BREAKS[-1]) + "分以上"]))
    legend = (f'<div class="ramp">{swatches}</div>'
              f'<div class="ticks">{ticks}</div>')

    html = f"""<!DOCTYPE html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>こどもぼうさいナビ — 東京23区</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 :root{{--surface:{SURFACE};--s2:#232322;--ink:#ffffff;--ink2:#c3c2b7;
   --ink3:#8b8a82;--line:#33332f;--s1:{SERIES1};--s2c:{SERIES2}}}
 *{{box-sizing:border-box}}
 body{{background:var(--surface);color:var(--ink);margin:0 auto;max-width:1180px;
   padding:26px 20px 70px;font-family:"Noto Sans JP",system-ui,sans-serif;
   line-height:1.7}}
 h1{{font-size:26px;margin:0 0 4px;letter-spacing:.01em}}
 h2{{font-size:17px;margin:38px 0 6px}}
 p{{color:var(--ink2);font-size:14px;margin:6px 0}}
 .sub{{color:var(--ink3);font-size:13px}}
 .tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));
   gap:12px;margin-top:18px}}
 .tile{{background:var(--s2);border:1px solid var(--line);border-radius:10px;
   padding:15px 16px}}
 .tile b{{display:block;font-size:31px;font-weight:650;letter-spacing:-.01em}}
 .tile span{{color:var(--ink2);font-size:13px}}
 .tile em{{color:var(--ink3);font-size:12px;font-style:normal;display:block;
   margin-top:5px}}
 #map{{height:560px;border-radius:10px;margin-top:10px;border:1px solid var(--line);
   background:#111318}}
 .ctl{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px}}
 button{{background:var(--s2);color:var(--ink2);border:1px solid var(--line);
   border-radius:7px;padding:7px 13px;font-size:13px;cursor:pointer;
   font-family:inherit}}
 button[aria-pressed=true]{{background:var(--s1);color:#fff;border-color:var(--s1)}}
 .lgs{{display:flex;align-items:center;gap:2px;flex-wrap:wrap;margin-top:10px;
   font-size:11px;color:var(--ink3)}}
 .lg{{display:flex;align-items:center;gap:3px;margin-right:4px}}
 .lg i{{width:20px;height:10px;border-radius:2px;display:inline-block}}
 .rampwrap{{max-width:430px;margin-top:12px}}
 .ramp{{display:flex;height:11px;border-radius:3px;overflow:hidden}}
 .ramp i{{flex:1}}
 .ticks{{display:flex;font-size:11px;color:var(--ink3);margin-top:3px}}
 table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}}
 th,td{{padding:7px 9px;border-bottom:1px solid var(--line);text-align:right}}
 th{{color:var(--ink3);font-weight:600;position:sticky;top:0;
   background:var(--surface)}}
 td:first-child,th:first-child{{text-align:left}}
 .bar{{display:grid;grid-template-columns:150px 1fr 52px;align-items:center;
   gap:9px;margin:5px 0;font-size:13px}}
 .bl{{color:var(--ink2)}}
 .bt{{background:#2a2a28;border-radius:4px;height:16px;overflow:hidden}}
 .bt i{{display:block;height:100%;background:var(--s1);border-radius:0 4px 4px 0}}
 .bv{{color:var(--ink);text-align:right;font-variant-numeric:tabular-nums}}
 .note{{background:#241f1a;border-left:3px solid var(--s2c);padding:12px 15px;
   border-radius:6px;font-size:13px;color:var(--ink2);margin-top:12px}}
 .leaflet-popup-content-wrapper,.leaflet-popup-tip{{background:var(--s2);
   color:var(--ink)}}
 .leaflet-popup-content{{font-size:13px;line-height:1.6}}
 a{{color:#6fb5ff}}
</style>

<h1>こどもぼうさいナビ</h1>
<p>東京23区で、<b>ベビーカーを押して最寄りの避難所にたどり着くまで</b>を推定した地図です。
道幅・勾配・建物倒壊による閉塞を考慮し、幼児連れの歩行速度で所要時間を出しています。</p>

<div class="tiles">
 <div class="tile"><b>{sh['pct']}%</b><span>妊産婦・乳幼児を想定した避難所がある自治体</span>
   <em>都内62自治体中{sh['yes']}。残り{sh['no']}は想定なし</em></div>
 <div class="tile"><b>{sup[0]['pct']}%</b><span>{sup[0]['label']}を備蓄している自治体</span>
   <em>毛布は100%。乳幼児用になると一桁になる</em></div>
 <div class="tile"><b>{100*n_slope//n_sh}%</b><span>スロープ等がある避難所</span>
   <em>23区の避難所{n_sh:,}か所のうち{n_slope}</em></div>
 <div class="tile"><b>{med:.0f}分</b><span>最寄り避難所までの所要時間（区の中央値の中央値）</span>
   <em>幼児連れ・徒歩{2.5}km/h想定</em></div>
</div>

<h2>どこが遠いか</h2>
<p class="sub">250mメッシュごとの「最寄り避難所までの所要時間」。
明るいほど遠い。避難所のピンをクリックすると設備が出ます。</p>
<div class="ctl">
  <button id="bn" aria-pressed="true">平常時</button>
  <button id="bq" aria-pressed="false">地震時（倒壊閉塞あり）</button>
  <button id="bs" aria-pressed="true">避難所を表示</button>
</div>
<div class="rampwrap">{legend}</div>
<div id="map"></div>
<div class="lgs" style="margin-top:8px">
  <span class="lg"><i style="background:{SERIES2};border-radius:50%;width:11px;height:11px"></i>
   スロープ等あり（ベビーカーで入りやすい）</span>
  <span class="lg"><i style="border:2px solid {SERIES2};border-radius:50%;width:11px;height:11px"></i>
   スロープ等の記載なし</span>
</div>

<h2>区別の到達時間</h2>
<p class="sub">所要時間の長い順。90%タイルは「区内の9割がこの時間以内」という意味です。</p>
<table>
<tr><th>区</th><th>避難所</th><th>中央値 分</th><th>90%タイル 分</th>
<th>地震時 中央値 分</th><th>悪化率 %</th></tr>
{rows}
</table>

<h2>避難所に何が置いてあるか</h2>
<p class="sub">東京都福祉局の調査（都内62自治体）。備蓄率の低い順。
<b>この調査は自治体名を含まない集計値</b>なので、上の地図とは結合できません。
「東京都全体として何が足りないか」を示すものです。</p>
{bars}

<h2>避難所の運営で用意されているもの</h2>
<p class="sub">「あり」と答えた自治体の割合（62自治体中）。</p>
{oprows}

<div class="note">
<b>この地図の限界。</b>
避難所の乳幼児対応（授乳室・おむつ交換台・粉ミルク）は公開データに無いため、
ピンの色分けは<b>バリアフリー設備（スロープ・エレベータ）からの推定</b>です。
所要時間は幼児連れ2.5km/hを基準に道幅と勾配で減速させた粗いモデルで、
信号待ち・混雑・子どもの疲労は含みません。倒壊閉塞リスクは建蔽率を
建物高さの代理変数にした未較正の推定値です。避難所データの基準日は令和3年4月1日、
福祉局調査は都内62自治体を対象としたものです。
</div>

<p class="sub" style="margin-top:26px">
出典: <a href="https://catalog.data.metro.tokyo.lg.jp/dataset/t000003d0000000093">東京都防災マップ 避難所・避難場所一覧データ</a>（東京都総務局, CC BY） /
<a href="https://catalog.data.metro.tokyo.lg.jp/dataset/t000054d0000000064">都内区市町村の妊婦・乳幼児に関連した防災対策調査結果</a>（東京都福祉局, CC BY） /
道路網は<a href="https://fgd.gsi.go.jp/download/menu.php">国土地理院 基盤地図情報</a>から生成。
<a href="index.html">道路データ基盤のトップへ</a>
</p>

<script>
const D = {json.dumps({"mesh": mesh}, ensure_ascii=False, separators=(",", ":"))};
const RAMP = {json.dumps(RAMP)}, BREAKS = {json.dumps(BREAKS)};
const M = D.mesh, HALF = M.mesh_m / 2;

const map = L.map('map', {{preferCanvas:true}}).setView([35.702,139.75], 11);
// メッシュ専用のペインを避難所ピンより下に置く。同じペインだと
// 表示を切り替えるたびに描き直したメッシュがピンの上に乗ってしまう
map.createPane('meshPane');
map.getPane('meshPane').style.zIndex = 350;
L.tileLayer("https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png",
  {{maxZoom:18, attribution:'&copy; OpenStreetMap, &copy; CARTO'}}).addTo(map);

function color(t){{
  for (let i=0;i<BREAKS.length;i++) if (t < BREAKS[i]) return RAMP[i];
  return RAMP[RAMP.length-1];
}}
// 緯度1度=約111.32km。メッシュは平面直角座標系で切っているので、
// 表示用に度へ戻す近似で十分（250m格子の描画誤差は無視できる）
const dLat = HALF/111320;
const meshLayer = L.layerGroup().addTo(map);
let mode = 'n';
function drawMesh(){{
  meshLayer.clearLayers();
  const idx = mode==='n' ? 2 : 3;
  for (const c of M.cells){{
    const dLon = HALF/(111320*Math.cos(c[0]*Math.PI/180));
    L.rectangle([[c[0]-dLat,c[1]-dLon],[c[0]+dLat,c[1]+dLon]],
      {{stroke:false, fillColor:color(c[idx]), fillOpacity:0.72,
        interactive:true, pane:'meshPane'}})
     .bindTooltip(M.wards[c[4]]+'　平常 '+c[2]+'分 / 地震時 '+c[3]+'分',
                  {{sticky:true}})
     .addTo(meshLayer);
  }}
}}
drawMesh();

// 1,538点あるので、引いたときは小さく打つ。等倍のままだと面が見えなくなる
function shRadius(z){{ return z<=11 ? 2 : (z<=13 ? 3.5 : 6); }}
const shLayer = L.layerGroup().addTo(map), shMarks = [];
for (const s of M.shelters){{
  const ok = s[3]===1;
  const mk = L.circleMarker([s[0],s[1]],
    {{radius: shRadius(map.getZoom()), color:'{SERIES2}',
      weight: 1.5, fillColor: ok ? '{SERIES2}' : '{SURFACE}', fillOpacity:1}})
   .bindPopup('<b>'+s[2]+'</b><br>スロープ等: '+(s[3]?'あり':'記載なし')
     +'<br>EV・避難スペース1階: '+(s[4]?'あり':'記載なし')
     +'<br>車椅子対応トイレ: '+(s[5]?'あり':'記載なし'));
  mk.addTo(shLayer); shMarks.push(mk);
}}
map.on('zoomend', ()=>{{
  const r = shRadius(map.getZoom());
  for (const m of shMarks) m.setRadius(r);
}});

const bn=document.getElementById('bn'), bq=document.getElementById('bq'),
      bs=document.getElementById('bs');
bn.onclick=()=>{{mode='n';bn.ariaPressed='true';bq.ariaPressed='false';drawMesh();}};
bq.onclick=()=>{{mode='q';bn.ariaPressed='false';bq.ariaPressed='true';drawMesh();}};
bs.onclick=()=>{{
  const on = bs.ariaPressed!=='true';
  bs.ariaPressed = on?'true':'false';
  if(on) shLayer.addTo(map); else map.removeLayer(shLayer);
}};
</script>
</html>
"""
    p = os.path.join(ROOT, "child_nav.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"-> {p}  ({os.path.getsize(p)/1e6:.2f} MB)")


if __name__ == "__main__":
    build()
