import * as React from "react"
import { cn } from "@/lib/utils"

/** 붙어 있는 버튼 묶음(split button 등). 이웃 버튼의 맞닿는 모서리와 테두리를 합친다. */
function ButtonGroup({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      role="group"
      data-slot="button-group"
      className={cn(
        "flex w-fit shrink-0 items-stretch [&>*]:focus-visible:relative [&>*]:focus-visible:z-10 [&>*:not(:first-child)]:rounded-l-none [&>*:not(:first-child)]:border-l-0 [&>*:not(:last-child)]:rounded-r-none",
        className
      )}
      {...props}
    />
  )
}

export { ButtonGroup }
