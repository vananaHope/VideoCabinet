import { useEffect, useRef, useState } from "react"
import { Dialog } from "radix-ui"
import { request } from "@/bridge"
import type { CapturedKeyData, SettingKeyData, SettingsBridge } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { Notice, NoticeStack } from "@/components/ui/notice"

function browserKey(event: KeyboardEvent) {
  const aliases: Record<string, string> = { ' ': 'Space', Escape: 'Esc', ArrowLeft: 'Left', ArrowRight: 'Right', ArrowUp: 'Up', ArrowDown: 'Down', PageUp: 'PgUp', PageDown: 'PgDn', PrintScreen: 'Print', '₩': '\\' }
  if (['Control', 'Alt', 'Shift', 'Meta', 'Process', 'Dead', 'Unidentified'].includes(event.key)) return null
  if (event.key === 'Escape') return 'Esc'
  return `${event.ctrlKey ? 'Ctrl+' : ''}${event.altKey ? 'Alt+' : ''}${event.shiftKey ? 'Shift+' : ''}${event.metaKey ? 'Meta+' : ''}${aliases[event.key] ?? event.key}`
}

export function KeyBindingsEditor({ rows, bridge }: { rows: SettingKeyData[]; bridge: SettingsBridge }) {
  const [draft, setDraft] = useState<Record<string, { keys: string[]; display: string }>>({})
  const [capturing, setCapturing] = useState<string | null>(null)
  const [error, setError] = useState("")
  const [captureHint, setCaptureHint] = useState("")
  const [message, setMessage] = useState<{ tone: "info" | "success"; text: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const origin = useRef<HTMLButtonElement | null>(null)
  const restoreAfterSave = useRef(false)
  const keys = Object.fromEntries(rows.map(row => [row.id, draft[row.id]?.keys ?? row.keys]))
  const changed = rows.filter(row => JSON.stringify(keys[row.id]) !== JSON.stringify(row.keys))
  const changedIds = new Set(changed.map(row => row.id))
  const owners = new Map<string, string>()
  const conflicts: string[] = []
  for (const row of rows) for (const key of keys[row.id] ?? []) {
    const previous = owners.get(key)
    if (previous) conflicts.push(`${key}: ‘${previous}’와 ‘${row.label}’가 같은 키를 사용합니다.`)
    else owners.set(key, row.label)
  }
  useEffect(() => {
    const captured = (json: string) => {
      const result: CapturedKeyData = JSON.parse(json)
      if (result.continuing) { setCaptureHint(result.error); return }
      setCapturing(null)
      setCaptureHint("")
      setError(result.error)
      if (!result.cancelled && !result.error) {
        setDraft(previous => ({ ...previous, [result.command]: { keys: [result.key], display: result.display } }))
        setMessage({ tone: "info", text: `${result.display}로 바꿨습니다. 적용을 누르면 바로 반영됩니다.` })
      }
      requestAnimationFrame(() => origin.current?.focus())
    }
    bridge.keyCaptured.connect(captured)
    return () => bridge.keyCaptured.disconnect(captured)
  }, [bridge])
  useEffect(() => {
    if (!capturing) return
    const capture = (event: KeyboardEvent) => {
      // Qt가 먼저 전달받은 입력은 네이티브 필터에서 소모한다. Chromium 입력 경로도 보호한다.
      event.preventDefault()
      event.stopImmediatePropagation()
      if (event.repeat || event.isComposing) return
      const name = browserKey(event)
      request(reply => bridge.captureKey(name ?? '', reply)).catch(error => setError(String(error)))
    }
    document.addEventListener('keydown', capture, true)
    return () => document.removeEventListener('keydown', capture, true)
  }, [bridge, capturing])
  useEffect(() => () => { request(reply => bridge.cancelCapture(reply)).catch(() => {}) }, [bridge])
  useEffect(() => {
    // disabled 해제가 DOM에 반영된 뒤 복귀한다. 브리지 응답 직후의 프레임은 아직 비활성일 수 있다.
    if (!saving && restoreAfterSave.current) {
      restoreAfterSave.current = false
      origin.current?.focus()
    }
  }, [saving, message])

  async function begin(id: string, button: HTMLButtonElement) {
    origin.current = button
    setError("")
    setMessage(null)
    setCaptureHint("")
    try { await request(reply => bridge.beginCapture(id, reply)); setCapturing(id) }
    catch (error) { setError(String(error)) }
  }
  async function save() {
    setSaving(true)
    setError("")
    try { await request(reply => bridge.saveKeys(JSON.stringify(keys), reply)); setDraft({}); restoreAfterSave.current = true; setMessage({ tone: "success", text: "키 배치를 저장했습니다. 재생과 키 안내에 바로 반영됩니다." }) }
    catch (error) { setError(String(error)) }
    finally { setSaving(false) }
  }
  function cancel() { request(reply => bridge.cancelCapture(reply)).catch(error => setError(String(error))) }
  return <section className="flex min-h-0 flex-1 flex-col gap-3" aria-label="키 배치 편집">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-lg font-semibold">키 배치</h2><div className="flex gap-2"><Button variant="outline" disabled={saving} onClick={() => { setDraft(Object.fromEntries(rows.map(row => [row.id, { keys: row.defaults, display: row.defaultDisplay }]))); setMessage({ tone: 'info', text: '전체 기본값을 선택했습니다. 적용을 눌러 저장하세요.' }); setError('') }}>전체 기본값</Button><Button variant="outline" disabled={saving || changed.length === 0} onClick={() => { setDraft({}); setError(''); setMessage({ tone: 'info', text: '적용하지 않은 변경을 취소했습니다.' }) }}>변경 취소</Button><Button disabled={saving || changed.length === 0 || conflicts.length > 0} onClick={() => void save()}>적용</Button></div></div>
    <p className="text-sm text-muted-foreground">키 바꾸기에서 입력한 뒤 적용을 누르세요. Esc는 캡처 취소입니다. 목록 탐색과 편집 대화상자의 키는 바뀌지 않습니다.</p>
    <p className="text-sm text-muted-foreground">예약 키: Ctrl+1~Ctrl+8 · Alt+S (설정) · F1 (키 안내) · Esc (취소·복귀)</p>
    {/* 저장 실패·키 충돌(오류) → 적용 전 변경 수·작업 결과(정보·성공) 순으로 쌓는다. 충돌 목록은 한 안내로 묶는다. */}
    <NoticeStack layout="yield" items={[
      error && { tone: "error", message: error, onDismiss: () => setError("") },
      conflicts.length > 0 && { key: "conflicts", tone: "error", message: <div className="space-y-1">{conflicts.map(text => <p key={text}>{text}</p>)}</div> },
      changed.length > 0 && { key: "changed", tone: "info", message: `적용하지 않은 변경 ${changed.length}건` },
      message && { tone: message.tone, message: message.text, onDismiss: () => setMessage(null) },
    ]} />
    {/* 고정 머리글 높이만큼 스크롤 여백을 두어, 포커스·이동으로 보이게 한 행이 머리글 밑에 가려지지 않게 한다. */}
    <div className="min-h-40 flex-1 scroll-pt-10 overflow-y-auto rounded-xl border">
      <table className="w-full text-left text-sm" aria-label="명령별 키 배치"><thead className="sticky top-0 bg-muted"><tr><th className="px-3 py-2">명령</th><th className="px-3 py-2">현재 키 / 기본 키</th><th className="px-3 py-2">초안</th><th className="px-3 py-2">편집</th></tr></thead><tbody>{rows.map(row => <tr key={row.id} className="border-t" data-changed={changedIds.has(row.id)}><th scope="row" className="px-3 py-2 font-medium"><p>{row.label}</p>{row.note && <p className="mt-1 max-w-xs text-xs font-normal text-muted-foreground">{row.note}</p>}</th><td className="px-3 py-2"><p>{row.display}</p><p className="text-xs text-muted-foreground">기본: {row.defaultDisplay}</p></td><td className="px-3 py-2">{changedIds.has(row.id) && <div className="rounded-md bg-accent p-2 text-accent-foreground"><p className="text-xs font-semibold">변경</p><p>{draft[row.id].display}</p></div>}</td><td className="px-3 py-2"><div className="flex gap-2"><Button variant="outline" size="sm" disabled={saving} aria-label={`${row.label} 키 바꾸기`} data-command={row.id} onClick={event => void begin(row.id, event.currentTarget)}>키 바꾸기</Button><Button variant="ghost" size="sm" disabled={saving} aria-label={`${row.label} 기본값`} onClick={() => { setDraft({ ...draft, [row.id]: { keys: row.defaults, display: row.defaultDisplay } }); setError(''); setMessage({ tone: 'info', text: '기본값을 선택했습니다. 적용을 눌러 저장하세요.' }) }}>기본값</Button></div></td></tr>)}</tbody></table>
    </div>
    <Dialog.Root open={capturing !== null} onOpenChange={open => { if (!open) cancel() }}><Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-50 animate-fade-enter bg-background/80" /><Dialog.Content className="fixed inset-0 z-50 m-auto h-fit animate-fade-enter w-full max-w-lg space-y-4 rounded-xl border bg-popover p-6 text-popover-foreground shadow-lg" onEscapeKeyDown={event => { event.preventDefault(); cancel() }} onCloseAutoFocus={event => { event.preventDefault(); origin.current?.focus() }}><Dialog.Title className="text-lg font-semibold">새 키 입력</Dialog.Title><Dialog.Description className="text-sm text-muted-foreground">{rows.find(row => row.id === capturing)?.label}에 할당할 키를 누르세요. 문자·숫자·방향키·기능키와 Ctrl/Alt/Shift 조합을 사용할 수 있습니다. Esc로 취소합니다.</Dialog.Description>{captureHint && <Notice tone="warning">{captureHint}</Notice>}<Button variant="outline" onClick={cancel}>캡처 취소</Button></Dialog.Content></Dialog.Portal></Dialog.Root>
  </section>
}
