import { cva, type VariantProps } from "class-variance-authority"
import type { ComponentProps } from "react"
import { Film } from "lucide-react"
import { StatusBadge } from "@/components/page-parts"
import { VideoTags } from "@/components/video-tags"
import type { VideoData } from "@/bridge-types"

const cardVariants = cva("group flex h-full min-w-0 flex-col overflow-hidden rounded-lg border text-left transition-colors focus-visible:outline-2 focus-visible:outline-ring", {
  variants: { variant: { default: "border-border bg-card hover:border-ring", selected: "border-ring bg-accent" } },
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
  variants: { variant: { default: "aspect-video", card: "h-24", gem: "h-20", detail: "h-20 rounded-sm" } }, defaultVariants: { variant: "default" },
})
export function Thumbnail({ video, variant }: { video: VideoData } & VariantProps<typeof thumbnailVariants>) {
  return <div className={thumbnailVariants({ variant })}>
    <Film aria-hidden="true" className="absolute size-8 text-muted-foreground" />
    {video.thumbnail && <img className="relative size-full object-cover" src={video.thumbnail} alt="" loading="lazy" onError={e => { e.currentTarget.hidden = true }} />}
  </div>
}

type Props = Omit<ComponentProps<"button">, "className"> & VariantProps<typeof cardVariants> & { video: VideoData }
const dateFormatter = new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" })
function lastViewed(value: string | null) {
  return value ? dateFormatter.format(new Date(value)) : "기록 없음"
}
function VideoStatistics({ video }: { video: VideoData }) {
  return <span aria-label="시청 통계" className="grid grid-cols-2 gap-1 rounded-lg border bg-background/40 p-1.5 text-xs">
    <span className="flex flex-col gap-1 rounded-md border p-2"><span className="text-muted-foreground">시청 횟수</span><span className="font-medium tabular-nums">{video.viewingCount}회</span></span>
    <span className="flex flex-col gap-1 rounded-md border p-2"><span className="text-muted-foreground">시청 시간</span><span className="font-medium tabular-nums">{duration(video.watchedSeconds)}</span></span>
    <span className="col-span-2 flex items-center justify-between gap-1 rounded-md border px-2 py-1.5"><span className="text-muted-foreground">마지막 시청</span><span className="tabular-nums">{lastViewed(video.lastViewedAt)}</span></span>
  </span>
}
export function VideoCard({ video, variant, ...props }: Props) {
  return <button {...props} className={cardVariants({ variant })} title={video.title}>
    <Thumbnail video={video} variant="card" />
    <div className="flex min-h-0 w-full flex-1 flex-col gap-1.5 p-3">
      <span className="line-clamp-2 min-h-10 leading-5 font-medium wrap-anywhere">{video.title}</span>
      <span className="truncate text-xs text-muted-foreground" title={video.series}>{duration(video.duration)}{video.series && ` · ${video.series}`}</span>
      <span className="flex flex-wrap gap-1">
        <StatusBadge variant={video.missing ? "destructive" : video.finished ? "success" : video.abandoned ? "info" : "muted"}>{viewing(video)}</StatusBadge>
        {video.hasSubtitles && <StatusBadge variant="info">자막 있음</StatusBadge>}
        {video.favorite && <StatusBadge variant="highlight">즐겨 보는</StatusBadge>}
      </span>
      <VideoStatistics video={video} />
      <span className="mt-auto min-w-0"><VideoTags tags={video.tags} /></span>
    </div>
  </button>
}
