import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { buildContent, CONTENT_DIR, formatProblems } from "./scripts/content";

/** 開発中に content/*.yaml を保存したら、チェックしてすぐ画面に反映する */
function contentWatcher(): Plugin {
  return {
    name: "content-watcher",
    configureServer(server) {
      server.watcher.add(CONTENT_DIR);
      server.watcher.on("change", (file) => {
        if (!file.startsWith(CONTENT_DIR) || !file.endsWith(".yaml")) return;
        const result = buildContent();
        if (result.ok) server.config.logger.info("✅ 掲載情報を反映しました");
        else server.config.logger.error(formatProblems(result.problems));
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), contentWatcher()],
  server: {
    proxy: { "/api": "http://localhost:8787" },
  },
});
