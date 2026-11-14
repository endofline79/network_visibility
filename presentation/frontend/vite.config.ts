import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const dir = new URL(".", import.meta.url);
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", proxy: { "/api": "http://127.0.0.1:8096" } },
  build: {
    sourcemap: false,
    rollupOptions: {
      input: {
        main: new URL("index.html", dir).pathname,
        legacy: new URL("legacy.html", dir).pathname,
      },
    },
  },
});
