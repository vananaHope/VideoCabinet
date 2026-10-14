import type { DetailsData, LibraryData } from "./bridge-types"

import { publicBridge, scanLockedActions, type Bridge, type Reply, type Action } from "./bridge-types"
export { actions } from "./bridge-types"
export type { Bridge, Action } from "./bridge-types"

declare global {
  interface Window {
    qt?: { webChannelTransport: unknown }
    QWebChannel: new (transport: unknown, callback: (channel: { objects: { app: Bridge } }) => void) => unknown
  }
}

let connection: Promise<Bridge> | undefined
export function connectBridge(): Promise<Bridge> {
  return connection ??= new Promise((resolve, reject) => {
    if (!window.qt || !window.QWebChannel) {
      reject(new Error("Qt 앱에서 라이브러리를 열어 주세요. 개발 서버는 MVM_WEB_DEV_URL로 연결합니다."))
      return
    }
    new window.QWebChannel(window.qt.webChannelTransport, channel => resolve(publicBridge(channel.objects.app)))
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

export const lockedDuringScan = (name: Action) => scanLockedActions.includes(name)
