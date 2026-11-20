import { Skeleton } from "@/components/ui/skeleton"

/**
 * 통계 숫자 카드. 값이 오기 전(value 없음)에는 같은 칸 높이의 자리 표시를 그려 결과가 와도 카드 줄이 튀지 않는다.
 * 큰 숫자는 한 줄이고, 카드 폭(1100에서 한 줄 3장)은 기간 365일·영상 5만 개의 값도 줄바꿈 없이 들어가게 잡는다.
 * 설명은 두 줄 자리를 늘 잡아 기간·데이터에 따라 줄 수가 바뀌어도 카드 높이가 같다.
 */
export function StatisticsCard({ label, value, description }: { label: string; value?: string; description?: string }) {
  return <section className="min-w-0 space-y-2 rounded-xl border bg-card p-4">
    <h2 className="text-body text-muted-foreground">{label}</h2>
    {value === undefined
      ? <div className="flex h-line-display items-center"><Skeleton className="w-20" /></div>
      : <p className="truncate text-display tabular-nums" title={value}>{value}</p>}
    {description === undefined
      ? <div className="min-h-lines-label-2"><Skeleton shape="text" className="w-3/4" /></div>
      : <p className="line-clamp-2 min-h-lines-label-2 text-label text-muted-foreground" title={description}>{description}</p>}
  </section>
}
