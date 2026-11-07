import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.KRUVIM_API_URL || "http://127.0.0.1:8000", changeOrigin: true } },
  },
  preview: {
    port: 4173,
    proxy: { "/api": { target: process.env.KRUVIM_API_URL || "http://127.0.0.1:8000", changeOrigin: true } },
  },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          // Let Rollup split feature dependencies automatically. Grouping entire
          // dependency trees put shared helpers into charts/markdown, making
          // the entry point download those libraries on every page.
        },
      },
    },
  },
});
