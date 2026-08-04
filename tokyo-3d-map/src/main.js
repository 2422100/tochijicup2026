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

// コンパスをドラッグして視点の方角を変える
const CENTER_LON = 139.767;
const CENTER_LAT = 35.681;
const OFFSET = 0.01; // 中心からカメラを離す距離（度）
const CAMERA_HEIGHT = 400;
const PITCH = Cesium.Math.toRadians(-25);
const LAT_CORRECTION = Math.cos(Cesium.Math.toRadians(CENTER_LAT));

const compassDial = document.getElementById("compassDial");
let isDragging = false;

function updateCameraByBearing(bearingDeg) {
  const bearingRad = Cesium.Math.toRadians(bearingDeg);
  const latOffset = OFFSET * Math.cos(bearingRad);
  const lonOffset = (OFFSET * Math.sin(bearingRad)) / LAT_CORRECTION;
  const heading = (bearingDeg + 180) % 360;

  viewer.camera.setView({
    destination: Cesium.Cartesian3.fromDegrees(
      CENTER_LON + lonOffset,
      CENTER_LAT + latOffset,
      CAMERA_HEIGHT
    ),
    orientation: {
      heading: Cesium.Math.toRadians(heading),
      pitch: PITCH,
    },
  });
}

function angleFromCenter(event) {
  const rect = compassDial.getBoundingClientRect();
  const centerX = rect.left + rect.width / 2;
  const centerY = rect.top + rect.height / 2;
  const dx = event.clientX - centerX;
  const dy = event.clientY - centerY;
  // 0度=真上(北)、時計回りに増加
  let angle = (Math.atan2(dx, -dy) * 180) / Math.PI;
  if (angle < 0) angle += 360;
  return angle;
}

function setCompassRotation(angleDeg) {
  compassDial.style.transform = `rotate(${angleDeg}deg)`;
}

compassDial.addEventListener("pointerdown", (event) => {
  isDragging = true;
  compassDial.setPointerCapture(event.pointerId);
});

compassDial.addEventListener("pointermove", (event) => {
  if (!isDragging) return;
  const angle = angleFromCenter(event);
  setCompassRotation(angle);
  updateCameraByBearing(angle);
});

compassDial.addEventListener("pointerup", (event) => {
  isDragging = false;
  compassDial.releasePointerCapture(event.pointerId);
});