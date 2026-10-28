import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { ChevronDown, ChevronUp, CircleAlert, CircleCheck, Info, TriangleAlert, X } from "lucide-react"
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

// 떠 있는 안내 묶음 안인지. 묶음은 폭이 좁아(max-w-md) 동작 단추를 문구 옆이 아니라 아래에 둔다. 다른 자리의 기본 배치는 그대로다.
const InLayer = React.createContext(false)

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
  const below = React.useContext(InLayer)
  return (
    <div data-slot="notice" data-tone={tone} role={role ?? (tone === "error" ? "alert" : "status")} className={cn(noticeVariants({ tone, size }), className)} {...props}>
      <Icon aria-hidden="true" className={toneText({ tone, size })} />
      <div className="min-w-0 flex-1 space-y-1">
        {title && <div className="font-medium">{title}</div>}
        {children !== undefined && children !== null && children !== "" && <NoticeMessage clamp={!!clamp}>{children}</NoticeMessage>}
        {action && below && <div className="flex flex-wrap items-center gap-2 pt-1">{action}</div>}
      </div>
      {action && !below && <div className="flex shrink-0 items-center gap-2 self-center">{action}</div>}
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
 * band는 목록을 밀지 않는 띠다. relative인 목록 영역 위쪽에 떠서 겹치고, 영역 높이의 절반까지만 쓰고 안에서 스크롤한다.
 * 안내가 생기고 사라져도 목록의 자리·열 수·스크롤은 그대로다. 오른쪽은 목록 스크롤바 자리를 비운다.
 */
const stackVariants = cva("flex min-w-0 flex-col gap-2", {
  variants: { layout: {
    auto: "",
    yield: "min-h-10 shrink overflow-y-auto",
    band: "absolute inset-x-2 top-2 z-10 max-h-1/2 overflow-y-auto rounded-xl border bg-popover p-2 shadow-lg",
  } },
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

// 셸 안내 묶음. 페이지 영역(relative)의 한 모서리에 떠서 페이지를 밀지 않는다. 폭은 max-w-md, 높이는 영역의 1/3까지이고 넘치면 묶음 안에서 스크롤한다.
const layerVariants = cva("absolute inset-x-4 z-40 max-h-1/3 max-w-md flex-col overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-lg", {
  variants: {
    empty: { true: "hidden", false: "flex" },
    corner: { "bottom-right": "bottom-4 ml-auto", "bottom-left": "bottom-4 mr-auto", "top-right": "top-4 ml-auto" },
  },
  defaultVariants: { empty: false, corner: "bottom-right" },
})
const layerBody = cva("min-h-0 flex-col gap-2 overflow-y-auto p-2", {
  variants: { collapsed: { true: "hidden", false: "flex" } },
  defaultVariants: { collapsed: false },
})

type Corner = NonNullable<VariantProps<typeof layerVariants>["corner"]>
// 앞에 있을수록 먼저 고른다. 가리는 고정 조작 요소 수가 같으면 오른쪽 아래가 기본이다.
const corners: readonly Corner[] = ["bottom-right", "bottom-left", "top-right"]
const controls = "button, input, select, textarea, a[href], [role=combobox], [role=tab], [role=tree], [tabindex='0']"

/** 넘쳐서 스크롤되는 목록 안의 요소는 스크롤로 묶음 밖으로 옮길 수 있다. 그렇지 않은 툴바·작업 단추 줄·머리글 단추가 고정 조작 요소다. */
function fixedControls(region: Element) {
  const scrolls = (element: Element) => element.scrollHeight > element.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(element).overflowY)
  return [...region.querySelectorAll(controls)].filter(element => {
    if (!element.checkVisibility()) return false
    for (let parent = element.parentElement; parent && parent !== region; parent = parent.parentElement) if (scrolls(parent)) return false
    return true
  }).map(element => element.getBoundingClientRect())
}

/** 묶음이 지금 크기로 각 모서리에 놓일 때 가리는 고정 조작 요소가 가장 적은 모서리. current가 있으면 그 모서리가 아무것도 가리지 않을 때 그대로 둔다. */
function chooseCorner(layer: HTMLElement, region: Element | null, current: Corner | null): Corner {
  const area = (layer.offsetParent ?? layer.parentElement)?.getBoundingClientRect()
  if (!area || !region || layer.offsetWidth === 0) return current ?? corners[0]
  const inset = parseFloat(getComputedStyle(document.documentElement).fontSize)
  const width = layer.offsetWidth, height = layer.offsetHeight
  const boxes: Record<Corner, readonly [number, number]> = {
    "bottom-right": [area.right - inset - width, area.bottom - inset - height],
    "bottom-left": [area.left + inset, area.bottom - inset - height],
    "top-right": [area.right - inset - width, area.top + inset],
  }
  const rects = fixedControls(region)
  const covered = (corner: Corner) => {
    const [left, top] = boxes[corner]
    return rects.filter(rect => rect.left < left + width && left < rect.right && rect.top < top + height && top < rect.bottom).length
  }
  // 같은 페이지에서는 지금 모서리가 아무것도 가리지 않으면 옮기지 않아 묶음이 이유 없이 뛰지 않는다.
  if (current && covered(current) === 0) return current
  return corners.reduce((best, corner) => covered(corner) < covered(best) ? corner : best, corners[0])
}

/**
 * 여러 부품이 각자 그리는 안내를 떠 있는 한 묶음으로 모은다. 안내 순서와 닫기는 각 부품이 그대로 정한다.
 * 머리 줄은 안내 개수와 오류 개수를 보이고 접고 편다. 접어도 오류가 있다는 표시는 남고,
 * 새 안내가 생기거나 오류가 늘면 다시 편다. 안내가 하나도 없으면 묶음도 보이지 않는다(부품은 그대로 붙어 있어 상태를 잃지 않는다).
 * avoid 영역(지금 보이는 페이지)의 고정 조작 요소를 가리지 않는 모서리를 고른다. 오른쪽 아래가 기본이다.
 * 페이지가 바뀌거나 묶음이 새로 나타나면 처음부터 고르고, 같은 페이지에서 창 크기·묶음 크기·페이지 내용이 바뀌면
 * 지금 모서리가 무언가를 가릴 때만 다시 고른다.
 */
function NoticeLayer({ children, avoid, ...props }: Omit<React.ComponentProps<"section">, "className"> & {
  /** 가리지 않을 영역의 선택자. 바뀌면(페이지 전환) 모서리를 다시 고른다. */
  avoid?: string
}) {
  const layer = React.useRef<HTMLElement>(null)
  const body = React.useRef<HTMLDivElement>(null)
  const id = React.useId()
  const [total, setTotal] = React.useState(0)
  const [errors, setErrors] = React.useState(0)
  const [collapsed, setCollapsed] = React.useState(false)
  const [corner, setCorner] = React.useState<Corner>("bottom-right")
  const last = React.useRef({ total: 0, errors: 0 })
  const placed = React.useRef<{ avoid?: string; shown: boolean }>({ shown: false })
  React.useLayoutEffect(() => {
    const element = body.current!
    const count = () => {
      const notices = [...element.querySelectorAll("[data-slot=notice]")]
      const next = { total: notices.length, errors: notices.filter(notice => notice.getAttribute("data-tone") === "error").length }
      if (next.total > last.current.total || next.errors > last.current.errors) setCollapsed(false)
      last.current = next
      setTotal(next.total)
      setErrors(next.errors)
    }
    count()
    const observer = new MutationObserver(count)
    observer.observe(element, { subtree: true, childList: true, attributes: true, attributeFilter: ["data-tone"] })
    return () => observer.disconnect()
  }, [])
  React.useLayoutEffect(() => {
    const element = layer.current!
    const region = avoid ? document.querySelector(avoid) : null
    let frame = 0
    const place = (fresh: boolean) => { frame = 0; setCorner(current => chooseCorner(element, region, fresh ? null : current)) }
    const later = () => { if (!frame) frame = requestAnimationFrame(() => place(false)) }
    place(placed.current.avoid !== avoid || !placed.current.shown)
    placed.current = { avoid, shown: total > 0 }
    const resized = new ResizeObserver(later)
    resized.observe(element)
    const changed = new MutationObserver(later)
    if (region) changed.observe(region, { subtree: true, childList: true })
    window.addEventListener("resize", later)
    return () => { cancelAnimationFrame(frame); resized.disconnect(); changed.disconnect(); window.removeEventListener("resize", later) }
  }, [avoid, total, collapsed])
  return (
    <section ref={layer} data-slot="notice-layer" data-corner={corner} className={layerVariants({ empty: total === 0, corner })} {...props}>
      <div className="flex shrink-0 items-center gap-2 border-b py-1 pr-1 pl-3 text-xs text-muted-foreground">
        <span className="flex min-w-0 flex-1 items-center gap-1.5 tabular-nums">
          안내 {total}개
          {errors > 0 && <span className="flex items-center gap-1 text-destructive"><CircleAlert aria-hidden="true" className="size-3.5" />오류 {errors}개</span>}
        </span>
        <Button type="button" variant="ghost" size="xs" aria-label={collapsed ? "안내 묶음 펼치기" : "안내 묶음 접기"} aria-expanded={!collapsed} aria-controls={id} onClick={() => setCollapsed(value => !value)}>
          {collapsed ? <><ChevronUp aria-hidden="true" />펼치기</> : <><ChevronDown aria-hidden="true" />접기</>}
        </Button>
      </div>
      <div ref={body} id={id} className={layerBody({ collapsed })}><InLayer.Provider value>{children}</InLayer.Provider></div>
    </section>
  )
}

export { InlineNotice, Notice, NoticeLayer, NoticeStack, noticeVariants }
