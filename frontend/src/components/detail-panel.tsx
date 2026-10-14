import { cva, type VariantProps } from "class-variance-authority"
import { Button } from "@/components/ui/button"
import { Thumbnail, duration, viewing } from "@/components/video-card"
import type { VideoData, DetailsData } from "@/bridge-types"
import { actions, lockedDuringScan, type Action } from "@/bridge"

const detailVariants = cva("flex h-full w-64 shrink-0 flex-col gap-3 overflow-y-auto rounded-lg border border-border bg-card p-4", {
  variants: { variant: { selected: "", empty: "items-center justify-center text-center text-muted-foreground" } },
  defaultVariants: { variant: "selected" },
})
const queueLabels: Record<string, string> = { queued: "대기", transcribing: "받아쓰는 중", translating: "번역 중", completed: "완료", failed: "실패", held: "보류" }
type Props = VariantProps<typeof detailVariants> & { video?: VideoData; details: DetailsData | null; scanning: boolean; onAction: (action: Action, id: number) => void }
export function DetailPanel({ video, details, scanning, onAction, variant }: Props) {
  return <aside aria-label="선택 영상 상세" className={detailVariants({ variant })}>
    {!video ? <p>영상을 선택하면<br />상세 정보와 작업이 표시됩니다.</p> : <>
      <Thumbnail video={video} />
      <h2 className="text-base leading-6 font-semibold wrap-anywhere">{video.title}</h2>
      <p className="text-xs text-muted-foreground">{duration(video.duration)} · {viewing(video)}</p>
      <div className="flex flex-col gap-2">
        {actions.map(([name, title]) => <Button key={name} variant={name === "play" ? "default" : name === "exclude" ? "destructive" : "outline"} size="sm" disabled={scanning && lockedDuringScan(name)} onClick={() => onAction(name, video.id)}>{title}</Button>)}
      </div>
      <div className="space-y-2 border-t pt-3 text-xs leading-5 text-muted-foreground">
        {video.missing ? <p>파일 없음 · 다시 검사하거나 파일을 연결하세요.</p> : <p>위치 {video.locationCount}개</p>}
        {video.resumePoint !== null && <p>이어볼 위치 {duration(video.resumePoint)} ({Math.round(video.stoppedPercent ?? 0)}%)</p>}
        <p>태그: {video.tags.map(t => t.name).join(", ") || "없음"}</p>
        <p>시리즈: {video.series || "없음"}</p>
        {details && <>
          <p>{details.has_transcript ? `원어: ${details.spoken_language || "알 수 없음"} · ${details.original_lines}줄` : "원어 자막 없음"}</p>
          <p>{details.translated_lines ? `번역: ${details.translated_lines}/${details.original_lines}줄` : "번역 자막 없음"}</p>
          <p>대기열: {[details.subtitle_state && `원어 ${queueLabels[details.subtitle_state] || details.subtitle_state}`, details.translation_state && `번역 ${queueLabels[details.translation_state] || details.translation_state}`].filter(Boolean).join(" · ") || "없음"}</p>
          <p>하이라이트 {details.highlight_count}개</p>
        </>}
      </div>
    </>}
  </aside>
}
