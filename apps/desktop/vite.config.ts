import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri 开发模式固定端口；envPrefix 保留 TAURI_ENV_* 供 Rust 侧构建判断
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
  },
  envPrefix: ["VITE_", "TAURI_ENV_"],
  build: {
    // Tauri 目标基于 Chromium/WebKit，可用较新语法
    target: "es2022",
    sourcemap: !!process.env.TAURI_ENV_DEBUG,
  },
});
