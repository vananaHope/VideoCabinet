import { useEffect, useRef, useState } from "react"
import { connectBridge, request, type ShellBridge } from "@/bridge"
import type { ShellUpdateData, UpdateAction, UpdateChoice, UpdateInstallData, UpdateInstallResultData } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { Notice, NoticeStack, type NoticeTone } from "@/components/ui/notice"
import { Progress } from "@/components/ui/progress"
import { ConfirmDialog } from "@/components/page-parts"

function megabytes(bytes: number | null) {
  return bytes === null ? '' : ` ${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function kindLabel(kind: string | null) {
  return kind === 'patch' ? '패치 설치 파일' : '전체 설치 파일'
}

/** 새 버전 알림 제목. 버전과 받을 크기(서명된 매니페스트 값)를 한 줄에 둔다. */
export function UpdateTitle({ version, kind, downloadSize }: { version: string; kind: string; downloadSize: number | null }) {
  return <>새 버전이 있습니다 · {version}<span className="font-normal text-muted-foreground"> · {kindLabel(kind)}{megabytes(downloadSize)}</span></>
}

/** 셸 알림과 설정 업데이트 구역의 같은 선택지. 잠금은 aria-disabled로만 보여 키보드 포커스가 빠지지 않게 한다. */
export function UpdateChoices({ idPrefix, later, locked, onChoose }: { idPrefix: string; later: boolean; locked: boolean; onChoose: (name: UpdateChoice) => void }) {
  const choose = (name: UpdateChoice) => () => { if (!locked) onChoose(name) }
  return <>
    <Button id={`${idPrefix}-install`} size="sm" title="설치 파일을 받아 확인한 뒤 앱을 닫고 설치합니다" aria-disabled={locked || undefined} onClick={choose('update')}>업데이트</Button>
    {later && <Button id={`${idPrefix}-later`} size="sm" variant="outline" aria-disabled={locked || undefined} onClick={choose('later')}>나중에</Button>}
    <Button id={`${idPrefix}-skip`} size="sm" variant="ghost" aria-disabled={locked || undefined} onClick={choose('skip')}>이 버전 건너뛰기</Button>
  </>
}

/** 셸 업데이트 상태(새 버전 알림·내려받기·설치 결과). 진행률은 따로 오는 작은 신호로 install만 바꾼다. */
export function useShellUpdate() {
  const [bridge, setBridge] = useState<ShellBridge | null>(null)
  const [data, setData] = useState<ShellUpdateData | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(async ({ shell }) => {
      if (disposed) return
      const changed = (json: string) => setData(JSON.parse(json) as ShellUpdateData)
      const progressed = (json: string) => setData(previous => previous && { ...previous, install: JSON.parse(json) as UpdateInstallData })
      shell.shellUpdateChanged.connect(changed)
      shell.shellUpdateInstallChanged.connect(progressed)
      disconnect = () => { shell.shellUpdateChanged.disconnect(changed); shell.shellUpdateInstallChanged.disconnect(progressed) }
      const initial = await request<ShellUpdateData>(reply => shell.updateSnapshot(reply))
      if (!disposed) { setBridge(shell); setData(initial) }
    }).catch(error => setError(String(error)))
    return () => { disposed = true; disconnect() }
  }, [])
  return { bridge, data, setData, error, setError }
}

const activeTitle: Record<string, string> = {
  downloading: '업데이트 내려받는 중', cancelling: '내려받기 취소 중', confirm: '설치 확인을 기다립니다',
  ready: '설치 파일이 준비되었습니다', preparing: '설치 준비 중', failed: '업데이트하지 못했습니다',
}

function progressText(install: UpdateInstallData) {
  if (install.total === null) return '받을 파일을 확인하는 중…'
  const percent = install.total ? Math.floor(install.received * 100 / install.total) : 0
  return `${megabytes(install.received).trim()} /${megabytes(install.total)} · ${percent}%`
}

/** 내려받기·설치 진행 안내. 셸과 설정 업데이트 구역이 같은 모양을 쓴다. idle이면 그리지 않는다. */
export function UpdateProgress({ idPrefix, install, locked, onAction, readyDismissible = false }: { idPrefix: string; install: UpdateInstallData; locked: boolean; onAction: (name: UpdateAction) => void; readyDismissible?: boolean }) {
  if (install.phase === 'idle') return null
  const act = (name: UpdateAction) => () => { if (!locked) onAction(name) }
  const downloading = install.phase === 'downloading' || install.phase === 'cancelling'
  const tone: NoticeTone = install.phase === 'failed' ? 'error' : install.phase === 'confirm' ? 'warning' : 'info'
  const title = <>{activeTitle[install.phase] ?? '업데이트'} · {install.version}<span className="font-normal text-muted-foreground"> · {kindLabel(install.kind)}</span></>
  const action = downloading
    ? <Button id={`${idPrefix}-cancel`} size="sm" variant="outline" aria-disabled={locked || install.phase === 'cancelling' || undefined} onClick={install.phase === 'downloading' ? act('cancel') : undefined}>{install.phase === 'cancelling' ? '취소 중…' : '취소'}</Button>
    : install.phase === 'ready' || install.phase === 'confirm'
      ? <Button id={`${idPrefix}-now`} size="sm" aria-disabled={locked || undefined} onClick={act('install')}>지금 설치</Button>
      : install.phase === 'failed' && install.canRetry
        ? <Button id={`${idPrefix}-retry`} size="sm" aria-disabled={locked || undefined} onClick={act('retry')}>다시 시도</Button>
        : undefined
  return <Notice tone={tone} title={title} clamp={false} action={action} onDismiss={install.phase === 'failed' || (readyDismissible && install.phase === 'ready') ? act('dismiss') : undefined}>
    {downloading && <>
      <p className="tabular-nums">{progressText(install)}</p>
      <Progress value={install.total ? Math.floor(install.received * 100 / install.total) : 0} aria-label="업데이트 내려받기 진행률" />
    </>}
    {install.phase === 'confirm' && <p>진행 중인 작업이 있어 설치할지 묻고 있습니다.</p>}
    {install.phase === 'ready' && <p>‘지금 설치’를 누르면 앱을 닫고 설치한 뒤 다시 실행합니다.</p>}
    {install.phase === 'preparing' && <p>설치 도우미를 준비하고 있습니다. 준비되면 앱을 닫고 설치한 뒤 다시 실행합니다.</p>}
    {install.phase === 'failed' && <p>{install.failureMessage}</p>}
  </Notice>
}

/** 지난 실행에서 넘긴 설치의 결과. 다음 실행 때 한 번 보이고 닫으면 사라진다. */
function UpdateResult({ result, locked, onAction }: { result: UpdateInstallResultData; locked: boolean; onAction: (name: UpdateAction) => void }) {
  const retry = result.retry === 'full' ? '전체 설치 파일로 다시 시도' : result.retry === 'same' ? '다시 시도' : ''
  return <Notice tone={result.tone as NoticeTone} title={result.title} clamp={false}
    action={retry ? <Button id="update-result-retry" size="sm" aria-disabled={locked || undefined} onClick={() => { if (!locked) onAction('retry') }}>{retry}</Button> : undefined}
    onDismiss={() => { if (!locked) onAction('dismiss') }}>
    {(result.message || result.logPath) && <>
      {result.message && <p>{result.message}</p>}
      {result.logPath && <p className="text-xs text-muted-foreground">설치 기록: <span className="select-text wrap-anywhere">{result.logPath}</span></p>}
    </>}
  </Notice>
}

/** 셸 수준 업데이트 안내. 어느 탭에서나 셸 안내 묶음에 보인다. 릴리스 노트는 서명되지 않은 글이라 글자로만 보인다. */
export default function UpdateNotice() {
  const { bridge, data, setData, error, setError } = useShellUpdate()
  const [sending, setSending] = useState(false)
  const section = useRef<HTMLElement>(null)
  const restoreFocus = useRef(false)
  const answered = useRef(false)
  const notice = data?.notice ?? null
  const install = data?.install ?? null
  const confirming = install?.phase === 'confirm'
  useEffect(() => {
    // 알림 안의 버튼으로 고른 뒤 그 버튼이 사라지면 포커스를 현재 탭으로 돌려 body로 빠지지 않게 한다.
    if (!restoreFocus.current || section.current?.contains(document.activeElement)) return
    if (document.activeElement && document.activeElement !== document.body) return
    restoreFocus.current = false
    document.querySelector<HTMLButtonElement>('nav [aria-current="page"]')?.focus()
  }, [data])
  useEffect(() => { if (confirming) answered.current = false }, [confirming])
  async function send(task: (shell: ShellBridge) => Promise<ShellUpdateData>) {
    if (!bridge || sending) return
    restoreFocus.current = !!section.current?.contains(document.activeElement)
    setSending(true)
    setError('')
    try { setData(await task(bridge)) }
    catch (error) { restoreFocus.current = false; setError(String(error)) }
    finally { setSending(false) }
  }
  const choose = (name: UpdateChoice) => notice && void send(shell => request<ShellUpdateData>(reply => shell.updateChoice(name, notice.version, reply)))
  const act = (name: UpdateAction) => void send(shell => request<ShellUpdateData>(reply => shell.updateAction(name, reply)))
  const answer = (name: UpdateAction) => { if (!answered.current) { answered.current = true; act(name) } }
  const busy = install && install.phase !== 'idle' && !(install.phase === 'ready' && install.readyDismissed)
  if (!notice && !busy && !install?.result && !error) return null
  return <section ref={section} aria-label="업데이트 알림" className="flex flex-col gap-2">
    {install?.result && <UpdateResult result={install.result} locked={sending} onAction={act} />}
    {/* 준비됨 안내는 셸에서만 닫는다. 닫아도 받은 파일과 설정 업데이트 구역의 ‘지금 설치’는 남는다. */}
    {install && !(install.phase === 'ready' && install.readyDismissed) && <UpdateProgress idPrefix="update-progress" install={install} locked={sending} onAction={act} readyDismissible />}
    {notice && <Notice tone="info" aria-label="새 버전 알림" title={<UpdateTitle {...notice} />} action={<UpdateChoices idPrefix="update-notice" later locked={sending} onChoose={choose} />}>
      {notice.releaseNotes ?? undefined}
    </Notice>}
    <NoticeStack items={[error && { tone: 'error', message: error, onDismiss: () => setError('') }]} />
    {/* 막는 작업이 있을 때만 묻는다. 닫기(Esc)는 ‘나중에’와 같고, 받은 파일은 이번 실행 동안 남아 ‘지금 설치’로 다시 고른다. */}
    <ConfirmDialog open={confirming} onOpenChange={open => { if (!open) answer('later') }} title={`지금 ${install?.version ?? ''} 버전을 설치할까요?`}
      description={install?.confirmation ?? ''} confirmLabel="지금 설치" cancelLabel="나중에" onConfirm={() => answer('install')} onCancel={() => answer('later')} />
  </section>
}
