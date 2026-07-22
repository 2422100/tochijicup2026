# 東京23区 道幅・道路中心線データ基盤

国土地理院「基盤地図情報 基本項目」から、東京23区の**道路中心線**と
**局所道幅**を推定するパイプライン。避難ルーティングの基盤データを想定している。

外部APIに一切依存しない（OSMは使わない）。

---

## 成果物

| パス | 内容 |
|---|---|
| `03_network/edges_final_{区}.parquet` | **ルーティング用エッジ** u, v, length_m, width_m, bld_density, blockage_risk, dist_to_bld, barrier_cross, cost_general, cost_wheelchair, cost_quake, cost_quake_wc |
| `03_network/nodes_{区}.parquet` | ノード node_id + 座標 |
| `03_network/centerlines_{区}.parquet` | 道路中心線 + `width_m`（局所道幅, m）+ `ward` |
| `02_processed/_dem/` | DEM5A/5B ラスタ（2次メッシュ単位の .npy） |
| `reports/slope_by_ward.csv` | 区別の標高・勾配分布 |
| `02_processed/road_space_{区}.parquet` | 道路空間ポリゴン（可視化用） |
| `02_processed/blocks_{区}.parquet` | 街区ポリゴン |
| `02_processed/_bld/` | 建物ポリゴン 1,926,371棟（分割parquet。ディレクトリごと読む） |
| `02_processed/_rdedg/` | 道路縁 334,325本（分割parquet） |
| `02_processed/mesh250_bld_density.parquet` | 250mメッシュ建物密度 9,885セル |
| `02_processed/chocho.parquet` | 町丁目ポリゴン 3,263 |
| `02_processed/barriers.parquet` | 障壁（水涯線＋軌道）30,117 |
| `02_processed/wards23.parquet` | 23区境界 |
| `02_processed/water_areas.parquet` 他 | 水部・軌道・町丁目界などの整備済みレイヤ |
| **`reports/maps/index.html`** | **可視化の入口。ここを開く**（23区の俯瞰＋区別の対話地図） |
| `reports/maps/map_{区}.html` | 区ごとの対話地図（道幅・閉塞リスク・勾配を切替、クリックで詳細） |
| `reports/maps/ward_{区}.png` | 区ごとの静止画（3指標を並べたもの） |
| `reports/qc.md` | 品質レポート（**利用前に必読**） |
| `reports/width_by_ward.csv` | 区別の道幅分布 |

座標系はすべて **EPSG:6677**（平面直角座標系IX系）。

### 読み方

```python
import geopandas as gpd
cl = gpd.read_parquet("03_network/centerlines_荒川区.parquet")
cl["width_m"].median()          # 5.1
narrow = cl[cl["width_m"] < 4]  # 緊急車両が入りにくい区間
```

`centerlines_*` は 1m 格子上の短い線分の集合で位相を持たない中間生成物。
ルーティングには `edges_final_*` を使う。

### 経路探索

```python
import geopandas as gpd, networkx as nx
e = gpd.read_parquet("03_network/edges_final_荒川区.parquet")
G = nx.Graph()
for r in e.itertuples():
    G.add_edge(r.u, r.v, length=r.length_m,
               general=r.cost_general, wheelchair=r.cost_wheelchair)

nx.shortest_path(G, s, t, weight="general")      # 一般
nx.shortest_path(G, s, t, weight="wheelchair")   # 車椅子・要配慮者
```

コスト列は4つ:

| 列 | 用途 |
|---|---|
| `cost_general` | 平常時・一般 |
| `cost_wheelchair` | 平常時・車椅子・要配慮者 |
| `cost_quake` | **地震時**（倒壊閉塞リスクを加算） |
| `cost_quake_wc` | 地震時・車椅子 |

地震時モードは6.6%の遠回りで倒壊閉塞リスクを約1/3に下げる
（距離加重平均 0.210 → 0.066）。

23区合計 **694,712エッジ / 総延長 19,586 km**。
最大連結成分は平均でノードの87.1%（区によっては鉄道・運河で分断される。
江戸川区53.4%は原因未解明で要調査）。

重みは `scripts/config_weights.json` で調整でき、
`python 05_network.py --stage recost` で数秒で再計算できる
（空間結合をやり直さないため）。

---

## 手法

道路縁 `RdEdg` を polygonize すると得られるのは道路ではなく**街区**であり、
道路はその隙間である。したがって

```
道路空間 = 区ポリゴン − 街区 − 水部  ∩ (道路縁から25m以内)
（ただし道路縁の6m以内は水部でも残す＝橋を消さないため）
```

として道路空間を求め、これを 1m/px でラスタライズして

- 距離変換 (EDT) → 各画素の内接半径 ×2 = **局所道幅**
- 細線化 (skeletonize) → **中心線**

