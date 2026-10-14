import { useRef, useState, type KeyboardEvent } from "react"
import { cva } from "class-variance-authority"
import type { HighlightData } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/page-parts"

const item = cva("flex min-w-0 flex-col gap-2 rounded-lg border p-2", { variants: { selected: { true: "border-ring bg-accent", false: "bg-background/40" } } })
function timestamp(value: number) {
  const ms = Math.round(value * 1000)
  return `${Math.floor(ms / 3600000).toString().padStart(2, "0")}:${Math.floor(ms / 60000 % 60).toString().padStart(2, "0")}:${(ms / 1000 % 60).toFixed(3).padStart(6, "0")}`
}
export function HighlightPanel({ videoId, highlights, onAction }: { videoId: number; highlights: HighlightData[] | null; onAction: (videoId: number, highlightId: number, edit: boolean) => void }) {
  const [selected, setSelected] = useState<number | null>(null)
  const list = useRef<HTMLDivElement>(null)
  const entries = highlights ?? []
  const active = entries.some(h => h.id === selected) ? selected : entries[0]?.id
  function keyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.target !== event.currentTarget || event.nativeEvent.isComposing || event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || !entries.length) return
    const index = entries.findIndex(h => h.id === active)
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault()
      const next = event.key === "Home" ? 0 : event.key === "End" ? entries.length - 1 : Math.max(0, Math.min(entries.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)))
      setSelected(entries[next].id)
      document.getElementById(`highlight-${entries[next].id}`)?.scrollIntoView({ block: "nearest" })
    } else if (event.key === "Enter") {
      event.preventDefault()
      if (!event.repeat && active != null) onAction(videoId, active, false)
    }
  }
  return <div className="flex min-h-0 flex-1 flex-col gap-2">
    <p className="text-xs text-muted-foreground">↑/↓ 선택 · Enter 또는 클릭으로 재생</p>
    <div ref={list} id="detail-scroll" role="listbox" aria-label="영상 하이라이트" aria-activedescendant={active == null ? undefined : `highlight-${active}`} tabIndex={0} onKeyDown={keyDown} className="min-h-0 flex-1 space-y-2 overflow-y-auto rounded-md p-1">
      {highlights === null ? <p className="text-xs text-muted-foreground">하이라이트를 불러오는 중…</p> : !entries.length ? <EmptyState title="하이라이트 없음" description="재생 중 Insert 또는 Delete로 기억할 장면을 남기세요." /> : entries.map(h => <div key={h.id} id={`highlight-${h.id}`} role="option" aria-selected={h.id === active} className={item({ selected: h.id === active })}>
        <button type="button" tabIndex={-1} className="flex min-w-0 flex-col gap-2 text-left" onClick={() => { setSelected(h.id); list.current?.focus({ preventScroll: true }); onAction(videoId, h.id, false) }}>
          <span className="text-xs font-medium text-highlight tabular-nums">{timestamp(h.start)}{h.end === null ? " · 지점" : ` – ${timestamp(h.end)}`}</span>
          <span className="line-clamp-3 text-sm wrap-anywhere" title={h.note}>{h.note || "메모 없음"}</span>
          <span className="flex flex-wrap gap-1">{h.tags.map(tag => <span key={tag.id} className="max-w-full rounded-md bg-secondary px-2 py-0.5 text-xs text-secondary-foreground wrap-anywhere">{tag.name}</span>)}</span>
        </button>
        <Button variant="outline" size="sm" onClick={() => { setSelected(h.id); onAction(videoId, h.id, true) }}>시각·메모 편집</Button>
      </div>)}
    </div>
  </div>
}
