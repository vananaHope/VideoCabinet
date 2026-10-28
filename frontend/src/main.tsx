import { createRoot } from "react-dom/client"
import App from "./App"
import "./index.css"

// 번들 글꼴(토큰 font-sans)을 읽은 뒤 첫 렌더를 해 대체 글꼴로 그렸다가 바뀌는 깜박임과 줄 높이 변화를 막는다.
// 글꼴이 늦거나 실패해도 앱은 상한 시간 뒤 그대로 뜬다.
const FONT_WAIT_LIMIT_MS = 1000
const fontSans = getComputedStyle(document.documentElement).getPropertyValue("--font-sans")
const fontReady = document.fonts.load(`1em ${fontSans}`).catch(() => undefined)
const fontLimit = new Promise(resolve => setTimeout(resolve, FONT_WAIT_LIMIT_MS))

void Promise.race([fontReady, fontLimit]).then(() => createRoot(document.getElementById("root")!).render(<App />))
