import { cva, type VariantProps } from "class-variance-authority"
import type { ComponentProps } from "react"
import { Film } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import type { VideoData } from "@/bridge-types"

const cardVariants = cva("group flex h-full min-w-0 flex-col overflow-hidden rounded-lg border text-left transition-colors focus-visible:outline-2 focus-visible:outline-ring", {
  variants: { variant: { default: "border-border bg-card hover:border-primary", selected: "border-primary bg-accent" } },
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
  variants: { variant: { default: "aspect-video", card: "h-28" } }, defaultVariants: { variant: "default" },
})
export function Thumbnail({ video, variant }: { video: VideoData } & VariantProps<typeof thumbnailVariants>) {
  return <div className={thumbnailVariants({ variant })}>
    <Film aria-hidden="true" className="absolute size-8 text-muted-foreground" />
    {video.thumbnail && <img className="relative size-full object-cover" src={video.thumbnail} alt="" loading="lazy" onError={e => { e.currentTarget.hidden = true }} />}
  </div>
}

type Props = Omit<ComponentProps<"button">, "className"> & VariantProps<typeof cardVariants> & { video: VideoData }
export function VideoCard({ video, variant, ...props }: Props) {
  return <button {...props} className={cardVariants({ variant })} title={video.title}>
    <Thumbnail video={video} variant="card" />
    <div className="flex min-h-0 w-full flex-1 flex-col gap-1.5 p-3">
      <span className="line-clamp-2 leading-5 font-medium">{video.title}</span>
      <span className="text-xs text-muted-foreground">{duration(video.duration)} · {viewing(video)}</span>
      {video.series && <span className="truncate text-xs text-muted-foreground">{video.series}</span>}
      <span className="mt-auto flex min-w-0 gap-1 overflow-hidden">
        {video.favorite && <Badge variant="secondary">즐겨 보는</Badge>}
        {video.tags.slice(0, 2).map(tag => <Badge key={tag.id} variant="secondary">{tag.name}</Badge>)}
        {video.tags.length > 2 && <span className="text-xs text-muted-foreground">+{video.tags.length - 2}</span>}
      </span>
    </div>
  </button>
}
