import { cva, type VariantProps } from "class-variance-authority"
import { Button } from "@/components/ui/button"
import { Notice } from "@/components/ui/notice"
import { Placeholder, Skeleton } from "@/components/ui/skeleton"
import { EmptyState, Tabs } from "@/components/page-parts"
import { HighlightPanel, type HighlightSnapshot } from "@/components/highlight-panel"
import { ExternalSubtitleList } from "@/components/external-subtitle-list"
import { Thumbnail, duration, viewing } from "@/components/video-card"
import { TagMenuChips } from "@/components/video-tags"
import type { VideoData, DetailsData } from "@/bridge-types"
import { actions, lockedDuringScan, type Action } from "@/bridge"
import { formatDate } from "@/lib/dates"

const detailVariants = cva("flex h-full w-72 shrink-0 flex-col gap-2 overflow-hidden rounded-lg border border-border bg-card p-3", {
  // failed: 첫 데이터를 읽지 못했다. 격자가 실패를 알리므로 패널은 자리만 지킨다.
  variants: { variant: { selected: "", loading: "", failed: "", empty: "items-center justify-center text-center text-muted-foreground" } },
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
const wideActions: readonly Action[] = ['subtitles', 'review']
/** 첫 데이터가 오기 전의 상세 자리. "선택한 영상 없음" 같은 거짓 빈 상태 대신 선택 영상의 제목·탭·작업 단추·정보 줄 자리를 잡는다. */
function DetailPlaceholder() {
  return <Placeholder layout="stack">
    <Skeleton shape="line" className="w-4/5" />
    <Skeleton shape="block" className="h-11.5 w-full" />
    <div className="grid shrink-0 grid-cols-2 gap-1.5">
      {actions.map(([name]) => <div key={name} className={actionVariants({ variant: wideActions.includes(name) ? "wide" : "compact" })}><Skeleton shape="control" className="w-full" /></div>)}
    </div>
    <div className="min-h-0 flex-1 space-y-2 border-t pt-2">
      <Skeleton shape="block" className="h-20 w-full" />
      <Skeleton shape="text" className="w-1/2" />
      <Skeleton shape="text" className="w-2/5" />
      <Skeleton shape="text" className="w-3/5" />
    </div>
  </Placeholder>
}
function DetailActions({ videoId, scanning, onAction }: { videoId: number; scanning: boolean; onAction: Props['onAction'] }) {
  return <div aria-label="영상 작업" className="grid shrink-0 grid-cols-2 gap-1.5">
    {actions.map(([name, title]) => <DetailAction key={name} name={name} title={title} variant={wideActions.includes(name) ? "wide" : "compact"} videoId={videoId} scanning={scanning} onAction={onAction} />)}
  </div>
}
const queueLabels: Record<string, string> = { queued: "대기", transcribing: "받아쓰는 중", translating: "처리 중", completed: "완료", failed: "실패", held: "보류" }
const skipReasons: Record<string, string> = { no_speech: "원어 자막 줄이 없어 만들지 않았습니다.", unknown_language: "원어를 알 수 없어 만들지 않았습니다." }
function originalSummary(details: DetailsData) {
  if (!details.has_transcript) return "원어 자막 없음"
  if (details.no_speech) return `${details.spoken_language ? `원어: ${details.spoken_language}` : "원어 자막"} · 말소리를 찾지 못했습니다.`
  return `원어: ${details.spoken_language || "알 수 없음"} · ${details.original_lines}줄`
}
function translationSummary(details: DetailsData) {
  if (details.translated_lines) return `${details.taskLabel}: ${details.translated_lines}/${details.original_lines}줄`
  const reason = details.translation_skip_reason && skipReasons[details.translation_skip_reason]
  return `${details.subtitleLabel} 없음${reason ? ` · ${reason}` : ""}`
}
type Props = VariantProps<typeof detailVariants> & { video?: VideoData; details: DetailsData | null; highlights: HighlightSnapshot | null; revision: number; tab: string; onTabChange: (tab: string) => void; scanning: boolean; onAction: (action: Action, id: number) => void; onHighlight: (videoId: number, highlightId: number, edit: boolean) => void; highlightGuidance: string; onRandomTag: (tagId: number) => void }
export function DetailPanel({ video, details, highlights, revision, tab, onTabChange, scanning, onAction, onHighlight, highlightGuidance, onRandomTag, variant }: Props) {
  return <aside aria-label="선택 영상 상세" className={detailVariants({ variant })}>
    {variant === "loading" ? <DetailPlaceholder /> : variant === "failed" ? null : !video ? <EmptyState title="선택한 영상 없음" description="영상을 선택하면 상세 정보와 작업이 표시됩니다." /> : <>
      <h2 title={video.title} className="line-clamp-2 shrink-0 text-body-strong wrap-anywhere">{video.title}</h2>
      <Tabs variant="panel" label="영상 상세 탭" value={tab} onChange={onTabChange} items={[{ value: "info", label: "정보" }, { value: "highlights", label: `하이라이트${details ? ` · ${details.highlight_count}` : ""}` }]} />
      {tab === "highlights" ? <HighlightPanel key={video.id} videoId={video.id} snapshot={highlights} revision={revision} emptyDescription={highlightGuidance} onAction={onHighlight} /> : <>
      <DetailActions videoId={video.id} scanning={scanning} onAction={onAction} />
      <div id="detail-scroll" className="min-h-0 flex-1 space-y-2 overflow-y-auto border-t pt-2 text-label text-muted-foreground wrap-anywhere">
        <Thumbnail video={video} variant="detail" />
        <p>{duration(video.duration)} · {viewing(video)}</p>
        {video.missing ? <Notice tone="warning" size="compact" role="note">파일 없음 · 다시 검사하거나 파일을 연결하세요.</Notice> : <p>위치 {video.locationCount}개</p>}
        <p>수정한 날짜: {video.modifiedAt ? formatDate(video.modifiedAt) : video.missing ? "파일 없음" : "알 수 없음"}</p>
        {video.resumePoint !== null && <p>이어볼 위치 {duration(video.resumePoint)} ({Math.round(video.stoppedPercent ?? 0)}%)</p>}
        <TagMenuChips tags={video.tags} onRandomPlay={onRandomTag} />
        <p>시리즈: {video.series || "없음"}</p>
        {details && <>
          {/* 말소리 없음과 번역 미등록 사유는 정보 안내다. 줄 수 요약은 일반 정보 줄로 둔다. */}
          {details.has_transcript && details.no_speech ? <Notice tone="info" size="compact" role="note">{originalSummary(details)}</Notice> : <p>{originalSummary(details)}</p>}
          {!details.translated_lines && details.translation_skip_reason && skipReasons[details.translation_skip_reason] ? <Notice tone="info" size="compact" role="note">{translationSummary(details)}</Notice> : <p>{translationSummary(details)}</p>}
          <p>대기열: {[details.subtitle_state && `원어 ${queueLabels[details.subtitle_state] || details.subtitle_state}`, details.translation_state && `${details.taskLabel} ${queueLabels[details.translation_state] || details.translation_state}`].filter(Boolean).join(" · ") || "없음"}</p>
          <p>하이라이트 {details.highlight_count}개</p>
          <ExternalSubtitleList files={details.externalSubtitles} />
        </>}
      </div>
      </>}
    </>}
  </aside>
}
