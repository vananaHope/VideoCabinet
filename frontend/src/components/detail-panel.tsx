import { cva, type VariantProps } from "class-variance-authority"
import { Button } from "@/components/ui/button"
import { Thumbnail, duration, viewing } from "@/components/video-card"
import type { VideoData, DetailsData } from "@/bridge-types"
import { actions, lockedDuringScan, type Action } from "@/bridge"

const detailVariants = cva("flex h-full w-64 shrink-0 flex-col gap-2 overflow-y-auto rounded-lg border border-border bg-card p-2", {
  variants: { variant: { selected: "", empty: "items-center justify-center text-center text-muted-foreground" } },
  defaultVariants: { variant: "selected" },
})
const actionVariants = cva("min-w-0", {
  variants: { variant: { wide: "col-span-2", compact: "col-span-1" } }, defaultVariants: { variant: "compact" },
})
function DetailAction({ name, title, videoId, scanning, onAction, variant }: VariantProps<typeof actionVariants> & { name: Action; title: string; videoId: number; scanning: boolean; onAction: Props['onAction'] }) {
  return <div className={actionVariants({ variant })}>
    <Button className="w-full" variant={name === "play" ? "default" : name === "exclude" ? "destructive-outline" : "outline"} size="sm" disabled={scanning && lockedDuringScan(name)} onClick={() => onAction(name, videoId)}>{title}</Button>
  </div>
}
function DetailActions({ videoId, scanning, onAction }: { videoId: number; scanning: boolean; onAction: Props['onAction'] }) {
  const wide = ['play', 'subtitles', 'review']
  const ordered = [...actions.filter(([name]) => wide.includes(name)), ...actions.filter(([name]) => !wide.includes(name))]
  return <div aria-label="영상 작업" className="grid grid-cols-2 gap-1.5">
    {ordered.map(([name, title]) => <DetailAction key={name} name={name} title={title} variant={wide.includes(name) ? "wide" : "compact"} videoId={videoId} scanning={scanning} onAction={onAction} />)}
  </div>
}
const queueLabels: Record<string, string> = { queued: "대기", transcribing: "받아쓰는 중", translating: "번역 중", completed: "완료", failed: "실패", held: "보류" }
type Props = VariantProps<typeof detailVariants> & { video?: VideoData; details: DetailsData | null; scanning: boolean; onAction: (action: Action, id: number) => void }
export function DetailPanel({ video, details, scanning, onAction, variant }: Props) {
  return <aside aria-label="선택 영상 상세" className={detailVariants({ variant })}>
    {!video ? <p>영상을 선택하면<br />상세 정보와 작업이 표시됩니다.</p> : <>
      <Thumbnail video={video} variant="detail" />
      <h2 title={video.title} className="line-clamp-2 shrink-0 text-sm leading-5 font-semibold wrap-anywhere">{video.title}</h2>
      <p className="text-xs text-muted-foreground">{duration(video.duration)} · {viewing(video)}</p>
      <DetailActions videoId={video.id} scanning={scanning} onAction={onAction} />
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
