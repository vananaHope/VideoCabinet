import { cva, type VariantProps } from "class-variance-authority"
import type { ComponentProps, ReactNode } from "react"
import type { VideoData } from "@/bridge-types"
import { ContextMenu, ContextMenuTrigger, ContextMenuContent, ContextMenuItem } from "@/components/ui/context-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { Thumbnail, duration, viewing } from "@/components/video-card"

const cardVariants = cva("flex min-w-0 flex-col overflow-hidden rounded-lg border text-left transition-colors focus-visible:outline-2 focus-visible:outline-ring", {
  variants: { variant: { default: "border-border bg-card hover:bg-popover", selected: "border-ring bg-card ring-1 ring-ring", placeholder: "border-border bg-card" } },
  defaultVariants: { variant: "default" },
})
type Props = Omit<ComponentProps<"button">, "className"> & VariantProps<typeof cardVariants> & { video: VideoData; reason: string }
export function RecommendationCard({ video, reason, variant, ...props }: Props) {
  return <button {...props} className={cardVariants({ variant })} title={`${video.title}\n${reason}`}>
    <Thumbnail video={video} variant="card" />
    <div className="flex w-full min-w-0 flex-col gap-1 p-2">
      <span className="truncate font-medium">{video.title}</span>
      <span className="truncate text-xs text-muted-foreground">{duration(video.duration)} · {viewing(video)}</span>
      <span className="line-clamp-2 min-h-8 text-xs leading-4 wrap-anywhere text-primary-text">{reason}</span>
    </div>
  </button>
}

/** 추천이 오기 전의 카드 자리. RecommendationCard와 같은 테두리·16:9 썸네일·정보 칸 높이(제목 한 줄·정보 한 줄·이유 두 줄)를 쓴다. */
export function RecommendationCardPlaceholder() {
  return <div data-slot="recommendation-card-placeholder" aria-hidden="true" className={cardVariants({ variant: "placeholder" })}>
    <Skeleton shape="media" />
    <div className="flex w-full min-w-0 flex-col gap-1 p-2">
      <Skeleton className="w-3/4" />
      <Skeleton shape="text" className="w-1/2" />
      <Skeleton shape="block" className="h-8 w-full" />
    </div>
  </div>
}

// 메뉴를 닫으면 카드 버튼 대신 onClose가 정한 자리(추천 줄 목록)로 초점을 돌린다.
export function RecommendationMenu({ onPlay, onDismiss, onClose, children }: { onPlay: () => void; onDismiss: () => void; onClose: () => void; children: ReactNode }) {
  return <ContextMenu>
    <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
    <ContextMenuContent onCloseAutoFocus={event => { event.preventDefault(); onClose() }}>
      <ContextMenuItem onSelect={onPlay}>재생</ContextMenuItem>
      <ContextMenuItem onSelect={onDismiss}>관심 없음</ContextMenuItem>
    </ContextMenuContent>
  </ContextMenu>
}
