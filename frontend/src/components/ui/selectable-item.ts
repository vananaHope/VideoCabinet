import { cva } from "class-variance-authority"

// 고를 수 있는 목록 항목(설정 분류·머리글·패널 탭·폴더·대화상자 목록·태그 고르기 행·검색 결과·대기열 행·영상 카드)의 면.
// 호버는 놓인 면보다 한 단계 밝은 muted, 선택은 그보다 밝은 accent라 둘이 같은 모양이 되지 않는다.
// inner "muted"는 안에 muted 면(배지·태그 칩·썸네일 자리)이 있는 카드 면 항목이다. 호버를 muted로 두면 안쪽 면이 묻히므로
// 카드 바로 위 단계인 popover로 밝힌다. 선택 면 accent는 muted보다 밝아 그대로 둔다.
// selected "aria"는 선택을 aria-selected 속성으로 나타내는 항목(목록 상자 옵션)이다. quiet는 쉬는 글자를 보조 글자로 둔다.
export const selectableItem = cva("", {
  variants: {
    selected: {
      true: "bg-accent text-accent-foreground",
      false: "",
      aria: "aria-selected:bg-accent aria-selected:text-accent-foreground",
    },
    inner: { plain: "", muted: "" },
    tone: { default: "", quiet: "" },
    ring: { true: "", false: "" },
  },
  compoundVariants: [
    { selected: [false, "aria"], inner: "plain", class: "hover:bg-muted" },
    { selected: [false, "aria"], inner: "muted", class: "hover:bg-popover" },
    { selected: false, tone: "quiet", class: "text-muted-foreground hover:text-foreground" },
    { selected: true, ring: true, class: "ring-1 ring-ring ring-inset" },
  ],
  defaultVariants: { selected: false, inner: "plain", tone: "default", ring: false },
})
