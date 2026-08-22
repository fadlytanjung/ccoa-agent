import { fileURLToPath, URL } from "node:url";

import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // shadcn/ui components are copied into this repo and import each other as
    // "@/components/ui/…" — the alias is what makes those files droppable as-is.
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    // Explicit, not "localhost": on macOS that resolves to ::1 first, so a tool
    // checking http://127.0.0.1:5173 — Playwright's webServer, curl, a container
    // health check — sees connection refused while a browser works fine.
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    // Same-origin in development, exactly as it is behind the ALB in AWS. Proxying
    // rather than pointing at http://localhost:8000 means CORS is never in the picture
    // and the code path under test is the deployed one (docs/06 §3.9).
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/healthz": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    rollupOptions: {
      output: {
        // Split the dependencies that never change from the application code that does,
        // so a deploy re-downloads a few kilobytes rather than the whole bundle. These
        // three move on completely different schedules.
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          motion: ["framer-motion"],
          data: ["@tanstack/react-query", "oidc-client-ts"],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    // Playwright owns e2e/; vitest must not try to run those specs.
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
  },
});
