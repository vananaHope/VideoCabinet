import { useCallback, useEffect, useRef, useState } from "react"
import { connectBridge, request } from "@/bridge"
import type { SearchBridge, SearchData } from "@/bridge-types"
import { EmptyState, PageHeader, StatusBadge } from "@/components/page-parts"
import { MatchedText, ResultRow, SearchInput, listKey, restoreListFocus, timestamp } from "@/components/reel-search-parts"

export default function SearchPage() {
  const [bridge, setBridge] = useState<SearchBridge | null>(null)
  const [data, setData] = useState<SearchData | null>(null)
  const [query, setQuery] = useState("")
  const [pending, setPending] = useState(false)
  const [error, setError] = useState("")
  const composing = useRef(false)
  const draft = useRef("")
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const scroll = useRef(0)
  const focusAfterSearch = useRef(false)
  const showError = useCallback((error: unknown) => setError(error instanceof Error ? error.message : String(error)), [])
  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(async ({ search: api }) => {
      if (disposed) return
      const changed = (json: string) => {
        const next: SearchData = JSON.parse(json)
        if (!composing.current && next.query === draft.current) {
          setData(next); setPending(false)
          if (focusAfterSearch.current && next.state !== "preparing") {
            focusAfterSearch.current = false
            if (next.results.length) restoreListFocus("search-results", 0)
          }
        }
      }
      const focus = () => restoreListFocus(document.querySelector('#search-results [role="option"]') ? "search-results" : "search-query", scroll.current)
      api.changed.connect(changed); api.focusRequested.connect(focus); api.error.connect(showError)
      disconnect = () => { api.changed.disconnect(changed); api.focusRequested.disconnect(focus); api.error.disconnect(showError) }
      const initial = await request<SearchData>(reply => api.snapshot(reply))
      if (!disposed) { setData(initial); setQuery(initial.query); draft.current = initial.query; setBridge(api) }
    }).catch(showError)
    return () => { disposed = true; disconnect(); clearTimeout(timer.current) }
  }, [showError])
  useEffect(() => { if (bridge) request(reply => bridge.ready(reply)).catch(showError) }, [bridge, showError])
  function find(value: string) {
    clearTimeout(timer.current)
    if (bridge && !composing.current) request(reply => bridge.find(value, reply)).catch(showError)
  }
  function change(value: string) {
    setQuery(value); draft.current = value; setPending(true); setError(""); scroll.current = 0; focusAfterSearch.current = false
    clearTimeout(timer.current)
    if (!composing.current) timer.current = setTimeout(() => find(value), 200)
  }
  const results = pending ? [] : data?.results ?? []
  function select(index: number) {
    setData(previous => previous && { ...previous, selectedIndex: index })
    if (bridge) request(reply => bridge.select(index, reply)).catch(showError)
    document.getElementById(`search-result-${index}`)?.scrollIntoView({ block: "nearest" })
  }
  function play(index: number) {
    if (bridge && results[index]) { setError(""); request(reply => bridge.play(index, reply)).catch(showError) }
  }
  const state = pending ? "pending" : data?.state ?? "empty"
  const empty = state === "preparing" ? ["검색 색인을 준비하고 있습니다", "처음 한 번만 걸립니다. 준비가 끝나면 입력한 검색어로 바로 찾습니다."]
    : state === "no-results" ? ["검색 결과가 없습니다", "다른 낱말로 찾거나 더 짧게 입력해 보세요."]
    : state === "error" ? ["검색하지 못했습니다", data?.error ?? ""]
    : ["찾을 내용을 입력하세요", "제목, 파일 이름, 태그, 메모, 원어·번역 자막을 한 번에 찾습니다."]
  return <main aria-label="검색" className="flex h-full flex-col gap-3 p-4">
    <PageHeader title="검색" />
    <SearchInput id="search-query" aria-label="검색어" placeholder="제목 · 파일 이름 · 태그 · 메모 · 자막 내용" value={query}
      onCompositionStart={() => { composing.current = true; clearTimeout(timer.current); setPending(true) }}
      onCompositionEnd={event => { composing.current = false; change(event.currentTarget.value) }}
      onChange={event => change(event.target.value)}
      onKeyDown={event => {
        if (composing.current || event.nativeEvent.isComposing || event.keyCode === 229 || event.ctrlKey || event.altKey || event.metaKey || event.shiftKey) return
        if (event.key === "ArrowDown" || event.key === "Enter") {
          event.preventDefault()
          if (pending) { focusAfterSearch.current = true; find(query) }
          else if (results.length) document.getElementById("search-results")?.focus()
        }
      }} />
    <p className="text-xs text-muted-foreground">띄어쓰기와 대소문자를 구분하지 않습니다. ↓ 결과 선택 · Enter 또는 클릭으로 재생</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <div id="search-results" role="listbox" aria-label="검색 결과" aria-busy={pending || state === "preparing"} aria-activedescendant={results.length ? `search-result-${data?.selectedIndex}` : undefined} tabIndex={0}
      onScroll={event => { if (event.currentTarget.offsetParent) scroll.current = event.currentTarget.scrollTop }}
      onKeyDown={event => listKey(event, results.length, data?.selectedIndex ?? 0, select, () => play(data?.selectedIndex ?? -1))}
      className="min-h-0 flex-1 space-y-1.5 overflow-y-auto rounded-lg p-1 focus-visible:outline-2 focus-visible:outline-ring">
      {results.length ? results.map((result, index) => <ResultRow key={index} id={`search-result-${index}`} selected={index === data?.selectedIndex} onClick={() => { select(index); document.getElementById("search-results")?.focus({ preventScroll: true }); play(index) }}>
        <div className="min-w-0 flex-1 space-y-1"><p className="wrap-anywhere font-semibold"><MatchedText parts={result.title} /></p>
          <div className="flex items-center gap-3"><StatusBadge>{result.source}</StatusBadge>{result.start !== null && <span className="text-xs text-highlight tabular-nums">{timestamp(result.start)}</span>}{result.missing && <span className="text-xs text-muted-foreground">파일 없음</span>}</div>
          <p className="whitespace-pre-wrap wrap-anywhere text-sm"><MatchedText parts={result.text} /></p></div>
      </ResultRow>) : state !== "pending" && <EmptyState title={empty[0]} description={empty[1]} />}
    </div>
    <p role="status" className="text-sm text-muted-foreground">{state === "pending" ? "검색 중…" : state === "preparing" ? "검색 색인 준비 중…" : state === "error" ? `검색 실패: ${data?.error}` : !query.trim() ? "검색어를 입력하세요." : `검색 결과 ${results.length}개`}{!pending && data?.truncated && ` · 최대 ${data.limit}개까지 표시합니다. 결과가 많습니다. 더 길게 입력하세요.`}</p>
  </main>
}
