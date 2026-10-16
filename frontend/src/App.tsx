import { useEffect, useState } from "react"
import { pages } from "@/pages"
import { connectBridge, request, type ShellBridge } from "@/bridge"
import { tabs, type Tab, type ShellData } from "@/bridge-types"
import { Tabs } from "@/components/page-parts"
import DialogsLayer from "@/dialogs/DialogsLayer"
import ShellModals from "@/dialogs/ShellModals"
import SubtitlePreparation from "@/components/subtitle-preparation"
import { NoticeStack } from "@/components/ui/notice"

export default function App() {
  const [bridge, setBridge] = useState<ShellBridge | null>(null)
  const [tab, setTab] = useState("library")
  const [status, setStatus] = useState("")
  const [error, setError] = useState("")
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
      disconnect = () => { api.shellChanged.disconnect(changed); api.shellFocusRequested.disconnect(focus); api.shellStatusChanged.disconnect(setStatus) }
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
    </header>
    {/* 셸 안내는 탭 아래 한곳에 쌓는다. 자막 기능 준비가 먼저, 그 아래 연결 오류와 작업 알림이 온다.
        모두 펼쳐도 창 높이의 1/4까지만 쓰고 안에서 스크롤해 페이지 목록 자리를 남긴다. */}
    <div aria-label="앱 안내" className="max-h-1/4 shrink-0 overflow-y-auto">
      <SubtitlePreparation />
      {(error || status) && <div className="border-b px-4 py-2"><NoticeStack items={[
        error && { tone: "error", message: error, onDismiss: () => setError("") },
        status && { tone: "info", message: status, label: "작업 알림", onDismiss: () => setStatus("") },
      ]} /></div>}
    </div>
    {Object.entries(pages).map(([name, Page]) => Page && <div key={name} hidden={tab !== name} className="min-h-0 flex-1"><Page /></div>)}
    <DialogsLayer />
    <ShellModals />
  </div>
}
