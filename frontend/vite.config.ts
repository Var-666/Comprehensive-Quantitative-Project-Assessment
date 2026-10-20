import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
import { readFileSync } from "node:fs";

export default defineConfig(({ mode }) => ({
  plugins: [vue()],
  server: {
    https: process.env.VITE_TLS_CERT_FILE && process.env.VITE_TLS_KEY_FILE ? {cert:readFileSync(process.env.VITE_TLS_CERT_FILE),key:readFileSync(process.env.VITE_TLS_KEY_FILE)} : undefined,
    port: 5173,
    strictPort: true,
    proxy: {
      "/api":
        loadEnv(mode, ".", "").API_PROXY_TARGET || "http://127.0.0.1:8000",
    },
  },
}));
