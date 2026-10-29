import type { ExternalSubtitleFileData } from "@/bridge-types"
import { StatusBadge } from "@/components/page-parts"
import { Notice } from "@/components/ui/notice"

export function ExternalSubtitleList({ files }: { files: ExternalSubtitleFileData[] }) {
  return <section aria-label="외부 자막" className="space-y-2 border-t pt-2">
    <h3 className="text-label-strong text-foreground">외부 자막{files.length > 0 && ` · ${files.length}개 파일`}</h3>
    {!files.length ? <p>가져온 외부 자막이 없습니다.</p> : <ul className="space-y-3">
      {files.map(file => <li key={file.id} className="min-w-0 space-y-1">
        <p title={file.name} className="truncate text-label-strong text-foreground">{file.name}</p>
        {file.folderLabel && <p title={file.folderLabel} className="truncate text-muted-foreground">{file.folderLabel}</p>}
        {file.subtitles.length ? file.subtitles.map((track, index) => <div key={index} className="flex flex-wrap items-center gap-2">
          <StatusBadge>{track.languageLabel}</StatusBadge>
          <span>{track.lineCount}줄</span>
          {track.languageClass && <span title={track.languageClass} className="max-w-full truncate">{track.languageClass}</span>}
        </div>) : <div className="flex items-center gap-2"><StatusBadge variant="destructive">읽기 실패</StatusBadge><span>0줄</span></div>}
        {/* 한 트랙도 읽지 못했으면 실패 사유(오류), 일부만 읽었으면 확인할 점(경고)이다. */}
        {file.warning && <Notice tone={file.subtitles.length ? "warning" : "error"} size="compact" role="note">{file.warning}</Notice>}
      </li>)}
    </ul>}
  </section>
}
