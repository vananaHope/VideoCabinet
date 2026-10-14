import { cva, type VariantProps } from "class-variance-authority"
import type { ComponentProps } from "react"
import type { VideoData } from "@/bridge-types"
import { Thumbnail, duration, viewing } from "@/components/video-card"

const gemVariants = cva("flex min-w-0 flex-col overflow-hidden rounded-lg border text-left transition-colors focus-visible:outline-2 focus-visible:outline-ring", {
  variants: { variant: { default: "border-border bg-card hover:border-primary", selected: "border-primary bg-accent" } },
  defaultVariants: { variant: "default" },
})
type Props = Omit<ComponentProps<"button">, "className"> & VariantProps<typeof gemVariants> & { video: VideoData; reason: string }
export function GemCard({ video, reason, variant, ...props }: Props) {
  return <button {...props} className={gemVariants({ variant })} title={`${video.title}\n${reason}`}>
    <Thumbnail video={video} variant="gem" />
    <div className="flex w-full min-w-0 flex-col gap-1 p-2">
      <span className="truncate font-medium">{video.title}</span>
      <span className="text-xs text-muted-foreground">{duration(video.duration)} · {viewing(video)}</span>
      <span className="line-clamp-2 min-h-8 text-xs leading-4 text-primary">{reason}</span>
    </div>
  </button>
}
