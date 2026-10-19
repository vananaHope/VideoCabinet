import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react"
import { connectBridge, request } from "@/bridge"
import type { RecommendBridge, RecommendData, RecommendationRowData } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { NoticeStack } from "@/components/ui/notice"
import { EmptyState, PageHeader } from "@/components/page-parts"
import { RecommendationCard, RecommendationMenu } from "@/components/recommendation-card"
import { openKeyboardMenu } from "@/components/library-grid"

type Cursor = { kind: string; row: number; column: number; videoId: number }
type Position = { row: number; column: number }

const cardId = (videoId: number) => `recommendation-${videoId}`

// 커서가 가리킬 카드. 영상이 다른 줄로 옮겼으면 따라가고, 사라졌으면(관심 없음·다 봄) 같은 줄의 같은 자리,
// 줄도 사라졌으면 같은 순서의 줄로 간다.
function locate(rows: RecommendationRowData[], cursor: Cursor | null): Position | null {
  if (!rows.length) return null
  if (!cursor) return { row: 0, column: 0 }
  for (const [row, data] of rows.entries()) {
    const column = data.items.findIndex(item => item.video.id === cursor.videoId)
    if (column >= 0) return { row, column }
  }
  const same = rows.findIndex(data => data.kind === cursor.kind)
  const row = same >= 0 ? same : Math.min(cursor.row, rows.length - 1)
  return { row, column: Math.min(cursor.column, rows[row].items.length - 1) }
}

// 카드가 든 줄을 세로 목록 안에, 카드를 그 줄 안에 보이게 한다. 조상 요소는 움직이지 않는다.
function reveal(videoId: number) {
  const card = document.getElementById(cardId(videoId))
  const strip = card?.parentElement
  const section = card?.closest<HTMLElement>("[role=row]")
  const list = document.getElementById("recommendations")
  if (!card || !strip || !section || !list) return
  const bounds = strip.getBoundingClientRect()
  const rect = card.getBoundingClientRect()
  const padding = parseFloat(getComputedStyle(strip).paddingInlineStart)
  const left = rect.left - bounds.left - padding
  const right = rect.right - bounds.right + padding
  strip.scrollLeft += left < 0 ? left : right > 0 ? right : 0
  const outer = list.getBoundingClientRect()
  const row = section.getBoundingClientRect()
  const inset = parseFloat(getComputedStyle(list).paddingBlockStart)
  const top = row.top - outer.top - inset
  const bottom = row.bottom - outer.bottom + inset
  list.scrollTop += top < 0 ? top : bottom > 0 ? Math.min(bottom, top) : 0
}

