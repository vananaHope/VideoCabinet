import { useId, useState } from "react"
import { cva } from "class-variance-authority"
import type { ScanIssueData, ScanReportData } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { NoticeStack } from "@/components/ui/notice"

// 수백 줄이어도 안내 안에서만 스크롤해 폴더 목록을 밀어내지 않는다.
const issueList = cva("space-y-0.5 overflow-y-auto rounded-md text-xs leading-5 outline-none focus-visible:ring-2 focus-visible:ring-ring", {
  variants: { size: { default: "max-h-16", tall: "max-h-32" } },
  defaultVariants: { size: "default" },
})

function IssueList({ id, label, issues, size }: { id?: string; label: string; issues: ScanIssueData[]; size?: "default" | "tall" }) {
  // 스크롤 영역은 키보드로도 내려 볼 수 있게 포커스를 받는다.
  return <ul id={id} tabIndex={0} aria-label={label} className={issueList({ size })}>
    {issues.map((issue, index) => <li key={index} className="wrap-anywhere">{issue.path}<span className="text-muted-foreground">: {issue.message}</span></li>)}
  </ul>
}

/** 검사 안내. 종류는 코어가 나눈다: 영상 검사 실패는 오류, 외부 자막은 요약한 경고, 등록 요약과 알림은 정보다. */
export function ScanReport({ report }: { report: ScanReportData }) {
  const [subtitlesOpen, setSubtitlesOpen] = useState(false)
  const subtitleListId = useId()
  const { failures, subtitleWarnings, notes } = report
  return <NoticeStack layout="yield" clamp={false} items={[
    failures.length > 0 && { key: "failures", tone: "error", title: `영상 검사 오류 ${failures.length}개`, message: <IssueList label="영상 검사 오류 목록" issues={failures} /> },
    subtitleWarnings.length > 0 && {
      key: "subtitles", tone: "warning",
      // 펼침 단추는 제목 줄에 두어 Tab이 단추에서 펼친 목록으로 이어진다(Notice의 action 자리는 본문 뒤에 온다).
      title: <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span>외부 자막 경고 {subtitleWarnings.length}개<span className="font-normal text-muted-foreground"> · 영상별 경고는 영상 상세 정보 탭에서도 볼 수 있습니다.</span></span>
        <Button type="button" variant="outline" size="xs" aria-expanded={subtitlesOpen} aria-controls={subtitlesOpen ? subtitleListId : undefined}
          onClick={() => setSubtitlesOpen(open => !open)}>{subtitlesOpen ? "목록 접기" : "목록 보기"}</Button>
      </div>,
      message: subtitlesOpen ? <IssueList id={subtitleListId} label="외부 자막 경고 목록" issues={subtitleWarnings} size="tall" /> : undefined,
    },
    report.failed ? { tone: "error", message: report.message } : {
      key: "summary", tone: "info",
      message: notes.length ? <div className="space-y-1"><p>{report.message}</p><IssueList label="검사 알림 목록" issues={notes} /></div> : report.message,
    },
  ]} />
}
