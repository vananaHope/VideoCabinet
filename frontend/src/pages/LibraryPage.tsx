import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { PanelLeftClose, PanelLeftOpen } from "lucide-react"
import { Input } from "@/components/ui/input"
import { LibraryChoice, LibraryFilters, LibraryFilterChips } from "@/components/library-filters"
import { LibraryFolders } from "@/components/library-folders"
import { Button } from "@/components/ui/button"
import { NoticeStack } from "@/components/ui/notice"
import { LibraryGrid } from "@/components/library-grid"
import type { HighlightSnapshot } from "@/components/highlight-panel"
import { DetailPanel } from "@/components/detail-panel"
import { connectBridge, getSnapshot, getDetails, request, type LibraryBridge, type Action } from "@/bridge"
import type { LibraryData, DetailsData, HighlightData, LibraryViewOptions } from "@/bridge-types"

export default function LibraryPage() {
  const [bridge, setBridge] = useState<LibraryBridge | null>(null)
  const [data, setData] = useState<LibraryData | null>(null)
  const [details, setDetails] = useState<DetailsData | null>(null)
  const [highlights, setHighlights] = useState<HighlightSnapshot | null>(null)
  const [detailTab, setDetailTab] = useState("info")
  const detailVideo = useRef<number | null>(null)
  const highlightReturn = useRef(false)
  const optionsRef = useRef<LibraryViewOptions | null>(null)
  const [error, setError] = useState("")
  const [detailRevision, setDetailRevision] = useState(0)
  const savedScroll = useRef<{ grid: number; detail: number } | null>(null)
  const layoutPaused = useRef(false)
  const composing = useRef(false)
  const filterRevision = useRef(0)
  const showError = useCallback((error: unknown) => setError(error instanceof Error ? error.message : String(error)), [])

  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(async ({ library: api, shell }) => {
      if (disposed) return
      const changed = (json: string) => { const next: LibraryData = JSON.parse(json); if (composing.current && optionsRef.current) next.options.query = optionsRef.current.query; optionsRef.current = next.options; setData(next); setDetailRevision(n => n + 1) }
      const thumbnailsChanged = (json: string) => {
        const ids = new Set<number>(JSON.parse(json))
        setData(previous => previous && { ...previous, videos: previous.videos.map(video => ids.has(video.id) ? { ...video, thumbnail: `mvm-thumb://video/${video.id}?v=640` } : video) })
      }
      const detailsChanged = () => setDetailRevision(n => n + 1)
      const shellChanged = (json: string) => {
        if (JSON.parse(json).tab !== 'library' && !savedScroll.current) {
          layoutPaused.current = true
          savedScroll.current = {
            grid: document.getElementById('library-grid')?.scrollTop ?? 0,
            detail: document.getElementById('detail-scroll')?.scrollTop ?? 0,
          }
        }
      }
      const focus = (target: string) => {
        if (target === 'shell') return
        layoutPaused.current = false
        window.dispatchEvent(new Event('resize'))
        requestAnimationFrame(() => requestAnimationFrame(() => {
          const position = savedScroll.current
          const grid = document.getElementById('library-grid')
          const detail = document.getElementById('detail-scroll')
          if (position) {
            if (grid) grid.scrollTop = position.grid
            if (detail) detail.scrollTop = position.detail
            savedScroll.current = null
          }
          const destination = highlightReturn.current && detail ? detail : grid
          highlightReturn.current = false
          destination?.focus({ preventScroll: true })
        }))
      }
      api.thumbnailsChanged.connect(thumbnailsChanged)
      api.libraryChanged.connect(changed)
      api.libraryDetailsChanged.connect(detailsChanged)
      api.libraryFocusRequested.connect(focus)
      api.libraryError.connect(showError)
      shell.shellChanged.connect(shellChanged)
      disconnect = () => { api.thumbnailsChanged.disconnect(thumbnailsChanged); api.libraryChanged.disconnect(changed); api.libraryDetailsChanged.disconnect(detailsChanged); api.libraryFocusRequested.disconnect(focus); api.libraryError.disconnect(showError); shell.shellChanged.disconnect(shellChanged) }
      const initial = await getSnapshot(api)
      if (disposed) return
      setBridge(api)
      optionsRef.current = initial.options
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
    if (detailVideo.current !== data?.selectedId) {
      setDetails(null)
      setHighlights(null)
      detailVideo.current = data?.selectedId ?? null
    }
    if (bridge && data?.selectedId != null) getDetails(bridge, data.selectedId).then(value => { if (current) setDetails(value) }).catch(error => { if (current) showError(error) })
    return () => { current = false }
  }, [bridge, data?.selectedId, detailRevision, showError])

  useEffect(() => {
    let current = true
    const videoId = data?.selectedId
    if (bridge && videoId != null && detailTab === "highlights") request<HighlightData[]>(reply => bridge.highlights(videoId, reply)).then(value => { if (current) setHighlights({ videoId, revision: detailRevision, items: value }) }).catch(error => { if (current) showError(error) })
    return () => { current = false }
  }, [bridge, data?.selectedId, detailRevision, detailTab, showError])

  const byId = useMemo(() => new Map(data?.videos.map(video => [video.id, video]) ?? []), [data?.videos])
  const visible = useMemo(() => data?.visibleIds.flatMap(id => byId.get(id) ?? []) ?? [], [data?.visibleIds, byId])
  const foldersOpen = data?.options.mode === 'folders'

  function filter(patch: Partial<LibraryViewOptions>) {
    if (!bridge || !optionsRef.current) return
    const previous = optionsRef.current
    const next = { ...previous, ...patch }
    optionsRef.current = next
    setData(data => data && { ...data, options: next })
    const revision = ++filterRevision.current
    request<Pick<LibraryData, "visibleIds" | "selectedId" | "options" | "chips">>(reply => bridge.view(JSON.stringify(next), reply)).then(result => {
      if (revision === filterRevision.current) { optionsRef.current = result.options; setData(data => data && { ...data, ...result }) }
    }).catch(error => {
      if (revision === filterRevision.current) { optionsRef.current = previous; setData(data => data && { ...data, options: previous }); showError(error) }
    })
  }
  function select(id: number) {
    if (!bridge) return
    setData(previous => previous && { ...previous, selectedId: id })
    request(reply => bridge.select(id, reply)).catch(showError)
  }
  function action(name: Action, id: number) {
    if (name === 'play' || name === 'review') {
      // mpv 전환 중 숨은 웹 뷰의 폭이 바뀌어도 열 수와 스크롤을 유지한다.
      // 복귀 focus 신호에서 resize를 재측정하고 두 프레임 뒤 저장한 위치를 복원한다.
      layoutPaused.current = true
      savedScroll.current = {
        grid: document.getElementById('library-grid')?.scrollTop ?? 0,
        detail: document.getElementById('detail-scroll')?.scrollTop ?? 0,
      }
    }
    if (bridge) request(reply => bridge.action(name, id, reply)).catch(error => {
      layoutPaused.current = false
      savedScroll.current = null
      window.dispatchEvent(new Event('resize'))
      showError(error)
    })
  }
  function highlightAction(videoId: number, highlightId: number, edit: boolean) {
    if (!bridge) return
    if (!edit) {
      highlightReturn.current = true
      layoutPaused.current = true
      savedScroll.current = {
        grid: document.getElementById('library-grid')?.scrollTop ?? 0,
        detail: document.getElementById('detail-scroll')?.scrollTop ?? 0,
      }
    }
    request(reply => edit ? bridge.editHighlight(videoId, highlightId, reply) : bridge.playHighlight(videoId, highlightId, reply)).catch(error => {
      highlightReturn.current = false
      layoutPaused.current = false
      savedScroll.current = null
      window.dispatchEvent(new Event('resize'))
      showError(error)
    })
  }
  return <main aria-label="라이브러리" className="flex h-full flex-col gap-2 p-2">
    {data && <>
      <div className="flex shrink-0 items-center gap-2">
        <div className="min-w-24 flex-1"><Input aria-label="영상 제목 빠른 검색" placeholder="제목 검색" value={data.options.query}
          onCompositionStart={() => { composing.current = true }} onCompositionEnd={event => { composing.current = false; filter({ query: event.currentTarget.value }) }}
          onChange={event => { const query = event.target.value; if (!composing.current) filter({ query }); else { optionsRef.current = { ...data.options, query }; setData({ ...data, options: { ...data.options, query } }) } }} /></div>
        <LibraryChoice name="card_size" label="카드 크기" options={data.options} onChange={filter} />
        <LibraryChoice name="sort" label="정렬" options={data.options} onChange={filter} />
        <Button size="sm" variant="outline" aria-label="정렬 방향" onClick={() => filter({ descending: !data.options.descending })}>{data.options.descending ? "내림차순 ↓" : "오름차순 ↑"}</Button>
        <LibraryFilters options={data.options} tags={data.tags} onChange={filter} />
        <p aria-label="라이브러리 등록·표시 개수" className="shrink-0 text-xs text-muted-foreground">등록 영상 {data.videos.length}개 · 표시 {data.visibleIds.length}개</p>
      </div>
      <LibraryFilterChips options={data.options} chips={data.chips} onChange={filter} />
    </>}
    <NoticeStack layout="yield" items={[error && { tone: "error", message: error, onDismiss: () => setError("") }]} />
    {/* 안내가 길어도 카드 격자·상세 패널이 최소 높이를 지킨다. */}
    <div className="flex min-h-40 flex-1 gap-2">
      {/* 패널을 닫아도 고른 폴더(folder)는 옵션에 남아 다시 열 때 복원된다. */}
      {data && <Button size="icon-sm" variant={foldersOpen ? "secondary" : "outline"} aria-label="폴더 패널" aria-expanded={foldersOpen} aria-controls={foldersOpen ? "library-folder-panel" : undefined}
        title={foldersOpen ? "폴더 패널 닫기" : "폴더 패널 열기"} onClick={() => filter({ mode: foldersOpen ? 'all' : 'folders' })}>{foldersOpen ? <PanelLeftClose /> : <PanelLeftOpen />}</Button>}
      {foldersOpen && <LibraryFolders collapsedIds={data.options.collapsed_folders} onCollapse={collapsed_folders => filter({ collapsed_folders })} folders={data.folders} selected={data.options.folder} onSelect={folder => filter({ folder })} />}
      <LibraryGrid cardSize={data?.options.card_size ?? 'medium'} videos={visible} selectedId={data?.selectedId ?? null} scanning={data?.scanning ?? false} total={data?.videos.length ?? 0} onSelect={select} onAction={action} layoutPaused={layoutPaused} />
      <DetailPanel variant={data?.selectedId == null ? "empty" : "selected"} video={byId.get(data?.selectedId ?? -1)} details={details} highlights={highlights} revision={detailRevision} tab={detailTab} onTabChange={setDetailTab} scanning={data?.scanning ?? false} onAction={action} onHighlight={highlightAction} />
    </div>
  </main>
}
