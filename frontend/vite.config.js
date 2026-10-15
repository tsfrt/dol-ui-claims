import { defineConfig } from "vite";

export default defineConfig({
  base: "/",
  esbuild: { jsx: "automatic" },
  build: { outDir: "dist", chunkSizeWarningLimit: 1500 },
  server: { proxy: { "/api": "http://localhost:8000" } },
});
