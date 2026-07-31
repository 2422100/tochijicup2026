import { defineConfig } from "vite";
import cesium from "vite-plugin-cesium";

export default defineConfig({
  // GitHub Pagesに出す時は、リポジトリ名に合わせて '/リポジトリ名/' に変更してください
  // 例: https://ユーザー名.github.io/tokyo-3d-map/ で公開するなら base: '/tokyo-3d-map/'
  base: "./",
  plugins: [cesium()],
});
