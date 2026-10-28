import { useEffect, useState } from "react"
import { cva } from "class-variance-authority"
import { pages } from "@/pages"
import { connectBridge, request, type ShellBridge } from "@/bridge"
import { appName, tabs, type Tab, type ShellData } from "@/bridge-types"
import { Tabs } from "@/components/page-parts"
import { KeyGuideButton, KeyGuideDialog } from "@/components/key-guide"
import DialogsLayer from "@/dialogs/DialogsLayer"
import ShellModals from "@/dialogs/ShellModals"
import SubtitlePreparation from "@/components/subtitle-preparation"
import UpdateNotice from "@/components/update-notice"
import { NoticeLayer, NoticeStack } from "@/components/ui/notice"
import { shellStatusTone } from "@/lib/shell-status"

// 탭을 바꿀 때만 새 탭 내용이 투명도로 짧게 들어온다. 첫 진입·재생 복귀·같은 탭 다시 열기에는 전환이 없다.
// 숨은 탭은 그대로 남아 있으므로 이전 탭의 선택·스크롤·초점이 유지된다.
const pageArea = cva("min-h-0 flex-1 overflow-y-auto", { variants: { entering: { true: "animate-tab-enter", false: "" } } })

export default function App() {
  const [bridge, setBridge] = useState<ShellBridge | null>(null)
  const [view, setView] = useState({ tab: "library", entering: false })
  const tab = view.tab
  const setTab = (next: string) => setView(previous => previous.tab === next ? previous : { tab: next, entering: false })
  const [status, setStatus] = useState("")
  const [error, setError] = useState("")
  const [keyGuide, setKeyGuide] = useState(false)
  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(async ({ shell: api }) => {
      if (disposed) return
      const changed = (json: string) => {
        const next = JSON.parse(json).tab
        setView(previous => previous.tab === next ? previous : { tab: next, entering: true })
      }
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
      const prepareReturn = (token: number) => {
        // 복귀 첫 프레임이 반투명하지 않게 탭 내용 전환을 건너뛴다(이미 시작했으면 바로 끝낸다).
        setView(previous => previous.entering ? { ...previous, entering: false } : previous)
        requestAnimationFrame(() => requestAnimationFrame(() => {
          request(reply => api.returnReady(token, reply)).catch(error => {
            setError(String(error))
            request(reply => api.returnFailed(token, reply)).catch(failure => setError(String(failure)))
          })
        }))
      }
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
      <span className="shrink-0 text-sm font-semibold">{appName}</span>
      <Tabs label="페이지 이동" value={tab} items={tabs.map(([value, label], index) => ({ value, label, shortcut: `Ctrl+${index + 1}` }))} onChange={navigate} variant="navigation" />
      <KeyGuideButton onClick={() => setKeyGuide(true)} />
    </header>
    {/* 페이지 영역. 목록 최소 높이보다 창이 작으면(작은 창) 여기서 세로로 스크롤해 아래 작업 버튼에 닿는다.
        기본 창에서는 각 페이지가 높이에 맞춰 내부 목록만 스크롤하므로 바깥 스크롤이 생기지 않는다. */}
    <div className="relative flex min-h-0 flex-1 flex-col">
      {Object.entries(pages).map(([name, Page]) => Page && <div key={name} data-page={name} hidden={tab !== name} className={pageArea({ entering: view.entering && tab === name })}><Page /></div>)}
      {/* 셸 안내는 페이지를 밀지 않고 페이지 영역 모서리(기본 오른쪽 아래)에 떠 있는 한 묶음으로 쌓는다. 머리글·탭 줄은 덮지 않고,
          지금 페이지의 툴바·작업 단추 줄 같은 고정 조작 요소를 가장 적게 가리는 모서리를 고른다.
          자막 기능 준비가 먼저, 그 아래 연결 오류와 작업 알림, 마지막에 새 버전 알림이 온다. 묶음은 접을 수 있고 넘치면 안에서 스크롤한다. */}
      <NoticeLayer aria-label="앱 안내" avoid={`[data-page="${tab}"]`}>
        <SubtitlePreparation />
        <NoticeStack items={[
          error && { tone: "error", message: error, onDismiss: () => setError("") },
          status && { tone: shellStatusTone(status), message: status, label: "작업 알림", onDismiss: () => setStatus("") },
        ]} />
        <UpdateNotice />
      </NoticeLayer>
    </div>
    <DialogsLayer />
    {bridge && <KeyGuideDialog bridge={bridge} tab={tab} open={keyGuide} onOpenChange={setKeyGuide} />}
    <ShellModals />
  </div>
}
