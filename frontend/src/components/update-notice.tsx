import { useEffect, useRef, useState } from "react"
import { connectBridge, request, type ShellBridge } from "@/bridge"
import type { ShellUpdateData, UpdateChoice, UpdateNoticeData } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { Notice, NoticeStack } from "@/components/ui/notice"

function megabytes(bytes: number | null) {
  return bytes === null ? '' : ` ${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** 새 버전 알림 제목. 버전과 받을 크기(서명된 매니페스트 값)를 한 줄에 둔다. */
export function UpdateTitle({ version, kind, downloadSize }: { version: string; kind: string; downloadSize: number | null }) {
  return <>새 버전이 있습니다 · {version}<span className="font-normal text-muted-foreground"> · {kind === 'patch' ? '패치 설치 파일' : '전체 설치 파일'}{megabytes(downloadSize)}</span></>
}

/** 셸 알림과 설정 업데이트 구역의 같은 선택지. 잠금은 aria-disabled로만 보여 키보드 포커스가 빠지지 않게 한다. */
export function UpdateChoices({ idPrefix, later, locked, onChoose }: { idPrefix: string; later: boolean; locked: boolean; onChoose: (name: UpdateChoice) => void }) {
  const choose = (name: UpdateChoice) => () => { if (!locked) onChoose(name) }
  return <>
    {/* #142 전까지 "업데이트"는 그 버전의 GitHub Release 페이지를 연다. */}
    <Button id={`${idPrefix}-install`} size="sm" title="GitHub Release 페이지에서 설치 파일을 받습니다" aria-disabled={locked || undefined} onClick={choose('update')}>업데이트</Button>
    {later && <Button id={`${idPrefix}-later`} size="sm" variant="outline" aria-disabled={locked || undefined} onClick={choose('later')}>나중에</Button>}
    <Button id={`${idPrefix}-skip`} size="sm" variant="ghost" aria-disabled={locked || undefined} onClick={choose('skip')}>이 버전 건너뛰기</Button>
  </>
}

/** 셸 수준 새 버전 알림. 어느 탭에서나 탭 아래 안내 영역에 보인다. 릴리스 노트는 서명되지 않은 글이라 글자로만 보인다. */
export default function UpdateNotice() {
  const [bridge, setBridge] = useState<ShellBridge | null>(null)
  const [notice, setNotice] = useState<UpdateNoticeData | null>(null)
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const section = useRef<HTMLElement>(null)
  const restoreFocus = useRef(false)
  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(async ({ shell }) => {
      if (disposed) return
      const changed = (json: string) => setNotice((JSON.parse(json) as ShellUpdateData).notice)
      shell.shellUpdateChanged.connect(changed)
      disconnect = () => shell.shellUpdateChanged.disconnect(changed)
      const initial = await request<ShellUpdateData>(reply => shell.updateSnapshot(reply))
      if (!disposed) { setBridge(shell); setNotice(initial.notice) }
    }).catch(error => setError(String(error)))
    return () => { disposed = true; disconnect() }
  }, [])
  useEffect(() => {
    // 알림 안의 버튼으로 고른 뒤 알림이 사라지면 포커스를 현재 탭으로 돌려 body로 빠지지 않게 한다.
    if (notice || !restoreFocus.current) return
    restoreFocus.current = false
    document.querySelector<HTMLButtonElement>('nav [aria-current="page"]')?.focus()
  }, [notice])
  async function choose(name: UpdateChoice) {
    if (!bridge || !notice || sending) return
    restoreFocus.current = !!section.current?.contains(document.activeElement)
    setSending(true)
    setError('')
    try { setNotice((await request<ShellUpdateData>(reply => bridge.updateChoice(name, notice.version, reply))).notice) }
    catch (error) { restoreFocus.current = false; setError(String(error)) }
    finally { setSending(false) }
  }
  if (!notice && !error) return null
  return <section ref={section} aria-label="새 버전 알림" className="flex flex-col gap-2 border-b px-4 py-2">
    {notice && <Notice tone="info" title={<UpdateTitle {...notice} />} action={<UpdateChoices idPrefix="update-notice" later locked={sending} onChoose={name => void choose(name)} />}>
      {notice.releaseNotes ?? undefined}
    </Notice>}
    <NoticeStack items={[error && { tone: 'error', message: error, onDismiss: () => setError('') }]} />
  </section>
}
