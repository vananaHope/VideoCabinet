import { useEffect, useRef, useState } from "react"
import type { UpdateChoice, UpdateResultData, UpdateStatusData } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { NoticeStack, type NoticeItem } from "@/components/ui/notice"
import { UpdateChoices, UpdateTitle } from "@/components/update-notice"

function date(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '시각 정보 없음' : parsed.toLocaleString('ko-KR')
}

// 고른 뒤 사라지는 버튼 대신 포커스를 둘 자리. 건너뛰기와 건너뛰기 취소는 서로 자리를 바꾼다.
const focusAfter: Record<UpdateChoice, string> = {
  update: 'settings-update-install', later: 'settings-update-install', skip: 'settings-update-unskip', unskip: 'settings-update-skip',
}

/** 마지막 확인 결과의 안내. 이전 버전에서 확인한 결과는 현재 설치본의 업데이트 안내로 쓰지 않는다. */
function resultNotice(data: UpdateStatusData, last: UpdateResultData, locked: boolean, choose: (name: UpdateChoice, version: string) => void): NoticeItem {
  if (last.stale && last.currentVersion)
    return { key: 'update-result', tone: 'info', title: `이전 버전(${last.currentVersion})에서 확인한 결과입니다`, message: '지금 버전에서는 아직 확인하지 않았습니다. ‘지금 확인’으로 다시 확인하세요.' }
  if (last.kind === 'failed')
    return last.failureQuiet
      ? { key: 'update-result', tone: 'info', message: last.failureMessage }
      : { key: 'update-result', tone: 'warning', title: '업데이트를 확인하지 못했습니다', message: last.failureMessage }
  if (last.kind === 'none' || !last.latestVersion)
    return { key: 'update-result', tone: 'info', title: '최신 버전입니다', message: `GitHub Release의 최신 버전은 ${last.latestVersion}입니다.` }
  const version = last.latestVersion
  if (data.skipped)
    return {
      key: 'update-result', tone: 'info', title: `건너뛴 버전입니다 · ${version}`, message: '이 버전은 다시 알리지 않습니다. 더 새 버전이 나오면 알립니다.',
      action: <Button id="settings-update-unskip" size="sm" variant="outline" aria-disabled={locked || undefined} onClick={() => { if (!locked) choose('unskip', version) }}>건너뛰기 취소</Button>,
    }
  // 릴리스 노트는 서명되지 않은 GitHub 본문의 요약이라 글자로만 보인다. 못 받았으면 노트 없이 보인다.
  return {
    key: 'update-result', tone: 'info', title: <UpdateTitle version={version} kind={last.kind} downloadSize={last.downloadSize} />, message: last.releaseNotes ?? undefined,
    action: <UpdateChoices idPrefix="settings-update" later={data.noticeVisible} locked={locked} onChoose={name => choose(name, version)} />,
  }
}

export function UpdateSettings({ data, onCheck, onAutomatic, onChoose }: { data: UpdateStatusData; onCheck: () => Promise<void>; onAutomatic: (enabled: boolean) => Promise<void>; onChoose: (name: UpdateChoice, version: string) => Promise<void> }) {
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [dismissed, setDismissed] = useState('')
  const pendingFocus = useRef('')
  // 닫은 저장 실패 안내는 그 확인 한 번에만 숨긴다. 새 확인이 시작되면(시작 확인 포함) 같은 문구도 다시 보인다.
  const [wasChecking, setWasChecking] = useState(data.checking)
  if (data.checking !== wasChecking) {
    setWasChecking(data.checking)
    if (data.checking) setDismissed('')
  }
  useEffect(() => {
    if (!pendingFocus.current) return
    const target = document.getElementById(pendingFocus.current)
    if (target) { pendingFocus.current = ''; target.focus() }
  })
  // 키보드로 누른 뒤 포커스가 body로 빠지지 않게 잠금은 aria-disabled로만 보이고 중복 실행을 막는다.
  const locked = data.checking || sending
  async function run(task: () => Promise<void>) {
    if (sending) return
    setSending(true)
    setError('')
    try { await task() }
    catch (error) { pendingFocus.current = ''; setError(String(error)) }
    finally { setSending(false) }
  }
  function choose(name: UpdateChoice, version: string) {
    if (document.activeElement?.id.startsWith('settings-update-')) pendingFocus.current = focusAfter[name]
    void run(() => onChoose(name, version))
  }
  const last = data.last
  const checked = data.checking ? '확인 중…' : last ? `마지막 확인: ${date(last.checkedAt)}` : '아직 확인하지 않았습니다.'
  return <div className="space-y-6">
    <section className="space-y-3 rounded-xl border bg-card px-4 py-3" aria-labelledby="settings-update-heading">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div><h3 id="settings-update-heading" className="font-semibold">현재 버전 {data.installedVersion}</h3><p role="status" className="text-sm text-muted-foreground">{checked}</p></div>
        <Button id="settings-update-check" variant="outline" aria-disabled={locked || undefined} onClick={() => { if (!locked) { setDismissed(''); void run(onCheck) } }}>{data.checking ? '확인 중…' : '지금 확인'}</Button>
      </div>
      <NoticeStack items={[
        error && { tone: 'error', message: error, onDismiss: () => setError('') },
        data.error && data.error !== dismissed && { tone: 'error', message: data.error, onDismiss: () => setDismissed(data.error) },
        last && resultNotice(data, last, locked, choose),
      ]} />
      <p className="text-xs text-muted-foreground">GitHub Release에서 새 버전을 확인합니다. 지금은 ‘업데이트’를 누르면 그 버전의 GitHub Release 페이지가 열리고, 받은 설치 파일로 직접 설치합니다.</p>
    </section>
    <section className="space-y-1 rounded-xl border bg-card px-4 py-3" aria-labelledby="settings-update-automatic">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2"><div><h3 id="settings-update-automatic" className="font-semibold">시작할 때 업데이트 확인</h3><p className="text-sm text-muted-foreground">앱을 시작할 때 하루에 한 번 새 버전을 확인합니다.</p></div><Button id="settings-update-automatic-toggle" variant={data.automatic ? 'secondary' : 'outline'} aria-pressed={data.automatic} aria-disabled={sending || undefined} onClick={() => void run(() => onAutomatic(!data.automatic))}>시작할 때 확인: {data.automatic ? '켜짐' : '꺼짐'}</Button></div>
      <p className="text-xs text-muted-foreground">기본값 켬 · 꺼도 ‘지금 확인’으로 직접 확인할 수 있습니다. 연결 문제로 실패하면 몇 시간 뒤 다시 확인합니다.</p>
    </section>
  </div>
}
