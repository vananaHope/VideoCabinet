import * as React from "react"
import { cn } from "@/lib/utils"
import { CheckIcon, ChevronDownIcon, ChevronUpIcon } from "lucide-react"
import { Select as SelectPrimitive } from "radix-ui"

// QtWebEngine은 native select 팝업을 다시 그리지 못하므로 목록을 페이지 안에 그리는 Radix Select를 쓴다.
function Select({
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Root>) {
  return <SelectPrimitive.Root data-slot="select" {...props} />
}

function SelectValue({
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Value>) {
  return <SelectPrimitive.Value data-slot="select-value" {...props} />
}

function SelectTrigger({
  className,
  children,
  onPointerDown,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Trigger>) {
  return (
    <SelectPrimitive.Trigger
      data-slot="select-trigger"
      className={cn(
        "flex h-9 w-fit min-w-0 items-center justify-between gap-2 rounded-md border border-input bg-background px-3 text-sm whitespace-nowrap text-foreground shadow-xs outline-none focus-visible:outline-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-50 data-[placeholder]:text-muted-foreground *:data-[slot=select-value]:truncate dark:bg-input/30 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4 [&_svg:not([class*='text-'])]:text-muted-foreground",
        className
      )}
      // 비활성 fieldset 안의 트리거는 Radix가 비활성으로 알지 못하므로 여기서 열기를 막는다.
      onPointerDown={event => {
        onPointerDown?.(event)
        if (event.currentTarget.matches(":disabled")) event.preventDefault()
      }}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon asChild>
        <ChevronDownIcon />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  )
}

function SelectContent({
  className,
  children,
  onEscapeKeyDown,
  position = "popper",
  sideOffset = 4,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Content>) {
  return (
    <SelectPrimitive.Portal>
      {/* popper는 트리거 아래에 열고, 아래 공간이 모자라면 위로 뒤집어 보이는 높이 안에서 스크롤한다. */}
      <SelectPrimitive.Content
        data-slot="select-content"
        position={position}
        sideOffset={sideOffset}
        className={cn(
          "relative z-50 max-h-(--radix-select-content-available-height) max-w-(--radix-select-content-available-width) min-w-(--radix-select-trigger-width) origin-(--radix-select-content-transform-origin) animate-layer-enter overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md",
          className
        )}
        // Esc는 목록만 닫는다. 포털 안 키 입력이 React 트리를 타고 대화상자·페이지 단축키로 새지 않게 막는다.
        onEscapeKeyDown={event => {
          onEscapeKeyDown?.(event)
          event.stopPropagation()
        }}
        {...props}
      >
        <SelectScrollUpButton />
        <SelectPrimitive.Viewport className="p-1">{children}</SelectPrimitive.Viewport>
        <SelectScrollDownButton />
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  )
}

function SelectItem({
  className,
  children,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Item>) {
  return (
    <SelectPrimitive.Item
      data-slot="select-item"
      className={cn(
        "relative flex w-full cursor-default items-center gap-2 rounded-sm py-1.5 pr-8 pl-2 text-sm outline-hidden select-none focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[state=checked]:font-medium [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    >
      <span className="absolute right-2 flex size-3.5 items-center justify-center">
        <SelectPrimitive.ItemIndicator>
          <CheckIcon />
        </SelectPrimitive.ItemIndicator>
      </span>
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    </SelectPrimitive.Item>
  )
}

function SelectScrollUpButton({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.ScrollUpButton>) {
  return (
    <SelectPrimitive.ScrollUpButton
      data-slot="select-scroll-up-button"
      className={cn("flex cursor-default items-center justify-center py-1", className)}
      {...props}
    >
      <ChevronUpIcon className="size-4" />
    </SelectPrimitive.ScrollUpButton>
  )
}

function SelectScrollDownButton({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.ScrollDownButton>) {
  return (
    <SelectPrimitive.ScrollDownButton
      data-slot="select-scroll-down-button"
      className={cn("flex cursor-default items-center justify-center py-1", className)}
      {...props}
    >
      <ChevronDownIcon className="size-4" />
    </SelectPrimitive.ScrollDownButton>
  )
}

// Radix Item은 빈 문자열 값을 쓸 수 없다. 모든 값에 접두사를 붙여 안에서만 쓰고 바깥에는 원래 값을 넘긴다.
// 접두사는 일대일이라 사용자가 입력한 어떤 문자열(모델 이름 등)과도 내부 값이 겹치지 않는다.
const itemValue = (value: string) => `v:${value}`
const outerValue = (value: string) => value.slice(2)

type SelectOption = readonly [value: string, label: string]

// [값, 표시] 목록으로 만드는 단일 선택 필드. 목록에 없는 값이면 native select처럼 첫 항목 문구를 보인다.
// 트리거·항목의 data-value는 바깥 값 그대로라 검사 스크립트가 값으로 읽고 찾을 수 있다.
function SelectField({
  value,
  options,
  onValueChange,
  disabled,
  className,
  id,
  "aria-label": label,
}: {
  value: string
  options: readonly SelectOption[]
  onValueChange: (value: string) => void
  disabled?: boolean
  className?: string
  id?: string
  "aria-label": string
}) {
  const [open, setOpen] = React.useState(false)
  const known = options.some(([option]) => option === value)
  // 열린 목록의 Tab·Shift+Tab은 native select처럼 커서 항목을 확정하고 목록만 닫는다.
  // 포커스는 트리거로 돌아오고, 다음 Tab·Shift+Tab이 다음·이전 요소로 이동한다.
  function tabOut(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Tab") return
    event.preventDefault()
    const cursor = event.target instanceof HTMLElement ? event.target.closest<HTMLElement>("[data-slot=select-item]") : null
    const next = cursor?.dataset.value
    if (next !== undefined && next !== value) onValueChange(next)
    setOpen(false)
  }
  return (
    <Select open={open} onOpenChange={setOpen} value={known ? itemValue(value) : ""} onValueChange={next => onValueChange(outerValue(next))} disabled={disabled}>
      <SelectTrigger id={id} aria-label={label} data-value={value} className={className}>
        <SelectValue placeholder={options[0]?.[1]} />
      </SelectTrigger>
      <SelectContent onKeyDown={tabOut}>
        {options.map(([option, text]) => <SelectItem key={option} value={itemValue(option)} data-value={option}>{text}</SelectItem>)}
      </SelectContent>
    </Select>
  )
}

export {
  Select,
  SelectContent,
  SelectField,
  SelectItem,
  SelectScrollDownButton,
  SelectScrollUpButton,
  SelectTrigger,
  SelectValue,
}
export type { SelectOption }
