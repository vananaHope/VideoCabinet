import type { QueueCountData, QueueData, QueueRowData } from "@/bridge-types"

const sameRow = (a: QueueRowData, b: QueueRowData) =>
  a.title === b.title && a.state === b.state && a.progress === b.progress && a.message === b.message
  && a.taskLabel === b.taskLabel && a.stateLabel === b.stateLabel && a.queueKind === b.queueKind
const sameCounts = (a: QueueCountData[], b: QueueCountData[]) =>
  a.length === b.length && a.every((item, index) => item.count === b[index].count && item.state === b[index].state)
const sameOrder = (a: string[], b: string[]) => a.length === b.length && a.every((key, index) => key === b[index])

// 브리지는 매번 전체 항목을 보낸다(#265). 진행률 변경은 바뀐 행 구독자만 깨운다. 목록/개수는 구조가 바뀔 때만 렌더한다.
// 행은 (영상, 작업 종류) 단위라 같은 영상의 받아쓰기·화면 자막이 따로 줄을 선다. 키는 브리지의 row.key다.
export class QueueStore {
  rows = new Map<string, QueueRowData>()
  meta: { order: string[]; counts: QueueCountData[]; canRetryFailed: boolean } = { order: [], counts: [], canRetryFailed: false }
  private listeners = new Map<string, Set<() => void>>()
  private metaListeners = new Set<() => void>()
  subscribe = (listener: () => void) => { this.metaListeners.add(listener); return () => { this.metaListeners.delete(listener) } }
  snapshot = () => this.meta
  subscribeRow(key: string, listener: () => void) {
    const listeners = this.listeners.get(key) ?? new Set()
    listeners.add(listener)
    this.listeners.set(key, listeners)
    return () => { listeners.delete(listener); if (!listeners.size) this.listeners.delete(key) }
  }
  apply(data: QueueData) {
    let filterChanged = false
    const changed: string[] = []
    const order = data.rows.map(row => row.key)
    const present = new Set(order)
    for (const row of data.rows) {
      const previous = this.rows.get(row.key)
      if (previous && sameRow(previous, row)) continue
      if (previous?.state !== row.state) filterChanged = true
      this.rows.set(row.key, row)
      changed.push(row.key)
    }
    for (const key of [...this.rows.keys()]) if (!present.has(key)) { this.rows.delete(key); changed.push(key) }
    const orderChanged = !sameOrder(order, this.meta.order), countsChanged = !sameCounts(data.counts, this.meta.counts)
    if (orderChanged || countsChanged || filterChanged || data.canRetryFailed !== this.meta.canRetryFailed) {
      this.meta = { order: orderChanged ? order : this.meta.order, counts: countsChanged ? data.counts : this.meta.counts, canRetryFailed: data.canRetryFailed }
      this.metaListeners.forEach(listener => listener())
    }
    for (const key of changed) this.listeners.get(key)?.forEach(listener => listener())
  }
}
