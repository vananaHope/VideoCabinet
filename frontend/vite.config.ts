import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { fileURLToPath, URL } from "node:url"
import { appName } from "./src/bridge-types"

export default defineConfig({
  base: "./",
  // 문서 제목은 생성된 표시 이름으로 빌드 때 넣어 첫 렌더 전부터 정한 이름을 보인다.
  plugins: [react(), tailwindcss(), { name: "app-name-title", transformIndexHtml: () => [{ tag: "title", children: appName, injectTo: "head" }] },
    // 첫 렌더용 글꼴(부분 집합 파일)을 문서 머리에서 미리 읽어 스크립트 실행과 겹친다. main.tsx는 이 읽기가 끝나기를 기다려 첫 렌더를 한다.
    // 나머지 음절용 전체 파일은 미리 읽지 않는다. 앱은 file:// 문서라 글꼴 요청이 CORS 모드가 아니다.
    // crossorigin을 붙이면 미리 읽은 것을 못 써 같은 파일을 두 번 읽는다.
    { name: "font-preload", transformIndexHtml: { order: "post", handler: (_, context) => Object.keys(context.bundle ?? {}).filter(name => /\.subset-[^/]+\.woff2$/.test(name))
      .map(name => ({ tag: "link", attrs: { rel: "preload", as: "font", type: "font/woff2", href: `./${name}` }, injectTo: "head-prepend" })) } }],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: { outDir: "../src/my_video_manager/web", emptyOutDir: true },
})
