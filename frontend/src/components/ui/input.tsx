import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

// 글자 크기는 선택 목록·단추와 같은 text-sm이다. search는 검색 탭 맨 위의 큰 검색 칸이다.
const inputVariants = cva(
  "w-full min-w-0 border border-input bg-transparent shadow-xs transition-colors selection:bg-primary selection:text-primary-foreground file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive dark:bg-input/30",
  {
    variants: {
      variant: {
        default: "h-9 rounded-md px-3 py-1 text-sm",
        search: "h-12 rounded-lg px-4 text-lg",
      },
    },
    defaultVariants: { variant: "default" },
  }
)

function Input({ className, type, variant, ...props }: React.ComponentProps<"input"> & VariantProps<typeof inputVariants>) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(inputVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Input }
