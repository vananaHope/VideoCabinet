import type { ComponentProps } from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

/**
 * 자리 표시의 면. 데이터가 오기 전에 실제 내용과 같은 크기로 자리를 잡는다.
 * 쉬는 면처럼 평평하고 움직이지 않는다(DESIGN.md "조용한 상영실"). 읽기 프로그램에는 숨기고,
 * 감싼 영역(Placeholder 또는 실제 목록 요소)이 aria-busy와 상태 문구를 낸다.
 */
const skeletonVariants = cva("shrink-0 bg-muted", {
  variants: {
    shape: {
      /** 본문 한 줄(leading-5)과 같은 높이. */
      line: "h-5 rounded-sm",
      /** 작은 글자 한 줄(text-xs). */
      text: "h-4 rounded-sm",
      /** 작은 단추·탭(size sm)과 같은 높이. */
      control: "h-8 rounded-md",
      /** 상태 배지와 같은 높이. */
      badge: "h-5 rounded-md",
      /** 카드 안 묶음처럼 높이를 쓰는 곳에서 정한다. */
      block: "rounded-lg",
      /** 16:9 썸네일 자리. */
      media: "aspect-video w-full",
    },
  },
  defaultVariants: { shape: "line" },
})

function Skeleton({ shape, className, ...props }: Omit<ComponentProps<"div">, "children"> & VariantProps<typeof skeletonVariants>) {
  return <div data-slot="skeleton" aria-hidden="true" className={cn(skeletonVariants({ shape }), className)} {...props} />
}

const placeholderVariants = cva("min-w-0", {
  variants: {
    /** stack: 패널처럼 남은 높이를 채우며 위에서 아래로 쌓는다. */
    layout: { block: "", stack: "flex min-h-0 flex-1 flex-col gap-2" },
  },
  defaultVariants: { layout: "block" },
})

/**
 * 데이터를 기다리는 영역. aria-busy와 읽기용 문구를 달고, 자식 Skeleton으로 실제 배치를 흉내 낸다.
 * 목록 요소(role=grid·listbox)처럼 역할이 정해진 자리는 그 요소에 aria-busy를 직접 달고 Skeleton만 쓴다.
 */
function Placeholder({ label = "불러오는 중", layout, className, children, ...props }: ComponentProps<"div"> & VariantProps<typeof placeholderVariants> & { label?: string }) {
  return <div data-slot="placeholder" aria-busy="true" className={cn(placeholderVariants({ layout }), className)} {...props}>
    <span className="sr-only">{label}</span>
    {children}
  </div>
}

export { Placeholder, Skeleton }
