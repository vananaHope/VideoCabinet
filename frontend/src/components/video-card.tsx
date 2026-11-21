import { cva, type VariantProps } from "class-variance-authority"
import type { ComponentProps } from "react"
import { Captions, Film, Star } from "lucide-react"
import { StatusBadge } from "@/components/page-parts"
import { selectableItem } from "@/components/ui/selectable-item"
import { Skeleton } from "@/components/ui/skeleton"
import { VideoTags } from "@/components/video-tags"
import type { VideoData } from "@/bridge-types"
import { formatDate } from "@/lib/dates"

const cardVariants = cva("group flex h-full min-w-0 flex-col overflow-hidden rounded-lg border text-left transition-colors", {
  variants: { variant: { default: ["border-border bg-card", selectableItem({ selected: false, inner: "muted" })], selected: "border-ring bg-card ring-1 ring-ring", placeholder: "border-border bg-card" } },
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
// 시청 상태 배지. 라이브러리 카드와 추천 카드가 같은 배지로 시청 상태를 보인다.
export function ViewingBadge({ video }: { video: VideoData }) {
  return <StatusBadge variant={video.missing ? "destructive" : video.finished ? "success" : video.abandoned ? "info" : "muted"}>{viewing(video)}</StatusBadge>
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
/**
 * 시청 통계 한 줄. 카드 속 상자 없이 라벨 글자로 "횟수 · 시간 · 마지막 시청"을 잇는다. 이름표는 줄의 title과 읽기 이름에 둔다.
 * 마지막 날짜가 틀어보기뿐이면 "틀어봄"을 앞에 붙인다(틀어보기는 횟수·시간에 넣지 않는다).
 */
function VideoStatistics({ video }: { video: VideoData }) {
  const glanceOnly = video.viewingCount === 0 && video.lastViewedAt !== null
  const totals = `${video.viewingCount}회 · ${duration(video.watchedSeconds)}`
  const last = `${glanceOnly ? "마지막 틀어보기" : "마지막 시청"} ${lastViewed(video.lastViewedAt)}`
  return <span aria-label="시청 통계" title={`시청 ${totals} · ${last}${glanceOnly ? " (틀어보기는 시청 횟수·시간에 넣지 않습니다)" : ""}`}
    className="flex h-line-label min-w-0 items-center gap-1 text-label text-muted-foreground tabular-nums">
    <span className="shrink-0">{totals}</span>
    <span aria-hidden="true">·</span>
    <span className="truncate">{glanceOnly && "틀어봄 "}<span>{lastViewed(video.lastViewedAt)}</span></span>
  </span>
}
/**
 * 있을 때만 붙는 표시(자막 있음·즐겨 보는). 정보 칸이 좁으면(작게, 좁은 보통) 같은 줄에 다 들어가도록 글자 배지 대신 작은 기호로 보이고,
 * 이름은 기호의 읽기 이름과 title로 남는다. 넓으면 글자 배지다.
 */
const flagIcon = cva("size-3.5", { variants: { variant: { outline: "text-muted-foreground", highlight: "fill-highlight text-highlight" } } })
type Flag = { label: string; icon: typeof Film; variant: "outline" | "highlight" }
function videoFlags(video: VideoData): Flag[] {
  return [
    ...video.hasSubtitles ? [{ label: "자막 있음", icon: Captions, variant: "outline" } as const] : [],
    ...video.favorite ? [{ label: "즐겨 보는", icon: Star, variant: "highlight" } as const] : [],
  ]
}
/**
 * 정보 칸은 네 줄이다: 제목, 길이·상태 배지, 시청 통계, 분류(시리즈·태그). 줄마다 늘 내용이 있어 빈 띠가 생기지 않고,
 * 높이는 web_tokens.json layout.library-card-info-height 한곳에서 정한다(격자 줄 높이 계산도 같은 토큰을 읽는다).
 * 있을 때만 붙는 표시(자막 있음·즐겨 보는)는 넓은 칸에서는 상태 배지 옆 글자 배지이고, 칸이 좁으면(card-flags 미만) 둘째 줄이 넘치지 않게
 * 제목 줄 끝의 작은 기호가 된다. 제목은 줄여 쓰므로 기호 자리는 늘 있고, 이름은 기호의 읽기 이름과 title로 남는다.
 */
export function VideoCard({ video, variant, cardSize = "medium", ...props }: Props) {
  const flags = videoFlags(video)
  return <button {...props} className={cardVariants({ variant })} title={video.title}>
    <Thumbnail video={video} variant={cardSize === "large" ? "large" : cardSize === "small" ? "card" : "medium"} />
    <div className="@container/info flex h-card-info w-full shrink-0 flex-col gap-1 p-2">
      <span className="flex h-line-body min-w-0 shrink-0 items-center gap-1">
        <span className="min-w-0 flex-1 truncate text-body-strong">{video.title}</span>
        {flags.map(({ label, icon: Icon, variant }) => <span key={label} title={label} className="hidden shrink-0 @max-card-flags/info:inline-flex">
          <Icon aria-hidden="true" className={flagIcon({ variant })} /><span className="sr-only">{label}</span></span>)}
      </span>
      <span className="flex h-badge min-w-0 items-center gap-1.5">
        <span className="shrink-0 text-label text-muted-foreground tabular-nums">{duration(video.duration)}</span>
        <ViewingBadge video={video} />
        {flags.map(({ label, variant }) => <span key={label} className="contents @max-card-flags/info:hidden"><StatusBadge variant={variant}>{label}</StatusBadge></span>)}
      </span>
      <VideoStatistics video={video} />
      <span aria-label="분류" className="flex h-badge min-w-0 items-center gap-1.5">
        {video.series && <span className="max-w-1/2 min-w-0 shrink-0 truncate text-label text-muted-foreground" title={`시리즈 ${video.series}`}>{video.series}</span>}
        {video.tags.length ? <span className="min-w-0 flex-1"><VideoTags tags={video.tags} /></span>
          : !video.series && <span className="text-label text-muted-foreground">태그 없음</span>}
      </span>
    </div>
  </button>
}

/**
 * 영상 정보가 오기 전의 카드 자리. VideoCard와 같은 테두리·16:9 썸네일·정보 칸 높이를 써서 바뀔 때 크기가 같다.
 * 결과에 든 영상의 카드를 아직 받지 못했으면(#267) 격자 칸 역할과 선택 표시를 받아 그 자리에서 고르고 이동할 수 있다.
 */
export function VideoCardPlaceholder({ selected = false, ...props }: Omit<ComponentProps<"div">, "className" | "children"> & { selected?: boolean }) {
  return <div data-slot="video-card-placeholder" aria-hidden={props.role ? undefined : true} {...props} className={cardVariants({ variant: selected ? "selected" : "placeholder" })}>
    <Skeleton shape="media" />
    <div className="flex h-card-info w-full shrink-0 flex-col gap-1 p-2">
      <Skeleton shape="line" className="w-3/4" />
      <span className="flex gap-1.5"><Skeleton shape="badge" className="w-10" /><Skeleton shape="badge" className="w-14" /></span>
      <Skeleton shape="text" className="w-1/2" />
      <Skeleton shape="badge" className="w-16" />
    </div>
  </div>
}
