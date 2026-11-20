import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Notice } from "@/components/ui/notice"
import { SettingsCard } from "@/components/settings-parts"

export function MinimumDuration({ value, scanning, onSave, id }: { value: number; scanning: boolean; onSave: (value: number) => Promise<void>; id: string }) {
  const [draft, setDraft] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const text = draft ?? String(value)
  const locked = scanning || saving
  async function save() {
    if (locked) return
    const seconds = Number(text)
    if (!text.trim() || !Number.isFinite(seconds) || seconds < 0 || seconds > 31536000) {
      setError("최소 길이는 0~31536000초 사이로 입력하세요.")
      return
    }
    setSaving(true)
    setError("")
    try { await onSave(seconds); setDraft(null) }
    catch (error) { setError(String(error)) }
    finally { setSaving(false) }
  }
  return <SettingsCard labelFor={id} title="새 영상의 최소 길이" status description={<>저장된 최소 길이: {value}초{scanning && " · 검사 중 변경 잠금"}</>}
    control={<><Input id={id} className="w-28" type="number" min="0" max="31536000" step="0.01" value={text} disabled={scanning || saving} onChange={e => setDraft(e.target.value)} /><span>초</span><Button variant="outline" aria-disabled={locked || undefined} onClick={() => void save()}>저장</Button></>}
    note="기본값 60초 · 0이면 제한 없음. 다시 검사할 때 새 영상에 적용하며 기존 영상은 유지합니다.">
    {error && <Notice tone="error">{error}</Notice>}
  </SettingsCard>
}
