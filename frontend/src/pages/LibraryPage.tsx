import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { PanelLeftClose, PanelLeftOpen } from "lucide-react"
import { Input } from "@/components/ui/input"
import { LibraryChoice, LibraryFilters, LibraryFilterChips } from "@/components/library-filters"
import { LibraryFolders, folderKeyRows } from "@/components/library-folders"
import { Button } from "@/components/ui/button"
import { NoticeStack } from "@/components/ui/notice"
import { PendingStatus } from "@/components/ui/pending-status"
import { LibraryGrid, gridKeyRows, type FirstLoad } from "@/components/library-grid"
import type { HighlightSnapshot } from "@/components/highlight-panel"
import { DetailPanel } from "@/components/detail-panel"
import { RandomPlayButton } from "@/components/random-play-button"
import { RandomTagDialog } from "@/components/random-tag-dialog"
import { connectBridge, getSnapshot, getDetails, request, type LibraryBridge, type Action } from "@/bridge"
import { libraryViewDefaults, type LibraryData, type DetailsData, type HighlightData, type LibraryKeyBindingsData, type LibraryViewOptions, type TagCandidatesData } from "@/bridge-types"
import type { KeyGuideGroup } from "@/lib/key-guide"
import { useLayoutChange } from "@/lib/layout-change"

// 이 화면에서만 쓰는 키. pages/index.ts의 pageKeyGuides에 등록해 키 안내 '지금 화면'에 보인다.
export const keyGuide: readonly KeyGuideGroup[] = [
  { title: "영상 격자", rows: gridKeyRows },
  { title: "폴더 패널 (열었을 때)", rows: folderKeyRows },
  { title: "상세 패널", rows: [
    { keys: ["↑ ↓", "Home", "End"], label: "하이라이트 선택" },
    { keys: ["Enter"], label: "선택한 하이라이트부터 재생" },
    { keys: ["F2"], label: "하이라이트 편집" },
    { keys: ["Enter", "메뉴 키"], label: "태그 칩 메뉴 (이 태그에서 무작위 재생)" },
  ] },
]

