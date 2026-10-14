import type { ComponentProps } from "react"

// 브라우저 기본 화살표·문자 선택·Tab 동작을 유지하는 태그 필터 컨트롤.
export function NativeSelect(props: Omit<ComponentProps<"select">, "className">) {
  return <select {...props} className="h-9 max-w-48 rounded-md border border-input bg-background px-3 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-ring" />
}
