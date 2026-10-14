import { cva, type VariantProps } from "class-variance-authority"
import type { ComponentProps } from "react"
import type { VideoData } from "@/bridge-types"
import { duration, viewing } from "@/components/video-card"

const gemVariants = cva("flex w-56 shrink-0 items-center gap-3 rounded-lg border p-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-ring", {
  variants: { variant: { default: "border-border bg-card hover:border-primary", selected: "border-primary bg-accent" } },
  defaultVariants: { variant: "default" },
})
type Props = Omit<ComponentProps<"button">, "className"> & VariantProps<typeof gemVariants> & { video: VideoData; reason: string }
export function GemCard({ video, reason, variant, ...props }: Props) {
  return <button {...props} className={gemVariants({ variant })} title={`${video.title}\n${reason}`}>
    <div className="flex w-full min-w-0 flex-col gap-1">
      <span className="truncate font-medium">{video.title}</span>
      <span className="text-xs text-muted-foreground">{duration(video.duration)} · {viewing(video)}</span>
      <span className="truncate text-xs text-primary">{reason}</span>
    </div>
    {video.thumbnail && <img src={video.thumbnail} alt="" className="aspect-video w-16 rounded-sm object-cover" />}
  </button>
}
