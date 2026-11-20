import * as React from "react"
import { Checkbox as CheckboxPrimitive } from "radix-ui"
import { Check } from "lucide-react"
import { cn } from "@/lib/utils"

/** 켜고 끄는 선택지 하나(대화상자 안). 꺼짐은 조작 경계 `input` 테두리, 켜짐은 선택 상태라 `primary` 면이다. 초점 윤곽선은 전역 규칙이 준다. */
function Checkbox({ className, ...props }: React.ComponentProps<typeof CheckboxPrimitive.Root>) {
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      className={cn(
        "peer size-4 shrink-0 rounded-xs border border-input bg-input/30 transition-colors disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground",
        className
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator data-slot="checkbox-indicator" className="flex items-center justify-center text-current">
        <Check className="size-3.5" aria-hidden="true" />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  )
}

export { Checkbox }
