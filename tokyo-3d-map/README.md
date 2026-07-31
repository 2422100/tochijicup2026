# 東京都 3Dマップ プロトタイプ

CesiumJS + PLATEAU（Cesium ion上の "Japan 3D Buildings" アセット）で
東京都の3D建物モデルを表示する最小構成のプロトタイプ

## セットアップ

```bash
npm install
```

## Cesium ionトークンの設定

1. https://ion.cesium.com/ で無料アカウントを作成
2. ログイン後、右上メニューの「Access Tokens」を開く
3. デフォルトトークンをコピー
4. `tokyo-3d-map/.venv` を作成し 、`VITE_CESIUM_TOKEN={コピーしたトークン}` を追記

## 開発サーバーの起動

```bash
npm run dev
```

表示されたURL（通常 http://localhost:5173）をブラウザで開くと、
東京駅付近の3D建物モデルが表示される

## GitHub Pagesへのデプロイ（将来的に行う場合のメモ）

1. `vite.config.js` の `base` を、実際のリポジトリ名に合わせて変更する
   例: `https://ユーザー名.github.io/tokyo-3d-map/` で公開するなら
   `base: '/tokyo-3d-map/'`
2. `npm run build` で `dist/` フォルダを生成
3. `dist/` の中身を `gh-pages` ブランチ、または GitHub Actions で
   GitHub Pages用に公開する

## 今後の拡張ポイント（チームの分析結果と繋ぐ場所）

- `src/main.js` の `loadJapanBuildings()` の中で、建物ごとのリスクスコアを
  持つJSON（例: `{ buildingId: string, score: number }[]`）を読み込み、
  `tileset.style = new Cesium.Cesium3DTileStyle({...})` で建物の色分けを行う
- 避難所・避難路・危険エリアなどのGeoJSONは
  `Cesium.GeoJsonDataSource.load('path/to/data.geojson')` で読み込んで
  `viewer.dataSources.add(...)` すれば地図に重ねられる
