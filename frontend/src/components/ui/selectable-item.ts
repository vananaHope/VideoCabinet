import { cva } from "class-variance-authority"

// 고를 수 있는 목록 항목(설정 분류·머리글·패널 탭·폴더·대화상자 목록·태그 고르기 행)의 면.
// 호버는 놓인 면보다 한 단계 밝은 muted, 선택은 그보다 밝은 accent라 둘이 같은 모양이 되지 않는다.
// selected "aria"는 선택을 aria-selected 속성으로 나타내는 항목(목록 상자 옵션)이다. quiet는 쉬는 글자를 보조 글자로 둔다.
export const selectableItem = cva("", {
  variants: {
    selected: {
      true: "bg-accent text-accent-foreground",
      false: "hover:bg-muted",
      aria: "hover:bg-muted aria-selected:bg-accent aria-selected:text-accent-foreground",
    },
    tone: { default: "", quiet: "" },
    ring: { true: "", false: "" },
  },
  compoundVariants: [
    { selected: false, tone: "quiet", class: "text-muted-foreground hover:text-foreground" },
    { selected: true, ring: true, class: "ring-1 ring-ring ring-inset" },
  ],
  defaultVariants: { selected: false, tone: "default", ring: false },
})
