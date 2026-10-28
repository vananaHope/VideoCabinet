import { useEffect, useRef, useState } from "react"
import { connectBridge, request } from "@/bridge"
import type { StatisticsBridge, StatisticsDashboard, StatisticsData } from "@/bridge-types"
import { EmptyState, PageHeader, Tabs } from "@/components/page-parts"
import { Button } from "@/components/ui/button"
import { Notice } from "@/components/ui/notice"
import { PendingStatus } from "@/components/ui/pending-status"
import { Placeholder } from "@/components/ui/skeleton"
import { DailyChart, duration, type Metric } from "@/components/statistics/DailyChart"
import { ActivityChart } from "@/components/statistics/ActivityChart"
import { Inventory } from "@/components/statistics/Inventory"
import { StatisticsCard } from "@/components/statistics/StatisticsCard"
import { formatDate } from "@/lib/dates"
import type { KeyGuideGroup } from "@/lib/key-guide"
import { useLayoutChange } from "@/lib/layout-change"

const periods = [7, 30, 90, 365].map(days => ({ value: String(days), label: `${days}일` }))
const metrics = [{ value: "watched_seconds", label: "시청 시간" }, { value: "viewing_count", label: "시청 횟수" }]
const weekdays = ["일", "월", "화", "수", "목", "금", "토"]
const hours = Array.from({ length: 24 }, (_, hour) => `${hour}시`)
const change = (value: number | null) => value === null ? "이전 기록 없음" : `이전 같은 기간 대비 ${value > 0 ? "+" : ""}${value.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}%`

/**
 * 시청 활동 구역. result가 없으면(첫 계산 중) 같은 카드 줄·차트 틀에 자리 표시를 그려 첫 화면 높이를 잡는다.
 * 첫 화면 아래의 가장 많이 본 영상 목록은 결과가 온 뒤에 그린다.
 */
function Activity({ result, metric, onMetric, onPlay }: { result?: StatisticsDashboard; metric: Metric; onMetric: (metric: Metric) => void; onPlay: (id: number) => void }) {
  const data = result?.period
  return <>
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <StatisticsCard label="시청 시간" value={data && duration(data.watched_seconds)} description={data && change(data.watched_seconds_change_percent)} />
      <StatisticsCard label="시청 횟수" value={data && `${data.viewing_count.toLocaleString()}회`} description={data && change(data.viewing_count_change_percent)} />
      <StatisticsCard label="시청한 영상" value={data && `${data.watched_video_count.toLocaleString()}개`} description="중복 없이 센 영상" />
      <StatisticsCard label="시청한 날" value={data && `${data.watched_day_count}일`} description={data && `선택한 ${data.days}일 중`} />
      <StatisticsCard label="최장 연속 시청" value={data && `${data.longest_streak_days}일`} description="기간 안에서 이어 본 날" />
      <StatisticsCard label="새로 추가한 영상" value={data && `${data.added_video_count.toLocaleString()}개`} description="제외 영상은 빼고 집계" />
    </div>
    <section className="space-y-4 rounded-xl border bg-card p-5"><PageHeader variant="section" title="일별 시청" actions={<Tabs label="통계 지표" value={metric} items={metrics} onChange={value => onMetric(value as Metric)} />} />
      <DailyChart daily={data?.daily} metric={metric} />
      {data?.viewing_count === 0 && <p className="text-sm text-muted-foreground">이 기간에는 시청 기록이 없습니다.</p>}
    </section>
    <div className="grid gap-5 lg:grid-cols-2"><ActivityChart title="요일별 시청 시간" values={result?.weekday_seconds} labels={weekdays} /><ActivityChart title="시간대별 시청 시간" values={result?.hourly_seconds} labels={hours} tickStep={3} /></div>
    {data && <section className="min-w-0 space-y-3 rounded-xl border bg-card p-5"><PageHeader variant="section" title="가장 많이 본 영상" description="이 기간의 시청 시간순 · 최대 5개" />
      {data.top_videos.length === 0 ? <EmptyState title="아직 시청한 영상이 없어요" description="영상을 시청하면 여기에 표시됩니다." /> : <ol className="space-y-2">{data.top_videos.map((video, index) => <li key={video.video_id}><button type="button" data-statistics-video={video.video_id} onClick={() => onPlay(video.video_id)} disabled={video.excluded || video.missing} className="flex w-full min-w-0 items-center gap-3 rounded-lg p-3 text-left hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-60" title={video.title}><span className="text-sm text-muted-foreground">{index + 1}</span><span className="min-w-0 flex-1"><span className="block truncate font-medium">{video.title}</span><span className="block text-xs text-muted-foreground">{duration(video.watched_seconds)} · {video.viewing_count.toLocaleString()}회{video.excluded ? " · 제외한 영상" : video.missing ? " · 파일 없음" : " · 재생"}</span></span></button></li>)}</ol>}
    </section>}
  </>
}

