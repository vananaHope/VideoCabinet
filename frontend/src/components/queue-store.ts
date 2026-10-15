import type { QueueCountData, QueueDeltaData, QueueRowData } from "@/bridge-types"

// 진행률 변경은 해당 행 구독자만 깨운다. 목록/개수는 구조가 바뀔 때만 렌더한다.
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
  apply(delta: QueueDeltaData) {
    let filterChanged = false
    for (const row of delta.rows) {
      if (this.rows.get(row.videoId)?.state !== row.state) filterChanged = true
      this.rows.set(row.videoId, row)
    }
    for (const id of delta.removed) this.rows.delete(id)
    if (delta.order || delta.counts || filterChanged || delta.canRetryFailed !== this.meta.canRetryFailed) {
      this.meta = { order: delta.order ?? this.meta.order, counts: delta.counts ?? this.meta.counts, canRetryFailed: delta.canRetryFailed }
      this.metaListeners.forEach(listener => listener())
    }
    for (const id of [...delta.rows.map(row => row.videoId), ...delta.removed]) this.listeners.get(id)?.forEach(listener => listener())
  }
}
