import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { readFileSync } from "node:fs"
import { fileURLToPath, URL } from "node:url"
import { appName } from "./src/bridge-types"

// Qt(재생 화면·트레이 메뉴·공용 경고)는 woff2를 읽지 못하므로 같은 글꼴의 정적 TrueType을 web/qt-fonts/에 이름 그대로 둔다.
// 같은 패키지의 otf(CFF)는 Qt 기본 힌팅에서 12~14px 한글 가로획(으·그의 ㅡ)이 사라져 힌팅된 ttf를 쓴다.
// 계열 이름과 굵기는 web_tokens.json(font-sans 첫 이름, bundled-font)에서 온다. theme.py가 이 파일들을 Qt 글꼴 데이터베이스에 등록한다.
const tokens = JSON.parse(readFileSync(new URL("../src/my_video_manager/web_tokens.json", import.meta.url), "utf8")) as {
  typography: { "font-sans": string }, "bundled-font": { weights: Record<string, string> } }
const fontFamily = tokens.typography["font-sans"].split(",")[0].trim().replace(/^"|"$/g, "")
const qtFonts = Object.values(tokens["bundled-font"].weights).map(stem => `${fontFamily}-${stem}.ttf`)

export default defineConfig({
  base: "./",
  // 문서 제목은 생성된 표시 이름으로 빌드 때 넣어 첫 렌더 전부터 정한 이름을 보인다.
  plugins: [react(), tailwindcss(), { name: "app-name-title", transformIndexHtml: () => [{ tag: "title", children: appName, injectTo: "head" }] },
    // 첫 렌더용 글꼴(부분 집합 파일)을 문서 머리에서 미리 읽어 스크립트 실행과 겹친다. main.tsx는 이 읽기가 끝나기를 기다려 첫 렌더를 한다.
    // 그 밖의 글자용 전체 파일은 미리 읽지 않는다. tests/test_bundled_font.py가 미리 읽는 파일과 block face 파일이 같은지 본다. 앱은 file:// 문서라 글꼴 요청이 CORS 모드가 아니다.
    // crossorigin을 붙이면 미리 읽은 것을 못 써 같은 파일을 두 번 읽는다.
    { name: "font-preload", transformIndexHtml: { order: "post", handler: (_, context) => Object.keys(context.bundle ?? {}).filter(name => /\.subset-[^/]+\.woff2$/.test(name))
      .map(name => ({ tag: "link", attrs: { rel: "preload", as: "font", type: "font/woff2", href: `./${name}` }, injectTo: "head-prepend" })) } },
    { name: "qt-fonts", apply: "build", generateBundle() {
      for (const name of qtFonts) this.emitFile({ type: "asset", fileName: `qt-fonts/${name}`,
        source: readFileSync(new URL(`./node_modules/pretendard/dist/public/static/alternative/${name}`, import.meta.url)) })
    } }],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: { outDir: "../src/my_video_manager/web", emptyOutDir: true },
})
