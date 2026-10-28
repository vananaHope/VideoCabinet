import { cva } from "class-variance-authority"
import { useVirtualizer } from "@tanstack/react-virtual"
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type RefObject } from "react"
import { flushSync } from "react-dom"
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

/** 첫 데이터의 상태. 실패는 끝난 상태라 기다림을 알리지 않는다. 뒤에 데이터가 오면 ready가 된다. */
export type FirstLoad = "pending" | "failed" | "ready"

type Dimensions = { columns: number; rowHeight: number; visibleRows: number }
/**
 * 보던 자리. 기준 카드마다 그 줄 위쪽이 격자 보기 영역 위쪽에서 얼마나 떨어져 있었는지와 그때의 스크롤.
 * 보이던 선택 카드가 먼저이고, 그 카드가 결과에서 빠지면 보이던 다른 카드를 왼쪽 위부터 차례로 쓴다.
 */
type Place = { cards: { id: number; offset: number }[]; top: number }

function placeOf(videos: VideoData[], selectedId: number | null, { columns, rowHeight }: Dimensions, top: number, height: number): Place | null {
  if (!videos.length) return null
  const rowTop = (index: number) => Math.floor(index / columns) * rowHeight
  const card = (index: number) => ({ id: videos[index].id, offset: rowTop(index) - top })
  const first = Math.min(videos.length - 1, Math.floor(top / rowHeight) * columns)
  const last = Math.min(videos.length, Math.ceil((top + height) / rowHeight) * columns)
  const cards = Array.from({ length: last - first }, (_, index) => card(first + index))
  const selected = videos.findIndex(video => video.id === selectedId)
  if (selected >= 0 && rowTop(selected) + rowHeight > top && rowTop(selected) < top + height) cards.unshift(card(selected))
  return { cards, top }
}

function GridMessage({ title, description }: { title: string; description: string }) {
  return <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-muted-foreground">
    <h2 className="text-base font-semibold text-foreground">{title}</h2>
    <p>{description}</p>
  </div>
}

