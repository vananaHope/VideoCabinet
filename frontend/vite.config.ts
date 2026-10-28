import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { fileURLToPath, URL } from "node:url"
import { appName } from "./src/bridge-types"

export default defineConfig({
  base: "./",
  // 문서 제목은 생성된 표시 이름으로 빌드 때 넣어 첫 렌더 전부터 정한 이름을 보인다.
  plugins: [react(), tailwindcss(), { name: "app-name-title", transformIndexHtml: () => [{ tag: "title", children: appName, injectTo: "head" }] }],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: { outDir: "../src/my_video_manager/web", emptyOutDir: true },
})
