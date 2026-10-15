import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts"
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart"
import { exactDuration } from "./DailyChart"

export function ActivityChart({ values, labels, title, tickStep = 1 }: { values: number[]; labels: string[]; title: string; tickStep?: number }) {
  const maximum = Math.max(...values, 0)
  const divisor = maximum >= 3600 ? 3600 : maximum >= 60 ? 60 : 1
  const unit = divisor === 3600 ? "시간" : divisor === 60 ? "분" : "초"
  const data = values.map((seconds, index) => ({ label: labels[index], seconds: seconds / divisor }))
  return <section className="min-w-0 space-y-3 rounded-xl border bg-card p-5"><h2 className="text-lg font-semibold">{title}</h2><p className="text-xs text-muted-foreground">단위: {unit} · 시청 시작 시각에 전량 배정</p><ChartContainer label={title} config={{ seconds: { label: "시청 시간", color: "var(--primary-text)" } }}>
    <BarChart accessibilityLayer data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
      <CartesianGrid vertical={false} stroke="var(--border)" />
      <XAxis dataKey="label" tickLine={false} axisLine={false} ticks={labels.filter((_, index) => index % tickStep === 0)} interval={0} tick={{ fill: "var(--muted-foreground)" }} />
      <YAxis width={56} tickLine={false} axisLine={false} allowDecimals={false} tickCount={Math.min(5, Math.max(2, Math.ceil(maximum / divisor) + 1))} domain={[0, maximum === 0 ? 1 : "auto"]} tick={{ fill: "var(--muted-foreground)" }} tickFormatter={value => Number(value).toLocaleString("ko-KR")} />
      <ChartTooltip cursor={{ fill: "var(--muted)" }} content={<ChartTooltipContent format={value => exactDuration(value * divisor)} />} />
      <Bar dataKey="seconds" fill="var(--primary-text)" radius={2} isAnimationActive={false} />
    </BarChart>
  </ChartContainer></section>
}
