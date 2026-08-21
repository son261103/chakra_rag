import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy: /api/* → backend FastAPI ở localhost:8000, khỏi lo CORS khi dev.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
