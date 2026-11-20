import { useState } from "react"
import { Switch } from "@/components/ui/switch"
import { Notice } from "@/components/ui/notice"
import { SettingsCard } from "@/components/settings-parts"

export function AutomaticDetection({ enabled, scanning, onChange }: { enabled: boolean; scanning: boolean; onChange: (enabled: boolean) => Promise<void> }) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  // 키보드로 누른 뒤 포커스가 body로 빠지지 않게 잠금은 aria-disabled로만 보이고 중복 실행을 막는다.
  const locked = scanning || saving
  async function toggle() {
    if (locked) return
    setSaving(true)
    setError("")
    try { await onChange(!enabled) }
    catch (error) { setError(String(error)) }
    finally { setSaving(false) }
  }
  return <SettingsCard aria-labelledby="settings-automatic-detection" titleId="settings-automatic-detection" title="자동 감지" status
    description={<>감시 폴더에서 바뀐 영상을 목록에 바로 반영합니다.{scanning && " · 검사 중 변경 잠금"}</>}
    control={<><span aria-hidden="true" className="text-body text-muted-foreground">{enabled ? '켜짐' : '꺼짐'}</span><Switch id="settings-automatic-detection-toggle" aria-labelledby="settings-automatic-detection" checked={enabled} aria-disabled={locked || undefined} onCheckedChange={() => void toggle()} /></>}
    note="기본값 켬 · 끄면 앱을 시작할 때의 검사도 하지 않습니다. 다시 켜면 그동안 바뀐 파일을 한 번 검사합니다.">
    {error && <Notice tone="error">{error}</Notice>}
  </SettingsCard>
}
