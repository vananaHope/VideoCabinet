import { useEffect, useRef, useState } from "react"
import { flushSync } from "react-dom"
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
import { focusPage, markPageShown, rememberPageFocus } from "@/lib/page-focus"
import { restorePageScroll, savePageScroll } from "@/lib/page-scroll"
import { shellShown, startTab } from "@/lib/entry"

// 탭을 바꿀 때만 새 탭 내용이 투명도로 짧게 들어온다. 첫 진입·재생 복귀·같은 탭 다시 열기에는 전환이 없다.
// 숨은 탭은 그대로 남아 있으므로 이전 탭의 선택·스크롤·초점이 유지된다. 페이지 안에서 마지막으로 초점을 받은 요소를
// 기억해 두고, 셸이 그 탭을 다시 보이며 "restore"를 보내면 그 요소에 초점을 되돌린다(#265). 초점 규칙은 lib/page-focus(#264).
const pageArea = cva("min-h-0 flex-1 overflow-y-auto", { variants: { entering: { true: "animate-tab-enter", false: "" } } })

export default function App() {
  const [bridge, setBridge] = useState<ShellBridge | null>(null)
  // 첫 렌더부터 셸이 넣어 준 시작 탭을 보인다(#267). 다시 읽은 웹이 잠깐 라이브러리를 보였다가 바뀌지 않는다.
  const [view, setView] = useState<{ tab: string; entering: boolean }>({ tab: startTab, entering: false })
  const tab = view.tab
  // 지금 보이는 탭. 탭 변경 신호에서 떠나는 페이지의 스크롤을 저장할 때 쓴다.
  const shown = useRef<string>(startTab)
  const setTab = (next: string) => { shown.current = next; setView(previous => previous.tab === next ? previous : { tab: next, entering: false }) }
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
        const leaving = shown.current
        // 탭 전환·재생 복귀(같은 탭)마다 셸이 보낸다. 이 뒤의 사용자 입력만 늦게 온 초점 요청을 건너뛰게 한다.
        markPageShown(next)
        if (leaving === next) return
        shown.current = next
        savePageScroll(leaving)
        // 뒤따르는 페이지 갱신·초점 요청이 이미 보이는 탭에 닿도록 탭 전환을 바로 그린다(#265).
        // 미뤄 그리면 페이지의 초점 처리가 아직 숨은 요소를 만나 초점을 잃을 때가 있다.
        flushSync(() => setView({ tab: next, entering: true }))
        restorePageScroll(next)
      }
      api.shellChanged.connect(changed)
      api.shellStatusChanged.connect(setStatus)
      const focus = (target: string) => focusPage(shown.current, target)
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
      if (disposed) return
      // 스냅숏 응답은 탭이 보이게 된 순간이 아니다. 이미 보이는 탭이면 그 뒤의 사용자 입력 이력을 그대로 두고,
      // 다른 탭으로 바뀔 때만 새로 보인 것으로 친다(첫 화면은 첫 렌더부터 보이는 시작 탭, 스냅숏·데이터 도착 순서와 무관).
      if (state.tab !== shown.current) markPageShown(state.tab)
      setBridge(api); setTab(state.tab); setStatus(state.status)
    }).catch(error => { shellShown(); setError(String(error)) })
    return () => { disposed = true; disconnect() }
  }, [])
  useEffect(() => {
    if (!bridge) return
    request(reply => bridge.ready(reply)).catch(error => setError(String(error)))
    shellShown()
  }, [bridge])
  function navigate(value: string) {
    if (bridge) request(reply => bridge.navigate(value as Tab, reply)).catch(error => setError(String(error)))
  }
  return <div className="flex h-full flex-col">
    <header className="flex shrink-0 items-center gap-4 border-b bg-background px-4 py-3">
      <span className="shrink-0 text-body-strong">{appName}</span>
      <Tabs label="페이지 이동" value={tab} items={tabs.map(([value, label], index) => ({ value, label, shortcut: `Ctrl+${index + 1}` }))} onChange={navigate} variant="navigation" />
      <KeyGuideButton onClick={() => setKeyGuide(true)} />
    </header>
    {/* 페이지 영역. 목록 최소 높이보다 창이 작으면(작은 창) 여기서 세로로 스크롤해 아래 작업 버튼에 닿는다.
        기본 창에서는 각 페이지가 높이에 맞춰 내부 목록만 스크롤하므로 바깥 스크롤이 생기지 않는다. */}
    <div className="relative flex min-h-0 flex-1 flex-col">
      {Object.entries(pages).map(([name, Page]) => Page && <div key={name} data-page={name} hidden={tab !== name} onFocus={event => rememberPageFocus(name, event.target)} className={pageArea({ entering: view.entering && tab === name })}><Page /></div>)}
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
