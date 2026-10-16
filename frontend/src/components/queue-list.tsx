import { memo, useCallback, useSyncExternalStore, type KeyboardEvent, type ReactNode } from "react"
import { cva } from "class-variance-authority"
import { StatusBadge } from "@/components/page-parts"
import { InlineNotice } from "@/components/ui/notice"
import { QueueStore } from "./queue-store"

// 열 비율은 영상 2 : 상태 1 : 진행률 1 : 안내 2로 두어 긴 안내가 일찍 잘리지 않게 한다.
const columns = "grid grid-cols-6 gap-3 px-3"
const wide = "col-span-2 min-w-0"
const rowClass = cva(`${columns} items-center border-b py-1 text-sm`, { variants: { selected: { true: "bg-accent", false: "bg-card" } } })
const listClass = cva("min-h-0 flex-1 rounded-lg focus-visible:outline-2 focus-visible:outline-ring", { variants: { empty: { true: "flex flex-col", false: "overflow-auto border" } } })
const trackClass = cva("h-2 w-full rounded-full", { variants: { selected: { true: "bg-muted-foreground", false: "bg-muted" } } })
const badges = { completed: "success", failed: "destructive", transcribing: "info", translating: "info", held: "highlight", queued: "muted" } as const
// 행 안내의 위계: 실패 사유는 오류, 보류 사유는 경고, 그 밖의 안내(말소리 없음·이어받기 등)는 정보다.
const tones = { failed: "error", held: "warning" } as const

const QueueRow = memo(function QueueRow({ store, id, selected, onSelect }: { store: QueueStore; id: number; selected: boolean; onSelect: (id: number) => void }) {
  const subscribe = useCallback((listener: () => void) => store.subscribeRow(id, listener), [store, id])
  const row = useSyncExternalStore(subscribe, () => store.rows.get(id))
  if (!row) return null
  return <div id={`queue-row-${id}`} role="row" aria-selected={selected} data-queue-row={id} className={rowClass({ selected })} onClick={() => onSelect(id)}>
    <div role="gridcell" title={row.title} className={`${wide} truncate font-medium`}>{row.title}</div>
    <div role="gridcell"><StatusBadge variant={selected && row.state === "queued" ? "selectedMuted" : badges[row.state as keyof typeof badges]}>{row.stateLabel}</StatusBadge></div>
    <div role="gridcell" className="flex min-w-0 items-center gap-2"><svg viewBox="0 0 100 8" preserveAspectRatio="none" role="progressbar" aria-label={`${row.title} 진행률`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(row.progress * 100)} className={trackClass({ selected })}><rect width={Math.max(0, Math.min(100, row.progress * 100))} height={8} className="fill-primary" /></svg><span className="text-xs tabular-nums">{Math.round(row.progress * 100)}%</span></div>
    <div role="gridcell" className={`${wide} text-muted-foreground`}>{row.message && <InlineNotice tone={tones[row.state as keyof typeof tones] ?? "info"} text={row.message} />}</div>
  </div>
})

export function QueueList({ store, ids, selected, onSelect, emptyState }: { store: QueueStore; ids: number[]; selected: number | null; onSelect: (id: number) => void; emptyState: ReactNode }) {
  function keyDown(event: KeyboardEvent) {
    if (event.nativeEvent.isComposing || event.ctrlKey || event.altKey || event.metaKey || !ids.length) return
    const index = Math.max(0, ids.indexOf(selected ?? -1))
    let next = event.key === "ArrowDown" ? Math.min(index + 1, ids.length - 1) : event.key === "ArrowUp" ? Math.max(index - 1, 0) : event.key === "Home" ? 0 : event.key === "End" ? ids.length - 1 : -1
    if (event.key === "PageDown" || event.key === "PageUp") {
      const list = event.currentTarget
      const headerHeight = list.querySelector('[role="columnheader"]')?.parentElement?.getBoundingClientRect().height ?? 0
      const rowHeight = list.querySelector('[data-queue-row]')?.getBoundingClientRect().height ?? 1
      const pageSize = Math.max(1, Math.floor((list.clientHeight - headerHeight) / rowHeight))
      next = Math.max(0, Math.min(ids.length - 1, index + (event.key === "PageDown" ? pageSize : -pageSize)))
    }
    if (next < 0) return
    event.preventDefault()
    onSelect(ids[next])
    document.getElementById(`queue-row-${ids[next]}`)?.scrollIntoView({ block: "nearest" })
  }
  return <div id="queue-list" role={ids.length ? "grid" : "region"} aria-label="자막 대기열" aria-activedescendant={selected === null ? undefined : `queue-row-${selected}`} tabIndex={0} onKeyDown={keyDown} className={listClass({ empty: !ids.length })}>
    {!ids.length ? emptyState : <div role="row" className={`${columns} sticky top-0 z-10 border-b bg-muted py-1.5 text-xs text-muted-foreground`}>{["영상", "상태", "진행률", "안내"].map(label => <div key={label} role="columnheader" className={label === "영상" || label === "안내" ? wide : undefined}>{label}</div>)}</div>}
    {ids.map(id => <QueueRow key={id} store={store} id={id} selected={id === selected} onSelect={onSelect} />)}
  </div>
}
