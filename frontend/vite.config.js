import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 백엔드(FastAPI, uvicorn --port 8000)로 프록시
      "/api": "http://localhost:8000",
    },
  },
});
