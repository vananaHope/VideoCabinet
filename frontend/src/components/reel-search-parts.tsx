import { cva } from "class-variance-authority"
import type { ComponentProps, KeyboardEvent } from "react"
import type { SearchTextData } from "@/bridge-types"
import type { KeyGuideRow } from "@/lib/key-guide"

const row = cva("flex min-w-0 gap-3 rounded-lg border p-3 text-left", { variants: { selected: { true: "border-ring bg-accent", false: "border-border bg-card hover:bg-muted" } } })
export function ResultRow({ selected, ...props }: ComponentProps<"div"> & { selected: boolean }) {
  return <div {...props} role="option" aria-selected={selected} className={row({ selected })} />
}

export function SearchInput(props: ComponentProps<"input">) {
  return <input {...props} className="h-12 w-full min-w-0 rounded-lg border border-input bg-card px-4 text-lg placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring" />
}

export function MatchedText({ parts }: { parts: SearchTextData[] }) {
  return <>{parts.map((part, index) => part.matched ? <mark key={index} className="bg-transparent font-semibold text-primary-text">{part.text}</mark> : part.text)}</>
}

export function timestamp(value: number) {
  const ms = Math.round(value * 1000)
  return `${Math.floor(ms / 3600000).toString().padStart(2, "0")}:${Math.floor(ms / 60000 % 60).toString().padStart(2, "0")}:${(ms / 1000 % 60).toFixed(3).padStart(6, "0")}`
}

// listKey와 같은 키. 모아보기·검색 목록의 키 안내에 보인다.
export const listKeyRows: readonly KeyGuideRow[] = [
  { keys: ["↑ ↓"], label: "항목 선택" },
  { keys: ["Page Up", "Page Down"], label: "5개씩 이동" },
  { keys: ["Home", "End"], label: "처음 / 끝 항목" },
  { keys: ["Enter"], label: "선택한 항목 재생" },
]

export function listKey(event: KeyboardEvent<HTMLDivElement>, count: number, current: number, select: (index: number) => void, play: () => void) {
  if (!count || event.nativeEvent.isComposing || event.ctrlKey || event.altKey || event.metaKey || event.shiftKey) return
  const steps: Record<string, number> = { ArrowDown: 1, ArrowUp: -1, PageDown: 5, PageUp: -5 }
  if (event.key in steps || event.key === "Home" || event.key === "End") {
    event.preventDefault()
    select(event.key === "Home" ? 0 : event.key === "End" ? count - 1 : Math.max(0, Math.min(count - 1, current + steps[event.key])))
  } else if (event.key === "Enter") {
    event.preventDefault()
    if (!event.repeat) play()
  }
}

export function restoreListFocus(id: string, scrollTop: number) {
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const element = document.getElementById(id)
    if (element) { element.scrollTop = scrollTop; element.focus({ preventScroll: true }) }
  }))
}
