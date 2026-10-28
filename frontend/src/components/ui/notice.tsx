import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

/**
 * 앱 공용 안내. 위계는 네 가지다.
 * - error: 요청·작업이 실패했다(role=alert).
 * - warning: 진행은 되지만 사용자가 확인하거나 바꿔야 한다.
 * - info: 상태·설명. 사용자가 할 일이 없다.
 * - success: 사용자가 시킨 작업을 마쳤다.
 * 여러 개가 겹치면 NoticeStack이 위계 순서로 쌓고 같은 문구는 한 번만 보인다.
 */
export type NoticeTone = "error" | "warning" | "info" | "success"

const icons = { error: CircleAlert, warning: TriangleAlert, info: Info, success: CircleCheck } as const
const rank: Record<NoticeTone, number> = { error: 0, warning: 1, success: 2, info: 3 }

// 안내는 나타날 때만 투명도로 들어온다. 자리는 처음부터 차지하므로 전환이 배치를 밀지 않는다.
const noticeVariants = cva("flex min-w-0 animate-fade-enter items-start rounded-lg border text-foreground", {
  variants: {
    tone: {
      error: "border-destructive/60 bg-destructive/10",
      warning: "border-status-warning/60 bg-status-warning/10",
      info: "border-status-info/40 bg-status-info/10",
      success: "border-status-success/50 bg-status-success/10",
    },
    size: { default: "gap-2 px-3 py-2 text-sm", compact: "gap-1.5 px-2 py-1 text-xs leading-5" },
  },
  defaultVariants: { tone: "info", size: "default" },
})
const toneText = cva("shrink-0", {
  variants: {
    tone: { error: "text-destructive", warning: "text-status-warning", info: "text-status-info", success: "text-status-success" },
    size: { default: "mt-0.5 size-4", compact: "mt-1 size-3", inline: "size-3.5" },
  },
  defaultVariants: { size: "default" },
})
// 긴 문구는 줄바꿈하되 두 줄까지만 보이고 “전체 보기”로 펼친다. 펼쳐도 안내 안에서만 스크롤해 페이지 목록이 밀려 사라지지 않는다.
const message = cva("whitespace-pre-wrap wrap-anywhere", {
  variants: { overflow: { clamped: "line-clamp-2", expanded: "max-h-40 overflow-y-auto", full: "" } },
  defaultVariants: { overflow: "full" },
})

