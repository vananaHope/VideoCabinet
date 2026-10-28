import { createContext, useContext, type ComponentProps, type ReactNode } from "react"
import { ResponsiveContainer, Tooltip } from "recharts"
import { Skeleton } from "@/components/ui/skeleton"

// shadcn/ui Chart의 합성 구조를 사용한다. 색은 전역 web_tokens.json 변수만 받는다.
export type ChartConfig = Record<string, { label: string; color: string }>
const ChartContext = createContext<ChartConfig>({})
export function ChartContainer({ config, children, label }: { config: ChartConfig; children: ComponentProps<typeof ResponsiveContainer>["children"]; label: string }) {
  return <ChartContext.Provider value={config}><div data-slot="chart" role="figure" aria-label={label} className="h-48 w-full min-w-0 text-xs">
    <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 600, height: 192 }}>{children}</ResponsiveContainer>
  </div></ChartContext.Provider>
}
/** 차트 자료가 오기 전의 자리. ChartContainer와 같은 높이(h-48)를 잡는다. */
export function ChartPlaceholder() {
  return <Skeleton shape="block" data-chart-placeholder className="h-48 w-full" />
}
export const ChartTooltip = Tooltip
export function ChartTooltipContent({ active, payload, label, format, formatLabel }: { active?: boolean; payload?: readonly { dataKey?: string | number; value?: unknown }[]; label?: ReactNode; format: (value: number) => string; formatLabel?: (label: string) => string }) {
  const config = useContext(ChartContext)
  if (!active || !payload?.length) return null
  return <div className="grid gap-2 rounded-lg border bg-popover p-3 text-xs text-popover-foreground shadow-xl"><p className="font-medium">{formatLabel ? formatLabel(String(label)) : label}</p>{payload.map((entry, index) => <p key={index} className="flex gap-4"><span className="text-muted-foreground">{config[String(entry.dataKey)]?.label}</span><span className="font-medium tabular-nums">{format(Number(entry.value))}</span></p>)}</div>
}
