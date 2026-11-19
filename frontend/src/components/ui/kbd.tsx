import * as React from "react"
import { cn } from "@/lib/utils"

function Kbd({ className, ...props }: React.ComponentProps<"kbd">) {
  return (
    <kbd
      data-slot="kbd"
      className={cn(
        "pointer-events-none inline-flex h-5 w-fit min-w-5 items-center justify-center gap-1 rounded-xs bg-muted px-1 font-sans text-label-strong whitespace-nowrap text-muted-foreground select-none",
        "[&_svg:not([class*='size-'])]:size-3",
        className
      )}
      {...props}
    />
  )
}

function KbdGroup({ className, ...props }: React.ComponentProps<"kbd">) {
  return (
    <kbd
      data-slot="kbd-group"
      className={cn("inline-flex flex-wrap items-center gap-1", className)}
      {...props}
    />
  )
}

/**
 * 키 배치의 표시 문자열(key_display.display_keys: 키마다 " / "로 이은 문자열, 없으면 "키 미할당")을 키 칩으로 그린다.
 * 메뉴 단축키·키 배치 표처럼 Python이 만든 표시 문자열을 그대로 받는 곳이 쓴다. 문구와 순서는 바꾸지 않는다(textContent가 display와 같다).
 */
function Keys({ display, className }: { display: string; className?: string }) {
  if (!display || display === "키 미할당") return <span data-slot="keys" className={cn("text-label whitespace-nowrap text-muted-foreground", className)}>{display || "키 미할당"}</span>
  // 키 사이의 " / "는 화면에서는 칩 간격으로 보이고, 글자(읽기 프로그램·textContent)로는 표시 문자열 그대로 남는다.
  return <KbdGroup data-slot="keys" className={className}>{display.split(" / ").map((key, index) => <React.Fragment key={`${index}:${key}`}>{index > 0 && <span className="sr-only"> / </span>}<Kbd>{key}</Kbd></React.Fragment>)}</KbdGroup>
}

export { Kbd, KbdGroup, Keys }
