import { useEffect, useState } from "react"
import { pages } from "@/pages"
import { connectBridge, request, type ShellBridge } from "@/bridge"
import { tabs, type Tab, type ShellData } from "@/bridge-types"
import { Tabs } from "@/components/page-parts"
import { KeyGuideButton, KeyGuideDialog } from "@/components/key-guide"
import DialogsLayer from "@/dialogs/DialogsLayer"
import ShellModals from "@/dialogs/ShellModals"
import SubtitlePreparation from "@/components/subtitle-preparation"
import UpdateNotice from "@/components/update-notice"
import { NoticeStack } from "@/components/ui/notice"
import { shellStatusTone } from "@/lib/shell-status"

export default function App() {
  const [bridge, setBridge] = useState<ShellBridge | null>(null)
  const [tab, setTab] = useState("library")
  const [status, setStatus] = useState("")
  const [error, setError] = useState("")
  const [keyGuide, setKeyGuide] = useState(false)
  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(async ({ shell: api }) => {
      if (disposed) return
      const changed = (json: string) => setTab(JSON.parse(json).tab)
      api.shellChanged.connect(changed)
      api.shellStatusChanged.connect(setStatus)
      const focus = (target: string) => {
        if (target === 'shell') requestAnimationFrame(() => document.querySelector<HTMLButtonElement>('nav [aria-current="page"]')?.focus())
      }
      api.shellFocusRequested.connect(focus)
      // F1 예약 키. 대화상자·IME 조합 중에는 셸이 보내지 않는다.
      const openKeyGuide = () => setKeyGuide(true)
      api.shellKeyGuideRequested.connect(openKeyGuide)
      // 페이지 데이터와 초점/스크롤 복원이 DOM에 반영되고 한 프레임을
      // 그린 뒤에만 Qt의 이전 재생 표면을 걷는다. 시간 지연으로 추측하지 않는다.
      const prepareReturn = (token: number) => requestAnimationFrame(() => requestAnimationFrame(() => {
        request(reply => api.returnReady(token, reply)).catch(error => setError(String(error)))
      }))
      api.shellPrepareReturn.connect(prepareReturn)
      disconnect = () => { api.shellChanged.disconnect(changed); api.shellFocusRequested.disconnect(focus); api.shellStatusChanged.disconnect(setStatus); api.shellKeyGuideRequested.disconnect(openKeyGuide); api.shellPrepareReturn.disconnect(prepareReturn) }
      const state = await request<ShellData>(reply => api.shellSnapshot(reply))
      if (!disposed) { setBridge(api); setTab(state.tab); setStatus(state.status) }
    }).catch(error => setError(String(error)))
    return () => { disposed = true; disconnect() }
  }, [])
  useEffect(() => {
    if (bridge) request(reply => bridge.ready(reply)).catch(error => setError(String(error)))
  }, [bridge])
  function navigate(value: string) {
    if (bridge) request(reply => bridge.navigate(value as Tab, reply)).catch(error => setError(String(error)))
  }
  return <div className="flex h-full flex-col">
    <header className="flex shrink-0 items-center gap-4 border-b bg-background px-4 py-3">
      <span className="shrink-0 text-sm font-semibold">영상 라이브러리</span>
      <Tabs label="페이지 이동" value={tab} items={tabs.map(([value, label], index) => ({ value, label, shortcut: `Ctrl+${index + 1}` }))} onChange={navigate} variant="navigation" />
      <KeyGuideButton onClick={() => setKeyGuide(true)} />
    </header>
    {/* 셸 안내는 탭 아래 한곳에 쌓는다. 자막 기능 준비가 먼저, 그 아래 연결 오류와 작업 알림, 마지막에 새 버전 알림이 온다.
        모두 펼쳐도 창 높이의 1/4까지만 쓰고 안에서 스크롤해 페이지 목록 자리를 남긴다. */}
    <div aria-label="앱 안내" className="max-h-1/4 shrink-0 overflow-y-auto">
      <SubtitlePreparation />
      {(error || status) && <div className="border-b px-4 py-2"><NoticeStack items={[
        error && { tone: "error", message: error, onDismiss: () => setError("") },
        status && { tone: shellStatusTone(status), message: status, label: "작업 알림", onDismiss: () => setStatus("") },
      ]} /></div>}
      <UpdateNotice />
    </div>
    {/* 페이지 영역. 목록 최소 높이와 안내를 합친 높이가 창보다 크면(작은 창) 여기서 세로로 스크롤해 아래 작업 버튼에 닿는다.
        기본 창에서는 각 페이지가 높이에 맞춰 내부 목록만 스크롤하므로 바깥 스크롤이 생기지 않는다. */}
    {Object.entries(pages).map(([name, Page]) => Page && <div key={name} data-page={name} hidden={tab !== name} className="min-h-0 flex-1 overflow-y-auto"><Page /></div>)}
    <DialogsLayer />
    {bridge && <KeyGuideDialog bridge={bridge} tab={tab} open={keyGuide} onOpenChange={setKeyGuide} />}
    <ShellModals />
  </div>
}
