import { useState } from "react"
import type { RecommendationPeriodData } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Notice } from "@/components/ui/notice"
import { StatusBadge } from "@/components/page-parts"

type Save = (criterion: string, days: string) => Promise<void>
type Reset = (criterion: string) => Promise<void>

/** 추천 기간 하나. 입력은 그대로 보내고 수 읽기·범위 검증은 Python과 코어가 한다. Enter나 저장으로 저장한다. */
function PeriodRow({ period, onSave, onReset }: { period: RecommendationPeriodData; onSave: Save; onReset: Reset }) {
  const [draft, setDraft] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const id = `settings-recommend-${period.criterion}`
  const saved = String(period.days)
  const text = draft ?? saved
  const changed = draft !== null && draft !== saved
  const atDefault = period.days === period.defaultDays && !changed
  async function run(task: () => Promise<void>) {
    if (saving) return
    setSaving(true)
    setError("")
    try { await task(); setDraft(null) }
    catch (error) { setError(error instanceof Error ? error.message : String(error)) }
    finally { setSaving(false) }
  }
  return <form noValidate className="space-y-1 rounded-xl border bg-card px-4 py-3" onSubmit={event => { event.preventDefault(); if (changed) void run(() => onSave(period.criterion, text)) }}>
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2"><label htmlFor={id} className="font-semibold">{period.label}</label>{changed && <StatusBadge variant="info">저장 안 됨</StatusBadge>}</div>
        <p id={`${id}-description`} className="text-sm text-muted-foreground">{period.description}</p>
      </div>
      <div className="flex items-center gap-2">
        <Input id={id} className="w-28" inputMode="decimal" autoComplete="off" value={text} aria-invalid={!!error || undefined} aria-describedby={`${id}-description ${id}-range${error ? ` ${id}-error` : ""}`} onChange={event => { setDraft(event.target.value); setError("") }} />
        <span>일</span>
        <Button type="submit" variant="outline" aria-disabled={saving || !changed || undefined}>저장</Button>
        <Button type="button" variant="ghost" aria-label={`${period.label} 기본값`} aria-disabled={saving || atDefault || undefined} onClick={() => { if (!atDefault) void run(() => onReset(period.criterion)) }}>기본값</Button>
      </div>
    </div>
    <p id={`${id}-range`} role="status" className="text-xs text-muted-foreground">저장된 값 {saved}일 · 기본값 {period.defaultDays}일 · {period.minimumDays}~{period.maximumDays}일, 소수 가능</p>
    {error && <Notice id={`${id}-error`} tone="error" className="mt-2" onDismiss={() => setError("")}>{error}</Notice>}
  </form>
}

export function RecommendationPeriods({ periods, onSave, onReset }: { periods: RecommendationPeriodData[]; onSave: Save; onReset: Reset }) {
  return <section className="space-y-3" aria-labelledby="settings-recommend-heading">
    <div className="space-y-1">
      <h2 id="settings-recommend-heading" className="text-lg font-semibold">추천</h2>
      <p className="text-sm text-muted-foreground">추천 줄이 영상을 고르는 기간을 일 단위로 바꿉니다. 저장하면 추천 탭을 열 때 새 기간으로 다시 계산합니다.</p>
    </div>
    {periods.map(period => <PeriodRow key={period.criterion} period={period} onSave={onSave} onReset={onReset} />)}
  </section>
}
