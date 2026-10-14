import type { DetailsData, LibraryData } from "./bridge-types"

type Signal<T> = { connect: (handler: (value: T) => void) => void; disconnect: (handler: (value: T) => void) => void }
type Reply = (json: string) => void
export interface Bridge {
  ready: (reply: Reply) => void
  snapshot: (reply: Reply) => void
  filter: (query: string, tag: number, reply: Reply) => void
  select: (id: number, reply: Reply) => void
  details: (id: number, reply: Reply) => void
  action: (name: string, id: number, reply: Reply) => void
  changed: Signal<string>
  detailsChanged: Signal<number>
  focusRequested: Signal<string>
  error: Signal<string>
}
declare global {
  interface Window {
    qt?: { webChannelTransport: unknown }
    QWebChannel: new (transport: unknown, callback: (channel: { objects: { library: Bridge } }) => void) => unknown
  }
}

export function connectBridge(): Promise<Bridge> {
  return new Promise((resolve, reject) => {
    if (!window.qt || !window.QWebChannel) {
      reject(new Error("Qt 앱에서 라이브러리를 열어 주세요. 개발 서버는 MVM_WEB_DEV_URL로 연결합니다."))
      return
    }
    new window.QWebChannel(window.qt.webChannelTransport, channel => resolve(channel.objects.library))
  })
}

export function request<T>(invoke: (reply: Reply) => void): Promise<T> {
  return new Promise((resolve, reject) => invoke(json => {
    try {
      const result = JSON.parse(json)
      if (result.error) reject(new Error(result.error))
      else resolve(result as T)
    } catch (error) { reject(error) }
  }))
}
export const getSnapshot = (bridge: Bridge) => request<LibraryData>(reply => bridge.snapshot(reply))
export const getDetails = (bridge: Bridge, id: number) => request<DetailsData>(reply => bridge.details(id, reply))

export const actions = [
  ["play", "재생"], ["tags", "태그 편집"], ["subtitles", "자막 만들기 / 원어 지정"],
  ["review", "자막 검수 / SRT 내보내기"], ["series", "시리즈 편집"],
  ["rename", "제목 변경"], ["reconnect", "파일 다시 연결"], ["exclude", "제외"],
] as const
export type Action = typeof actions[number][0] | "playGem" | "dismiss"
export const lockedDuringScan = (name: Action) => ["rename", "reconnect", "exclude"].includes(name)