export default function LibraryPage() {
  const [bridge, setBridge] = useState<LibraryBridge | null>(null)
  const [data, setData] = useState<LibraryData | null>(null)
  const [details, setDetails] = useState<DetailsData | null>(null)
  const [highlights, setHighlights] = useState<HighlightSnapshot | null>(null)
  const [detailTab, setDetailTab] = useState("info")
  const detailVideo = useRef<number | null>(null)
  const highlightReturn = useRef(false)
  const randomReturn = useRef(false)
  const [revealRequest, setRevealRequest] = useState(0)
  // 후보 없음 안내는 그때의 결과에 묶어, 결과가 바뀌면 함께 사라진다.
  const [randomNotice, setRandomNotice] = useState<{ message: string; scope: string } | null>(null)
  const [tagDialogOpen, setTagDialogOpen] = useState(false)
  const randomMenu = useRef<HTMLButtonElement>(null)
  const optionsRef = useRef<LibraryViewOptions | null>(null)
  const [error, setError] = useState("")
  // 첫 데이터 요청이 실패했는지. 오류 안내를 닫아도 실패는 그대로이고, 뒤에 데이터가 오면 ready가 된다.
  const [firstLoadFailed, setFirstLoadFailed] = useState(false)
  const [detailRevision, setDetailRevision] = useState(0)
  const savedScroll = useRef<{ grid: number; detail: number } | null>(null)
  const layoutPaused = useRef(false)
  const composing = useRef(false)
  const filterRevision = useRef(0)
  // 결과가 바뀔 때 목록을 맨 위로 올리지 않고 보던 카드의 자리를 지킬지. 폴더 패널 여닫기만 자리를 지킨다.
  const [keepPlace, setKeepPlace] = useState(false)
  // 격자 스크롤·썸네일 도착은 고정 조작 요소를 옮기지 않으므로 결과·선택·상세가 바뀔 때만 알린다.
  useLayoutChange(data?.options, data?.visibleIds, data?.selectedId, details, detailTab, error)
  const showError = useCallback((error: unknown) => setError(error instanceof Error ? error.message : String(error)), [])

  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(async ({ library: api, shell }) => {
      if (disposed) return
      const changed = (json: string) => {
        const next: LibraryData = JSON.parse(json)
        if (composing.current && optionsRef.current) next.options.query = optionsRef.current.query
        optionsRef.current = next.options
        // 자막·번역 완료가 늦게 도착해도 그사이 고른 영상이 결과에 남아 있으면 유지한다.
        // 조건에서 빠진 영상이나 명시적인 선택 변경은 코어가 보낸 선택을 따른다.
        setData(previous => next.preserveSelection && previous?.selectedId != null && next.visibleIds.includes(previous.selectedId)
          ? { ...next, selectedId: previous.selectedId } : next)
        setKeepPlace(false)
        setDetailRevision(n => n + 1)
      }
      const thumbnailsChanged = (json: string) => {
        const ids = new Set<number>(JSON.parse(json))
        setData(previous => previous && { ...previous, videos: previous.videos.map(video => ids.has(video.id) ? { ...video, thumbnail: `mvm-thumb://video/${video.id}?v=640` } : video) })
      }
      const detailsChanged = () => setDetailRevision(n => n + 1)
      const keyBindingsChanged = (json: string) => { const keyBindings: LibraryKeyBindingsData = JSON.parse(json); setData(previous => previous && { ...previous, keyBindings }) }
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
        requestAnimationFrame(() => requestAnimationFrame(() => {
          const position = savedScroll.current
          const grid = document.getElementById('library-grid')
          const detail = document.getElementById('detail-scroll')
          if (position) {
            if (grid) grid.scrollTop = position.grid
            if (detail) detail.scrollTop = position.detail
            savedScroll.current = null
          }
          layoutPaused.current = false
          window.dispatchEvent(new Event('resize'))
          const destination = highlightReturn.current && detail ? detail : grid
          highlightReturn.current = false
          // 무작위로 고른 영상은 화면 밖일 수 있어 복원한 스크롤에서 그 카드까지 보이게 한다.
          if (randomReturn.current) { randomReturn.current = false; setRevealRequest(n => n + 1) }
          destination?.focus({ preventScroll: true })
        }))
      }
      api.thumbnailsChanged.connect(thumbnailsChanged)
      api.libraryChanged.connect(changed)
      api.libraryDetailsChanged.connect(detailsChanged)
      api.libraryFocusRequested.connect(focus)
      api.libraryError.connect(showError)
      api.libraryKeyBindingsChanged.connect(keyBindingsChanged)
      shell.shellChanged.connect(shellChanged)
      disconnect = () => { api.thumbnailsChanged.disconnect(thumbnailsChanged); api.libraryChanged.disconnect(changed); api.libraryDetailsChanged.disconnect(detailsChanged); api.libraryFocusRequested.disconnect(focus); api.libraryError.disconnect(showError); api.libraryKeyBindingsChanged.disconnect(keyBindingsChanged); shell.shellChanged.disconnect(shellChanged) }
      // 첫 스냅숏이 실패해도 뒤에 libraryChanged로 온 데이터를 조작할 수 있게 브리지를 먼저 잡는다.
      setBridge(api)
      const initial = await getSnapshot(api)
      if (disposed) return
      optionsRef.current = initial.options
      setData(initial)
    }).catch(error => {
      if (disposed) return
      setFirstLoadFailed(true)
      showError(error)
    })
    return () => { disposed = true; disconnect() }
  }, [showError])

  // effect는 첫 데이터의 격자가 DOM에 반영된 뒤 실행된다.
  const loaded = data !== null
  const firstLoad: FirstLoad = loaded ? "ready" : firstLoadFailed ? "failed" : "pending"
  useEffect(() => {
    if (bridge && loaded) request(reply => bridge.ready(reply)).catch(showError)
  }, [bridge, loaded, showError])

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
  // 첫 데이터 전에는 기본 보기 조건으로 툴바를 같은 자리·같은 크기에 그린다. 저장된 조건을 먼저 받는 일은 #267이 맡는다.
  const options = data?.options ?? libraryViewDefaults
  const foldersOpen = data?.options.mode === 'folders'
  const resultScope = useMemo(() => data?.visibleIds.join(",") ?? "", [data?.visibleIds])

  function filter(patch: Partial<LibraryViewOptions>) {
    if (!bridge || !optionsRef.current) return
    const previous = optionsRef.current
    const next = { ...previous, ...patch }
    optionsRef.current = next
    setData(data => data && { ...data, options: next })
    const revision = ++filterRevision.current
    request<Pick<LibraryData, "visibleIds" | "selectedId" | "options" | "chips">>(reply => bridge.view(JSON.stringify(next), reply)).then(result => {
      if (revision === filterRevision.current) { optionsRef.current = result.options; setData(data => data && { ...data, ...result }); setKeepPlace("mode" in patch) }
    }).catch(error => {
      if (revision === filterRevision.current) { optionsRef.current = previous; setData(data => data && { ...data, options: previous }); showError(error) }
    })
  }
  function select(id: number) {
    if (!bridge) return
    setData(previous => previous && { ...previous, selectedId: id })
    request(reply => bridge.select(id, reply)).catch(showError)
  }
  // mpv 전환 중 숨은 웹 뷰의 폭이 바뀌어도 열 수와 스크롤을 유지한다.
  // 복귀 focus 신호에서 resize를 재측정하고 두 프레임 뒤 저장한 위치를 복원한다.
  function holdLayout() {
    layoutPaused.current = true
    savedScroll.current = {
      grid: document.getElementById('library-grid')?.scrollTop ?? 0,
      detail: document.getElementById('detail-scroll')?.scrollTop ?? 0,
    }
  }
  function releaseLayout() {
    layoutPaused.current = false
    savedScroll.current = null
    window.dispatchEvent(new Event('resize'))
  }
  function action(name: Action, id: number) {
    if (name === 'play' || name === 'review') holdLayout()
    if (bridge) request(reply => bridge.action(name, id, reply)).catch(error => {
      releaseLayout()
      showError(error)
    })
  }
  const loadTagCandidates = useCallback(() => bridge
    ? request<{ tags: TagCandidatesData[] }>(reply => bridge.randomTagCandidates(reply)).then(result => result.tags)
    : Promise.resolve([]), [bridge])
  // 범위가 없으면 현재 결과에서, "all"이면 검색 조건과 상관없이 영상 전체에서, 태그 목록이면 그 태그 중 하나라도 붙은 영상에서 고른다.
  // 재생·복귀·안내는 같은 경로다.
  function randomPlay(range?: number[] | "all") {
    if (!bridge) return
    const scope = resultScope
    holdLayout()
    request<{ videoId: number | null; message?: string }>(reply => range === "all" ? bridge.randomPlayAll(reply) : range ? bridge.randomPlayTags(JSON.stringify(range), reply) : bridge.randomPlay(reply)).then(({ videoId, message }) => {
      if (videoId === null) {
        releaseLayout()
        setRandomNotice({ message: message ?? "", scope })
        return
      }
      setRandomNotice(null)
      randomReturn.current = true
      setData(previous => previous && { ...previous, selectedId: videoId })
    }).catch(error => {
      releaseLayout()
      showError(error)
    })
  }
  function highlightAction(videoId: number, highlightId: number, edit: boolean) {
    if (!bridge) return
    if (!edit) {
      highlightReturn.current = true
      holdLayout()
    }
    request(reply => edit ? bridge.editHighlight(videoId, highlightId, reply) : bridge.playHighlight(videoId, highlightId, reply)).catch(error => {
      highlightReturn.current = false
      releaseLayout()
      showError(error)
    })
  }
  return <main aria-label="라이브러리" className="flex h-full flex-col gap-2 p-2">
    {/* 툴바는 첫 데이터 전에도 같은 자리에 그리고, 데이터가 올 때까지 누를 수 없다. */}
    <div className="flex shrink-0 items-center gap-2">
      <div className="min-w-24 flex-1"><Input aria-label="영상 제목 빠른 검색" placeholder="제목 검색" value={options.query} disabled={!data}
        onCompositionStart={() => { composing.current = true }} onCompositionEnd={event => { composing.current = false; filter({ query: event.currentTarget.value }) }}
        onChange={event => { const query = event.target.value; if (!composing.current) filter({ query }); else if (data) { optionsRef.current = { ...data.options, query }; setData({ ...data, options: { ...data.options, query } }) } }} /></div>
      <LibraryChoice name="card_size" label="카드 크기" options={options} disabled={!data} onChange={filter} />
      <LibraryChoice name="sort" label="정렬" options={options} disabled={!data} onChange={filter} />
      <Button size="sm" variant="outline" aria-label="정렬 방향" disabled={!data} onClick={() => filter({ descending: !options.descending })}>{options.descending ? "내림차순 ↓" : "오름차순 ↑"}</Button>
      <LibraryFilters options={options} tags={data?.tags ?? []} disabled={!data} onChange={filter} />
      {/* 개수 자리는 9,999개까지 들어가는 폭을 잡아 두어 첫 데이터가 와도 옆 컨트롤이 밀리지 않는다. 그 전에는 "0개" 대신 기다림 표시를 둔다. */}
      {data ? <p aria-label="라이브러리 등록·표시 개수" className="min-w-44 shrink-0 text-xs text-muted-foreground tabular-nums">등록 영상 {data.videos.length}개 · 표시 {data.visibleIds.length}개</p>
        : <PendingStatus pending={firstLoad === "pending"} className="min-w-44 shrink-0" />}
      <RandomPlayButton menuRef={randomMenu} disabled={!data} scopes={[
        { key: "results", label: "현재 결과에서", onSelect: () => randomPlay() },
        { key: "all", label: "영상 전체에서", onSelect: () => randomPlay("all"), shortcut: data?.keyBindings.randomPlay },
        { key: "tags", label: "태그에서…", onSelect: () => setTagDialogOpen(true), opensDialog: true },
      ]} />
      {data && <RandomTagDialog open={tagDialogOpen} onOpenChange={setTagDialogOpen} tags={data.tags} load={loadTagCandidates}
        onPlay={randomPlay} onReturnFocus={() => randomMenu.current?.focus()} />}
    </div>
    {/* 칩 줄은 칩이 없거나 첫 데이터 전에도 같은 높이를 차지해 아래 목록이 밀리지 않는다. */}
    <LibraryFilterChips options={options} chips={data?.chips ?? []} onChange={filter} />
    <div className="flex min-h-40 flex-1 gap-2">
      {/* 패널을 닫아도 고른 폴더(folder)는 옵션에 남아 다시 열 때 복원된다. */}
      <Button size="icon-sm" variant={foldersOpen ? "secondary" : "outline"} aria-label="폴더 패널" aria-expanded={foldersOpen} aria-controls={foldersOpen ? "library-folder-panel" : undefined} disabled={!data}
        title={foldersOpen ? "폴더 패널 닫기" : "폴더 패널 열기"} onClick={() => filter({ mode: foldersOpen ? 'all' : 'folders' })}>{foldersOpen ? <PanelLeftClose /> : <PanelLeftOpen />}</Button>
      {foldersOpen && <LibraryFolders collapsedIds={data.options.collapsed_folders} onCollapse={collapsed_folders => filter({ collapsed_folders })} folders={data.folders} selected={data.options.folder} onSelect={folder => filter({ folder })} />}
      {/* 페이지 안내는 격자 위쪽에 떠 있는 띠라 생기고 사라져도 격자의 자리·열 수·스크롤이 그대로다. 툴바·칩 줄·상세 패널은 덮지 않는다. */}
      <div className="relative flex min-w-0 flex-1">
        <LibraryGrid cardSize={options.card_size} load={firstLoad} videos={visible} selectedId={data?.selectedId ?? null} scanning={data?.scanning ?? false} total={data?.videos.length ?? 0} onSelect={select} onAction={action} layoutPaused={layoutPaused} revealRequest={revealRequest} keepPlace={keepPlace} />
        <NoticeStack layout="band" aria-label="라이브러리 안내" items={[
          error && { tone: "error", message: error, onDismiss: () => setError("") },
          randomNotice?.scope === resultScope && { tone: "info", message: randomNotice.message, onDismiss: () => setRandomNotice(null) },
        ]} />
      </div>
      <DetailPanel variant={!data ? (firstLoad === "failed" ? "failed" : "loading") : data.selectedId == null ? "empty" : "selected"} video={byId.get(data?.selectedId ?? -1)} details={details} highlights={highlights} revision={detailRevision} tab={detailTab} onTabChange={setDetailTab} scanning={data?.scanning ?? false} onAction={action} onHighlight={highlightAction} highlightGuidance={data?.keyBindings.highlightGuidance ?? ""} onRandomTag={tagId => randomPlay([tagId])} />
    </div>
  </main>
}
