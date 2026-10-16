import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Notice } from "@/components/ui/notice"

export function AutomaticDetection({ enabled, scanning, onChange }: { enabled: boolean; scanning: boolean; onChange: (enabled: boolean) => Promise<void> }) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  async function toggle() {
    setSaving(true)
    setError("")
    try { await onChange(!enabled) }
    catch (error) { setError(String(error)) }
    finally { setSaving(false) }
  }
  return <section className="space-y-1 rounded-xl border bg-card px-4 py-3" aria-labelledby="settings-automatic-detection">
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2"><div><h3 id="settings-automatic-detection" className="font-semibold">자동 감지</h3><p role="status" className="text-sm text-muted-foreground">감시 폴더에서 바뀐 영상을 목록에 바로 반영합니다.{scanning && " · 검사 중 변경 잠금"}</p></div><Button id="settings-automatic-detection-toggle" variant={enabled ? 'secondary' : 'outline'} aria-pressed={enabled} disabled={scanning || saving} onClick={() => void toggle()}>자동 감지: {enabled ? '켜짐' : '꺼짐'}</Button></div>
    <p className="text-xs text-muted-foreground">기본값 켬 · 끄면 앱을 시작할 때의 검사도 하지 않습니다. 다시 켜면 그동안 바뀐 파일을 한 번 검사합니다.</p>
    {error && <Notice tone="error" className="mt-2">{error}</Notice>}
  </section>
}
