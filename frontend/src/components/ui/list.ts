import { cva } from "class-variance-authority"
import { selectableItem } from "@/components/ui/selectable-item"

// 공용 목록 틀과 행. 대화상자 목록·태그 고르기·폴더 관리·자동 자막 규칙·자동 백업 목록이 같은 모양을 쓴다.
// 틀은 얇은 테두리·lg 둥글기·안쪽 0.25rem이고, 행은 md 둥글기·최소 높이 2.25rem(입력란·단추와 같은 높이)이며 구분선 없이 2px 간격으로 놓인다.
// 선택은 selectableItem의 accent 면 + 안쪽 ring 1px라 둥근 행 모서리를 따라간다. 면은 놓인 자리를 따르고(대화상자는 popover),
// 바탕 위에 놓인 목록만 surface "card"로 카드 면을 깐다. 키보드로 고르는 목록 상자(aria-activedescendant)는 틀 자체가 초점을 받고,
// 초점 윤곽선은 전역 :focus-visible 규칙이 준다.
export const listFrame = cva("flex min-h-0 flex-col gap-0.5 overflow-auto rounded-lg border p-1", {
  variants: {
    surface: { none: "", card: "bg-card" },
  },
  defaultVariants: { surface: "none" },
})

// selected "static"은 고르지 않는 행(폴더·자동 백업)이다. 행 안 단추가 동작을 맡으므로 호버 면도 없다.
// inline은 한 줄 글자와 오른쪽 조작(작은 단추 2rem까지)이 같은 높이 2.25rem으로 들어가고, stacked는 제목·설명이 여러 줄로 쌓인다.
export const listRow = cva("flex min-h-9 w-full min-w-0 shrink-0 cursor-default rounded-md px-3 text-left text-body", {
  variants: {
    selected: {
      true: selectableItem({ selected: true, ring: true }),
      false: selectableItem({ selected: false }),
      static: "",
    },
    layout: {
      inline: "items-center gap-3 py-0.5",
      stacked: "flex-col justify-center gap-0.5 py-2",
    },
  },
  defaultVariants: { selected: "static", layout: "inline" },
})
