import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const backend = "http://127.0.0.1:19899";
const proxied = ["/studio", "/upload", "/trace", "/traces", "/control", "/user_interaction", "/stdout"];

export default defineConfig({
  // Served by the Flask log server from git_ignore_folder/static/app/ in production.
  base: "/app/",
  plugins: [react(), tailwindcss()],
  build: { outDir: "../git_ignore_folder/static/app", emptyOutDir: true },
  server: { proxy: Object.fromEntries(proxied.map((route) => [route, { target: backend, changeOrigin: true }])) },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
