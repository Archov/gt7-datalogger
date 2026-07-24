import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: { echarts: ["echarts"] },
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
