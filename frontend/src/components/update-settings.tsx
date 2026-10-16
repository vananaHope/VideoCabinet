import { useState } from "react"
import type { UpdateResultData, UpdateStatusData } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { NoticeStack, type NoticeItem } from "@/components/ui/notice"

function date(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '시각 정보 없음' : parsed.toLocaleString('ko-KR')
}

function size(bytes: number | null) {
  return bytes === null ? '' : ` · ${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** 마지막 확인 결과의 안내. 이전 버전에서 확인한 결과는 현재 설치본의 업데이트 안내로 쓰지 않는다. */
function resultNotice(last: UpdateResultData, releases: () => void): NoticeItem {
  if (last.stale && last.currentVersion)
    return { key: 'update-result', tone: 'info', title: `이전 버전(${last.currentVersion})에서 확인한 결과입니다`, message: '지금 버전에서는 아직 확인하지 않았습니다. ‘지금 확인’으로 다시 확인하세요.' }
  if (last.kind === 'failed')
    return last.failureQuiet
      ? { key: 'update-result', tone: 'info', message: last.failureMessage }
      : { key: 'update-result', tone: 'warning', title: '업데이트를 확인하지 못했습니다', message: last.failureMessage }
  if (last.kind === 'none')
    return { key: 'update-result', tone: 'info', title: '최신 버전입니다', message: `GitHub Release의 최신 버전은 ${last.latestVersion}입니다.` }
  const download = last.kind === 'patch' ? `패치 설치 파일로 올릴 수 있습니다${size(last.downloadSize)}` : `실행 환경이 바뀌어 전체 설치 파일이 필요합니다${size(last.downloadSize)}`
  return {
    key: 'update-result', tone: 'info', title: `새 버전이 있습니다 · ${last.latestVersion}`, message: `${download}. GitHub Release에서 받아 설치하세요.`,
    action: <Button variant="link" size="sm" onClick={releases}>GitHub Release 열기 ↗</Button>,
  }
}

export function UpdateSettings({ data, onCheck, onAutomatic, onReleases }: { data: UpdateStatusData; onCheck: () => Promise<void>; onAutomatic: (enabled: boolean) => Promise<void>; onReleases: () => void }) {
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [dismissed, setDismissed] = useState('')
  // 키보드로 누른 뒤 포커스가 body로 빠지지 않게 잠금은 aria-disabled로만 보이고 중복 실행을 막는다.
  const locked = data.checking || sending
  async function run(task: () => Promise<void>) {
    if (sending) return
    setSending(true)
    setError('')
    try { await task() }
    catch (error) { setError(String(error)) }
    finally { setSending(false) }
  }
  const last = data.last
  const checked = data.checking ? '확인 중…' : last ? `마지막 확인: ${date(last.checkedAt)}` : '아직 확인하지 않았습니다.'
  return <div className="space-y-6">
    <section className="space-y-3 rounded-xl border bg-card px-4 py-3" aria-labelledby="settings-update-heading">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div><h3 id="settings-update-heading" className="font-semibold">현재 버전 {data.installedVersion}</h3><p role="status" className="text-sm text-muted-foreground">{checked}</p></div>
        <Button id="settings-update-check" variant="outline" aria-disabled={locked || undefined} onClick={() => { if (!locked) void run(onCheck) }}>{data.checking ? '확인 중…' : '지금 확인'}</Button>
      </div>
      <NoticeStack items={[
        error && { tone: 'error', message: error, onDismiss: () => setError('') },
        data.error && data.error !== dismissed && { tone: 'error', message: data.error, onDismiss: () => setDismissed(data.error) },
        last && resultNotice(last, onReleases),
      ]} />
      <p className="text-xs text-muted-foreground">GitHub Release에서 새 버전이 있는지만 확인합니다. 내려받거나 설치하지 않습니다.</p>
    </section>
    <section className="space-y-1 rounded-xl border bg-card px-4 py-3" aria-labelledby="settings-update-automatic">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2"><div><h3 id="settings-update-automatic" className="font-semibold">시작할 때 업데이트 확인</h3><p className="text-sm text-muted-foreground">앱을 시작할 때 하루에 한 번 새 버전을 확인합니다.</p></div><Button id="settings-update-automatic-toggle" variant={data.automatic ? 'secondary' : 'outline'} aria-pressed={data.automatic} aria-disabled={sending || undefined} onClick={() => void run(() => onAutomatic(!data.automatic))}>시작할 때 확인: {data.automatic ? '켜짐' : '꺼짐'}</Button></div>
      <p className="text-xs text-muted-foreground">기본값 켬 · 꺼도 ‘지금 확인’으로 직접 확인할 수 있습니다. 연결 문제로 실패하면 몇 시간 뒤 다시 확인합니다.</p>
    </section>
  </div>
}
