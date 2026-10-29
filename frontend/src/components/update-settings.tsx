import { useEffect, useRef, useState } from "react"
import { request } from "@/bridge"
import type { ShellUpdateData, UpdateAction, UpdateChoice, UpdateResultData, UpdateStatusData } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { NoticeStack, type NoticeItem } from "@/components/ui/notice"
import { UpdateChoices, UpdateProgress, UpdateTitle, useShellUpdate } from "@/components/update-notice"
import { formatDateTime } from "@/lib/dates"

// 고른 뒤 사라지는 버튼 대신 포커스를 둘 자리. 건너뛰기와 건너뛰기 취소는 서로 자리를 바꾸고, 업데이트는 진행 안내의 취소로 간다.
const focusAfter: Record<UpdateChoice, string> = {
  update: 'settings-update-progress-cancel', later: 'settings-update-install', skip: 'settings-update-unskip', unskip: 'settings-update-skip',
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
    // 진행 중이거나 설치를 넘겼으면 버전과 무관하게 선택지를 두지 않는다(눌러도 받지 않는 버튼을 남기지 않는다).
    action: data.updateAllowed ? <UpdateChoices idPrefix="settings-update" later={data.noticeVisible} locked={locked} onChoose={name => choose(name, version)} /> : undefined,
  }
}

export function UpdateSettings({ data, onCheck, onAutomatic, onChoose }: { data: UpdateStatusData; onCheck: () => Promise<void>; onAutomatic: (enabled: boolean) => Promise<void>; onChoose: (name: UpdateChoice, version: string) => Promise<void> }) {
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [dismissed, setDismissed] = useState('')
  // 내려받기·설치 진행은 셸 알림과 같은 값을 셸 신호로 받는다(진행률은 약 100ms마다).
  const shellUpdate = useShellUpdate()
  const install = shellUpdate.data?.install ?? null
  const installing = !!install && install.phase !== 'idle'
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
  function act(name: UpdateAction) {
    const shell = shellUpdate.bridge
    // 진행 안내의 버튼이 사라지면(취소·닫기) 지금 확인으로 포커스를 옮긴다.
    if (document.activeElement?.id.startsWith('settings-update-')) pendingFocus.current = 'settings-update-check'
    if (shell) void run(async () => { shellUpdate.setData(await request<ShellUpdateData>(reply => shell.updateAction(name, reply))) })
  }
  const last = data.last
  const checked = data.checking ? '확인 중…' : last ? `마지막 확인: ${formatDateTime(last.checkedAt)}` : '아직 확인하지 않았습니다.'
  return <div className="space-y-6">
    <section className="space-y-3 rounded-xl border bg-card px-4 py-3" aria-labelledby="settings-update-heading">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div><h3 id="settings-update-heading" className="text-body-strong">현재 버전 {data.installedVersion}</h3><p role="status" className="text-body text-muted-foreground">{checked}</p></div>
        <Button id="settings-update-check" variant="outline" aria-disabled={locked || undefined} onClick={() => { if (!locked) { setDismissed(''); void run(onCheck) } }}>{data.checking ? '확인 중…' : '지금 확인'}</Button>
      </div>
      <NoticeStack items={[
        error && { tone: 'error', message: error, onDismiss: () => setError('') },
        data.error && data.error !== dismissed && { tone: 'error', message: data.error, onDismiss: () => setDismissed(data.error) },
        // 내려받거나 설치를 넘기는 동안에는 같은 버전의 선택지 대신 진행 안내를 보인다.
        last && !(installing && last.latestVersion === install.version) && resultNotice(data, last, locked, choose),
      ]} />
      {installing && <UpdateProgress idPrefix="settings-update-progress" install={install} locked={sending} onAction={act} />}
      <p className="text-label text-muted-foreground">GitHub Release에서 새 버전을 확인합니다. ‘업데이트’를 누르면 설치 파일을 받아 크기와 SHA-256을 확인한 뒤, 앱을 닫고 설치하고 다시 실행합니다.</p>
    </section>
    <section className="space-y-1 rounded-xl border bg-card px-4 py-3" aria-labelledby="settings-update-automatic">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2"><div><h3 id="settings-update-automatic" className="text-body-strong">시작할 때 업데이트 확인</h3><p className="text-body text-muted-foreground">앱을 시작할 때 하루에 한 번 새 버전을 확인합니다.</p></div><Button id="settings-update-automatic-toggle" variant={data.automatic ? 'secondary' : 'outline'} aria-pressed={data.automatic} aria-disabled={sending || undefined} onClick={() => void run(() => onAutomatic(!data.automatic))}>시작할 때 확인: {data.automatic ? '켜짐' : '꺼짐'}</Button></div>
      <p className="text-label text-muted-foreground">기본값 켬 · 꺼도 ‘지금 확인’으로 직접 확인할 수 있습니다. 연결 문제로 실패하면 몇 시간 뒤 다시 확인합니다.</p>
    </section>
  </div>
}
