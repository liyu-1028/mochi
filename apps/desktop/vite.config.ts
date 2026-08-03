import { cpSync, existsSync, readFileSync, statSync } from "node:fs";
import { extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const SKINS_DIR = resolve(fileURLToPath(new URL("../../assets/skins", import.meta.url)));

const CONTENT_TYPES: Record<string, string> = {
  ".json": "application/json",
  ".moc3": "application/octet-stream",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
};

/**
 * 把仓库根 assets/skins/（许可隔离区，见 assets/README.md）以 /skins/* 提供给前端：
 * dev 走中间件直读，build 时整体拷入产物（Tauri 打包随包分发）。
 */
function skinAssets(): Plugin {
  let outDir = "";
  return {
    name: "mochi:skin-assets",
    configResolved(config) {
      outDir = config.build.outDir;
    },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (!req.url?.startsWith("/skins/")) return next();
        const rel = decodeURIComponent(req.url.slice("/skins/".length).split("?")[0]);
        const file = resolve(SKINS_DIR, rel);
        if (!file.startsWith(SKINS_DIR) || !existsSync(file) || !statSync(file).isFile()) {
          return next();
        }
        res.setHeader("content-type", CONTENT_TYPES[extname(file)] ?? "application/octet-stream");
        res.end(readFileSync(file));
      });
    },
    writeBundle() {
      if (existsSync(SKINS_DIR)) {
        cpSync(SKINS_DIR, join(outDir, "skins"), { recursive: true });
      }
    },
  };
}

// Tauri 开发模式固定端口；envPrefix 保留 TAURI_ENV_* 供 Rust 侧构建判断
export default defineConfig({
  plugins: [react(), skinAssets()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
  },
  envPrefix: ["VITE_", "TAURI_ENV_*"],
  build: {
    // Tauri 目标基于 Chromium/WebKit，可用较新语法
    target: "es2022",
    sourcemap: !!process.env.TAURI_ENV_DEBUG,
    // pixi.js v6 体积较大，但桌面应用本地加载无需在意包体
    chunkSizeWarningLimit: 1000,
  },
});