export default function RecommendPage() {
  const [bridge, setBridge] = useState<RecommendBridge | null>(null)
  const [data, setData] = useState<RecommendData | null>(null)
  const [error, setError] = useState("")
  const [cursor, setCursor] = useState<Cursor | null>(null)
  const [dismissed, setDismissed] = useState<{ id: number; title: string } | null>(null)
  // 줄마다 마지막으로 고른 카드. ↑/↓로 돌아오면 그 카드로 간다.
  const remembered = useRef(new Map<string, number>())
  const focusTarget = useRef(() => {})
  const showError = useCallback((error: unknown) => setError(error instanceof Error ? error.message : String(error)), [])
  const rows = data?.rows ?? []
  const active = locate(rows, cursor)
  const activeId = active ? rows[active.row].items[active.column].video.id : null

  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(async ({ recommend: api }) => {
      if (disposed) return
      const changed = (json: string) => setData(JSON.parse(json))
      // 재생에서 돌아오면 남아 있는 커서 자리의 카드에 초점을 둔다. 레이아웃이 다시 잡힌 뒤 보이게 한다.
      const focus = () => requestAnimationFrame(() => requestAnimationFrame(() => focusTarget.current()))
      api.changed.connect(changed); api.focusRequested.connect(focus); api.error.connect(showError)
      disconnect = () => { api.changed.disconnect(changed); api.focusRequested.disconnect(focus); api.error.disconnect(showError) }
      const initial = await request<RecommendData>(reply => api.snapshot(reply))
      if (!disposed) { setData(initial); setBridge(api) }
    }).catch(showError)
    return () => { disposed = true; disconnect() }
  }, [showError])
  useEffect(() => { if (bridge) request(reply => bridge.ready(reply)).catch(showError) }, [bridge, showError])
  useEffect(() => {
    focusTarget.current = () => {
      if (activeId === null) { document.getElementById("recommend-dismissed")?.focus({ preventScroll: true }); return }
      document.getElementById("recommendations")?.focus({ preventScroll: true })
      reveal(activeId)
    }
  }, [activeId])

  function move(position: Position) {
    const videoId = rows[position.row].items[position.column].video.id
    remembered.current.set(rows[position.row].kind, videoId)
    setCursor({ kind: rows[position.row].kind, ...position, videoId })
    reveal(videoId)
  }
  function play(videoId: number) {
    if (bridge) request(reply => bridge.play(videoId, reply)).catch(showError)
  }
  function dismiss(videoId: number, title: string) {
    if (bridge) request(reply => bridge.dismiss(videoId, reply)).then(() => setDismissed({ id: videoId, title })).catch(showError)
  }
  function restore(videoId: number) {
    if (!bridge) return
    request(reply => bridge.restore(videoId, reply)).then(() => {
      setDismissed(null)
      document.getElementById("recommendations")?.focus({ preventScroll: true })
    }).catch(showError)
  }
  function key(event: KeyboardEvent<HTMLDivElement>) {
    if (!active || (event.target as HTMLElement).closest('[role="menu"]')) return
    const item = rows[active.row].items[active.column]
    if (openKeyboardMenu(event, document.getElementById(cardId(item.video.id)))) return
    if (event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || event.nativeEvent.isComposing) return
    const last = rows[active.row].items.length - 1
    if (event.key === "ArrowLeft" || event.key === "ArrowRight" || event.key === "Home" || event.key === "End") {
      event.preventDefault()
      const column = event.key === "Home" ? 0 : event.key === "End" ? last : Math.max(0, Math.min(last, active.column + (event.key === "ArrowLeft" ? -1 : 1)))
      move({ row: active.row, column })
    } else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault()
      const row = Math.max(0, Math.min(rows.length - 1, active.row + (event.key === "ArrowUp" ? -1 : 1)))
      const items = rows[row].items
      const saved = items.findIndex(entry => entry.video.id === remembered.current.get(rows[row].kind))
      move({ row, column: row === active.row ? active.column : saved >= 0 ? saved : Math.min(active.column, items.length - 1) })
    } else if (event.key === "Enter" || event.key === "Backspace") {
      event.preventDefault()
      if (!event.repeat) {
        if (event.key === "Enter") play(item.video.id)
        else dismiss(item.video.id, item.video.title)
      }
    }
  }

  const count = rows.reduce((sum, row) => sum + row.items.length, 0)
  return <main aria-label="추천" className="flex h-full flex-col gap-3 p-4">
    <PageHeader title="추천" description="시청·하이라이트·태그를 근거로 지금 볼 만한 영상을 이유별 줄로 보여 줍니다. 영상은 한 줄에만 나오고 줄마다 최대 20개입니다."
      actions={<Button id="recommend-dismissed" variant="outline" onClick={() => { if (bridge) request(reply => bridge.showDismissed(reply)).catch(showError) }}>관심 없음 되돌리기</Button>} />
    <NoticeStack layout="yield" items={[
      error && { tone: "error", message: error, onDismiss: () => setError("") },
      data?.error && { tone: "error", message: `추천을 불러오지 못했어요: ${data.error}` },
      dismissed && { tone: "success", message: `관심 없음으로 뺐어요: ${dismissed.title}`, onDismiss: () => setDismissed(null),
        action: <Button size="xs" variant="outline" onClick={() => restore(dismissed.id)}>되돌리기</Button> },
    ]} />
    {count > 0 && <p className="text-xs text-muted-foreground">{`추천 ${rows.length}줄 · ${count}개 · ←/→ 줄 안 이동 · ↑/↓ 줄 사이 이동 · Enter 재생 · Backspace 관심 없음 · 우클릭 메뉴`}</p>}
    {!rows.length ? (!data?.error && <EmptyState variant="page" title={data?.loaded ? "지금은 추천할 영상이 없어요" : "불러오는 중…"}
      description={data?.loaded ? "영상을 보거나 하이라이트·태그를 남기면 이유와 함께 여기에 보여 줍니다. 관심 없음으로 뺀 영상은 ‘관심 없음 되돌리기’에서 다시 추천받을 수 있어요." : ""} />)
      : <div id="recommendations" role="grid" aria-label="추천 줄" aria-activedescendant={activeId !== null ? cardId(activeId) : undefined} tabIndex={0} onKeyDown={key}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto rounded-lg p-1 focus-visible:outline-2 focus-visible:outline-ring">
        {rows.map((row, rowIndex) => <section key={row.kind} role="row" aria-label={`${row.title} · ${row.items.length}개`} className="flex flex-col gap-1">
          <div role="rowheader" className="flex items-baseline gap-2 px-1"><h2 className="text-sm font-semibold">{row.title}</h2><span className="text-xs text-muted-foreground">{row.items.length}개</span></div>
          <div className="recommendation-row rounded-lg p-1">
            {row.items.map((item, column) => <RecommendationMenu key={item.video.id} onPlay={() => play(item.video.id)} onDismiss={() => dismiss(item.video.id, item.video.title)}>
              <RecommendationCard id={cardId(item.video.id)} video={item.video} reason={item.reason} role="gridcell" aria-selected={activeId === item.video.id} tabIndex={-1}
                variant={activeId === item.video.id ? "selected" : "default"}
                onClick={() => { move({ row: rowIndex, column }); play(item.video.id) }} onContextMenu={() => move({ row: rowIndex, column })} />
            </RecommendationMenu>)}
          </div>
        </section>)}
      </div>}
  </main>
}
