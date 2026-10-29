import type { DistributionBucket, LibraryInventory, LibraryStatistics } from "@/bridge-types"
import { PageHeader } from "@/components/page-parts"
import { Skeleton } from "@/components/ui/skeleton"
import { StatisticsCard } from "./StatisticsCard"
import { duration } from "./DailyChart"

function Distribution({ title, buckets, total, description }: { title: string; buckets: DistributionBucket[]; total: number; description?: string }) {
  return <section className="min-w-0 space-y-4 rounded-xl border bg-card p-5"><PageHeader variant="section" title={title} description={description} />
    <dl className="max-h-64 space-y-3 overflow-y-auto">{buckets.map(bucket => <div key={bucket.label} className="flex justify-between gap-4"><dt className="min-w-0 break-words text-body text-muted-foreground">{bucket.label}</dt><dd className="shrink-0 text-body tabular-nums">{bucket.video_count.toLocaleString()}개 · {total ? (bucket.video_count / total * 100).toLocaleString("ko-KR", { maximumFractionDigits: 1 }) : 0}%</dd></div>)}</dl>
    {!buckets.length && <p className="text-body text-muted-foreground">등록된 영상이 없습니다.</p>}
  </section>
}
function size(bytes: number) {
  const units = ["B", "KiB", "MiB", "GiB", "TiB"]
  const index = bytes ? Math.min(4, Math.floor(Math.log(bytes) / Math.log(1024))) : 0
  return `${(bytes / 1024 ** index).toLocaleString("ko-KR", { maximumFractionDigits: 2 })} ${units[index]}`
}
// 자료가 없으면(첫 계산 중) 카드 줄과 관리 현황을 같은 크기의 자리 표시로 그린다. 첫 화면 아래의 구성 분포는 자료가 온 뒤에 그린다.
export function Inventory({ inventory, library }: { inventory?: LibraryInventory; library?: LibraryStatistics }) {
  const cards = [
    ["전체 영상", inventory && `${inventory.video_count.toLocaleString()}개`, "제외 영상은 빼고 집계"],
    ["영상 총 길이", inventory && duration(inventory.duration_seconds), "복사본은 한 번만 집계"],
    ["영상 총 용량", inventory && size(inventory.known_size_bytes), inventory && `알려진 용량 · 용량 미확인 ${inventory.unknown_size_count.toLocaleString()}개`],
    ["누적 시청 시간", inventory && duration(inventory.all_watched_seconds), "전체 기간 · 제외한 영상 기록 포함"],
  ] as const
  const counts = [
    ["다 본 영상", library?.finished_count], ["보다 만 영상", library?.abandoned_count], ["아직 안 본 영상", library?.unwatched_count],
    ["자막 있는 영상", library?.subtitled_video_count], ["그중 한국어 자막", inventory?.korean_subtitled_count],
    ["재생 이력 없음", inventory?.never_played_count], ["하이라이트 있는 영상", inventory?.highlighted_video_count],
    ["하이라이트", library?.highlight_count], ["태그 있는 영상", inventory?.tagged_video_count],
  ] as const
  return <div className="space-y-5" data-statistics-inventory>
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{cards.map(([label, value, description]) => <StatisticsCard key={label} label={label} value={value} description={description} />)}</div>
    <section className="space-y-4 rounded-xl border bg-card p-5"><PageHeader variant="section" title="관리 현황" description="현재 라이브러리 · 제외 영상은 빼고 집계" />
      <dl className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">{counts.map(([label, value]) => <div key={label} className="flex justify-between gap-4"><dt className="text-body text-muted-foreground">{label}</dt>{value === undefined ? <dd className="flex h-line-body items-center"><Skeleton className="w-12" /></dd> : <dd className="text-body-strong tabular-nums">{value.toLocaleString()}개</dd>}</div>)}</dl>
      <p className="text-label text-muted-foreground">아직 안 본 영상은 틀어보기·복습만 한 영상도 포함합니다. 재생 이력 없음은 일반 재생과 완료한 복습 기록이 모두 없는 영상입니다.</p>
    </section>
    {inventory && <section className="space-y-3"><PageHeader variant="section" title="라이브러리 구성" description="해상도는 짧은 변 기준" /><div className="grid gap-5 lg:grid-cols-3"><Distribution title="영상 길이 분포" buckets={inventory.duration_distribution} total={inventory.video_count} /><Distribution title="파일 형식 분포" buckets={inventory.format_distribution} total={inventory.video_count} /><Distribution title="해상도 분포" description={inventory.resolution_pending_description} buckets={inventory.resolution_distribution} total={inventory.video_count} /></div></section>}
  </div>
}
