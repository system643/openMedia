import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Deux pages : la fenêtre principale et la bulle (widget toujours au-dessus).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  clearScreen: false,
  server: { port: 1427, strictPort: true, watch: { ignored: ["**/src-tauri/**", "**/backend/**"] } },
  build: {
    target: "es2022",
    rollupOptions: {
      input: { main: "index.html", bulle: "bulle.html" },
    },
  },
});
