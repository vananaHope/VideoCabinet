import { useEffect, useRef, useState } from "react"
import { connectBridge, request } from "@/bridge"
import type { FolderAction, FoldersBridge, FoldersData, ScanNoticeGroup } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { InlineNotice, Notice, NoticeStack } from "@/components/ui/notice"
import { ConfirmDialog, EmptyState, PageHeader, StatusBadge, Tabs } from "@/components/page-parts"
import { MinimumDuration } from "@/components/minimum-duration"
import { ScanReport } from "@/components/scan-report"
import type { KeyGuideGroup } from "@/lib/key-guide"
import { useLayoutChange } from "@/lib/layout-change"
import { useGenerationGuard } from "@/lib/generation"
import { focusPage } from "@/lib/page-focus"

// 이 화면에서만 쓰는 키. pages/index.ts의 pageKeyGuides에 등록해 키 안내 '지금 화면'에 보인다.
export const keyGuide: readonly KeyGuideGroup[] = []

export default function FoldersPage() {
  const [bridge, setBridge] = useState<FoldersBridge | null>(null)
  const [data, setData] = useState<FoldersData | null>(null)
  const fresh = useGenerationGuard()
  const [error, setError] = useState("")
  const [section, setSection] = useState("folders")
  const [remove, setRemove] = useState<string | null>(null)
  useLayoutChange(section, data, error)
  const reportRevision = useRef(0)
  const dismissSequence = useRef(0)
  useEffect(() => { reportRevision.current = data?.report.revision ?? 0 }, [data])
  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(async ({ folders: api }) => {
      if (disposed) return
      const changed = (json: string) => { const next: FoldersData = JSON.parse(json); if (fresh(next)) setData(next) }
      const focus = (target: string) => {
        const next = target.replace('folders-', '')
        if (['folders', 'excluded', 'dismissed'].includes(next)) setSection(next)
        // 구역을 바꾼 렌더가 끝난 뒤 공용 규칙이 초점을 둔다.
        focusPage('folders', target)
      }
      api.foldersChanged.connect(changed)
      api.foldersError.connect(setError)
      api.foldersFocusRequested.connect(focus)
      disconnect = () => { api.foldersChanged.disconnect(changed); api.foldersError.disconnect(setError); api.foldersFocusRequested.disconnect(focus) }
      const initial = await request<FoldersData>(reply => api.snapshot(reply))
      if (disposed) return
      if (fresh(initial)) setData(initial)
      setBridge(api)
    }).catch(error => setError(String(error)))
    return () => { disposed = true; disconnect() }
  }, [fresh])
  useEffect(() => { if (bridge) request(reply => bridge.ready(reply)).catch(error => setError(String(error))) }, [bridge])
  function dismissReport(revision: number, group: ScanNoticeGroup, index: number) {
    if (!bridge) return
    const sequence = ++dismissSequence.current
    // 초점은 가장 최근 닫기의 응답에서만, 그사이 새 결과가 오지 않았고(revision) 사용자가 초점을 검사 안내 밖으로
    // 옮기지 않았을 때만 옮긴다. 닫은 단추가 사라지면 초점은 body로 빠지므로 body는 아직 옮기지 않은 것으로 본다.
    const current = () => {
      const section = document.getElementById('folders-report')
      const active = document.activeElement
      return sequence === dismissSequence.current && reportRevision.current === revision
        && (!active || active === document.body || !!section?.contains(active))
    }
    // 닫은 상태는 foldersChanged로만 받는다. 응답은 늦게 올 수 있어 그사이 온 새 검사 결과를 덮지 않도록 데이터를 싣지 않는다.
    request(reply => bridge.dismissReport(revision, group, reply)).then(() => {
      if (!current()) return
      // 닫은 단추가 사라지므로 같은 자리에 온 다음 검사 안내의 닫기 단추로, 남은 안내가 없으면 검사 안내 구역으로 초점을 옮긴다.
      requestAnimationFrame(() => {
        if (!current()) return
        const section = document.getElementById('folders-report')
        const remaining = [...section?.querySelectorAll<HTMLElement>('button[aria-label="안내 닫기"]') ?? []]
        ;(remaining[Math.min(index, remaining.length - 1)] ?? section)?.focus()
      })
    }).catch(error => setError(String(error)))
  }
  function act(name: FolderAction, target = "") {
    setError("")
    if (bridge) request(reply => bridge.action(name, target, reply)).catch(error => setError(String(error)))
  }
  if (!data || !bridge) return error ? <Notice tone="error" className="m-4">{error}</Notice> : <p role="status" className="p-6">폴더 정보를 불러오는 중…</p>
  const videos = section === 'excluded' ? data.excluded : data.dismissed
  // 목록만 스크롤한다. 바깥 스크롤은 목록이 최소 높이까지 줄어든 아주 작은 창에서만 생긴다.
  return <main className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto p-4" aria-label="폴더 관리">
    <PageHeader title="폴더 관리" description="감시 폴더의 하위 폴더까지 검사합니다. 실제 파일과 영상 기록은 유지합니다." actions={<Button variant="outline" onClick={() => act('manageTags')}>모든 태그 관리</Button>} />
    <NoticeStack items={[
      error && { tone: "error", message: error, onDismiss: () => setError("") },
      data.unwatched.length > 0 && { key: "unwatched", tone: "warning", title: `감시하지 못하는 폴더 ${data.unwatched.length}개`, message: data.watchStartFailed ? "자동 감지를 시작하지 못했습니다. 설정에서 자동 감지를 껐다 켜면 다시 시도합니다." : "연결되면 자동으로 다시 감시하고 바뀐 파일을 검사합니다." },
      !data.automaticDetection && { tone: "info", message: "자동 감지가 꺼져 있습니다. 파일을 옮긴 뒤에는 다시 검사를 누르세요." },
    ]} />
    <div className="flex flex-wrap gap-2">
      <Button id="folders-add" disabled={data.scanning} onClick={() => act('addFolder')}>감시 폴더 추가</Button>
      <Button variant="outline" disabled={data.scanning} onClick={() => act('scan')}>다시 검사</Button>
      <Button variant="outline" disabled={data.scanning} onClick={() => act('addFile')}>파일 직접 추가</Button>
      {data.scanning && <StatusBadge variant="info">검사 중 · 폴더 및 제외 변경 잠금</StatusBadge>}
    </div>
    <Tabs label="폴더 관리 구역" value={section} onChange={setSection} items={[{ value: 'folders', label: `감시 폴더 ${data.folders.length}` }, { value: 'excluded', label: `제외 목록 ${data.excluded.length}` }, { value: 'dismissed', label: `관심 없음 되돌리기 ${data.dismissed.length}` }]} />
    <section id="folders-section" tabIndex={-1} className="min-h-32 flex-1 overflow-y-auto rounded-xl border bg-card" aria-label={section === 'folders' ? '감시 폴더 목록' : '되돌리기 목록'}>
      {section === 'folders' ? (data.folders.length ? <ul className="divide-y">{data.folders.map(path => <li key={path} className="flex items-center gap-3 px-3 py-1.5"><p className="min-w-0 flex-1 break-all text-body" title={path}>{path}</p>{data.unwatched.includes(path) && <InlineNotice tone="warning" text="감시 안 됨" className="shrink-0" />}<Button variant="outline" size="sm" disabled={data.scanning} aria-label={`${path} 해제`} onClick={() => setRemove(path)}>해제</Button></li>)}</ul> : <div className="p-3"><EmptyState title="감시 폴더가 없습니다" description="감시 폴더 추가로 영상이 있는 폴더를 고르면 자동으로 검사합니다." /></div>)
      : <><p className="border-b px-3 py-2 text-body text-muted-foreground">{section === 'excluded' ? '되돌리면 라이브러리에 다시 보입니다. 파일과 기록은 그대로 남아 있습니다.' : '되돌린 영상은 다시 추천에 나올 수 있습니다. 라이브러리 표시는 그대로입니다.'}</p>{videos.length ? <ul className="divide-y">{videos.map(video => <li key={video.id} className="flex items-center gap-3 px-3 py-1.5"><div className="min-w-0 flex-1"><p className="break-all text-body-strong">{video.title}</p>{(video.missing || (section !== 'excluded' && video.excluded)) && <p className="text-label text-muted-foreground">{section !== 'excluded' && video.excluded ? '제외' : '파일 없음'}</p>}</div><Button variant="outline" size="sm" disabled={section === 'excluded' && data.scanning} onClick={() => act(section === 'excluded' ? 'restoreExcluded' : 'restoreDismissed', String(video.id))}>되돌리기</Button></li>)}</ul> : <div className="p-3"><EmptyState title={section === 'excluded' ? '제외한 영상이 없습니다' : '관심 없음으로 뺀 영상이 없습니다'} description="되돌릴 영상이 있으면 여기에 표시합니다." /></div>}</>}
    </section>
    <MinimumDuration id="folders-minimum" value={data.minimum} scanning={data.scanning} onSave={async value => { await request(reply => bridge.setMinimum(value, reply)) }} />
    {/* 검사 안내는 폴더 목록이 최소 높이를 지키고 남은 자리까지만 차지하고, 넘치면 안내 묶음 안에서 스크롤한다. */}
    <section id="folders-report" tabIndex={-1} className="flex min-h-0 flex-col gap-2 outline-none" aria-label="검사 안내">{data.scanning && <div role="progressbar" aria-label="영상 검사 중" className="h-1 shrink-0 animate-pulse rounded-full bg-primary" />}<ScanReport report={data.report} onDismiss={(group, index) => dismissReport(data.report.revision, group, index)} /></section>
    <ConfirmDialog open={remove !== null} onOpenChange={open => { if (!open) setRemove(null) }} title="감시 폴더 해제" description="이 폴더 아래의 모든 위치를 해제합니다. 다른 위치가 없는 영상은 파일 없음으로 남습니다. 실제 파일과 영상 기록은 유지하며, 겹치는 감시 폴더의 위치는 다음 검사에서 복귀합니다." confirmLabel="해제" onConfirm={() => { if (remove) act('removeFolder', remove); setRemove(null) }} />
  </main>
}
