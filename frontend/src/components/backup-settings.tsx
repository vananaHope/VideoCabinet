import { useEffect, useRef, useState } from "react"
import { request } from "@/bridge"
import type { BackupAction, BackupData, SettingsBridge } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { InlineNotice, Notice, NoticeStack } from "@/components/ui/notice"
import { ConfirmDialog, StatusBadge } from "@/components/page-parts"

function date(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '시각 정보 없음' : parsed.toLocaleString('ko-KR')
}

function size(bytes: number) {
  return bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const operations: Partial<Record<BackupAction, string>> = {
  create: '백업을 만드는 중…', choose: '백업 파일을 검사하는 중…', preview: '백업 파일을 검사하는 중…',
  schedule: '백업 복원을 예약하는 중…', cancel: '예약을 취소하는 중…', refresh: '자동 백업 목록을 읽는 중…',
}

export function BackupSettings({ bridge, active }: { bridge: SettingsBridge; active: boolean }) {
  const [data, setData] = useState<BackupData | null>(null)
  const [thumbnails, setThumbnails] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [error, setError] = useState('')
  // 작업 결과·실패 안내를 닫으면 다음 작업을 시작할 때까지 숨긴다.
  const [dismissed, setDismissed] = useState<string[]>([])
  const [sending, setSending] = useState(false)
  const section = useRef<HTMLElement>(null)
  const lastOperation = useRef('')
  const returnFocus = useRef<HTMLElement | null>(null)
  const confirmTrigger = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    let disposed = false
    const changed = (json: string) => { if (!disposed) setData(JSON.parse(json)) }
    bridge.backupChanged.connect(changed)
    request<BackupData>(reply => bridge.backupSnapshot(reply)).then(result => { if (!disposed) setData(result) }).catch(error => { if (!disposed) setError(String(error)) })
    return () => { disposed = true; bridge.backupChanged.disconnect(changed) }
  }, [bridge])
  useEffect(() => {
    if (active) request(reply => bridge.backupAction('refresh', '', false, reply)).catch(error => setError(String(error)))
  }, [bridge, active])
  useEffect(() => {
    if (data?.busy) { lastOperation.current = data.operation; return }
    const operation = lastOperation.current
    lastOperation.current = ''
    if (!active || !operation || operation === 'refresh') return
    const selector = data?.preview && ['choose', 'preview'].includes(operation) ? '[data-backup-preview]' : data?.pending && operation === 'schedule' ? '[data-backup-pending]' : ['cancel', 'discard'].includes(operation) ? '[data-backup-create]' : null
    const target = !data?.failure && selector ? section.current?.querySelector<HTMLElement>(selector) : returnFocus.current
    requestAnimationFrame(() => { if (target?.isConnected) { target.focus(); target.scrollIntoView({ block: 'nearest' }) } })
  }, [data, active])
  async function action(name: BackupAction, target = '') {
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    setError('')
    setDismissed([])
    setSending(true)
    try { await request(reply => bridge.backupAction(name, target, thumbnails, reply)) }
    catch (error) { setError(String(error)) }
    finally { setSending(false) }
  }
  if (!data) return error ? <Notice hidden={!active} tone="error">{error}</Notice> : <p hidden={!active} role="status">백업 정보를 불러오는 중…</p>
  const busy = data.busy || sending
  return <section ref={section} hidden={!active} aria-label="백업 설정" className="space-y-4 pb-4">
    <h2 className="text-lg font-semibold">백업</h2>
    <p className="text-sm text-muted-foreground">라이브러리 기록과 설정을 보관합니다. 영상 파일·받아쓰기 모델·구독 키는 포함하지 않습니다.</p>
    {/* 진행 중·실패·완료 안내를 한곳에 쌓는다. 실패와 완료는 닫을 수 있고, 진행 중 안내는 작업이 끝나면 사라진다. */}
    <NoticeStack items={[
      data.busy && { tone: 'info', message: operations[data.operation as BackupAction] || '처리 중…' },
      error && { tone: 'error', message: error, onDismiss: () => setError('') },
      !error && data.failure && !dismissed.includes(data.failure) && { tone: 'error', message: data.failure, onDismiss: () => setDismissed(list => [...list, data.failure]) },
      data.message && !dismissed.includes(data.message) && { tone: 'success', message: data.message, onDismiss: () => setDismissed(list => [...list, data.message]) },
    ]} />
    {data.pending && <section className="space-y-2 rounded-xl border bg-card p-4" aria-label="백업 복원 예약">
      <div className="flex items-center gap-2"><h3 tabIndex={-1} data-backup-pending className="font-semibold">백업 복원 예약됨</h3><StatusBadge variant="info">다시 시작하면 적용</StatusBadge></div>
      <p className="text-sm text-muted-foreground">현재 기록은 다음 시작 때 선택한 백업으로 바뀝니다. 적용 전 상태는 자동 백업으로 남깁니다.</p>
      {data.pendingDeferred && <Notice tone="warning" role="note">지난 시작 때 적용하지 못한 예약이 남아 있습니다. 원인이 해결될 때까지 시작할 때마다 다시 시도합니다. 아래 실패 이유를 확인하거나 예약을 취소하세요.</Notice>}
      <p className="break-all text-xs text-muted-foreground">예약 파일: {data.pendingPath}</p>
      <div className="flex gap-2"><Button disabled={busy} onClick={() => void action('restart')}>앱 다시 시작</Button><Button variant="outline" disabled={busy} onClick={() => void action('cancel')}>예약 취소</Button></div>
    </section>}
    {data.startup && <section aria-label="마지막 시작의 백업 복원 결과" className="space-y-2 rounded-xl border bg-card p-4">
      <h3 className="font-semibold">마지막 시작의 백업 복원: {({ applied: '적용됨', rejected: '거부됨', deferred: '미뤄짐', scheduled: '예약됨' } as Record<string, string>)[data.startup.status] || data.startup.status}</h3>
      {data.startup.error && <Notice tone="error" role="note">{data.startup.error}</Notice>}
      <p className="text-sm text-muted-foreground">{data.startup.status === 'deferred' ? '당시 복원을 적용하지 못했습니다. 현재 예약 여부는 위 예약 안내를 확인하세요.' : data.startup.guidance}</p>
      {data.startup.safety_backup && <p className="break-all text-xs text-muted-foreground">적용 전 보존 사본: {data.startup.safety_backup}</p>}
      {data.startup.rejected_path && <p className="break-all text-xs text-muted-foreground">거부된 파일: {data.startup.rejected_path}</p>}
    </section>}
    <div className="grid grid-cols-2 gap-4">
      <section className="space-y-3 rounded-xl border bg-card p-4"><h3 className="font-semibold">백업 만들기</h3><p className="text-sm text-muted-foreground">저장할 위치를 선택해 .zip 파일 하나로 보관합니다.</p>
        <Button variant={thumbnails ? 'secondary' : 'outline'} aria-pressed={thumbnails} disabled={busy} onClick={() => setThumbnails(!thumbnails)}>썸네일 포함: {thumbnails ? '켜짐' : '꺼짐'}</Button>
        <p className="text-xs text-muted-foreground">썸네일은 다시 만들 수 있으며 포함하면 파일이 커집니다.</p>
        <Button data-backup-create disabled={busy} onClick={() => void action('create')}>백업 만들기</Button>
      </section>
      <section className="space-y-3 rounded-xl border bg-card p-4"><h3 className="font-semibold">백업 복원</h3><p className="text-sm text-muted-foreground">백업을 검사하고 내용을 확인한 뒤 다음 시작에 적용하도록 예약합니다.</p><p className="text-xs text-muted-foreground">현재 DB 버전: {data.dbVersion}. 더 최신 DB 버전의 백업은 앱 업데이트가 필요합니다.</p><Button variant="outline" disabled={busy} onClick={() => void action('choose')}>백업 파일 선택</Button></section>
    </div>
    {data.preview && <section aria-label="백업 미리보기" className="space-y-3 rounded-xl border bg-card p-4">
      <h3 tabIndex={-1} data-backup-preview className="font-semibold">백업 미리보기</h3><p className="break-all text-xs text-muted-foreground">{data.previewPath}</p>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm"><div><dt className="text-muted-foreground">만든 시각</dt><dd>{date(data.preview.created_at)}</dd></div><div><dt className="text-muted-foreground">영상 수</dt><dd>{data.preview.video_count.toLocaleString()}개</dd></div><div><dt className="text-muted-foreground">앱 / DB 버전</dt><dd>{data.preview.app_version} / {data.preview.db_version}</dd></div><div><dt className="text-muted-foreground">썸네일</dt><dd>{data.preview.includes_thumbnails ? '포함' : '제외'}</dd></div></dl>
      <Notice tone="info">{data.preview.version_message}</Notice>
      <div className="flex gap-2"><Button ref={confirmTrigger} variant="destructive" disabled={busy} onClick={() => setConfirm(true)}>이 백업으로 복원 예약</Button><Button variant="outline" disabled={busy} onClick={() => void action('discard')}>선택 취소</Button></div>
    </section>}
    <section className="space-y-3 rounded-xl border bg-card p-4" aria-label="자동 백업">
      <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">자동 백업 <span className="text-sm font-normal text-muted-foreground">최근 {data.keep}개 보관</span></h3><div className="flex gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void action('refresh')}>새로고침</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => void action('openFolder')}>폴더 열기</Button></div></div>
      <p className="break-all text-xs text-muted-foreground">{data.folder}</p>
      {data.automatic.length === 0 ? <p className="py-2 text-sm text-muted-foreground">자동 백업이 아직 없습니다. 백업 복원이나 DB 형식 변경 전에 자동으로 만듭니다.</p> : <ul className="divide-y">{data.automatic.map(row => <li key={row.path} className="flex items-center justify-between gap-3 py-3"><div className="min-w-0 space-y-1"><p className="text-sm">{date(row.created_at)} · {size(row.size)}</p><p className="break-words text-xs text-muted-foreground">{row.reason}</p>{row.error && <p className="text-xs"><InlineNotice tone="error" text={row.error} /></p>}</div><Button size="sm" variant="outline" className="shrink-0" disabled={busy} onClick={() => void action('preview', row.path)}>복원 미리보기</Button></li>)}</ul>}
    </section>
    <p className="text-sm text-muted-foreground">다른 PC·드라이브로 옮겼나요? {data.guidance}</p>
    <ConfirmDialog open={confirm} onOpenChange={open => { setConfirm(open); if (!open) requestAnimationFrame(() => confirmTrigger.current?.focus()) }} title="이 백업으로 복원을 예약할까요?" description={`${data.preview ? `${date(data.preview.created_at)} · 영상 ${data.preview.video_count}개. ` : ''}다음 시작 때 현재 라이브러리 기록과 설정을 선택한 백업으로 바꿉니다. 진행 중인 자막 처리는 재시작 시 안전하게 멈추고, 적용 전 데이터를 자동 백업으로 남깁니다.${data.pending ? ' 기존 예약은 이 백업으로 바뀝니다.' : ''} 다시 시작하기 전까지 예약을 취소할 수 있습니다.`} confirmLabel="백업 복원 예약" variant="destructive" onConfirm={() => void action('schedule')} />
  </section>
}
