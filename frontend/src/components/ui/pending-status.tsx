import * as React from "react"
import { cn } from "@/lib/utils"

/** 기다림 표시가 나타나기 전 유예. 이보다 빨리 끝나는 동작에서는 아무것도 번쩍이지 않는다. */
const PENDING_DELAY_MS = 300

/** pending이 delay 동안 이어졌을 때만 true다. pending이 끝나면 곧바로 false로 돌아온다. */
function usePendingVisible(pending: boolean, delay = PENDING_DELAY_MS) {
  const [visible, setVisible] = React.useState(false)
  React.useEffect(() => {
    if (!pending) return
    const timer = window.setTimeout(() => setVisible(true), delay)
    return () => { window.clearTimeout(timer); setVisible(false) }
  }, [pending, delay])
  return pending && visible
}

/**
 * 기다림 표시. 상태 문구 자리(role=status)는 처음부터 있어 읽기 프로그램이 바뀐 문구를 알리고,
 * 문구는 pending이 유예보다 오래 이어질 때만 보인다. 회전 표시 없이 조용한 글자만 쓴다.
 */
function PendingStatus({ pending, label = "불러오는 중…", delay, className, ...props }: Omit<React.ComponentProps<"span">, "children"> & {
  pending: boolean
  label?: string
  delay?: number
}) {
  const visible = usePendingVisible(pending, delay)
  return <span data-slot="pending-status" role="status" aria-live="polite" className={cn("text-xs text-muted-foreground", className)} {...props}>
    {visible ? label : ""}
  </span>
}

export { PENDING_DELAY_MS, PendingStatus, usePendingVisible }
