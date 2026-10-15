import { useEffect, useRef, useState } from "react"
import { Dialog } from "radix-ui"
import { request } from "@/bridge"
import type { CapturedKeyData, SettingKeyData, SettingsBridge } from "@/bridge-types"
import { Button } from "@/components/ui/button"

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
  const [message, setMessage] = useState("")
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
        setMessage(`${result.display}로 바꿨습니다. 적용을 누르면 바로 반영됩니다.`)
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
    setMessage("")
    setCaptureHint("")
    try { await request(reply => bridge.beginCapture(id, reply)); setCapturing(id) }
    catch (error) { setError(String(error)) }
  }
  async function save() {
    setSaving(true)
    setError("")
    try { await request(reply => bridge.saveKeys(JSON.stringify(keys), reply)); setDraft({}); restoreAfterSave.current = true; setMessage("키 배치를 저장했습니다. 재생과 키 안내에 바로 반영됩니다.") }
    catch (error) { setError(String(error)) }
    finally { setSaving(false) }
  }
  function cancel() { request(reply => bridge.cancelCapture(reply)).catch(error => setError(String(error))) }
  return <section className="flex min-h-0 flex-1 flex-col gap-3" aria-label="키 배치 편집">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-lg font-semibold">키 배치</h2><div className="flex gap-2"><Button variant="outline" disabled={saving} onClick={() => { setDraft(Object.fromEntries(rows.map(row => [row.id, { keys: row.defaults, display: row.defaultDisplay }]))); setMessage('전체 기본값을 선택했습니다. 적용을 눌러 저장하세요.'); setError('') }}>전체 기본값</Button><Button variant="outline" disabled={saving || changed.length === 0} onClick={() => { setDraft({}); setError(''); setMessage('적용하지 않은 변경을 취소했습니다.') }}>변경 취소</Button><Button disabled={saving || changed.length === 0 || conflicts.length > 0} onClick={() => void save()}>적용</Button></div></div>
    <p className="text-sm text-muted-foreground">키 바꾸기에서 입력한 뒤 적용을 누르세요. Esc는 캡처 취소입니다. 목록 탐색과 편집 대화상자의 키는 바뀌지 않습니다.</p>
    <p className="text-sm text-muted-foreground">예약 키: Ctrl+1~Ctrl+7 · Alt+S (설정) · F1 (키 안내) · Esc (취소·복귀)</p>
    {changed.length > 0 && <p role="status" className="text-sm font-medium">적용하지 않은 변경 {changed.length}건</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {conflicts.length > 0 && <div role="alert" className="space-y-1 text-sm text-destructive">{conflicts.map(text => <p key={text}>{text}</p>)}</div>}
    {message && <p role="status" className="text-sm text-muted-foreground">{message}</p>}
    <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border">
      <table className="w-full text-left text-sm" aria-label="명령별 키 배치"><thead className="sticky top-0 bg-muted"><tr><th className="px-3 py-2">명령</th><th className="px-3 py-2">현재 키 / 기본 키</th><th className="px-3 py-2">초안</th><th className="px-3 py-2">편집</th></tr></thead><tbody>{rows.map(row => <tr key={row.id} className="border-t" data-changed={changedIds.has(row.id)}><th scope="row" className="px-3 py-2 font-medium">{row.label}</th><td className="px-3 py-2"><p>{row.display}</p><p className="text-xs text-muted-foreground">기본: {row.defaultDisplay}</p></td><td className="px-3 py-2">{changedIds.has(row.id) && <div className="rounded-md bg-accent p-2 text-accent-foreground"><p className="text-xs font-semibold">변경</p><p>{draft[row.id].display}</p></div>}</td><td className="px-3 py-2"><div className="flex gap-2"><Button variant="outline" size="sm" disabled={saving} aria-label={`${row.label} 키 바꾸기`} data-command={row.id} onClick={event => void begin(row.id, event.currentTarget)}>키 바꾸기</Button><Button variant="ghost" size="sm" disabled={saving} aria-label={`${row.label} 기본값`} onClick={() => { setDraft({ ...draft, [row.id]: { keys: row.defaults, display: row.defaultDisplay } }); setError(''); setMessage('기본값을 선택했습니다. 적용을 눌러 저장하세요.') }}>기본값</Button></div></td></tr>)}</tbody></table>
    </div>
    <Dialog.Root open={capturing !== null} onOpenChange={open => { if (!open) cancel() }}><Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-50 bg-background/80" /><Dialog.Content className="fixed inset-0 z-50 m-auto h-fit w-full max-w-lg space-y-4 rounded-xl border bg-popover p-6 text-popover-foreground shadow-lg" onEscapeKeyDown={event => { event.preventDefault(); cancel() }} onCloseAutoFocus={event => { event.preventDefault(); origin.current?.focus() }}><Dialog.Title className="text-lg font-semibold">새 키 입력</Dialog.Title><Dialog.Description className="text-sm text-muted-foreground">{rows.find(row => row.id === capturing)?.label}에 할당할 키를 누르세요. 문자·숫자·방향키·기능키와 Ctrl/Alt/Shift 조합을 사용할 수 있습니다. Esc로 취소합니다.</Dialog.Description>{captureHint && <p role="status" className="text-sm text-destructive">{captureHint}</p>}<Button variant="outline" onClick={cancel}>캡처 취소</Button></Dialog.Content></Dialog.Portal></Dialog.Root>
  </section>
}
