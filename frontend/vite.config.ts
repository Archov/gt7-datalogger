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
    // Listen on all interfaces (IPv4 loopback included — hosts-file aliases
    // like gt.traefik.test resolve to 127.0.0.1) and on the LAN for phones.
    host: true,
    // Allow custom hosts-file aliases (e.g. streaming apps that reject raw
    // IPs/localhost). Vite otherwise blocks unknown Host headers.
    allowedHosts: [".test", ".local"],
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
