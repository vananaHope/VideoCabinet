import { cva } from "class-variance-authority"
import { useVirtualizer } from "@tanstack/react-virtual"
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type RefObject } from "react"
import { VideoCard } from "@/components/video-card"
import { VideoMenu } from "@/components/video-menu"
import type { VideoData } from "@/bridge-types"
import type { Action } from "@/bridge"

export function openKeyboardMenu(event: KeyboardEvent, element: HTMLElement | null) {
  if (event.key !== "ContextMenu" && !(event.key === "F10" && event.shiftKey)) return false
  event.preventDefault()
  if (element && !event.repeat) {
    const rect = element.getBoundingClientRect()
    element.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 }))
  }
  return true
}

const gridVariants = cva("scroll-stable h-full min-w-0 flex-1 overflow-y-auto rounded-lg p-1 focus-visible:outline-2 focus-visible:outline-ring", {
  variants: { cardSize: { small: "library-grid-small", medium: "library-grid-medium", large: "library-grid-large" } },
})

export function LibraryGrid({ cardSize, videos, selectedId, scanning, total, onSelect, onAction, layoutPaused }: {
  cardSize: string; videos: VideoData[]; selectedId: number | null; scanning: boolean; total: number;
  onSelect: (id: number) => void; onAction: (action: Action, id: number) => void;
  layoutPaused: RefObject<boolean>;
}) {
  const scroll = useRef<HTMLDivElement>(null)
  const [dimensions, setDimensions] = useState({ columns: 2, rowHeight: 256 })
  useLayoutEffect(() => {
    const element = scroll.current!
    const measure = () => {
      if (!element.clientWidth || document.hidden || layoutPaused.current) return
      const css = getComputedStyle(element)
      const rootSize = parseFloat(getComputedStyle(document.documentElement).fontSize)
      const cardWidth = parseFloat(css.getPropertyValue("--grid-card-width")) * rootSize
      const rowHeight = parseFloat(css.getPropertyValue("--grid-row-height")) * rootSize
      setDimensions({ columns: Math.max(1, Math.floor(element.clientWidth / cardWidth)), rowHeight })
    }
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    window.addEventListener('resize', measure)
    measure()
    return () => { observer.disconnect(); window.removeEventListener('resize', measure) }
  }, [layoutPaused, cardSize])
  const { columns, rowHeight } = dimensions
  const virtual = useVirtualizer({ count: Math.ceil(videos.length / columns), getScrollElement: () => scroll.current, estimateSize: () => rowHeight, overscan: 2 })
  // estimateSize 변경만으로는 TanStack의 기존 행 위치 캐시가 비워지지 않는다.
  useLayoutEffect(() => { virtual.measure() }, [virtual, rowHeight, columns])
  const selectedIndex = videos.findIndex(video => video.id === selectedId)
  const lastIds = useRef("")
  useEffect(() => {
    const ids = videos.map(v => v.id).join(",")
    if (ids !== lastIds.current) {
      if (lastIds.current) scroll.current?.scrollTo({ top: 0 })
      lastIds.current = ids
    }
  }, [videos])

  function keyDown(event: KeyboardEvent<HTMLDivElement>) {
    if ((event.target as HTMLElement).closest('[role="menu"]') || event.nativeEvent.isComposing) return
    const element = document.getElementById(`video-${selectedId}`)
    if (openKeyboardMenu(event, element)) return
    if (event.ctrlKey || event.altKey || event.metaKey || event.shiftKey) return
    const offsets: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -columns, ArrowDown: columns }
    if (event.key in offsets && videos.length) {
      event.preventDefault()
      const index = Math.max(0, Math.min(videos.length - 1, Math.max(0, selectedIndex) + offsets[event.key]))
      onSelect(videos[index].id)
      virtual.scrollToIndex(Math.floor(index / columns), { align: "auto" })
    } else if (event.key === "Enter" && selectedId !== null) {
      event.preventDefault()
      if (!event.repeat) onAction("play", selectedId)
    }
  }

  return <div ref={scroll} id="library-grid" role="grid" aria-label="라이브러리 영상 격자" aria-rowcount={Math.ceil(videos.length / columns)} aria-colcount={columns} aria-activedescendant={selectedId === null ? undefined : `video-${selectedId}`} tabIndex={0} onKeyDown={keyDown} className={gridVariants({ cardSize: cardSize as "small" | "medium" | "large" })}>
    {!videos.length ? <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-muted-foreground">
      <h2 className="text-base font-semibold text-foreground">{total ? "조건에 맞는 영상이 없습니다" : "라이브러리가 비어 있습니다"}</h2>
      <p>{total ? "검색 조건이나 선택한 폴더를 바꿔 보세요." : "폴더 관리(Ctrl+6)에서 감시 폴더나 영상 파일을 추가하세요."}</p>
    </div> : <div className="virtual-canvas" style={{ "--virtual-height": `${virtual.getTotalSize()}px` } as CSSProperties}>
      {virtual.getVirtualItems().map(row => <div key={row.key} role="row" aria-rowindex={row.index + 1} className="virtual-row gap-3 pb-3" style={{ "--virtual-top": `${row.start}px`, "--virtual-columns": columns } as CSSProperties}>
        {videos.slice(row.index * columns, (row.index + 1) * columns).map((video, index) => <VideoMenu key={video.id} id={video.id} scanning={scanning} onAction={onAction}>
          <VideoCard id={`video-${video.id}`} video={video} cardSize={cardSize} variant={selectedId === video.id ? "selected" : "default"} role="gridcell" aria-colindex={index + 1} aria-selected={selectedId === video.id} tabIndex={-1}
            onClick={() => { onSelect(video.id); scroll.current?.focus({ preventScroll: true }) }}
            onDoubleClick={() => onAction("play", video.id)} onContextMenu={() => onSelect(video.id)} />
        </VideoMenu>)}
      </div>)}
    </div>}
  </div>
}