function NoticeMessage({ clamp, children }: { clamp: boolean; children: React.ReactNode }) {
  const ref = React.useRef<HTMLDivElement>(null)
  const [expanded, setExpanded] = React.useState(false)
  const [overflowing, setOverflowing] = React.useState(false)
  React.useLayoutEffect(() => {
    const element = ref.current
    // 펼친 동안은 잘림을 잴 수 없으므로 마지막 판단(넘침)을 유지해 접기 버튼을 남긴다.
    if (!element || !clamp || expanded) return
    const measure = () => setOverflowing(element.scrollHeight > element.clientHeight + 1)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [clamp, expanded, children])
  return <>
    <div ref={ref} className={message({ overflow: !clamp ? "full" : expanded ? "expanded" : "clamped" })}>{children}</div>
    {clamp && overflowing && <Button type="button" variant="link" size="xs" className="-ml-2" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>
      {expanded ? "접기" : "전체 보기"}
    </Button>}
  </>
}

type NoticeProps = Omit<React.ComponentProps<"div">, "title"> & VariantProps<typeof noticeVariants> & {
  tone: NoticeTone
  title?: React.ReactNode
  action?: React.ReactNode
  onDismiss?: () => void
  /** 기본 크기의 긴 문구를 두 줄로 접는다. 진행 막대처럼 줄로 셀 수 없는 내용은 끈다. */
  clamp?: boolean
}

function Notice({ tone, size = "default", title, action, onDismiss, clamp = size === "default", children, className, role, ...props }: NoticeProps) {
  const Icon = icons[tone]
  return (
    <div data-slot="notice" data-tone={tone} role={role ?? (tone === "error" ? "alert" : "status")} className={cn(noticeVariants({ tone, size }), className)} {...props}>
      <Icon aria-hidden="true" className={toneText({ tone, size })} />
      <div className="min-w-0 flex-1 space-y-1">
        {title && <div className="font-medium">{title}</div>}
        {children !== undefined && children !== null && children !== "" && <NoticeMessage clamp={!!clamp}>{children}</NoticeMessage>}
      </div>
      {action && <div className="flex shrink-0 items-center gap-2 self-center">{action}</div>}
      {onDismiss && <Button type="button" variant="ghost" size="icon-xs" aria-label="안내 닫기" title="안내 닫기" onClick={onDismiss}><X aria-hidden="true" /></Button>}
    </div>
  )
}

/** 목록 행처럼 한 줄에 맞춰야 하는 자리. 잘린 문구 전체는 툴팁으로 본다. */
function InlineNotice({ tone, text, className, ...props }: Omit<React.ComponentProps<"span">, "children"> & { tone: NoticeTone; text: string }) {
  const Icon = icons[tone]
  return (
    <span data-slot="notice" data-tone={tone} title={text} className={cn("flex min-w-0 items-center gap-1.5", className)} {...props}>
      <Icon aria-hidden="true" className={toneText({ tone, size: "inline" })} />
      <span className="truncate">{text}</span>
    </span>
  )
}

export type NoticeItem = {
  /** 문구가 문자열이 아니면 같은 안내를 가리는 기준으로 쓴다. */
  key?: string
  tone: NoticeTone
  title?: React.ReactNode
  message?: React.ReactNode
  action?: React.ReactNode
  /** 요청 실패·작업 결과처럼 한 번 생긴 안내만 닫을 수 있다. 현재 상태에서 나온 안내는 원인이 사라지면 함께 사라진다. */
  onDismiss?: () => void
  role?: React.AriaRole
  label?: string
}

/**
 * 높이 정책. 목록이 있는 페이지는 yield를 쓴다. 안내 묶음은 목록이 최소 높이를 지키고 남은 자리까지만 차지하고,
 * 넘치면 묶음 안에서 스크롤한다. 그래도 안내 한 줄 높이는 남겨 오류가 통째로 가려지지 않게 한다.
 */
const stackVariants = cva("flex min-w-0 flex-col gap-2", {
  variants: { layout: { auto: "", yield: "min-h-10 shrink overflow-y-auto" } },
  defaultVariants: { layout: "auto" },
})

/** 쌓는 순서는 오류 → 경고 → 성공 → 정보다. 기본 세 개까지 보이고 나머지는 “더 보기”로 펼친다. */
function NoticeStack({ items, max = 3, size, clamp, layout, className, ...props }: Omit<React.ComponentProps<"div">, "children"> & VariantProps<typeof stackVariants> & {
  items: readonly (NoticeItem | false | null | undefined | "")[]
  max?: number
  size?: VariantProps<typeof noticeVariants>["size"]
  /** 대화상자처럼 바깥이 스크롤되는 자리는 끄고 전부 보인다. */
  clamp?: boolean
}) {
  const [expanded, setExpanded] = React.useState(false)
  const seen = new Set<string>()
  const visible = items
    .filter((item): item is NoticeItem => !!item && (!!item.title || (item.message !== undefined && item.message !== null && item.message !== "")))
    .map((item, index) => ({ item, index }))
    .sort((a, b) => rank[a.item.tone] - rank[b.item.tone] || a.index - b.index)
    .filter(({ item, index }) => {
      const key = typeof item.message === "string" ? `message:${item.message}` : item.key ?? `index:${index}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  if (!visible.length) return null
  const hidden = Math.max(0, visible.length - max)
  const shown = expanded ? visible : visible.slice(0, max)
  return (
    <div data-slot="notice-stack" className={cn(stackVariants({ layout }), className)} {...props}>
      {shown.map(({ item, index }) => (
        <Notice key={item.key ?? (typeof item.message === "string" ? item.message : index)} tone={item.tone} size={size} clamp={clamp} title={item.title}
          action={item.action} onDismiss={item.onDismiss} role={item.role} aria-label={item.label}>
          {item.message}
        </Notice>
      ))}
      {hidden > 0 && <Button type="button" variant="ghost" size="xs" className="self-start" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>
        {expanded ? "안내 접기" : `안내 ${hidden}개 더 보기`}
      </Button>}
    </div>
  )
}

export { InlineNotice, Notice, NoticeStack, noticeVariants }
