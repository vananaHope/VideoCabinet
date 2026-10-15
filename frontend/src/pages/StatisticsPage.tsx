import { useEffect, useRef, useState } from "react"
import { connectBridge, request } from "@/bridge"
import type { StatisticsBridge, StatisticsData } from "@/bridge-types"
import { EmptyState, PageHeader, Tabs } from "@/components/page-parts"
import { Button } from "@/components/ui/button"
import { DailyChart, duration, type Metric } from "@/components/statistics/DailyChart"

import { ActivityChart } from "@/components/statistics/ActivityChart"
import { Inventory } from "@/components/statistics/Inventory"

const periods = [7, 30, 90, 365].map(days => ({ value: String(days), label: `${days}일` }))
const metrics = [{ value: "watched_seconds", label: "시청 시간" }, { value: "viewing_count", label: "시청 횟수" }]
const change = (value: number | null) => value === null ? "이전 기록 없음" : `이전 같은 기간 대비 ${value > 0 ? "+" : ""}${value.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}%`

function StatisticsCard({ label, value, description }: { label: string; value: string; description: string }) {
  return <section className="min-w-0 space-y-2 rounded-xl border bg-card p-4"><h2 className="text-sm text-muted-foreground">{label}</h2><p className="break-words text-xl font-semibold tabular-nums">{value}</p><p className="text-xs text-muted-foreground">{description}</p></section>
}

export default function StatisticsPage() {
  const [state, setState] = useState<StatisticsData>({ days: 30, loading: false, message: "", result: null })
  const [section, setSection] = useState("activity")
  const [metric, setMetric] = useState<Metric>("watched_seconds")
  const [error, setError] = useState("")
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
  const data = state.result?.period
  return <main ref={root} aria-label="통계" aria-busy={state.loading} className="flex h-full min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-5">
    <PageHeader title="시청 통계" description="오늘을 포함한 로컬 날짜 기준 · 틀어보기와 모아보기 복습 제외" actions={<Tabs label="통계 기간" value={String(state.days)} items={periods} onChange={choose} />} />
    <div role="status" aria-live="polite" className="text-sm text-muted-foreground">{state.loading ? `${state.days}일 시청 기록을 계산하고 있어요…${data ? ` 현재 ${data.start_date} ~ ${data.end_date} 결과 표시 중` : ""}` : section === "inventory" ? "현재 라이브러리 현황 · 기간 선택과 무관" : data ? `${data.start_date} ~ ${data.end_date} · 1회 평균 ${duration(data.average_seconds)}` : "기간을 선택하면 시청 기록을 보여 드립니다."}</div>
    {(error || state.message) && <div role="alert" className="flex items-center justify-between gap-4 rounded-lg border p-4 text-destructive"><p>{error || state.message}</p><Button variant="outline" onClick={() => choose(String(state.days))}>다시 시도</Button></div>}
    <Tabs label="통계 구역" value={section} items={[{ value: "activity", label: "시청 활동" }, { value: "inventory", label: "라이브러리 현황" }]} onChange={setSection} />
    {data && state.result && section === "inventory" && <Inventory inventory={state.result.inventory} library={data.library} />}
    {data && state.result && section === "activity" && <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatisticsCard label="시청 시간" value={duration(data.watched_seconds)} description={change(data.watched_seconds_change_percent)} />
        <StatisticsCard label="시청 횟수" value={`${data.viewing_count.toLocaleString()}회`} description={change(data.viewing_count_change_percent)} />
        <StatisticsCard label="시청한 영상" value={`${data.watched_video_count.toLocaleString()}개`} description="중복 없이 센 영상" />
        <StatisticsCard label="시청한 날" value={`${data.watched_day_count}일`} description={`선택한 ${data.days}일 중`} />
        <StatisticsCard label="최장 연속 시청" value={`${data.longest_streak_days}일`} description="기간 안에서 이어 본 날" />
        <StatisticsCard label="새로 추가한 영상" value={`${data.added_video_count.toLocaleString()}개`} description="제외 영상은 빼고 집계" />
      </div>
      <section className="space-y-4 rounded-xl border bg-card p-5"><PageHeader variant="section" title="일별 시청" actions={<Tabs label="통계 지표" value={metric} items={metrics} onChange={value => setMetric(value as Metric)} />} />
        <DailyChart daily={data.daily} metric={metric} />
        {data.viewing_count === 0 && <p className="text-sm text-muted-foreground">이 기간에는 시청 기록이 없습니다.</p>}
      </section>
      <div className="grid gap-5 lg:grid-cols-2"><ActivityChart title="요일별 시청 시간" values={state.result.weekday_seconds} labels={["일", "월", "화", "수", "목", "금", "토"]} /><ActivityChart title="시간대별 시청 시간" values={state.result.hourly_seconds} labels={Array.from({ length: 24 }, (_, hour) => `${hour}시`)} tickStep={3} /></div>
        <section className="min-w-0 space-y-3 rounded-xl border bg-card p-5"><PageHeader variant="section" title="가장 많이 본 영상" description="이 기간의 시청 시간순 · 최대 5개" />
          {data.top_videos.length === 0 ? <EmptyState title="아직 시청한 영상이 없어요" description="영상을 시청하면 여기에 표시됩니다." /> : <ol className="space-y-2">{data.top_videos.map((video, index) => <li key={video.video_id}><button type="button" data-statistics-video={video.video_id} onClick={() => play(video.video_id)} disabled={video.excluded || video.missing} className="flex w-full min-w-0 items-center gap-3 rounded-lg p-3 text-left hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-60" title={video.title}><span className="text-sm text-muted-foreground">{index + 1}</span><span className="min-w-0 flex-1"><span className="block truncate font-medium">{video.title}</span><span className="block text-xs text-muted-foreground">{duration(video.watched_seconds)} · {video.viewing_count.toLocaleString()}회{video.excluded ? " · 제외한 영상" : video.missing ? " · 파일 없음" : " · 재생"}</span></span></button></li>)}</ol>}
        </section>
    </div>}
  </main>
}
