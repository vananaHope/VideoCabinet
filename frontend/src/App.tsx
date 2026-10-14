import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react"
import { Sparkles } from "lucide-react"
import { Input } from "@/components/ui/input"
import { NativeSelect } from "@/components/ui/native-select"
import { Button } from "@/components/ui/button"
import { GemCard } from "@/components/gem-card"
import { VideoMenu } from "@/components/video-menu"
import { LibraryGrid, openKeyboardMenu } from "@/components/library-grid"
import { DetailPanel } from "@/components/detail-panel"
import { connectBridge, getSnapshot, getDetails, request, type Bridge, type Action } from "@/bridge"
import type { LibraryData, DetailsData } from "@/bridge-types"

export default function App() {
  const [bridge, setBridge] = useState<Bridge | null>(null)
  const [data, setData] = useState<LibraryData | null>(null)
  const [details, setDetails] = useState<DetailsData | null>(null)
  const [query, setQuery] = useState("")
  const [tag, setTag] = useState(0)
  const [error, setError] = useState("")
  const [gemId, setGemId] = useState<number | null>(null)
  const [detailRevision, setDetailRevision] = useState(0)
  const savedScroll = useRef<{ grid: number; gems: number; detail: number } | null>(null)
  const layoutPaused = useRef(false)
  const composing = useRef(false)
  const filterRevision = useRef(0)
  const showError = useCallback((error: unknown) => setError(error instanceof Error ? error.message : String(error)), [])

  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(async api => {
      if (disposed) return
      const changed = (json: string) => { setData(JSON.parse(json)); setDetailRevision(n => n + 1) }
      const detailsChanged = () => setDetailRevision(n => n + 1)
      const focus = (target: string) => {
        layoutPaused.current = false
        window.dispatchEvent(new Event('resize'))
        requestAnimationFrame(() => requestAnimationFrame(() => {
          const position = savedScroll.current
          const grid = document.getElementById('library-grid')
          const gems = document.getElementById('hidden-gems')
          const detail = document.querySelector('aside')
          if (position) {
            if (grid) grid.scrollTop = position.grid
            if (gems) gems.scrollLeft = position.gems
            if (detail) detail.scrollTop = position.detail
            savedScroll.current = null
          }
          const destination = target === 'gems' && gems ? gems : grid
          destination?.focus({ preventScroll: true })
        }))
      }
      api.changed.connect(changed)
      api.detailsChanged.connect(detailsChanged)
      api.focusRequested.connect(focus)
      api.error.connect(showError)
      disconnect = () => { api.changed.disconnect(changed); api.detailsChanged.disconnect(detailsChanged); api.focusRequested.disconnect(focus); api.error.disconnect(showError) }
      const initial = await getSnapshot(api)
      if (disposed) return
      setBridge(api)
      setData(initial)
    }).catch(showError)
    return () => { disposed = true; disconnect() }
  }, [showError])

  // effect는 첫 스냅숏의 격자가 DOM에 반영된 뒤 실행된다.
  useEffect(() => {
    if (bridge) request(reply => bridge.ready(reply)).catch(showError)
  }, [bridge, showError])

  useEffect(() => {
    let current = true
    setDetails(null)
    if (bridge && data?.selectedId != null) getDetails(bridge, data.selectedId).then(value => { if (current) setDetails(value) }).catch(error => { if (current) showError(error) })
    return () => { current = false }
  }, [bridge, data?.selectedId, detailRevision, showError])

  const byId = useMemo(() => new Map(data?.videos.map(video => [video.id, video]) ?? []), [data?.videos])
  const visible = useMemo(() => data?.visibleIds.flatMap(id => byId.get(id) ?? []) ?? [], [data?.visibleIds, byId])
  const gems = data?.gems ?? []
  const activeGem = gems.some(g => g.videoId === gemId) ? gemId : gems[0]?.videoId
  const activeTag = data?.tags.some(t => t.id === tag) ? tag : 0

  function filter(text: string, tagId: number) {
    if (!bridge) return
    const revision = ++filterRevision.current
    request<Pick<LibraryData, "visibleIds" | "selectedId">>(reply => bridge.filter(text, tagId, reply)).then(result => {
      if (revision === filterRevision.current) setData(previous => previous && { ...previous, ...result })
    }).catch(showError)
  }
  function select(id: number) {
    if (!bridge) return
    setData(previous => previous && { ...previous, selectedId: id })
    request(reply => bridge.select(id, reply)).catch(showError)
  }
  function action(name: Action, id: number) {
    if (name === 'play' || name === 'playGem' || name === 'review') {
      // mpv 전환 중 숨은 웹 뷰의 폭이 바뀌어도 열 수와 스크롤을 유지한다.
      // 복귀 focus 신호에서 resize를 재측정하고 두 프레임 뒤 저장한 위치를 복원한다.
      layoutPaused.current = true
      savedScroll.current = {
        grid: document.getElementById('library-grid')?.scrollTop ?? 0,
        gems: document.getElementById('hidden-gems')?.scrollLeft ?? 0,
        detail: document.querySelector('aside')?.scrollTop ?? 0,
      }
    }
    if (bridge) request(reply => bridge.action(name, id, reply)).catch(error => {
      layoutPaused.current = false
      savedScroll.current = null
      window.dispatchEvent(new Event('resize'))
      showError(error)
    })
  }
  function gemKey(event: KeyboardEvent<HTMLDivElement>) {
    if (!activeGem || (event.target as HTMLElement).closest('[role="menu"]')) return
    if (openKeyboardMenu(event, document.getElementById(`gem-${activeGem}`))) return
    if (event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || event.nativeEvent.isComposing) return
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault()
      const index = gems.findIndex(gem => gem.videoId === activeGem)
      const next = gems[Math.max(0, Math.min(gems.length - 1, index + (event.key === "ArrowLeft" ? -1 : 1)))].videoId
      setGemId(next)
      document.getElementById(`gem-${next}`)?.scrollIntoView({ block: "nearest", inline: "nearest" })
    } else if (event.key === "Enter" || event.key === "Backspace") {
      event.preventDefault()
      if (!event.repeat) action(event.key === "Enter" ? "playGem" : "dismiss", activeGem)
    }
  }

  return <main aria-label="라이브러리" className="flex h-full flex-col gap-2 p-2">
    <div className="flex items-center gap-3">
      <div className="min-w-0 flex-1"><Input aria-label="영상 제목 빠른 검색" placeholder="제목으로 빠른 검색" value={query}
        onCompositionStart={() => { composing.current = true }} onCompositionEnd={event => { composing.current = false; filter(event.currentTarget.value, activeTag) }}
        onChange={event => { setQuery(event.target.value); if (!composing.current) filter(event.target.value, activeTag) }} /></div>
      <label className="flex items-center gap-2 text-xs text-muted-foreground">태그
        <NativeSelect aria-label="라이브러리 태그 필터" value={activeTag} onChange={event => { const value = Number(event.target.value); setTag(value); filter(query, value) }}>
          <option value={0}>모든 태그</option>{data?.tags.map(tag => <option key={tag.id} value={tag.id}>{tag.name}</option>)}
        </NativeSelect>
      </label>
    </div>
    {error && <div role="alert" className="flex items-center justify-between gap-2 rounded-lg border border-destructive p-3 text-destructive"><span>{error}</span><Button variant="outline" size="sm" onClick={() => setError("")}>닫기</Button></div>}
    <section aria-label="숨겨진 보석" className="flex flex-col gap-1">
      <div className="flex items-center gap-2"><Sparkles className="size-4 text-primary" aria-hidden="true" /><h2 className="text-sm font-semibold">숨겨진 보석</h2><span className="text-xs text-muted-foreground">{data?.gemError ? `불러오지 못했어요: ${data.gemError}` : gems.length ? "←/→ 선택 · Enter 재생 · Backspace 관심 없음" : "지금은 추천할 영상이 없어요"}</span></div>
      {gems.length > 0 && <div id="hidden-gems" role="listbox" aria-label="숨겨진 보석 추천 카드" aria-activedescendant={`gem-${activeGem}`} tabIndex={0} onKeyDown={gemKey} className="grid grid-cols-4 gap-2 rounded-lg p-1">
        {gems.map(gem => { const video = byId.get(gem.videoId); return video && <VideoMenu key={gem.videoId} id={gem.videoId} gem scanning={false} onAction={action}>
          <GemCard id={`gem-${gem.videoId}`} video={video} reason={gem.reason} variant={activeGem === gem.videoId ? "selected" : "default"} role="option" aria-selected={activeGem === gem.videoId} tabIndex={-1}
            onClick={() => { setGemId(gem.videoId); action("playGem", gem.videoId) }} onContextMenu={() => setGemId(gem.videoId)} />
        </VideoMenu> })}
      </div>}
    </section>
    <div className="flex min-h-0 flex-1 gap-2">
      <LibraryGrid videos={visible} selectedId={data?.selectedId ?? null} scanning={data?.scanning ?? false} total={data?.videos.length ?? 0} onSelect={select} onAction={action} layoutPaused={layoutPaused} />
      <DetailPanel variant={data?.selectedId == null ? "empty" : "selected"} video={byId.get(data?.selectedId ?? -1)} details={details} scanning={data?.scanning ?? false} onAction={action} />
    </div>
  </main>
}
