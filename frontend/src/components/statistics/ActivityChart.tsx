import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts"
import { ChartContainer, ChartPlaceholder, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart"
import { Skeleton } from "@/components/ui/skeleton"
import { exactDuration, timeDivisor } from "./DailyChart"

// values가 없으면(첫 계산 중) 제목은 그대로 두고 단위 줄과 차트 자리를 같은 높이로 잡는다.
export function ActivityChart({ values, labels, title, tickStep = 1 }: { values?: number[]; labels: string[]; title: string; tickStep?: number }) {
  return <section className="min-w-0 space-y-3 rounded-xl border bg-card p-5"><h2 className="text-section-title">{title}</h2>
    {values ? <ActivityBars values={values} labels={labels} title={title} tickStep={tickStep} /> : <><Skeleton shape="text" className="w-48" /><ChartPlaceholder /></>}
  </section>
}

function ActivityBars({ values, labels, title, tickStep }: { values: number[]; labels: string[]; title: string; tickStep: number }) {
  const maximum = Math.max(...values, 0)
  const divisor = timeDivisor(maximum)
  const unit = divisor === 3600 ? "시간" : divisor === 60 ? "분" : "초"
  const data = values.map((seconds, index) => ({ label: labels[index], seconds: seconds / divisor }))
  return <><p className="text-label text-muted-foreground">단위: {unit} · 시청 시작 시각에 전량 배정</p><ChartContainer label={title} config={{ seconds: { label: "시청 시간", color: "var(--primary-text)" } }}>
    <BarChart accessibilityLayer data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
      <CartesianGrid vertical={false} stroke="var(--border)" />
      <XAxis dataKey="label" tickLine={false} axisLine={false} ticks={labels.filter((_, index) => index % tickStep === 0)} interval={0} tick={{ fill: "var(--muted-foreground)" }} />
      <YAxis width={56} tickLine={false} axisLine={false} allowDecimals={false} tickCount={Math.min(5, Math.max(2, Math.ceil(maximum / divisor) + 1))} domain={[0, maximum === 0 ? 1 : "auto"]} tick={{ fill: "var(--muted-foreground)" }} tickFormatter={value => Number(value).toLocaleString("ko-KR")} />
      <ChartTooltip cursor={{ fill: "var(--muted)" }} content={<ChartTooltipContent format={value => exactDuration(value * divisor)} />} />
      <Bar dataKey="seconds" fill="var(--primary-text)" radius={2} isAnimationActive={false} />
    </BarChart>
  </ChartContainer></>
}
