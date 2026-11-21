import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"
import { cn } from "@/lib/utils"

// 태그·조건처럼 "분류"를 보이는 알약 칩. 상태를 보이는 StatusBadge(각진 모양)와 모양으로 구별된다.
// 높이는 배지와 같은 h-badge이고, 긴 글자는 안쪽 <span className="truncate">가 줄인다. 쓰는 곳은 최대 폭 같은 배치만 더한다.
const chipVariants = cva(
  "inline-flex h-badge max-w-full min-w-0 items-center gap-1 rounded-full bg-secondary px-2 text-label whitespace-nowrap text-secondary-foreground [&_svg]:pointer-events-none [&_svg]:size-3 [&_svg]:shrink-0",
  {
    variants: {
      // 누를 수 있는 칩(태그 메뉴, 조건 지우기). 호버는 보조 단추와 같은 accent 면이다.
      interactive: { true: "shrink-0 transition-colors hover:bg-accent disabled:pointer-events-none disabled:opacity-50", false: "" },
      // 목록 상자 옵션으로 쓰는 칩(태그 고르기의 자주 쓴 태그 후보). Lit Ladder대로 호버는 muted, 고름은 그보다 밝은 accent 면 +
      // 안쪽 ring 1px(공용 목록 행과 같은 선택)이다. interactive와 함께 쓰지 않는다. 쓰는 곳이 체크 표시를 함께 둔다.
      selectable: { true: "shrink-0 transition-colors hover:bg-muted aria-selected:bg-accent aria-selected:text-accent-foreground aria-selected:ring-1 aria-selected:ring-ring aria-selected:ring-inset", false: "" },
    },
    defaultVariants: { interactive: false, selectable: false },
  }
)

function Chip({ className, interactive, selectable, asChild = false, ...props }: React.ComponentProps<"span"> & VariantProps<typeof chipVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span"
  return <Comp data-slot="chip" className={cn(chipVariants({ interactive, selectable }), className)} {...props} />
}

export { Chip }
