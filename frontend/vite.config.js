import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // java-backend(Spring Boot, :8081)로 프록시. Python(FastAPI, :8000)과 API 계약이
      // 동일하므로 그쪽에 붙이려면 이 값만 8000으로 바꾸면 된다.
      "/api": "http://localhost:8081",
    },
  },
});
