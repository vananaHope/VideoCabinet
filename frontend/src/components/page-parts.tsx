import { cva, type VariantProps } from "class-variance-authority"
import type { ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogFooter, AlertDialogHeader } from "@/components/ui/dialog"

export function PageHeader({ title, description, actions, variant = "page" }: { title: string; description?: string; actions?: ReactNode; variant?: "page" | "section" }) {
  return <div className="flex min-w-0 items-start justify-between gap-4"><div className="min-w-0 space-y-1">
    {variant === "section" ? <h2 className="text-lg font-semibold">{title}</h2> : <h1 className="text-2xl font-semibold">{title}</h1>}
    {description && <p className="text-sm text-muted-foreground">{description}</p>}
  </div>{actions}</div>
}
export function SectionTitle(props: Omit<Parameters<typeof PageHeader>[0], "variant">) { return <PageHeader {...props} variant="section" /> }

const empty = cva("flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed text-center", { variants: { variant: { page: "min-h-0 flex-1 p-12", section: "p-6" } }, defaultVariants: { variant: "section" } })
export function EmptyState({ title, description, action, variant }: { title: string; description: string; action?: ReactNode } & VariantProps<typeof empty>) {
  return <section className={empty({ variant })}><h2 className="text-lg font-semibold">{title}</h2><p className="text-sm text-muted-foreground">{description}</p>{action}</section>
}
const number = cva("rounded-xl border bg-card p-6", { variants: { variant: { default: "text-card-foreground", accent: "text-primary-text" } }, defaultVariants: { variant: "default" } })
export function NumberCard({ label, value, description, variant }: { label: string; value: ReactNode; description?: string } & VariantProps<typeof number>) {
  return <section className={number({ variant })}><h3 className="text-sm text-muted-foreground">{label}</h3><p className="my-3 text-3xl font-semibold tabular-nums">{value}</p>{description && <p className="text-xs text-muted-foreground">{description}</p>}</section>
}
const status = cva("inline-flex w-fit items-center rounded-md px-2 py-0.5 text-xs font-medium", { variants: { variant: { success: "bg-status-success text-status-success-foreground", info: "bg-status-info text-status-info-foreground", highlight: "bg-highlight text-highlight-foreground", destructive: "bg-destructive text-destructive-foreground", muted: "bg-muted text-muted-foreground", selectedMuted: "bg-muted-foreground text-background", outline: "bg-transparent text-muted-foreground ring-1 ring-inset ring-input" } }, defaultVariants: { variant: "muted" } })
export function StatusBadge({ children, variant }: { children: ReactNode } & VariantProps<typeof status>) { return <span className={status({ variant })}>{children}</span> }

const tabList = cva("flex min-w-0 items-center gap-1", { variants: { variant: { navigation: "flex-1", section: "rounded-lg bg-muted p-1", panel: "shrink-0 rounded-lg border p-1" } }, defaultVariants: { variant: "section" } })
const tabButton = cva("shrink-0 rounded-md px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-ring", { variants: { variant: { navigation: "", section: "", panel: "" }, selected: { true: "", false: "text-muted-foreground hover:text-foreground" }, last: { true: "ml-auto", false: "" } }, compoundVariants: [
  // 호버는 놓인 면보다 한 단계 밝은 면, 선택은 그보다 분명한 면(accent·primary)이다. 구역 탭은 묶음 면이 muted라 호버가 accent다.
  { variant: "navigation", selected: true, class: "bg-accent text-accent-foreground" },
  { variant: "navigation", selected: false, class: "hover:bg-muted" },
  { variant: "section", selected: true, class: "bg-primary text-primary-foreground" },
  { variant: "section", selected: false, class: "hover:bg-accent" },
  { variant: "panel", selected: true, class: "bg-accent text-accent-foreground" },
  { variant: "panel", selected: false, class: "hover:bg-muted" },
], defaultVariants: { variant: "section" } })
export function Tabs({ label, value, items, onChange, variant }: { label: string; value: string; items: readonly { value: string; label: string; shortcut?: string }[]; onChange: (value: string) => void } & VariantProps<typeof tabList>) {
  return <nav aria-label={label} className={tabList({ variant })}>{items.map((item, index) => <button key={item.value} data-tab={item.value} type="button" aria-current={item.value === value ? "page" : undefined} title={item.shortcut ? `${item.label} (${item.shortcut})` : item.label} aria-keyshortcuts={item.shortcut?.replace("Ctrl", "Control")} className={tabButton({ variant, selected: item.value === value, last: variant === "navigation" && index === items.length - 1 })} onClick={() => onChange(item.value)}>{item.label}</button>)}</nav>
}
const row = cva("flex min-w-0 items-center justify-between gap-4 rounded-lg border p-4", { variants: { variant: { default: "bg-card", selected: "border-ring bg-accent" } }, defaultVariants: { variant: "default" } })
export function ListItem({ title, description, action, variant }: { title: string; description?: string; action?: ReactNode } & VariantProps<typeof row>) { return <div className={row({ variant })}><div className="min-w-0"><p className="truncate font-medium">{title}</p>{description && <p className="text-sm text-muted-foreground">{description}</p>}</div>{action}</div> }

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
