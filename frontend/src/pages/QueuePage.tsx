import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react"
import { connectBridge, request } from "@/bridge"
import { queueStates, type QueueAction, type QueueBridge, type QueueData, type QueueRulesData } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { SelectField } from "@/components/ui/select"
import { NoticeStack } from "@/components/ui/notice"
import { ConfirmDialog, EmptyState, PageHeader, Tabs } from "@/components/page-parts"
import { QueueList, queueKeyRows } from "@/components/queue-list"
import { QueueStore } from "@/components/queue-store"
import { QueueRules, queueRuleKeyRows } from "@/components/queue-rules"
import type { KeyGuideGroup } from "@/lib/key-guide"
import { useLayoutChange } from "@/lib/layout-change"
import { useGenerationGuard } from "@/lib/generation"
import { focusAfterRender, focusPage } from "@/lib/page-focus"
import { firstData } from "@/lib/entry"

// 이 화면에서만 쓰는 키. pages/index.ts의 pageKeyGuides에 등록해 키 안내 '지금 화면'에 보인다.
export const keyGuide: readonly KeyGuideGroup[] = [
  { title: "처리 상태 목록", rows: queueKeyRows },
  { title: "자동 자막 규칙 목록", rows: queueRuleKeyRows },
]

export default function QueuePage() {
  const [store] = useState(() => new QueueStore())
  const meta = useSyncExternalStore(store.subscribe, store.snapshot)
  const [bridge, setBridge] = useState<QueueBridge | null>(null)
  const [rules, setRules] = useState<QueueRulesData>({ targets: [], rules: [] })
  const [tab, setTab] = useState("status")
  const currentTab = useRef(tab)
  currentTab.current = tab
  const [filter, setFilter] = useState("")
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState("")
  const [message, setMessage] = useState("")
  const [confirmation, setConfirmation] = useState("")
  const [busy, setBusy] = useState(false)
  useLayoutChange(tab, rules, error, message)
  const showError = useCallback((error: unknown) => setError(error instanceof Error ? error.message : String(error)), [])
  const select = useCallback((key: string) => setSelected(key), [])
  // 브리지는 매번 전체 상태를 보내므로 늦게 도착한 앞 세대는 버려도 잃는 것이 없다.
  const fresh = useGenerationGuard()

  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(async ({ queue: api }) => {
      if (disposed) return
      const changed = (json: string) => { const data: QueueData = JSON.parse(json); if (fresh(data)) store.apply(data) }
      const rulesChanged = (json: string) => setRules(JSON.parse(json))
      // 기본 초점(보고 있는 목록)과 시점은 공용 규칙이 정한다.
      const focus = (target: string) => focusPage("queue", target)
      const bulkFinished = (json: string) => {
        const result = JSON.parse(json)
        setBusy(false)
        if (result.error) showError(result.error)
        if (result.message) setMessage(result.message)
      }
      api.bulkFinished.connect(bulkFinished)
      api.queueChanged.connect(changed)
      api.rulesChanged.connect(rulesChanged)
      api.queueFocusRequested.connect(focus)
      disconnect = () => { api.bulkFinished.disconnect(bulkFinished); api.queueChanged.disconnect(changed); api.rulesChanged.disconnect(rulesChanged); api.queueFocusRequested.disconnect(focus) }
      const data = await firstData("queue", () => request<QueueData>(reply => api.snapshot(reply)))
      if (disposed) return
      if (fresh(data)) store.apply(data)
      const ruleData = await request<QueueRulesData>(reply => api.rulesSnapshot(reply))
      if (!disposed) { setRules(ruleData); setBridge(api) }
    }).catch(showError)
    return () => { disposed = true; disconnect() }
  }, [showError, store, fresh])
  useEffect(() => { if (bridge) request(reply => bridge.ready(reply)).catch(showError) }, [bridge, showError])

  const ids = meta.order.filter(key => !filter || store.rows.get(key)?.state === filter)
  const active = selected !== null && ids.includes(selected) ? selected : ids[0] ?? null
  const activeRow = active === null ? undefined : store.rows.get(active)
  async function action(name: QueueAction) {
    if (!bridge || busy) return
    setBusy(true); setError(""); setMessage("")
    let pending = false
    try {
      const result = await request<{ message?: string; confirmation?: string; pending?: boolean }>(reply => bridge.action(name, activeRow?.videoId ?? -1, activeRow?.queueKind ?? "", reply))
      pending = !!result.pending
      if (result.confirmation) setConfirmation(result.confirmation)
      if (result.message) setMessage(result.message)
    } catch (error) { showError(error) }
    finally { if (!pending) setBusy(false) }
  }
  function changeTab(value: string) {
    setTab(value)
    if (value === "rules" && bridge) request<QueueRulesData>(reply => bridge.rulesSnapshot(reply)).then(setRules).catch(showError)
  }
  // 빈 상태의 다음 동작. 필터를 풀면 단추가 사라지므로 초점을 목록으로 옮긴다.
  function openRules() {
    changeTab("rules")
    focusAfterRender(() => document.getElementById("queue-rules"))
  }
  function showAllStates() {
    setFilter("")
    document.getElementById("queue-list")?.focus({ preventScroll: true })
  }
  return <main className="flex h-full min-h-0 flex-col gap-3 p-4">
    <ConfirmDialog open={!!confirmation} onOpenChange={open => { if (!open) setConfirmation("") }} title="기존 한국어 자막 모두 다듬기" description={confirmation} confirmLabel="다듬기 요청" onConfirm={() => void action("refineExisting")} />
    <PageHeader title="자막 대기열" />
    <Tabs label="대기열 영역" value={tab} onChange={changeTab} items={[{ value: "status", label: "처리 상태" }, { value: "rules", label: "자동 자막 규칙" }]} />
    {/* 요청 실패와 일괄 작업 결과는 탭 아래 한곳에 쌓는다. */}
    <NoticeStack layout="yield" items={[
      error && { tone: "error", message: error, onDismiss: () => setError("") },
      message && { tone: "success", message, onDismiss: () => setMessage("") },
    ]} />
    {/* 처리 상태 구역은 필터·목록 최소 높이(머리글+행 세 개)·개수·버튼이 들어갈 높이 아래로 줄지 않는다.
        모자라면 위 안내 묶음이 줄어 스크롤한다. 자동 최소 높이는 목록 전체 높이를 따르므로 값을 정해 둔다. */}
    <section hidden={tab !== "status"} className="flex min-h-64 flex-1 flex-col gap-3">
      <div className="flex items-center justify-between gap-4"><SelectField aria-label="대기열 상태 필터" value={filter} options={[["", "모든 상태"], ...queueStates]} onValueChange={setFilter} className="max-w-48" /><p className="text-label text-muted-foreground">↑ / ↓ 선택 · Tab 버튼 이동 · Space 실행</p></div>
      <QueueList store={store} ids={ids} selected={active} onSelect={select} emptyState={<EmptyState variant="page" title={meta.order.length ? "이 상태의 항목이 없습니다" : "자막 대기열이 비어 있습니다"} description={meta.order.length ? "상태 필터를 '모든 상태'로 바꾸면 전체 대기열이 보입니다." : "라이브러리 상세 패널의 '자막 만들기'나 재생 작업 메뉴의 '화면 자막 영역 정하기'로 요청하거나, '자동 자막 규칙' 탭에서 규칙을 추가하세요."}
        action={meta.order.length ? <Button variant="outline" onClick={showAllStates}>모든 상태 보기</Button> : <Button variant="outline" onClick={openRules}>자동 자막 규칙 열기</Button>} />} />
      <p aria-label="상태별 개수" className="text-label text-muted-foreground">{meta.counts.map(item => `${item.label} ${item.count}개`).join(" · ")}</p>
      <div className="flex flex-wrap gap-2"><Button disabled={!bridge || busy} onClick={() => action("previewRefineExisting")}>기존 한국어 자막 모두 다듬기</Button><Button variant="outline" disabled={active === null || busy} onClick={() => action("promote")}>앞당기기</Button><Button variant="outline" disabled={active === null || busy} onClick={() => action("remove")}>빼기</Button><Button disabled={!bridge || busy || !meta.canRetryFailed} onClick={() => action("retryFailed")}>실패 항목 모두 재시도</Button><Button variant="outline" disabled={active === null || busy} onClick={() => action("retryHeld")}>선택한 보류 재시도</Button></div>
    </section>
    <section hidden={tab !== "rules"} className="flex min-h-0 flex-1 flex-col"><QueueRules bridge={bridge} data={rules} showError={showError} /></section>
  </main>
}
