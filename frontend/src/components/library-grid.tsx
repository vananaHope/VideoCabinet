import { cva } from "class-variance-authority"
import { useVirtualizer } from "@tanstack/react-virtual"
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type RefObject } from "react"
import { VideoCard, VideoCardPlaceholder } from "@/components/video-card"
import { VideoMenu } from "@/components/video-menu"
import type { VideoData } from "@/bridge-types"
import type { Action } from "@/bridge"
import { menuKeyRow, type KeyGuideRow } from "@/lib/key-guide"

export function openKeyboardMenu(event: KeyboardEvent, element: HTMLElement | null) {
  if (event.key !== "ContextMenu" && !(event.key === "F10" && event.shiftKey)) return false
  event.preventDefault()
  if (element && !event.repeat) {
    const rect = element.getBoundingClientRect()
    element.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 }))
  }
  return true
}

// 아래 keyDown과 같은 키. 키 안내 '지금 화면'에 보인다.
export const gridKeyRows: readonly KeyGuideRow[] = [
  { keys: ["← → ↑ ↓"], label: "영상 선택" },
  { keys: ["Enter"], label: "선택한 영상 재생 (더블클릭과 같음)" },
  menuKeyRow,
]

// 자리 표시는 보이는 줄만 채우므로 스크롤하지 않는다. 스크롤바 자리는 scroll-stable이 늘 예약해 바뀔 때 열 폭이 같다.
const gridVariants = cva("scroll-stable h-full min-w-0 flex-1 rounded-lg p-1 focus-visible:outline-2 focus-visible:outline-ring", {
  variants: {
    cardSize: { small: "library-grid-small", medium: "library-grid-medium", large: "library-grid-large" },
    loading: { true: "overflow-y-hidden", false: "overflow-y-auto" },
  },
  defaultVariants: { loading: false },
})

export function LibraryGrid({ cardSize, videos, selectedId, scanning, total, onSelect, onAction, layoutPaused, revealRequest = 0, loading = false }: {
  cardSize: string; videos: VideoData[]; selectedId: number | null; scanning: boolean; total: number;
  onSelect: (id: number) => void; onAction: (action: Action, id: number) => void;
  layoutPaused: RefObject<boolean>;
  /** 값이 바뀔 때마다 선택한 카드의 행이 보이도록 스크롤한다. */
  revealRequest?: number;
  /** 첫 데이터가 오기 전이다. 빈 라이브러리 안내 대신 실제 카드와 같은 크기의 자리 표시로 보이는 줄을 채운다. */
  loading?: boolean;
}) {
  const scroll = useRef<HTMLDivElement>(null)
  const [dimensions, setDimensions] = useState({ columns: 2, rowHeight: 256, visibleRows: 1 })
  useLayoutEffect(() => {
    const element = scroll.current!
    const measure = () => {
      if (!element.clientWidth || document.hidden || layoutPaused.current) return
      const css = getComputedStyle(element)
      const rootSize = parseFloat(getComputedStyle(document.documentElement).fontSize)
      const cardWidth = parseFloat(css.getPropertyValue("--grid-card-width")) * rootSize
      const available = element.clientWidth - 8
      const columns = Math.max(1, Math.floor((available + 12) / (cardWidth + 12)))
      const width = (available - (columns - 1) * 12) / columns
      const rowHeight = (width - 2) * 9 / 16 + 10 * rootSize + 14
      element.style.setProperty('--grid-row-height', `${rowHeight / rootSize}rem`)
      setDimensions({ columns, rowHeight, visibleRows: Math.max(1, Math.ceil(element.clientHeight / rowHeight)) })
    }
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    window.addEventListener('resize', measure)
    measure()
    return () => { observer.disconnect(); window.removeEventListener('resize', measure) }
  }, [layoutPaused, cardSize])
  const { columns, rowHeight, visibleRows } = dimensions
  const virtual = useVirtualizer({ count: Math.ceil(videos.length / columns), getScrollElement: () => scroll.current, estimateSize: () => rowHeight, overscan: 2 })
  // estimateSize 변경만으로는 TanStack의 기존 행 위치 캐시가 비워지지 않는다.
  useLayoutEffect(() => { virtual.measure() }, [virtual, rowHeight, columns])
  const selectedIndex = videos.findIndex(video => video.id === selectedId)
  const lastIds = useRef("")
  useLayoutEffect(() => {
    const ids = videos.map(v => v.id).join(",")
    if (ids !== lastIds.current) {
      if (lastIds.current && !layoutPaused.current) scroll.current?.scrollTo({ top: 0 })
      lastIds.current = ids
    }
  }, [videos, layoutPaused])

  const revealed = useRef(revealRequest)
  useEffect(() => {
    if (revealed.current === revealRequest) return
    revealed.current = revealRequest
    if (selectedIndex >= 0) virtual.scrollToIndex(Math.floor(selectedIndex / columns), { align: "auto" })
  }, [revealRequest, selectedIndex, columns, virtual])

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

  return <div ref={scroll} id="library-grid" role="grid" aria-label="라이브러리 영상 격자" aria-rowcount={Math.ceil(videos.length / columns)} aria-colcount={columns} aria-activedescendant={selectedId === null ? undefined : `video-${selectedId}`} aria-busy={loading} tabIndex={0} onKeyDown={keyDown} className={gridVariants({ cardSize: cardSize as "small" | "medium" | "large", loading })}>
    {loading ? <div aria-hidden="true" className="virtual-canvas" style={{ "--virtual-height": `${visibleRows * rowHeight}px` } as CSSProperties}>
      {Array.from({ length: visibleRows }, (_, row) => <div key={row} className="virtual-row gap-3 pb-3" style={{ "--virtual-top": `${row * rowHeight}px`, "--virtual-columns": columns } as CSSProperties}>
        {Array.from({ length: columns }, (_, column) => <VideoCardPlaceholder key={column} />)}
      </div>)}
    </div> : !videos.length ? <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-muted-foreground">
      <h2 className="text-base font-semibold text-foreground">{total ? "조건에 맞는 영상이 없습니다" : "라이브러리가 비어 있습니다"}</h2>
      <p>{total ? "검색 조건이나 선택한 폴더를 바꿔 보세요." : "폴더 관리(Ctrl+7)에서 감시 폴더나 영상 파일을 추가하세요."}</p>
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
