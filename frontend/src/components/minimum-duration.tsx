import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

export function MinimumDuration({ value, scanning, onSave, id }: { value: number; scanning: boolean; onSave: (value: number) => Promise<void>; id: string }) {
  const [draft, setDraft] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const text = draft ?? String(value)
  async function save() {
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
  return <section className="space-y-1 rounded-xl border bg-card px-4 py-3">
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2"><div><label htmlFor={id} className="font-semibold">새 영상의 최소 길이</label><p role="status" className="text-sm text-muted-foreground">저장된 최소 길이: {value}초{scanning && " · 검사 중 변경 잠금"}</p></div><div className="flex w-64 items-center gap-2"><Input id={id} type="number" min="0" max="31536000" step="0.01" value={text} disabled={scanning || saving} onChange={e => setDraft(e.target.value)} /><span>초</span><Button variant="outline" disabled={scanning || saving} onClick={() => void save()}>저장</Button></div></div>
    <p className="text-xs text-muted-foreground">기본값 60초 · 0이면 제한 없음. 다시 검사할 때 새 영상에 적용하며 기존 영상은 유지합니다.</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </section>
}
