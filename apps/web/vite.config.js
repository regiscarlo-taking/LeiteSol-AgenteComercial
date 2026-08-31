import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
    plugins: [react()],
    server: {
        host: "0.0.0.0",
        port: 3000,
        strictPort: true,
        proxy: {
            "/health": "http://localhost:3001",
            "/api": "http://localhost:3001",
        },
    },
    preview: {
        host: "0.0.0.0",
        port: 3000,
        strictPort: true,
    },
});
