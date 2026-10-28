import type { QueueCountData, QueueData, QueueRowData } from "@/bridge-types"

const sameRow = (a: QueueRowData, b: QueueRowData) =>
  a.title === b.title && a.state === b.state && a.progress === b.progress && a.message === b.message
  && a.taskLabel === b.taskLabel && a.stateLabel === b.stateLabel && a.queueKind === b.queueKind
const sameCounts = (a: QueueCountData[], b: QueueCountData[]) =>
  a.length === b.length && a.every((item, index) => item.count === b[index].count && item.state === b[index].state)
const sameOrder = (a: number[], b: number[]) => a.length === b.length && a.every((id, index) => id === b[index])

// 브리지는 매번 전체 항목을 보낸다(#265). 진행률 변경은 바뀐 행 구독자만 깨운다. 목록/개수는 구조가 바뀔 때만 렌더한다.
export class QueueStore {
  rows = new Map<number, QueueRowData>()
  meta: { order: number[]; counts: QueueCountData[]; canRetryFailed: boolean } = { order: [], counts: [], canRetryFailed: false }
  private listeners = new Map<number, Set<() => void>>()
  private metaListeners = new Set<() => void>()
  subscribe = (listener: () => void) => { this.metaListeners.add(listener); return () => { this.metaListeners.delete(listener) } }
  snapshot = () => this.meta
  subscribeRow(id: number, listener: () => void) {
    const listeners = this.listeners.get(id) ?? new Set()
    listeners.add(listener)
    this.listeners.set(id, listeners)
    return () => { listeners.delete(listener); if (!listeners.size) this.listeners.delete(id) }
  }
  apply(data: QueueData) {
    let filterChanged = false
    const changed: number[] = []
    const order = data.rows.map(row => row.videoId)
    const present = new Set(order)
    for (const row of data.rows) {
      const previous = this.rows.get(row.videoId)
      if (previous && sameRow(previous, row)) continue
      if (previous?.state !== row.state) filterChanged = true
      this.rows.set(row.videoId, row)
      changed.push(row.videoId)
    }
    for (const id of [...this.rows.keys()]) if (!present.has(id)) { this.rows.delete(id); changed.push(id) }
    const orderChanged = !sameOrder(order, this.meta.order), countsChanged = !sameCounts(data.counts, this.meta.counts)
    if (orderChanged || countsChanged || filterChanged || data.canRetryFailed !== this.meta.canRetryFailed) {
      this.meta = { order: orderChanged ? order : this.meta.order, counts: countsChanged ? data.counts : this.meta.counts, canRetryFailed: data.canRetryFailed }
      this.metaListeners.forEach(listener => listener())
    }
    for (const id of changed) this.listeners.get(id)?.forEach(listener => listener())
  }
}
