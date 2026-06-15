import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const backendPort = process.env.WEBUI_PORT || "8765";

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      "/api": `http://127.0.0.1:${backendPort}`,
    },
  },
});
