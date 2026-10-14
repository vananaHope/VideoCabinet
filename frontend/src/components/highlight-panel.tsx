import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react"
import { cva } from "class-variance-authority"
import { Pencil } from "lucide-react"
import type { HighlightData } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/page-parts"

const item = cva("flex h-8 min-w-0 items-center gap-1 rounded-md border bg-card px-1", { variants: { selected: { true: "border-ring", false: "border-border" } } })
function timestamp(value: number) {
  const ms = Math.round(value * 1000)
  return `${Math.floor(ms / 3600000).toString().padStart(2, "0")}:${Math.floor(ms / 60000 % 60).toString().padStart(2, "0")}:${(ms / 1000 % 60).toFixed(3).padStart(6, "0")}`
}
export type HighlightSnapshot = { videoId: number; revision: number; items: HighlightData[] }
export function HighlightPanel({ videoId, snapshot, revision, onAction }: { videoId: number; snapshot: HighlightSnapshot | null; revision: number; onAction: (videoId: number, highlightId: number, edit: boolean) => void }) {
  const [selected, setSelected] = useState<number | null>(null)
  const list = useRef<HTMLDivElement>(null)
  const scrollTop = useRef(0)
  const highlights = snapshot?.videoId === videoId ? snapshot.items : null
  const busy = highlights === null || snapshot?.revision !== revision
  const entries = highlights ?? []
  useLayoutEffect(() => {
    // 갱신 중의 빈 목록이 기존 스크롤 위치를 덮어쓰지 않게 한다.
    if (highlights !== null && list.current) list.current.scrollTop = scrollTop.current
  }, [highlights])
  const active = entries.some(h => h.id === selected) ? selected : entries[0]?.id
  function keyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.target !== event.currentTarget || event.nativeEvent.isComposing || event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || !entries.length) return
    const index = entries.findIndex(h => h.id === active)
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault()
      const next = event.key === "Home" ? 0 : event.key === "End" ? entries.length - 1 : Math.max(0, Math.min(entries.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)))
      setSelected(entries[next].id)
      document.getElementById(`highlight-${entries[next].id}`)?.scrollIntoView({ block: "nearest" })
    } else if (event.key === "Enter" || event.key === "F2") {
      event.preventDefault()
      if (!busy && !event.repeat && active != null) onAction(videoId, active, event.key === "F2")
    }
  }
  return <div className="flex min-h-0 flex-1 flex-col gap-2">
    <p className="text-xs text-muted-foreground">↑/↓ 선택 · Enter 재생 · F2 편집</p>
    <div ref={list} id="detail-scroll" role="listbox" aria-label="영상 하이라이트" aria-busy={busy} aria-activedescendant={active == null ? undefined : `highlight-${active}`} tabIndex={0} onKeyDown={keyDown} onScroll={event => { if (highlights !== null) scrollTop.current = event.currentTarget.scrollTop }} className="min-h-0 flex-1 space-y-1 overflow-y-auto rounded-md p-1">
      {highlights === null ? <p className="text-xs text-muted-foreground">하이라이트를 불러오는 중…</p> : !entries.length ? <EmptyState title="하이라이트 없음" description="재생 중 Insert 또는 Delete로 기억할 장면을 남기세요." /> : entries.map(h => <div key={h.id} id={`highlight-${h.id}`} role="option" aria-selected={h.id === active} className={item({ selected: h.id === active })}>
        <button type="button" tabIndex={-1} disabled={busy} className="flex min-w-0 flex-1 items-center gap-1 text-left" onClick={() => { if (busy) return; setSelected(h.id); list.current?.focus({ preventScroll: true }); onAction(videoId, h.id, false) }}>
          <span className="shrink-0 text-xs font-medium text-highlight tabular-nums" title={`${timestamp(h.start)}${h.end === null ? " · 지점" : ` – ${timestamp(h.end)}`}`}>{timestamp(h.start).slice(0, 8)}{h.end !== null && <span aria-label="구간">~</span>}</span>
          <span className="min-w-0 flex-1 truncate text-xs" title={h.note}>{h.note || "메모 없음"}</span>
          <span className="flex shrink-0 items-center gap-1" title={h.tags.map(tag => tag.name).join(", ")}>
            {h.tags.slice(0, 1).map(tag => <span key={tag.id} className="max-w-16 truncate rounded-md bg-secondary px-1 py-0.5 text-xs text-secondary-foreground">{tag.name}</span>)}
            {h.tags.length > 1 && <span className="text-xs text-muted-foreground">+{h.tags.length - 1}</span>}
          </span>
        </button>
        <Button variant="ghost" size="icon-xs" tabIndex={-1} disabled={busy} aria-label="시각·메모 편집" title="시각·메모 편집 (F2)" onClick={() => { if (busy) return; setSelected(h.id); list.current?.focus({ preventScroll: true }); onAction(videoId, h.id, true) }}><Pencil /></Button>
      </div>)}
    </div>
  </div>
}
