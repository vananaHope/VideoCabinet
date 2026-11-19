import { cva, type VariantProps } from "class-variance-authority"
import { Kbd, KbdGroup } from "@/components/ui/kbd"

export interface KeyHint {
  /** 같은 일을 하는 키들. 하나씩 키 칩으로 보인다. 비우면 글자만 보인다(우클릭 같은 마우스 동작). */
  keys?: readonly string[]
  label: string
}

// 줄 높이는 키 칩(h-5)과 같은 h-badge다. 힌트가 있든 없든 그 줄의 높이가 같다.
const hints = cva("flex min-h-badge min-w-0 items-center gap-x-3 gap-y-1 text-label text-muted-foreground", {
  variants: { wrap: { true: "flex-wrap", false: "overflow-hidden whitespace-nowrap" } },
  defaultVariants: { wrap: false },
})

/**
 * 목록의 키 힌트. 키는 키 안내와 같은 키 칩(Kbd)으로 보인다.
 * 자리 규칙: 힌트는 그 키를 받는 목록 바로 위 줄에 둔다(목록 아래나 단추 옆에 두지 않는다).
 */
export function KeyHints({ items, wrap, label = "키 힌트" }: { items: readonly KeyHint[]; label?: string } & VariantProps<typeof hints>) {
  return <p data-slot="key-hints" aria-label={label} className={hints({ wrap })}>
    {items.map(item => <span key={`${item.keys?.join("+") ?? ""}:${item.label}`} className="inline-flex shrink-0 items-center gap-1">
      {item.keys && <KbdGroup>{item.keys.map(key => <Kbd key={key}>{key}</Kbd>)}</KbdGroup>}{item.label}
    </span>)}
  </p>
}
