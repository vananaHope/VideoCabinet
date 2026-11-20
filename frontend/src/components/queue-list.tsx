import { memo, useCallback, useSyncExternalStore, type KeyboardEvent, type ReactNode } from "react"
import { cva } from "class-variance-authority"
import { StatusBadge } from "@/components/page-parts"
import { InlineNotice } from "@/components/ui/notice"
import { selectableItem } from "@/components/ui/selectable-item"
import type { KeyGuideRow } from "@/lib/key-guide"
import { QueueStore } from "./queue-store"

// 열 비율은 영상 2 : 상태 1 : 진행률 1 : 안내 2로 두어 긴 안내가 일찍 잘리지 않게 한다.
const columns = "grid grid-cols-6 gap-3 px-3"
const wide = "col-span-2 min-w-0"
const rowClass = cva(`${columns} items-center border-b py-1 text-body`, { variants: { selected: { true: selectableItem({ selected: true }), false: ["bg-card", selectableItem({ selected: false, inner: "muted" })] } } })
// 안내가 많아도 머리글과 행 세 개 이상이 보이는 높이를 지킨다.
// 고정 머리글 높이 토큰을 scroll-padding에도 써서, 키보드로 위쪽 행을 골라도 머리글에 가리지 않게 한다.
const listClass = cva("min-h-32 flex-1 rounded-lg focus-visible:outline-2 focus-visible:outline-ring", { variants: { empty: { true: "flex flex-col", false: "overflow-auto border scroll-pt-queue-header" } } })
// 트랙은 놓인 면보다 어두운 홈이다. 선택 행(accent 면)에서는 바탕색으로 내려 빈 트랙이 꽉 찬 막대처럼 보이지 않게 한다.
const trackClass = "h-2 min-w-0 flex-1 rounded-full border border-border bg-background"
// 채움은 진행 중에만 강조색이고, 끝난 상태는 배지와 같은 의미색이다.
const fillClass = cva("", { variants: { state: { completed: "fill-status-success", failed: "fill-destructive", held: "fill-status-warning", active: "fill-primary" } } })
const fills = { completed: "completed", failed: "failed", held: "held" } as const
const badges = { completed: "success", failed: "destructive", transcribing: "info", reading: "info", translating: "info", held: "highlight", queued: "muted" } as const
// 행 안내의 위계: 실패 사유는 오류, 보류 사유는 경고, 그 밖의 안내(말소리 없음·이어받기 등)는 정보다.
const tones = { failed: "error", held: "warning" } as const

const QueueRow = memo(function QueueRow({ store, id, selected, onSelect }: { store: QueueStore; id: string; selected: boolean; onSelect: (id: string) => void }) {
  const subscribe = useCallback((listener: () => void) => store.subscribeRow(id, listener), [store, id])
  const row = useSyncExternalStore(subscribe, () => store.rows.get(id))
  if (!row) return null
  return <div id={`queue-row-${id}`} role="row" aria-selected={selected} data-queue-row={id} data-queue-kind={row.queueKind} className={rowClass({ selected })} onClick={() => onSelect(id)}>
    <div role="gridcell" title={row.title} className={`${wide} truncate text-body-strong`}>{row.title}</div>
    <div role="gridcell"><StatusBadge variant={selected && row.state === "queued" ? "selectedMuted" : badges[row.state as keyof typeof badges]}>{row.stateLabel}</StatusBadge></div>
    <div role="gridcell" className="flex min-w-0 items-center gap-2"><svg viewBox="0 0 100 8" preserveAspectRatio="none" role="progressbar" aria-label={`${row.title} 진행률`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(row.progress * 100)} className={trackClass}><rect width={Math.max(0, Math.min(100, row.progress * 100))} height={8} className={fillClass({ state: fills[row.state as keyof typeof fills] ?? "active" })} /></svg><span className="w-9 shrink-0 text-right text-label tabular-nums">{Math.round(row.progress * 100)}%</span></div>
    <div role="gridcell" className={`${wide} text-muted-foreground`}>{row.message && <InlineNotice tone={tones[row.state as keyof typeof tones] ?? "info"} text={row.message} />}</div>
  </div>
})

// 아래 keyDown과 같은 키. 키 안내 '지금 화면'에 보인다.
export const queueKeyRows: readonly KeyGuideRow[] = [
  { keys: ["↑ ↓"], label: "항목 선택" },
  { keys: ["Page Up", "Page Down"], label: "한 화면씩 이동" },
  { keys: ["Home", "End"], label: "처음 / 끝 항목" },
]

export function QueueList({ store, ids, selected, onSelect, emptyState }: { store: QueueStore; ids: string[]; selected: string | null; onSelect: (id: string) => void; emptyState: ReactNode }) {
  function keyDown(event: KeyboardEvent) {
    if (event.nativeEvent.isComposing || event.ctrlKey || event.altKey || event.metaKey || !ids.length) return
    const index = Math.max(0, ids.indexOf(selected ?? ""))
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
    {!ids.length ? emptyState : <div role="row" className={`${columns} sticky top-0 z-10 h-queue-header items-center border-b bg-muted text-label text-muted-foreground`}>{["영상", "상태", "진행률", "안내"].map(label => <div key={label} role="columnheader" className={label === "영상" || label === "안내" ? wide : undefined}>{label}</div>)}</div>}
    {ids.map(id => <QueueRow key={id} store={store} id={id} selected={id === selected} onSelect={onSelect} />)}
  </div>
}