// 이 화면에서만 쓰는 키. pages/index.ts의 pageKeyGuides에 등록해 키 안내 '지금 화면'에 보인다.
export const keyGuide: readonly KeyGuideGroup[] = []

export default function StatisticsPage() {
  const [state, setState] = useState<StatisticsData>({ days: 30, loading: false, message: "", result: null })
  const [section, setSection] = useState("activity")
  const [metric, setMetric] = useState<Metric>("watched_seconds")
  const [error, setError] = useState("")
  useLayoutChange(section, state, error)
  const bridge = useRef<StatisticsBridge | null>(null)
  const root = useRef<HTMLElement>(null)
  useEffect(() => {
    let disposed = false
    let cleanup = () => {}
    connectBridge().then(async ({ statistics }) => {
      if (disposed) return
      bridge.current = statistics
      const update = (json: string) => { if (!disposed) setState(JSON.parse(json)) }
      const focus = () => root.current?.querySelector<HTMLButtonElement>(`nav[aria-label="통계 기간"] button[aria-current="page"]`)?.focus()
      statistics.statisticsChanged.connect(update)
      statistics.statisticsFocusRequested.connect(focus)
      cleanup = () => { statistics.statisticsChanged.disconnect(update); statistics.statisticsFocusRequested.disconnect(focus) }
      const snapshot = await request<StatisticsData>(reply => statistics.snapshot(reply))
      if (disposed) return
      setState(snapshot)
      await request(reply => statistics.ready(reply))
    }).catch(reason => { if (!disposed) setError(String(reason)) })
    return () => { disposed = true; bridge.current = null; cleanup() }
  }, [])
  const choose = (value: string) => {
    setError("")
    if (bridge.current) request(reply => bridge.current!.setPeriod(Number(value), reply)).catch(reason => setError(String(reason)))
  }
  const play = (id: number) => {
    setError("")
    if (bridge.current) request(reply => bridge.current!.playVideo(id, reply)).catch(reason => setError(String(reason)))
  }
  const result = state.result ?? undefined
  const data = result?.period
  // 첫 결과 전에는 결과 자리에 자리 표시를 둔다. 탭을 열면 바로 계산을 시작하므로 첫 프레임부터 보인다.
  // 결과가 오며 아래 구역이 붙어 스크롤바가 생겨도 폭이 같도록 main은 스크롤바 자리를 늘 잡는다(scroll-stable).
  // 실패하면 자리 표시를 끝내고 오류 안내를 따른다. 다시 계산할 때는 이전 결과를 그대로 두고 기다림 표시만 보인다.
  const failed = !!(error || state.message)
  const firstPending = !result && !failed
  const description = section === "inventory" ? "현재 라이브러리 현황 · 기간 선택과 무관" : data ? `${formatDate(data.start_date)} ~ ${formatDate(data.end_date)} · 1회 평균 ${duration(data.average_seconds)}` : ""
  const content = section === "inventory" ? <Inventory inventory={result?.inventory} library={data?.library} /> : <Activity result={result} metric={metric} onMetric={setMetric} onPlay={play} />
  return <main ref={root} aria-label="통계" className="flex h-full min-h-0 flex-1 flex-col gap-3 overflow-y-auto scroll-stable p-4">
    <PageHeader title="시청 통계" description="오늘을 포함한 로컬 날짜 기준 · 틀어보기와 모아보기 복습 제외" actions={<Tabs label="통계 기간" value={String(state.days)} items={periods} onChange={choose} />} />
    {/* 표시 중인 결과의 범위와 기다림 표시를 한 줄에 둔다. 줄 높이는 문구가 생기고 사라져도 같다. */}
    <div data-statistics-status className="flex h-5 min-w-0 shrink-0 items-center gap-3 text-sm text-muted-foreground">
      {description && <p className="min-w-0 truncate">{description}</p>}
      <PendingStatus pending={state.loading} label={`${state.days}일 시청 기록을 계산하고 있어요…`} className="shrink-0" />
    </div>
    {failed && <Notice tone="error" action={<Button variant="outline" size="sm" onClick={() => choose(String(state.days))}>다시 시도</Button>}><p>{error || state.message}</p>{data && <p className="text-muted-foreground">표시 중인 결과: {formatDate(data.start_date)} ~ {formatDate(data.end_date)} ({data.days}일){data.days !== state.days && ` · 선택한 ${state.days}일 결과가 아닙니다`}</p>}</Notice>}
    <Tabs label="통계 구역" value={section} items={[{ value: "activity", label: "시청 활동" }, { value: "inventory", label: "라이브러리 현황" }]} onChange={setSection} />
    {firstPending ? <Placeholder data-statistics-results label="시청 기록을 계산하는 중"><div className="space-y-5">{content}</div></Placeholder>
      : result ? <div data-statistics-results aria-busy={state.loading} className="space-y-5">{content}</div>
      : <EmptyState title="통계를 계산하지 못했어요" description="위 안내의 ‘다시 시도’로 다시 계산할 수 있어요." />}
  </main>
}
