import * as Cesium from "cesium";

Cesium.Ion.defaultAccessToken = import.meta.env.VITE_CESIUM_TOKEN;

const statusEl = document.getElementById("status");

const viewer = new Cesium.Viewer("cesiumContainer", {
  terrain: Cesium.Terrain.fromWorldTerrain(),
  timeline: false,
  animation: false,
  baseLayerPicker: false,
  geocoder: false,
  sceneModePicker: false,
  navigationHelpButton: false,
});

// 東京駅付近を初期表示位置にする
viewer.camera.flyTo({
  destination: Cesium.Cartesian3.fromDegrees(139.767, 35.681, 1200),
  orientation: {
    heading: Cesium.Math.toRadians(20),
    pitch: Cesium.Math.toRadians(-30),
  },
});

viewer.imageryLayers.removeAll();
viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#e8eaed");

async function loadJapanBuildings() {
  try {
    // Cesium ion上の "Japan 3D Buildings"（PLATEAUの全国建物データを統合したタイルセット）
    // Asset ID: 2602291
    const tileset = await Cesium.Cesium3DTileset.fromIonAssetId(2602291);
    tileset.maximumScreenSpaceError = 128; // デフォルトは16。数値を上げると軽くなる。
    tileset.colorBlendMode = Cesium.Cesium3DTileColorBlendMode.REPLACE;
    tileset.style = new Cesium.Cesium3DTileStyle({
      color: "color('#d5d5d5')",
    });
    viewer.scene.primitives.add(tileset);
    statusEl.textContent = "3D建物モデルを表示中（PLATEAU / Japan 3D Buildings）";
  } catch (error) {
    console.error(error);
    statusEl.textContent =
      "建物モデルの読み込みに失敗しました。Cesium ionのトークンを確認してください。";
  }
}

loadJapanBuildings();
