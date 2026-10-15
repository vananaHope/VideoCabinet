import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react"
import { connectBridge, request } from "@/bridge"
import { queueStates, type QueueAction, type QueueBridge, type QueueDeltaData, type QueueRulesData } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { NativeSelect } from "@/components/ui/native-select"
import { EmptyState, PageHeader, Tabs } from "@/components/page-parts"
import { QueueList } from "@/components/queue-list"
import { QueueStore } from "@/components/queue-store"
import { QueueRules } from "@/components/queue-rules"

export default function QueuePage() {
  const [store] = useState(() => new QueueStore())
  const meta = useSyncExternalStore(store.subscribe, store.snapshot)
  const [bridge, setBridge] = useState<QueueBridge | null>(null)
  const [rules, setRules] = useState<QueueRulesData>({ targets: [], rules: [] })
  const [tab, setTab] = useState("status")
  const currentTab = useRef(tab)
  currentTab.current = tab
  const [filter, setFilter] = useState("")
  const [selected, setSelected] = useState<number | null>(null)
  const [error, setError] = useState("")
  const [message, setMessage] = useState("")
  const [busy, setBusy] = useState(false)
  const showError = useCallback((error: unknown) => setError(error instanceof Error ? error.message : String(error)), [])
  const select = useCallback((id: number) => setSelected(id), [])

  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(async ({ queue: api }) => {
      if (disposed) return
      const changed = (json: string) => store.apply(JSON.parse(json))
      const rulesChanged = (json: string) => setRules(JSON.parse(json))
      const focus = () => requestAnimationFrame(() => document.getElementById(currentTab.current === "rules" ? "queue-rules" : "queue-list")?.focus({ preventScroll: true }))
      api.queueChanged.connect(changed)
      api.rulesChanged.connect(rulesChanged)
      api.queueFocusRequested.connect(focus)
      disconnect = () => { api.queueChanged.disconnect(changed); api.rulesChanged.disconnect(rulesChanged); api.queueFocusRequested.disconnect(focus) }
      const data = await request<QueueDeltaData>(reply => api.snapshot(reply))
      if (disposed) return
      store.apply(data)
      const ruleData = await request<QueueRulesData>(reply => api.rulesSnapshot(reply))
      if (!disposed) { setRules(ruleData); setBridge(api) }
    }).catch(showError)
    return () => { disposed = true; disconnect() }
  }, [showError, store])
  useEffect(() => { if (bridge) request(reply => bridge.ready(reply)).catch(showError) }, [bridge, showError])

  const ids = meta.order.filter(id => !filter || store.rows.get(id)?.state === filter)
  const active = selected !== null && ids.includes(selected) ? selected : ids[0] ?? null
  async function action(name: QueueAction) {
    if (!bridge || busy) return
    setBusy(true); setError("")
    try {
      const result = await request<{ message?: string }>(reply => bridge.action(name, active ?? -1, reply))
      if (result.message) setMessage(result.message)
    } catch (error) { showError(error) }
    finally { setBusy(false) }
  }
  function changeTab(value: string) {
    setTab(value)
    if (value === "rules" && bridge) request<QueueRulesData>(reply => bridge.rulesSnapshot(reply)).then(setRules).catch(showError)
  }
  return <main className="flex h-full min-h-0 flex-col gap-4 p-6">
    <PageHeader title="자막 대기열" />
    <Tabs label="대기열 영역" value={tab} onChange={changeTab} items={[{ value: "status", label: "처리 상태" }, { value: "rules", label: "자동 자막 규칙" }]} />
    {error && <p role="alert" className="shrink-0 text-sm text-destructive">{error}</p>}
    <section hidden={tab !== "status"} className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex items-center justify-between gap-4"><NativeSelect aria-label="대기열 상태 필터" value={filter} onChange={event => setFilter(event.target.value)}><option value="">모든 상태</option>{queueStates.map(([state, label]) => <option key={state} value={state}>{label}</option>)}</NativeSelect><p className="text-xs text-muted-foreground">↑ / ↓ 선택 · Tab 버튼 이동 · Space 실행</p></div>
      <QueueList store={store} ids={ids} selected={active} onSelect={select} />
      {!ids.length && <EmptyState title={meta.order.length ? "이 상태의 항목이 없습니다" : "자막 대기열이 비어 있습니다"} description={meta.order.length ? "상태 필터를 '모든 상태'로 바꾸면 전체 대기열이 보입니다." : "라이브러리 상세 패널의 '자막 만들기'로 요청하거나, '자동 자막 규칙' 탭에서 규칙을 추가하세요."} />}
      <p aria-label="상태별 개수" className="text-xs text-muted-foreground">{meta.counts.map(item => `${item.label} ${item.count}개`).join(" · ")}</p>
      <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={active === null || busy} onClick={() => action("promote")}>앞당기기</Button><Button variant="outline" disabled={active === null || busy} onClick={() => action("remove")}>빼기</Button><Button disabled={!bridge || busy} onClick={() => action("retryFailed")}>실패 항목 모두 재시도</Button><Button variant="outline" disabled={active === null || busy} onClick={() => action("retryHeld")}>선택한 번역 보류 재시도</Button></div>
      {message && <p role="status" className="max-h-24 overflow-auto whitespace-pre-wrap text-sm">{message}</p>}
    </section>
    <section hidden={tab !== "rules"} className="flex min-h-0 flex-1 flex-col"><QueueRules bridge={bridge} data={rules} showError={showError} /></section>
  </main>
}
