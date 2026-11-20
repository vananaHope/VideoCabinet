import { useEffect, useState } from "react"
import { connectBridge, request } from "@/bridge"
import { appName, type SettingsBridge, type SettingsData, type ShellBridge } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { Notice, NoticeStack } from "@/components/ui/notice"
import { ConfirmDialog, PageHeader, StatusBadge } from "@/components/page-parts"
import { MinimumDuration } from "@/components/minimum-duration"
import { AutomaticDetection } from "@/components/automatic-detection"
import { KeyBindingsEditor } from "@/components/key-bindings-editor"
import { BackupSettings } from "@/components/backup-settings"
import { UpdateSettings } from "@/components/update-settings"
import { RecommendationPeriods } from "@/components/recommendation-periods"
import { SettingsCard, SettingsSection } from "@/components/settings-parts"
import type { KeyGuideGroup } from "@/lib/key-guide"
import { useLayoutChange } from "@/lib/layout-change"
import { useGenerationGuard } from "@/lib/generation"
import { focusPage } from "@/lib/page-focus"
// 앱 아이콘: scripts/app_icon.py가 벡터 원본에서 만든 커밋 산출물. 웹 번들에 들어가 실행 중 네트워크를 쓰지 않는다.
import appIcon from "@/assets/app-icon.png"
import { firstData } from "@/lib/entry"

const categories = [['general', '일반'], ['keys', '키 배치'], ['recommend', '추천'], ['translation', '번역'], ['transcription', '받아쓰기'], ['backup', '백업'], ['update', '업데이트']] as const

// 이 화면에서만 쓰는 키. pages/index.ts의 pageKeyGuides에 등록해 키 안내 '지금 화면'에 보인다.
export const keyGuide: readonly KeyGuideGroup[] = [
  { title: "키 배치", rows: [{ keys: ["Esc"], label: "새 키 입력 취소" }] },
  { title: "추천 기간", rows: [
    { keys: ["Enter"], label: "입력한 기간 저장 (저장 단추와 같음)" },
    { keys: ["Esc"], label: "입력 칸의 저장하지 않은 값 되돌리기 (되돌리기 단추와 같음)" },
  ] },
]

