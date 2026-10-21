import { useCallback, useEffect, useRef, useState } from "react"
import { Film } from "lucide-react"
import { connectBridge, request } from "@/bridge"
import type { ReelBridge, ReelData } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { NoticeStack } from "@/components/ui/notice"
import { SelectField } from "@/components/ui/select"
import { EmptyState, PageHeader } from "@/components/page-parts"
import { ResultRow, listKey, restoreListFocus, timestamp } from "@/components/reel-search-parts"
import { formatDateTime } from "@/lib/dates"

export default function ReelPage() {
  const [bridge, setBridge] = useState<ReelBridge | null>(null)
  const [data, setData] = useState<ReelData | null>(null)
  const [error, setError] = useState("")
  const [hiddenStatus, setHiddenStatus] = useState("")
  const scroll = useRef(0)
  const goHome = useRef(() => {})
  const showError = useCallback((error: unknown) => setError(error instanceof Error ? error.message : String(error)), [])
  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(async ({ reel: api, shell }) => {
      if (disposed) return
      goHome.current = () => { request(reply => shell.navigate("library", reply)).catch(showError) }
      const changed = (json: string) => setData(JSON.parse(json))
      const focus = () => restoreListFocus("reel-list", scroll.current)
      api.changed.connect(changed); api.focusRequested.connect(focus); api.error.connect(showError)
      disconnect = () => { api.changed.disconnect(changed); api.focusRequested.disconnect(focus); api.error.disconnect(showError) }
      const initial = await request<ReelData>(reply => api.snapshot(reply))
      if (!disposed) { setData(initial); setBridge(api) }
    }).catch(showError)
    return () => { disposed = true; disconnect() }
  }, [showError])
  useEffect(() => { if (bridge) request(reply => bridge.ready(reply)).catch(showError) }, [bridge, showError])
  // 완료 안내가 사라지면(새로고침·필터·탭 이동) 닫은 기록도 지워 다음 완료 때 다시 보인다.
  // 재생에서 돌아올 때는 빈 상태 없이 같은 문구가 다시 올 수 있어 play()에서도 지운다.
  useEffect(() => { if (!data?.status) setHiddenStatus("") }, [data?.status])
  const entries = data?.entries ?? []
  const selected = entries.find(entry => entry.id === data?.selectedId)
  function select(index: number) {
    const id = entries[index].id
    setData(previous => previous && { ...previous, selectedId: id })
    if (bridge) request(reply => bridge.select(id, reply)).catch(showError)
    document.getElementById(`reel-${id}`)?.scrollIntoView({ block: "nearest" })
  }
  function play(id: number) {
    if (!bridge) return
    // 재생 요청이 새 모아보기의 시작이다. 코어도 이때 완료 안내를 비우므로 화면도 비우고 닫은 기록을 지워,
    // 같은 완료 문구가 다시 와도 새 완료로 보인다.
    setError(""); setHiddenStatus(""); setData(current => current?.status ? { ...current, status: "" } : current)
    request(reply => bridge.play(id, reply)).catch(showError)
  }
  return <main aria-label="하이라이트 모아보기" onKeyDown={event => { if (event.key === "Escape" && !event.nativeEvent.isComposing && !event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey) { event.preventDefault(); goHome.current() } }} className="flex h-full flex-col gap-3 p-4">
    <PageHeader title="하이라이트 모아보기" description="모든 영상의 하이라이트를 이어서 봅니다. 시청 기록과 별도로 복습을 기록합니다." />
    <div className="flex items-center gap-3">
      <label className="flex min-w-0 flex-1 items-center gap-3 text-sm">하이라이트 태그
        <SelectField aria-label="하이라이트 모아보기 태그 필터" value={String(data?.tagId ?? 0)} className="max-w-48"
          options={[["0", "모든 하이라이트"], ...(data?.tags ?? []).map(tag => [String(tag.id), tag.name] as const)]}
          onValueChange={value => { if (bridge) { scroll.current = 0; request(reply => bridge.filter(Number(value), reply)).catch(showError) } }} />
      </label>
      <Button variant="outline" onClick={() => { if (bridge) request(reply => bridge.refresh(reply)).catch(showError) }}>목록 갱신</Button>
    </div>
    {/* 재생 요청 실패와 모아보기 완료 안내를 목록 위 한곳에 쌓는다. 아래 줄은 늘 목록 설명을 보인다. */}
    <NoticeStack layout="yield" items={[
      error && { tone: "error", message: error, onDismiss: () => setError("") },
      data?.status && data.status !== hiddenStatus && { tone: "success", message: data.status, onDismiss: () => setHiddenStatus(data.status) },
    ]} />
    <div id="reel-list" role="listbox" aria-label="모든 영상의 하이라이트" aria-activedescendant={selected ? `reel-${selected.id}` : undefined} tabIndex={0}
      onScroll={event => { if (event.currentTarget.offsetParent) scroll.current = event.currentTarget.scrollTop }}
      onKeyDown={event => listKey(event, entries.length, entries.findIndex(e => e.id === selected?.id), select, () => { if (selected?.playable) play(selected.id) })}
      className="min-h-32 flex-1 space-y-1.5 overflow-y-auto rounded-lg p-1 focus-visible:outline-2 focus-visible:outline-ring">
      {!entries.length ? <EmptyState title={data?.emptyTitle ?? "불러오는 중…"} description={data?.emptyDescription ?? ""} /> : entries.map((entry, index) => <ResultRow key={entry.id} id={`reel-${entry.id}`} selected={entry.id === selected?.id}
        onClick={() => { select(index); document.getElementById("reel-list")?.focus({ preventScroll: true }) }} onDoubleClick={() => { if (entry.playable) play(entry.id) }}>
        <div className="relative flex aspect-video w-32 shrink-0 items-center justify-center self-start overflow-hidden rounded-md bg-muted"><Film aria-hidden="true" className="absolute size-8 text-muted-foreground" />{entry.thumbnail && <img src={entry.thumbnail} alt="" loading="lazy" onError={event => { event.currentTarget.hidden = true }} className="relative h-full w-full object-cover" />}</div>
        <div className="min-w-0 flex-1 space-y-1">
          <p className="wrap-anywhere font-semibold">{entry.title}</p>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs"><span className="text-highlight tabular-nums">{timestamp(entry.start)}{entry.end === null ? " · 지점" : ` — ${timestamp(entry.end)}`}</span><span className="text-muted-foreground">마지막 복습: {entry.lastRevisitedAt ? formatDateTime(entry.lastRevisitedAt) : "아직 없음"}</span></div>
          {!entry.playable && <p className="text-xs text-muted-foreground">{entry.missing ? "파일 없음 — 재생 불가" : "길이 0인 지점"} · 차례 재생에서 건너뜀</p>}
          {entry.note && <p className="line-clamp-3 whitespace-pre-wrap wrap-anywhere text-sm">{entry.note}</p>}
          {!!entry.tags.length && <div aria-label="하이라이트 태그" className="flex flex-wrap items-center gap-1"><span className="text-xs text-muted-foreground">태그:</span>{entry.tags.map(tag => <span key={tag.id} className="max-w-full rounded-md border border-border bg-secondary px-2 py-0.5 text-xs wrap-anywhere text-secondary-foreground">{tag.name}</span>)}</div>}
        </div>
      </ResultRow>)}
    </div>
    <div className="flex flex-wrap items-center gap-3"><Button disabled={!entries.some(e => e.playable)} onClick={() => play(0)}>처음부터 차례 재생</Button><Button variant="outline" disabled={!selected?.playable} onClick={() => selected && play(selected.id)}>선택한 하이라이트부터 재생</Button><span className="text-xs text-muted-foreground">↑/↓ 선택 · Enter 재생</span></div>
    <p role="status" className="text-xs text-muted-foreground">{`하이라이트 ${entries.length}개 · 영상 제목 → 영상 안 시각 순 · 파일 없음·길이 0인 지점은 건너뜁니다. 새 항목은 ‘목록 갱신’으로 불러옵니다.`}</p>
  </main>
}
