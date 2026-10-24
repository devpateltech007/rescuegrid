import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteStaticCopy } from "vite-plugin-static-copy";

// Cesium static assets (workers, widgets CSS) are copied to /cesium and CESIUM_BASE_URL points there.
const cesiumSource = "node_modules/cesium/Build/Cesium";

export default defineConfig({
  plugins: [
    react(),
    viteStaticCopy({
      targets: [
        { src: `${cesiumSource}/Workers`, dest: "cesium" },
        { src: `${cesiumSource}/ThirdParty`, dest: "cesium" },
        { src: `${cesiumSource}/Assets`, dest: "cesium" },
        { src: `${cesiumSource}/Widgets`, dest: "cesium" },
      ],
    }),
  ],
  define: { CESIUM_BASE_URL: JSON.stringify("/cesium") },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  build: { chunkSizeWarningLimit: 6000, sourcemap: false },
});
