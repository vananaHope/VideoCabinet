import { cva, type VariantProps } from "class-variance-authority"
import type { ComponentProps } from "react"
import { Film } from "lucide-react"
import { StatusBadge } from "@/components/page-parts"
import { Skeleton } from "@/components/ui/skeleton"
import { VideoTags } from "@/components/video-tags"
import type { VideoData } from "@/bridge-types"
import { formatDate } from "@/lib/dates"

const cardVariants = cva("group flex h-full min-w-0 flex-col overflow-hidden rounded-lg border text-left transition-colors focus-visible:outline-2 focus-visible:outline-ring", {
  variants: { variant: { default: "border-border bg-card hover:bg-muted", selected: "border-ring bg-card ring-1 ring-ring", placeholder: "border-border bg-card" } },
  defaultVariants: { variant: "default" },
})

export function duration(seconds: number) {
  const value = Math.floor(seconds)
  const h = Math.floor(value / 3600)
  const m = Math.floor(value / 60) % 60
  return `${h ? `${h}:${String(m).padStart(2, "0")}` : m}:${String(value % 60).padStart(2, "0")}`
}
export function viewing(video: VideoData) {
  return video.missing ? "파일 없음" : video.finished ? "다 봄" : video.abandoned ? `보다 만 ${Math.round(video.stoppedPercent ?? 0)}%` : "아직 안 봄"
}
const thumbnailVariants = cva("relative flex w-full shrink-0 items-center justify-center overflow-hidden bg-muted", {
  variants: { variant: { default: "aspect-video", card: "aspect-video", medium: "aspect-video", large: "aspect-video", detail: "h-20 rounded-sm" } }, defaultVariants: { variant: "default" },
})
export function Thumbnail({ video, variant }: { video: VideoData } & VariantProps<typeof thumbnailVariants>) {
  return <div className={thumbnailVariants({ variant })}>
    <Film aria-hidden="true" className="absolute size-8 text-muted-foreground" />
    {video.thumbnail && <img className="relative size-full object-cover" src={video.thumbnail} alt="" loading="lazy" onError={e => { e.currentTarget.hidden = true }} />}
  </div>
}

type Props = Omit<ComponentProps<"button">, "className"> & VariantProps<typeof cardVariants> & { video: VideoData; cardSize?: string }
function lastViewed(value: string | null) {
  return value ? formatDate(value) : "기록 없음"
}
function VideoStatistics({ video }: { video: VideoData }) {
  const glanceOnly = video.viewingCount === 0 && video.lastViewedAt !== null
  return <span aria-label="시청 통계" className="grid grid-cols-2 gap-1 rounded-lg border bg-background/40 p-1.5 text-xs">
    <span className="flex min-w-0 flex-col"><span className="text-muted-foreground">횟수 · 시간</span><span className="truncate font-medium tabular-nums" title={`${video.viewingCount}회 · ${duration(video.watchedSeconds)}`}>{video.viewingCount}회 · {duration(video.watchedSeconds)}</span></span>
    <span className="flex min-w-0 flex-col"><span className="truncate text-muted-foreground" title={glanceOnly ? "틀어보기는 시청 횟수·시간에 넣지 않습니다" : undefined}>{glanceOnly ? "마지막 틀어보기" : "마지막 시청"}</span><span className="truncate tabular-nums" title={lastViewed(video.lastViewedAt)}>{lastViewed(video.lastViewedAt)}</span></span>
  </span>
}
export function VideoCard({ video, variant, cardSize = "medium", ...props }: Props) {
  return <button {...props} className={cardVariants({ variant })} title={video.title}>
    <Thumbnail video={video} variant={cardSize === "large" ? "large" : cardSize === "small" ? "card" : "medium"} />
    <div className="flex h-40 w-full shrink-0 flex-col gap-0.5 p-2">
      <span className="shrink-0 truncate leading-5 font-medium">{video.title}</span>
      <span className="flex flex-wrap items-center gap-1">
        <span className="text-xs text-muted-foreground tabular-nums">{duration(video.duration)}</span>
        <StatusBadge variant={video.missing ? "destructive" : video.finished ? "success" : video.abandoned ? "info" : "muted"}>{viewing(video)}</StatusBadge>
        {video.hasSubtitles && <StatusBadge variant="outline">자막 있음</StatusBadge>}
        {video.favorite && <StatusBadge variant="highlight">즐겨 보는</StatusBadge>}
      </span>
      {video.series && <span className="shrink-0 truncate text-xs text-muted-foreground" title={video.series}>{video.series}</span>}
      <VideoStatistics video={video} />
      <span className="mt-auto min-w-0"><VideoTags tags={video.tags} /></span>
    </div>
  </button>
}

/** 영상 정보가 오기 전의 카드 자리. VideoCard와 같은 테두리·16:9 썸네일·정보 칸 높이를 써서 바뀔 때 크기가 같다. */
export function VideoCardPlaceholder() {
  return <div data-slot="video-card-placeholder" aria-hidden="true" className={cardVariants({ variant: "placeholder" })}>
    <Skeleton shape="media" />
    <div className="flex h-40 w-full shrink-0 flex-col gap-0.5 p-2">
      <Skeleton shape="line" className="w-3/4" />
      <span className="flex gap-1"><Skeleton shape="badge" className="w-10" /><Skeleton shape="badge" className="w-14" /></span>
      <Skeleton shape="block" className="mt-1 h-12 w-full" />
      <Skeleton shape="badge" className="mt-auto w-16" />
    </div>
  </div>
}