export function LibraryGrid({ cardSize, videos, selectedId, scanning, total, onSelect, onAction, layoutPaused, revealRequest = 0, load = "ready", keepPlace = false }: {
  cardSize: string; videos: VideoData[]; selectedId: number | null; scanning: boolean; total: number;
  onSelect: (id: number) => void; onAction: (action: Action, id: number) => void;
  layoutPaused: RefObject<boolean>;
  /** 값이 바뀔 때마다 선택한 카드의 행이 보이도록 스크롤한다. */
  revealRequest?: number;
  /** pending: 빈 라이브러리 안내 대신 실제 카드와 같은 크기의 자리 표시로 보이는 줄을 채운다. failed: 읽지 못했다고 알린다. */
  load?: FirstLoad;
  /** 결과가 바뀌어도 맨 위로 올리지 않고 보던 카드를 같은 세로 위치에 둔다. 선택 카드가 결과에서 빠지면 보이던 다른 카드로 이전 스크롤 근처를 지킨다. */
  keepPlace?: boolean;
}) {
  const loading = load === "pending"
  const scroll = useRef<HTMLDivElement>(null)
  const [dimensions, setDimensions] = useState<Dimensions>({ columns: 2, rowHeight: 256, visibleRows: 1 })
  // 그린 결과와 마지막 스크롤 위치. 목록이 줄어 브라우저가 스크롤을 깎기 전의 위치로 보던 자리를 찾는다.
  const shown = useRef({ ids: "", videos, selectedId, dimensions, top: 0 })
  const pendingPlace = useRef<Place | null>(null)
  function restore(place: Place | null) {
    const element = scroll.current
    if (!place || !element) return
    const { videos, dimensions: { columns, rowHeight } } = shown.current
    const indexes = new Map(videos.map((video, index) => [video.id, index]))
    const anchor = place.cards.find(card => indexes.has(card.id))
    // 보이던 카드가 모두 결과에서 빠지면 맨 위가 아니라 이전 스크롤 근처에 남는다.
    // 같은 세로 위치에 두려면 스크롤이 0보다 작거나 끝보다 커야 할 때(예: 열이 늘어 선택 카드가 새 첫 줄이 됨)는
    // 목록 위아래에 빈 여백을 만들지 않고 브라우저가 가능한 범위로 깎게 둔다. 그 차이는 깎인 만큼뿐이고 카드는 계속 보인다.
    element.scrollTop = anchor ? Math.floor(indexes.get(anchor.id)! / columns) * rowHeight - anchor.offset : place.top
    shown.current.top = element.scrollTop
  }
  useLayoutEffect(() => {
    const element = scroll.current!
    const measure = (sync: boolean) => {
      if (!element.clientWidth || document.hidden || layoutPaused.current) return
      const css = getComputedStyle(element)
      const rootSize = parseFloat(getComputedStyle(document.documentElement).fontSize)
      const cardWidth = parseFloat(css.getPropertyValue("--grid-card-width")) * rootSize
      const available = element.clientWidth - 8
      const columns = Math.max(1, Math.floor((available + 12) / (cardWidth + 12)))
      const width = (available - (columns - 1) * 12) / columns
      const rowHeight = (width - 2) * 9 / 16 + 10 * rootSize + 14
      element.style.setProperty('--grid-row-height', `${rowHeight / rootSize}rem`)
      const previous = shown.current
      // 폭이 바뀌어(폴더 패널 여닫기·창 크기·카드 크기) 열 수나 줄 높이가 바뀌면 보던 카드를 같은 세로 위치에 다시 둔다.
      if (previous.dimensions.columns !== columns || previous.dimensions.rowHeight !== rowHeight)
        pendingPlace.current = placeOf(previous.videos, previous.selectedId, previous.dimensions, element.scrollTop, element.clientHeight)
      const next = { columns, rowHeight, visibleRows: Math.max(1, Math.ceil(element.clientHeight / rowHeight)) }
      // 관찰자 콜백에서는 새 열 수를 같은 프레임에 그려, 늘어난 옛 열이나 어긋난 스크롤이 한 프레임도 보이지 않게 한다.
      if (sync) flushSync(() => setDimensions(next))
      else setDimensions(next)
    }
    const changed = () => measure(true)
    const observer = new ResizeObserver(changed)
    observer.observe(element)
    window.addEventListener('resize', changed)
    measure(false)
    return () => { observer.disconnect(); window.removeEventListener('resize', changed) }
  }, [layoutPaused, cardSize])
  const { columns, rowHeight, visibleRows } = dimensions
  const virtual = useVirtualizer({ count: Math.ceil(videos.length / columns), getScrollElement: () => scroll.current, estimateSize: () => rowHeight, overscan: 2 })
  // estimateSize 변경만으로는 TanStack의 기존 행 위치 캐시가 비워지지 않는다.
  useLayoutEffect(() => { virtual.measure() }, [virtual, rowHeight, columns])
  useLayoutEffect(() => {
    shown.current.dimensions = dimensions
    const place = pendingPlace.current
    pendingPlace.current = null
    restore(place)
  }, [dimensions])
  const selectedIndex = videos.findIndex(video => video.id === selectedId)
  useLayoutEffect(() => {
    const ids = videos.map(v => v.id).join(",")
    const before = shown.current
    shown.current = { ...before, ids, videos, selectedId }
    if (ids === before.ids || !before.ids || layoutPaused.current) return
    if (keepPlace) restore(placeOf(before.videos, before.selectedId, before.dimensions, before.top, scroll.current?.clientHeight ?? 0))
    else { scroll.current?.scrollTo({ top: 0 }); shown.current.top = 0 }
  }, [videos, selectedId, keepPlace, layoutPaused])

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

  return <div ref={scroll} id="library-grid" role="grid" aria-label="라이브러리 영상 격자" aria-rowcount={Math.ceil(videos.length / columns)} aria-colcount={columns} aria-activedescendant={selectedId === null ? undefined : `video-${selectedId}`} aria-busy={loading} tabIndex={0} onKeyDown={keyDown} onScroll={event => { shown.current.top = event.currentTarget.scrollTop }} className={gridVariants({ cardSize: cardSize as "small" | "medium" | "large", loading })}>
    {loading ? <div aria-hidden="true" className="virtual-canvas" style={{ "--virtual-height": `${visibleRows * rowHeight}px` } as CSSProperties}>
      {Array.from({ length: visibleRows }, (_, row) => <div key={row} className="virtual-row gap-3 pb-3" style={{ "--virtual-top": `${row * rowHeight}px`, "--virtual-columns": columns } as CSSProperties}>
        {Array.from({ length: columns }, (_, column) => <VideoCardPlaceholder key={column} />)}
      </div>)}
    </div> : load === "failed" ? <GridMessage title="영상 목록을 읽지 못했습니다" description="앱을 다시 시작하면 목록을 다시 읽습니다." />
    : !videos.length ? <GridMessage title={total ? "조건에 맞는 영상이 없습니다" : "라이브러리가 비어 있습니다"}
      description={total ? "검색 조건이나 선택한 폴더를 바꿔 보세요." : "폴더 관리(Ctrl+7)에서 감시 폴더나 영상 파일을 추가하세요."} />
    // 줄 높이가 고정이라 전체 높이는 줄 수 × 줄 높이다. 가상화 캐시는 measure 뒤에야 바뀌므로 직접 계산해, 새 열 수를 그린 커밋에서 바로 보던 자리로 스크롤할 수 있게 한다.
    : <div className="virtual-canvas" style={{ "--virtual-height": `${Math.ceil(videos.length / columns) * rowHeight}px` } as CSSProperties}>
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
