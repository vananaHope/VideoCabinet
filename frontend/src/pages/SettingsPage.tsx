import { useEffect, useState } from "react"
import { connectBridge, request } from "@/bridge"
import type { SettingsBridge, SettingsData, ShellBridge } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { ConfirmDialog, PageHeader, StatusBadge } from "@/components/page-parts"
import { MinimumDuration } from "@/components/minimum-duration"
import { KeyBindingsEditor } from "@/components/key-bindings-editor"

const categories = [['general', '일반'], ['keys', '키 배치'], ['translation', '번역 CLI'], ['transcription', '받아쓰기']] as const

export default function SettingsPage() {
  const [bridge, setBridge] = useState<SettingsBridge | null>(null)
  const [shell, setShell] = useState<ShellBridge | null>(null)
  const [data, setData] = useState<SettingsData | null>(null)
  const [category, setCategory] = useState('general')
  const [error, setError] = useState('')
  const [quit, setQuit] = useState(false)
  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(async ({ settings: api, shell }) => {
      if (disposed) return
      const changed = (json: string) => setData(JSON.parse(json))
      const focus = () => requestAnimationFrame(() => document.querySelector<HTMLButtonElement>('#settings-category [aria-current="true"]')?.focus())
      api.settingsChanged.connect(changed)
      api.settingsError.connect(setError)
      api.settingsFocusRequested.connect(focus)
      disconnect = () => { api.settingsChanged.disconnect(changed); api.settingsError.disconnect(setError); api.settingsFocusRequested.disconnect(focus) }
      const initial = await request<SettingsData>(reply => api.snapshot(reply))
      if (!disposed) { setData(initial); setBridge(api); setShell(shell) }
    }).catch(error => setError(String(error)))
    return () => { disposed = true; disconnect() }
  }, [])
  useEffect(() => { if (bridge) request(reply => bridge.ready(reply)).catch(error => setError(String(error))) }, [bridge])
  function action(name: 'translation' | 'quit') {
    setError('')
    if (bridge) request(reply => bridge.action(name, reply)).catch(error => setError(String(error)))
  }
  if (!data || !bridge || !shell) return <p role="status" className="p-6">{error || '설정을 불러오는 중…'}</p>
  return <main className="flex h-full min-h-0 flex-col gap-4 p-6" aria-label="설정">
    <PageHeader title="설정" description="키 배치와 라이브러리 설정을 한곳에서 관리합니다. Alt+S 또는 Ctrl+7로 엽니다." />
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <div className="flex min-h-0 flex-1 gap-6">
      <nav id="settings-category" aria-label="설정 분류" className="flex w-40 shrink-0 flex-col gap-2">{categories.map(([id, label]) => <Button key={id} variant={category === id ? 'secondary' : 'ghost'} aria-current={category === id ? 'true' : undefined} data-category={id} onClick={() => setCategory(id)}>{label}</Button>)}</nav>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto">
        <section hidden={category !== 'general'} className="space-y-6" aria-label="일반 설정">
          <h2 className="text-lg font-semibold">일반</h2>
          <MinimumDuration id="settings-minimum" value={data.minimum} scanning={data.scanning} onSave={async value => { await request(reply => bridge.setMinimum(value, reply)) }} />
          <section className="space-y-3 rounded-xl border bg-card p-4"><div className="flex items-center gap-3"><h3 className="font-semibold">완전 종료</h3><StatusBadge variant="destructive">위험 작업</StatusBadge></div><p className="text-sm text-muted-foreground">창을 닫으면 트레이로 숨습니다. 완전 종료하면 진행 중인 자막 처리를 멈추고 앱을 끝냅니다.</p><Button variant="destructive" onClick={() => setQuit(true)}>완전 종료</Button></section>
        </section>
        <div hidden={category !== 'keys'} className="min-h-0 flex-1"><div className="flex h-full min-h-0 flex-col"><KeyBindingsEditor rows={data.bindings} bridge={bridge} /></div></div>
        <section hidden={category !== 'translation'} className="space-y-4" aria-label="번역 CLI 설정"><h2 className="text-lg font-semibold">번역 CLI</h2><section className="space-y-4 rounded-xl border bg-card p-6"><p className="text-sm text-muted-foreground">한국어 번역에 쓸 구독 CLI를 선택합니다. 설치와 로그인이 필요합니다.</p><p className="text-2xl font-semibold">{data.translationCli}</p><div className="flex gap-2"><StatusBadge variant="info">보류 {data.heldTranslations}건</StatusBadge><StatusBadge variant="muted">실패 {data.failedTranslations}건</StatusBadge></div><p className="text-sm text-muted-foreground">선택을 확인하면 실패·보류 번역을 저장한 묶음부터 재시도합니다. 사용량 한도 보류 시간이 남았다면 그 시각까지 기다립니다.</p><Button onClick={() => action('translation')}>선택 / 재시도</Button></section></section>
        <section hidden={category !== 'transcription'} className="space-y-4" aria-label="받아쓰기 설정"><h2 className="text-lg font-semibold">받아쓰기</h2><section className="space-y-4 rounded-xl border bg-card p-6"><h3 className="font-semibold">원어 자막과 자동 규칙</h3><p className="text-sm text-muted-foreground">라이브러리의 ‘자막 만들기 / 원어 지정’에서 영상마다 원어를 자동 감지하거나 직접 지정합니다. 재생 중에도 대기열 순서대로 받아쓰기를 계속합니다.</p><p className="text-sm text-muted-foreground">감시 폴더·태그에 대한 자동 자막 규칙, 처리 순서, 취소와 실패 항목 재시도는 자막 대기열에서 관리합니다.</p><Button onClick={() => request(reply => shell.navigate('queue', reply)).catch(error => setError(String(error)))}>자막 대기열 열기</Button></section></section>
      </div>
    </div>
    <ConfirmDialog open={quit} onOpenChange={setQuit} title="앱을 완전히 종료할까요?" description="진행 중인 자막 처리를 멈추고 앱을 종료합니다. 트레이에서 계속 처리하려면 취소한 뒤 창을 닫으세요." confirmLabel="완전 종료" variant="destructive" onConfirm={() => action('quit')} />
  </main>
}
