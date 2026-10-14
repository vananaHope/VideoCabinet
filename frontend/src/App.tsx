import { useEffect, useState } from "react"
import LibraryPage from "@/LibraryPage"
import { connectBridge, request, type Bridge } from "@/bridge"
import { tabs, type Tab, type ShellData } from "@/bridge-types"
import { EmptyState, PageHeader, Tabs } from "@/components/page-parts"

export default function App() {
  const [bridge, setBridge] = useState<Bridge | null>(null)
  const [tab, setTab] = useState("library")
  const [status, setStatus] = useState("")
  const [error, setError] = useState("")
  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(async api => {
      if (disposed) return
      const changed = (json: string) => setTab(JSON.parse(json).tab)
      api.shellChanged.connect(changed)
      api.shellStatusChanged.connect(setStatus)
      const focus = (target: string) => {
        if (target === 'shell') requestAnimationFrame(() => document.querySelector<HTMLButtonElement>('nav [aria-current="page"]')?.focus())
      }
      api.libraryFocusRequested.connect(focus)
      disconnect = () => { api.shellChanged.disconnect(changed); api.libraryFocusRequested.disconnect(focus); api.shellStatusChanged.disconnect(setStatus) }
      const state = await request<ShellData>(reply => api.shellSnapshot(reply))
      if (!disposed) { setBridge(api); setTab(state.tab); setStatus(state.status) }
    }).catch(error => setError(String(error)))
    return () => { disposed = true; disconnect() }
  }, [])
  function navigate(value: string) {
    if (bridge) request(reply => bridge.navigate(value as Tab, reply)).catch(error => setError(String(error)))
  }
  return <div className="flex h-full flex-col">
    <header className="flex shrink-0 items-center gap-4 border-b bg-background px-4 py-3">
      <span className="shrink-0 text-sm font-semibold">영상 라이브러리</span>
      <Tabs label="페이지 이동" value={tab} items={tabs.map(([value, label], index) => ({ value, label, shortcut: `Ctrl+${index + 1}` }))} onChange={navigate} variant="navigation" />
    </header>
    {status && <p role="status" aria-label="작업 알림" className="shrink-0 border-b px-4 py-2 text-sm text-muted-foreground">{status}</p>}
    {error && <p role="alert" className="p-3 text-destructive">{error}</p>}
    <div hidden={tab !== "library"} className="min-h-0 flex-1"><LibraryPage /></div>
    {tab === "statistics" && <main aria-label="통계" className="flex min-h-0 flex-1 flex-col gap-6 p-6">
      <PageHeader title="통계" description="시청 기록과 라이브러리 현황을 살펴봅니다." />
      <EmptyState title="준비 중" description="통계 화면을 준비하고 있어요." variant="page" />
    </main>}
  </div>
}
