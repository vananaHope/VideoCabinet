import { cva, type VariantProps } from "class-variance-authority"
import type { ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogFooter, AlertDialogHeader } from "@/components/ui/dialog"
import { selectableItem } from "@/components/ui/selectable-item"

export function PageHeader({ title, description, actions, variant = "page" }: { title: string; description?: string; actions?: ReactNode; variant?: "page" | "section" }) {
  return <div className="flex min-w-0 items-start justify-between gap-4"><div className="min-w-0 space-y-1">
    {variant === "section" ? <h2 className="text-section-title">{title}</h2> : <h1 className="text-page-title">{title}</h1>}
    {description && <p className="text-body text-muted-foreground">{description}</p>}
  </div>{actions}</div>
}

// page: 화면·목록 전체가 비었을 때. 틀 없이 그 영역 가운데에 둔다. section: 패널·카드 안의 한 구역이 비었을 때. 점선 상자로 자리를 보인다.
// 다음 동작(action)은 이미 있는 기능으로 가는 단추만 둔다.
const empty = cva("flex flex-col items-center justify-center gap-2 text-center", { variants: { variant: { page: "h-full min-h-0 flex-1 p-6", section: "rounded-xl border border-dashed p-6" } }, defaultVariants: { variant: "section" } })
export function EmptyState({ title, description, action, variant }: { title: string; description: string; action?: ReactNode } & VariantProps<typeof empty>) {
  return <section data-slot="empty-state" className={empty({ variant })}><h2 className="text-section-title">{title}</h2><p className="max-w-prose text-body text-muted-foreground">{description}</p>{action && <div className="mt-2 flex flex-wrap justify-center gap-2">{action}</div>}</section>
}
// 상태 배지는 각진 칩(rounded-xs)이다. 알약 모양은 태그·조건 칩(ui/chip.tsx)이 쓴다.
const status = cva("inline-flex h-badge w-fit items-center rounded-xs px-2 text-label-strong whitespace-nowrap", { variants: { variant: { success: "bg-status-success text-status-success-foreground", info: "bg-status-info text-status-info-foreground", highlight: "bg-highlight text-highlight-foreground", destructive: "bg-destructive text-destructive-foreground", muted: "bg-muted text-muted-foreground", selectedMuted: "bg-muted-foreground text-background", outline: "bg-transparent text-muted-foreground ring-1 ring-inset ring-input" } }, defaultVariants: { variant: "muted" } })
export function StatusBadge({ children, variant }: { children: ReactNode } & VariantProps<typeof status>) { return <span data-slot="status-badge" className={status({ variant })}>{children}</span> }

const tabList = cva("flex min-w-0 items-center gap-1", { variants: { variant: { navigation: "flex-1", section: "w-fit max-w-full rounded-lg bg-muted p-1", panel: "shrink-0 rounded-lg border p-1" } }, defaultVariants: { variant: "section" } })
const tabButton = cva("shrink-0 rounded-md px-3 py-2 text-sm font-medium transition-colors", { variants: { variant: { navigation: "", section: "", panel: "" }, selected: { true: "", false: "" }, last: { true: "ml-auto", false: "" } }, compoundVariants: [
  // 머리글·패널 탭은 고를 수 있는 목록 항목(호버 muted, 선택 accent)이다. 구역 탭은 묶음 면이 muted라 호버가 한 단계 밝은 accent다.
  // 구역 탭 선택은 강조색 없이 묶음에서 파낸 바탕 면 + 본문 글자 + 조작 경계(input) 한 겹이다. 인디고는 초점 윤곽선에만 남는다.
  { variant: ["navigation", "panel"], selected: true, class: selectableItem({ selected: true }) },
  { variant: ["navigation", "panel"], selected: false, class: selectableItem({ selected: false, tone: "quiet" }) },
  { variant: "section", selected: true, class: "bg-background text-foreground ring-1 ring-input ring-inset" },
  { variant: "section", selected: false, class: "text-muted-foreground hover:bg-accent hover:text-foreground" },
], defaultVariants: { variant: "section" } })
export function Tabs({ label, value, items, onChange, variant }: { label: string; value: string; items: readonly { value: string; label: string; shortcut?: string }[]; onChange: (value: string) => void } & VariantProps<typeof tabList>) {
  return <nav aria-label={label} className={tabList({ variant })}>{items.map((item, index) => <button key={item.value} data-tab={item.value} type="button" aria-current={item.value === value ? "page" : undefined} title={item.shortcut ? `${item.label} (${item.shortcut})` : item.label} aria-keyshortcuts={item.shortcut?.replace("Ctrl", "Control")} className={tabButton({ variant, selected: item.value === value, last: variant === "navigation" && index === items.length - 1 })} onClick={() => onChange(item.value)}>{item.label}</button>)}</nav>
}

export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel = "확인", cancelLabel = "취소", onConfirm, onCancel, variant = "default" }: { open: boolean; onOpenChange: (open: boolean) => void; title: string; description: string; confirmLabel?: string; cancelLabel?: string; onConfirm: () => void; onCancel?: () => void; variant?: "default" | "destructive" }) {
  return <AlertDialog open={open} onOpenChange={onOpenChange}>
    <AlertDialogContent>
      <AlertDialogHeader title={title} description={description} />
      <AlertDialogFooter>
        <AlertDialogCancel asChild><Button variant="outline" onClick={onCancel}>{cancelLabel}</Button></AlertDialogCancel>
        <AlertDialogAction asChild><Button variant={variant} onClick={onConfirm}>{confirmLabel}</Button></AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
}