を得る。妥当性の検証は `reports/qc.md` を参照。

---

## パイプライン

```bash
pip install --break-system-packages geopandas shapely pyproj lxml numpy pandas \
  pyogrio pyarrow scipy scikit-image rasterio networkx matplotlib mapclassify

cd project/scripts
python 01_parse_fgd.py --skip-done      # GML → ftype別parquet
python 02_merge_clip.py                 # 結合・EPSG:6677投影・23区クリップ
python 03_width.py --stage blocks --skip-done   # 街区
python 03_width.py --stage space --skip-done    # 道路空間ポリゴン
python 03_width.py --stage lines  --skip-done   # 中心線 + 道幅
python 01_parse_fgd.py --item 11 --skip-done    # 建物
python 02_merge_clip.py                         # 建物の区クリップ
python 04_layers.py                             # 建物密度・町丁目・障壁
python 05_network.py --stage topology --skip-done   # ノード・エッジへ縮約
python 05_network.py --stage cost     --skip-done   # コスト付与
python 06_slope.py   --stage dem      --skip-done   # DEM → 標高ラスタ
python 06_slope.py   --stage slope    --skip-done   # 勾配を付与
python 05_network.py --stage recost                 # 勾配をコストに反映
python 07_maps.py    --stage overview               # 23区俯瞰PNG
python 07_maps.py    --stage ward_all               # 区別PNG
python 07_maps.py    --stage web_all --min-len 3    # 区別の対話地図HTML
python 07_maps.py    --stage index                  # 索引ページ
```

### 大きなファイルを書かないこと

マウント先の書き込みは**約5MB/秒**しか出ない。230MB級の単一parquetは
1回の実行(45秒)で書き切れず必ず破損する。建物のような大きなレイヤは
分割parquetのディレクトリとして持ち、`gpd.read_parquet(dir)` で読むこと。

### 実行環境の制約

処理は**中断・再開可能**に作ってある。1コールの実行時間が制限された環境
（Coworkのサンドボックスは45秒で強制終了）を前提としているため、
`--skip-done` を付けて**同じコマンドを完了するまで繰り返し実行**すればよい。

- `01_parse_fgd.py` … (メッシュ, 項目) 単位で完了マーカを持つ
- `03_width.py` … 区単位＋2kmタイル単位でキャッシュする。
  中断で壊れた parquet は自動検出して作り直す

---

## 現状と残作業

**01〜06 のパイプラインは23区分すべて完了**し、経路探索が動作する。
道幅・倒壊閉塞・勾配がすべてコストに反映されている。

残っているもの:
- **江戸川区の連結性(53.4%)** — 原因未解明。要調査
- 混雑(`w4`) — 人口データが必要
- 緊急輸送道路(`w5`) — 東京都の指定路線データが必要
- 倒壊閉塞のパラメータ（`debris_max_m` / `density_ref`）は未較正の仮定値

詳細は `RESUME.md`、品質と検証結果は `reports/qc.md` を参照。

---

## データ範囲の注意

当初 533937 / 533947 / 533957 が欠けており江戸川区が47.4%しか収録されて
いなかったが、追加取得して**解消済み**（現在97.9%）。

---

## データの入手（このリポジトリには含まれていません）

元データと中間・成果 parquet はリポジトリに含めていません。
基盤地図情報は国土地理院の利用規約があり再配布に配慮が必要なこと、
また parquet はスクリプトで再生成できるためです。

1. [基盤地図情報ダウンロードサービス](https://fgd.gsi.go.jp/download/menu.php)
   から、東京23区を覆う2次メッシュ **14枚** を取得する:

   ```
   533925 533926
   533934 533935 533936 533937
   533944 533945 533946 533947
   533954 533955 533956 533957
   ```

   - **基本項目**: 行政区画の境界線／道路縁／軌道の中心線／水涯線／
     建築物の外周線／町の境界線（＝項目 05/06/08/10/11/12）
   - **数値標高モデル**: DEM5A（5mメッシュ・航空レーザ測量）

2. 取得したZIPを **展開せず** に次の場所へ置く（ファイル名は不問。中身で判定する）:
   - 基本項目のZIP → リポジトリの1つ上の階層（`tokyoHackthon/` 直下）
   - DEMのZIP → `20_external/`

3. 上の「パイプライン」の手順で 01〜07 を実行する。

## ライセンス・出典

- 元データ: **国土地理院 基盤地図情報**（基本項目・数値標高モデル）。
  利用にあたっては[国土地理院の利用規約](https://www.gsi.go.jp/kikaku/kikaku40003.html)
  に従うこと。成果物を公開・配布する際は出典の明記が必要。
- 本リポジトリのコード: リポジトリの `LICENSE` を参照。
