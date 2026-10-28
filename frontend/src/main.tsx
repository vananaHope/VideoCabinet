import { createRoot } from "react-dom/client"
import App from "./App"
import "./index.css"

// 번들 글꼴(토큰 font-sans의 첫 이름) 중 첫 렌더용(font-display: block) 파일을 읽은 뒤 렌더해
// 대체 글꼴로 그렸다가 바뀌는 깜박임과 줄 높이 변화를 막는다. 나머지 음절 파일(swap)은 기다리지 않는다.
// 글꼴이 늦거나 실패해도 앱은 상한 시간 뒤 그대로 뜬다.
const FONT_WAIT_LIMIT_MS = 1000
const unquote = (name: string) => name.trim().replace(/^"|"$/g, "")
const family = unquote(getComputedStyle(document.documentElement).getPropertyValue("--font-sans").split(",")[0])
const firstFaces = [...document.fonts].filter(face => unquote(face.family) === family && face.display === "block")
const fontReady = Promise.all(firstFaces.map(face => face.load())).catch(() => undefined)
const fontLimit = new Promise(resolve => setTimeout(resolve, FONT_WAIT_LIMIT_MS))

void Promise.race([fontReady, fontLimit]).then(() => createRoot(document.getElementById("root")!).render(<App />))
