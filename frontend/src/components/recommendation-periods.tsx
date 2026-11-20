import { useRef, useState } from "react"
import type { RecommendationPeriodData } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { NoticeStack } from "@/components/ui/notice"
import { StatusBadge } from "@/components/page-parts"
import { SettingsCard, SettingsSection } from "@/components/settings-parts"

type Save = (criterion: string, days: string) => Promise<void>
type Reset = (criterion: string) => Promise<void>

/** 추천 기간 하나. 입력은 그대로 보내고 수 읽기·범위 검증은 Python과 코어가 한다. Enter나 저장으로 저장하고 Esc나 되돌리기는 저장 전 입력을 버린다. */
function PeriodRow({ period, onSave, onReset }: { period: RecommendationPeriodData; onSave: Save; onReset: Reset }) {
  const [draft, setDraft] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  // 입력·Esc마다 늘린다. 응답을 기다리는 동안 새로 편집했으면 그 응답으로 초안을 지우거나 오류를 띄우지 않는다.
  const edits = useRef(0)
  const input = useRef<HTMLInputElement>(null)
  const id = `settings-recommend-${period.criterion}`
  const saved = period.days === null ? "" : String(period.days)
  const text = draft ?? saved
  const changed = draft !== null && draft !== saved
  const describedBy = [`${id}-description`, `${id}-range`, (error || period.error) && `${id}-notices`].filter(Boolean).join(" ")
  const atDefault = period.days === period.defaultDays && !changed
  async function run(task: () => Promise<void>) {
    if (saving) return
    setSaving(true)
    setError("")
    const version = edits.current
    try { await task(); if (edits.current === version) setDraft(null) }
    catch (error) { if (edits.current === version) setError(error instanceof Error ? error.message : String(error)) }
    finally { setSaving(false) }
  }
  // Esc와 되돌리기가 같이 쓴다. 저장 응답을 기다리는 중에 버려도 그 응답이 초안을 지우거나 오류를 띄우지 않는다.
  function discard() {
    if (!changed) return false
    edits.current += 1
    setDraft(null)
    setError("")
    return true
  }
  return <SettingsCard as="form" noValidate onSubmit={event => { event.preventDefault(); if (changed) void run(() => onSave(period.criterion, text)) }}
    labelFor={id} title={period.label} description={period.description} descriptionId={`${id}-description`}
    badge={changed && <><StatusBadge variant="info">저장 안 됨</StatusBadge><Button type="button" size="xs" variant="ghost" aria-label={`${period.label} 되돌리기`} title="저장 전 입력을 버리고 저장된 값으로 돌아갑니다 (Esc)" onClick={() => { if (discard()) input.current?.focus() }}>되돌리기</Button></>}
    control={<>
      <Input ref={input} id={id} className="w-28" inputMode="decimal" autoComplete="off" value={text} aria-invalid={!!(error || period.error) || undefined} aria-describedby={describedBy} onChange={event => { edits.current += 1; setDraft(event.target.value); setError("") }} onKeyDown={event => { if (event.key === "Escape" && changed) { event.preventDefault(); discard() } }} />
      <span>일</span>
      <Button type="submit" variant="outline" aria-disabled={saving || !changed || undefined}>저장</Button>
      <Button type="button" variant="ghost" aria-label={`${period.label} 기본값`} aria-disabled={saving || atDefault || undefined} onClick={() => { if (!atDefault) void run(() => onReset(period.criterion)) }}>기본값</Button>
    </>}
    noteId={`${id}-range`} noteStatus note={`${period.days === null ? "저장된 값을 읽지 못함" : `저장된 값 ${saved}일`} · 기본값 ${period.defaultDays}일 · ${period.minimumDays}~${period.maximumDays}일, 소수 가능`}>
    {/* 요청 실패는 닫을 수 있고, 잘못된 저장값 경고는 고치면 사라진다. */}
    <NoticeStack id={`${id}-notices`} items={[
      error && { tone: "error", message: error, onDismiss: () => setError("") },
      period.error && { tone: "warning", message: period.error },
    ]} />
  </SettingsCard>
}

export function RecommendationPeriods({ periods, onSave, onReset }: { periods: RecommendationPeriodData[]; onSave: Save; onReset: Reset }) {
  return <SettingsSection headingId="settings-recommend-heading" title="추천" description="추천 줄이 영상을 고르는 기간을 일 단위로 바꿉니다. 저장하면 추천 탭을 열 때 새 기간으로 다시 계산합니다.">
    {periods.map(period => <PeriodRow key={period.criterion} period={period} onSave={onSave} onReset={onReset} />)}
  </SettingsSection>
}
