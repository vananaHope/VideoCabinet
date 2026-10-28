import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts"
import { ChartContainer, ChartPlaceholder, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart"
import { Skeleton } from "@/components/ui/skeleton"
import type { DailyViewingStatistics } from "@/bridge-types"
import { formatDate, formatShortDate } from "@/lib/dates"

const chartConfig = {
  watched_seconds: { label: "시청 시간", color: "var(--primary-text)" },
  viewing_count: { label: "시청 횟수", color: "var(--primary-text)" },
} satisfies ChartConfig
export type Metric = keyof typeof chartConfig
export function duration(seconds: number): string {
  const total = Math.round(seconds)
  if (total >= 3600) return `${Math.floor(total / 3600).toLocaleString()}시간 ${Math.floor(total % 3600 / 60)}분`
  if (total >= 60) return `${Math.floor(total / 60)}분 ${total % 60}초`
  return `${seconds.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}초`
}
// 최댓값이 2시간 이상일 때만 시간 단위로 그린다. 1~2시간을 시간으로 그리면 정수 눈금이 0/1/2뿐이라
// 막대 대부분이 첫 눈금 아래에 몰린다. 분 단위로는 같은 범위가 0~120 사이 눈금 3~5개로 나뉜다.
export function timeDivisor(maximum: number) { return maximum >= 7200 ? 3600 : maximum >= 60 ? 60 : 1 }
// 눈금은 표시 단위에서 계산하고 툴팁은 원래 초의 정밀도를 유지한다.
export function exactDuration(seconds: number): string {
  const milliseconds = Math.round(seconds * 1000)
  const hours = Math.floor(milliseconds / 3600000)
  const minutes = Math.floor(milliseconds % 3600000 / 60000)
  const remainder = (milliseconds % 60000 / 1000).toLocaleString("ko-KR", { maximumFractionDigits: 3 })
  return `${hours ? `${hours.toLocaleString()}시간 ` : ""}${hours || minutes ? `${minutes}분 ` : ""}${remainder}초`
}
// daily가 없으면(첫 계산 중) 단위 줄과 차트 자리를 같은 높이로 잡는다.
export function DailyChart({ daily, metric }: { daily?: DailyViewingStatistics[]; metric: Metric }) {
  if (!daily) return <div className="space-y-2"><Skeleton shape="text" className="w-40" /><ChartPlaceholder /></div>
  const maximum = Math.max(...daily.map(day => day[metric]), 0)
  const divisor = metric === "viewing_count" ? 1 : timeDivisor(maximum)
  const unit = metric === "viewing_count" ? "회" : divisor === 3600 ? "시간" : divisor === 60 ? "분" : "초"
  const data = daily.map(day => ({ ...day, [metric]: day[metric] / divisor }))
  const format = (value: number) => metric === "watched_seconds" ? exactDuration(value * divisor) : `${value.toLocaleString()}회`
  return <div className="space-y-2"><p className="text-xs text-muted-foreground">단위: {unit} · 시작한 날짜 기준</p><ChartContainer config={chartConfig} label={`일별 ${chartConfig[metric].label}`}>
    <BarChart accessibilityLayer data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
      <CartesianGrid vertical={false} stroke="var(--border)" />
      <XAxis dataKey="date" tickLine={false} axisLine={false} minTickGap={32} interval="preserveStartEnd" tick={{ fill: "var(--muted-foreground)" }} tickFormatter={value => formatShortDate(String(value))} />
      <YAxis width={64} tickLine={false} axisLine={false} allowDecimals={false} tickCount={Math.min(5, Math.max(2, Math.ceil(maximum / divisor) + 1))} domain={[0, maximum === 0 ? 1 : "auto"]} tick={{ fill: "var(--muted-foreground)" }} tickFormatter={value => Number(value).toLocaleString("ko-KR")} />
      <ChartTooltip cursor={{ fill: "var(--muted)" }} content={<ChartTooltipContent format={format} formatLabel={formatDate} />} />
      <Bar dataKey={metric} fill={chartConfig[metric].color} radius={2} isAnimationActive={false} />
    </BarChart>
  </ChartContainer></div>
}
