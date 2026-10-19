import type { DetailsData, LibraryData } from "./bridge-types"

import { publicBridges, scanLockedActions, type Bridges, type LibraryBridge, type Reply, type Action } from "./bridge-types"
export { actions } from "./bridge-types"
export type { Bridges, LibraryBridge, ShellBridge, Action } from "./bridge-types"

declare global {
  interface Window {
    qt?: { webChannelTransport: unknown }
    QWebChannel: new (transport: unknown, callback: (channel: { objects: Bridges }) => void) => unknown
  }
}

let connection: Promise<Bridges> | undefined
export function connectBridge(): Promise<Bridges> {
  return connection ??= new Promise((resolve, reject) => {
    if (!window.qt || !window.QWebChannel) {
      reject(new Error("Qt 앱에서 라이브러리를 열어 주세요. 개발 서버는 MVM_WEB_DEV_URL로 연결합니다."))
      return
    }
    new window.QWebChannel(window.qt.webChannelTransport, channel => {
      try { resolve(publicBridges(channel.objects)) }
      catch (error) { reject(error) }
    })
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
export const getSnapshot = (bridge: LibraryBridge) => request<LibraryData>(reply => bridge.snapshot(reply))
export const getDetails = (bridge: LibraryBridge, id: number) => request<DetailsData>(reply => bridge.details(id, reply))

export const lockedDuringScan = (name: Action) => scanLockedActions.includes(name)