export default function SettingsPage() {
  const [bridge, setBridge] = useState<SettingsBridge | null>(null)
  const [shell, setShell] = useState<ShellBridge | null>(null)
  const [data, setData] = useState<SettingsData | null>(null)
  const fresh = useGenerationGuard()
  const [category, setCategory] = useState('general')
  const [error, setError] = useState('')
  const [quit, setQuit] = useState(false)
  // 분류를 바꾸면 이미 붙은 구역의 hidden만 바뀌므로 셸 안내 묶음에 배치가 바뀌었다고 알린다.
  useLayoutChange(category, data, error)
  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(async ({ settings: api, shell }) => {
      if (disposed) return
      const changed = (json: string) => { const next: SettingsData = JSON.parse(json); if (fresh(next)) setData(next) }
      const focus = (target: string) => {
        if (target === 'settings-keys') setCategory('keys')
        // 분류를 바꾼 렌더가 끝난 뒤 공용 규칙이 지금 분류 단추에 초점을 둔다.
        focusPage('settings', target)
      }
      api.settingsChanged.connect(changed)
      api.settingsError.connect(setError)
      api.settingsFocusRequested.connect(focus)
      disconnect = () => { api.settingsChanged.disconnect(changed); api.settingsError.disconnect(setError); api.settingsFocusRequested.disconnect(focus) }
      const initial = await firstData("settings", () => request<SettingsData>(reply => api.snapshot(reply)))
      if (disposed) return
      if (fresh(initial)) setData(initial)
      setBridge(api); setShell(shell)
    }).catch(error => setError(String(error)))
    return () => { disposed = true; disconnect() }
  }, [fresh])
  useEffect(() => { if (bridge) request(reply => bridge.ready(reply)).catch(error => setError(String(error))) }, [bridge])
  function action(name: 'translation' | 'quit' | 'releases') {
    setError('')
    if (bridge) request(reply => bridge.action(name, reply)).catch(error => setError(String(error)))
  }
  if (!data || !bridge || !shell) return error ? <Notice tone="error" className="m-4">{error}</Notice> : <p role="status" className="p-6">설정을 불러오는 중…</p>
  const translationProvider = data.translation.providers.find(p => p.id === data.translation.provider)!
  const translationSelection = data.translation.selections.find(s => s.provider === data.translation.provider)!
  return <main className="flex h-full min-h-0 max-w-content flex-col gap-3 p-4" aria-label="설정">
    <PageHeader title="설정" description="키 배치와 라이브러리 설정을 한곳에서 관리합니다. Alt+S 또는 Ctrl+8로 엽니다." />
    <NoticeStack items={[error && { tone: 'error', message: error, onDismiss: () => setError('') }]} />
    <div className="flex min-h-0 flex-1 gap-6">
      <nav id="settings-category" aria-label="설정 분류" className="flex w-40 shrink-0 flex-col gap-2">{categories.map(([id, label]) => <Button key={id} variant={category === id ? 'item-selected' : 'item'} aria-current={category === id ? 'true' : undefined} data-category={id} onClick={() => setCategory(id)}>{label}</Button>)}</nav>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto">
        <BackupSettings bridge={bridge} active={category === 'backup'} />
        <SettingsSection hidden={category !== 'general'} aria-label="일반 설정" title="일반">
          <SettingsCard icon={<img src={appIcon} alt="" className="size-10 shrink-0" />} title={`${appName} · ${data.version}`}
            control={<Button variant="link" title={data.releasesUrl} onClick={() => action('releases')}>GitHub Release에서 버전 보기 ↗</Button>} />
          <MinimumDuration id="settings-minimum" value={data.minimum} scanning={data.scanning} onSave={async value => { await request(reply => bridge.setMinimum(value, reply)) }} />
          <AutomaticDetection enabled={data.automaticDetection} scanning={data.scanning} onChange={async enabled => { await request(reply => bridge.setAutomaticDetection(enabled, reply)) }} />
          <SettingsCard title="완전 종료" badge={<StatusBadge variant="destructive">위험 작업</StatusBadge>} description="창을 닫으면 트레이로 숨습니다. 완전 종료하면 진행 중인 자막 처리를 멈추고 앱을 끝냅니다."
            control={<Button variant="destructive-outline" onClick={() => setQuit(true)}>완전 종료</Button>} />
        </SettingsSection>
        <div hidden={category !== 'keys'} className="min-h-0 flex-1"><div className="flex h-full min-h-0 flex-col"><KeyBindingsEditor rows={data.bindings} bridge={bridge} /></div></div>
        <div hidden={category !== 'recommend'}><RecommendationPeriods periods={data.recommendationPeriods} onSave={async (criterion, days) => { await request(reply => bridge.setRecommendationPeriod(criterion, days, reply)) }} onReset={async criterion => { await request(reply => bridge.resetRecommendationPeriod(criterion, reply)) }} /></div>
        {/* 지금 고른 번역 방식은 값이라 본문 크기로 정의 목록에 둔다. 방식·모델 고르기와 재시도는 대화상자에서 한다. */}
        <SettingsSection hidden={category !== 'translation'} aria-label="번역 설정" title="번역" description="한국어 번역 방식과 모델·추론 강도를 선택합니다. 한국어 영상의 다듬기도 같은 방식을 씁니다.">
          <SettingsCard title="번역 방식" badge={<><StatusBadge variant="info">보류 {data.heldTranslations}건</StatusBadge><StatusBadge variant="muted">실패 {data.failedTranslations}건</StatusBadge></>}
            control={<Button onClick={() => action('translation')}>선택 / 재시도</Button>}
            description="선택을 확인하면 실패·보류 번역을 저장한 묶음부터 재시도합니다. 사용량 한도 보류 시간이 남았다면 그 시각까지 기다립니다.">
            <dl className="space-y-1 text-body">
              <div className="flex gap-4"><dt className="w-52 shrink-0 text-muted-foreground">방식</dt><dd>{translationProvider.label}</dd></div>
              <div className="flex gap-4"><dt className="w-52 shrink-0 text-muted-foreground">모델</dt><dd className="min-w-0 break-all" title={translationSelection.model}>{translationSelection.model || '기본(CLI 기본값)'}</dd></div>
              <div className="flex gap-4"><dt className="w-52 shrink-0 text-muted-foreground">추론 강도</dt><dd>{translationSelection.effort || '기본(모델 기본값)'}</dd></div>
              <div className="flex gap-4"><dt className="w-52 shrink-0 text-muted-foreground">OpenCode Go 키</dt><dd>{data.translation.key_masked ? `등록됨 (${data.translation.key_masked})` : '없음'}</dd></div>
              <div className="flex gap-4"><dt className="w-52 shrink-0 text-muted-foreground">실패하면 OpenCode Go로 이어서</dt><dd>{data.translation.fallback ? '켬' : '끔'}</dd></div>
            </dl>
          </SettingsCard>
        </SettingsSection>
        <SettingsSection hidden={category !== 'update'} aria-label="업데이트 설정" title="업데이트"><UpdateSettings data={data.update} onCheck={async () => { await request(reply => bridge.checkUpdate(reply)) }} onAutomatic={async enabled => { await request(reply => bridge.setAutomaticUpdateCheck(enabled, reply)) }} onChoose={async (name, version) => { await request(reply => shell.updateChoice(name, version, reply)) }} /></SettingsSection>
        {/* 자막 대기열 열기는 다른 탭으로 옮겨 가기만 하므로 주 단추가 아니라 윤곽선 단추다. */}
        <SettingsSection hidden={category !== 'transcription'} aria-label="받아쓰기 설정" title="받아쓰기">
          <SettingsCard title="원어 자막과 자동 규칙" description="라이브러리의 ‘자막 만들기 / 원어 지정’에서 영상마다 원어를 자동 감지하거나 직접 지정합니다. 재생 중에도 대기열 순서대로 받아쓰기를 계속합니다."
            control={<Button variant="outline" onClick={() => request(reply => shell.navigate('queue', reply)).catch(error => setError(String(error)))}>자막 대기열 열기</Button>}
            note="감시 폴더·태그에 대한 자동 자막 규칙, 처리 순서, 취소와 실패 항목 재시도는 자막 대기열에서 관리합니다." />
        </SettingsSection>
      </div>
    </div>
    <ConfirmDialog open={quit} onOpenChange={setQuit} title="앱을 완전히 종료할까요?" description="진행 중인 자막 처리를 멈추고 앱을 종료합니다. 트레이에서 계속 처리하려면 취소한 뒤 창을 닫으세요." confirmLabel="완전 종료" variant="destructive" onConfirm={() => action('quit')} />
  </main>
}
