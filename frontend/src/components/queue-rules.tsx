import { useEffect, useRef, useState, type KeyboardEvent } from "react"
import { request } from "@/bridge"
import type { QueueBridge, QueueRuleData, QueueRulesData } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { SelectField } from "@/components/ui/select"
import { listFrame, listRow } from "@/components/ui/list"
import { ConfirmDialog, EmptyState } from "@/components/page-parts"
import type { KeyGuideRow } from "@/lib/key-guide"


// 아래 keyDown과 같은 키. 키 안내 '지금 화면'에 보인다.
export const queueRuleKeyRows: readonly KeyGuideRow[] = [
  { keys: ["↑ ↓", "Home", "End"], label: "규칙 선택" },
]

export function QueueRules({ bridge, data, showError }: { bridge: QueueBridge | null; data: QueueRulesData; showError: (error: unknown) => void }) {
  const [selected, setSelected] = useState<number | null>(null)
  const [target, setTarget] = useState("")
  const [language, setLanguage] = useState("자동 감지")
  const [count, setCount] = useState(0)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const pending = useRef<{ target: string; language: string } | null>(null)
  const composing = useRef(false)
  const revision = useRef(0)
  const activeTarget = data.targets.some(item => item.key === target) ? target : data.targets[0]?.key ?? ""
  const activeRule = data.rules.find(rule => rule.id === selected)

  useEffect(() => {
    if (!bridge) return
    const deactivate = () => {
      // 외부 탭 이동·재생·트레이 숨김은 아니요와 달리 저장하지 않는다.
      // 후보 조회 응답이 늦게 와도 숨은 페이지에서 확인창을 다시 열지 않는다.
      revision.current += 1
      pending.current = null
      setOpen(false)
      setBusy(false)
    }
    bridge.queueDeactivated.connect(deactivate)
    return () => bridge.queueDeactivated.disconnect(deactivate)
  }, [bridge])

  function selectRule(rule: QueueRuleData) {
    setSelected(rule.id); setTarget(rule.target); setLanguage(rule.language)
  }
  function keyDown(event: KeyboardEvent) {
    if (event.nativeEvent.isComposing || event.ctrlKey || event.altKey || event.metaKey || !data.rules.length) return
    const index = data.rules.findIndex(rule => rule.id === selected)
    const next = event.key === "ArrowDown" ? Math.min(index + 1, data.rules.length - 1) : event.key === "ArrowUp" ? Math.max(index - 1, 0) : event.key === "Home" ? 0 : event.key === "End" ? data.rules.length - 1 : -1
    if (next < 0) return
    event.preventDefault()
    selectRule(data.rules[next])
    document.getElementById(`queue-rule-${data.rules[next].id}`)?.scrollIntoView({ block: "nearest" })
  }
  async function save(include: boolean) {
    const draft = pending.current
    const requestRevision = revision.current
    pending.current = null // Action 클릭 뒤 오는 onOpenChange(false)가 중복 저장하지 않는다.
    setOpen(false)
    if (!bridge || !draft) return
    try { await request(reply => bridge.saveRule(draft.target, draft.language, include, reply)) }
    catch (error) { if (requestRevision === revision.current) showError(error) }
    finally { if (requestRevision === revision.current) setBusy(false) }
  }
  async function prepare() {
    if (!bridge || !activeTarget || busy || composing.current) return
    setBusy(true)
    const requestRevision = ++revision.current
    pending.current = { target: activeTarget, language }
    try {
      const result = await request<{ count: number }>(reply => bridge.candidates(activeTarget, reply))
      if (requestRevision !== revision.current) return
      if (result.count > 0) { setCount(result.count); setOpen(true) }
      else await save(false)
    } catch (error) { if (requestRevision === revision.current) { pending.current = null; setBusy(false); showError(error) } }
  }
  async function remove() {
    if (!bridge || !activeRule || busy) return
    setBusy(true)
    try { await request(reply => bridge.removeRule(activeRule.id, reply)); setSelected(null) }
    catch (error) { showError(error) }
    finally { setBusy(false) }
  }
  return <div className="flex min-h-0 max-w-content flex-1 flex-col gap-3">
    <p className="text-body text-muted-foreground">감시 폴더나 태그에 새로 등록되는 영상의 자막을 자동으로 만듭니다.</p>
    <div id="queue-rules" role="listbox" aria-label="저장된 자동 자막 규칙" aria-activedescendant={activeRule ? `queue-rule-${activeRule.id}` : undefined} tabIndex={0} onKeyDown={keyDown} className={listFrame({ surface: "card", class: "flex-1" })}>
      {data.rules.map(rule => <div key={rule.id} id={`queue-rule-${rule.id}`} role="option" aria-selected={rule.id === selected} className={listRow({ selected: rule.id === selected })} onClick={() => selectRule(rule)}><p className="min-w-0 break-all">{rule.label} · {rule.language}</p></div>)}
      {!data.rules.length && <EmptyState title="자동 자막 규칙이 없습니다" description="아래에서 감시 폴더나 태그를 고르고 '규칙 저장'을 누르세요." />}
    </div>
    <label htmlFor="queue-target" className="text-body">감시 폴더 또는 영상 태그</label>
    <SelectField id="queue-target" aria-label="자동 자막 대상" value={activeTarget} onValueChange={setTarget} disabled={busy} className="w-full"
      options={data.targets.length ? data.targets.map(item => [item.key, item.label] as const) : [["", "감시 폴더나 태그를 먼저 추가하세요."]]} />
    <label htmlFor="queue-language" className="text-body">원어 (선택하지 않으면 자동 감지)</label>
    <Input id="queue-language" aria-label="원어" list="queue-languages" value={language} disabled={busy} onChange={event => setLanguage(event.target.value)} onCompositionStart={() => { composing.current = true }} onCompositionEnd={() => { composing.current = false }} />
    <datalist id="queue-languages">{["자동 감지", "ko", "en", "ja", "zh", "de", "fr", "es"].map(value => <option key={value} value={value} />)}</datalist>
    <div className="flex gap-2"><Button disabled={!bridge || !activeTarget || busy} onClick={prepare}>규칙 저장</Button><Button variant="outline" disabled={!activeRule || busy} onClick={remove}>선택 규칙 해제</Button></div>
    <ConfirmDialog open={open} onOpenChange={value => { if (!value && pending.current) void save(false); else setOpen(value) }} title="기존 영상도 추가" description={`기존 영상 ${count}개도 대기열에 넣을까요? 원어 자막이 있거나 이미 대기 중인 영상은 제외합니다.`} confirmLabel="예" cancelLabel="아니요" onConfirm={() => void save(true)} onCancel={() => void save(false)} />
  </div>
}
