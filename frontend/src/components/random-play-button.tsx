import { useRef, type Ref } from "react"
import { ChevronDown, Dices } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ButtonGroup } from "@/components/ui/button-group"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuShortcut, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"

/** ▾ 메뉴의 범위 항목. 범위마다 하나씩 더한다. 창을 여는 항목(opensDialog)은 메뉴가 닫혀도 ▾로 초점을 되돌리지 않는다. shortcut은 현재 키 배치의 키이며 비면 보이지 않는다. */
export type RandomPlayScope = { key: string; label: string; onSelect: () => void; opensDialog?: boolean; shortcut?: string }

/** '무작위 재생' 버튼과 범위 메뉴(▾)의 묶음. 버튼은 첫 범위로 바로 재생하고, 툴팁에 키가 있는 다른 범위를 함께 알린다. */
export function RandomPlayButton({ scopes, menuRef, disabled }: { scopes: readonly [RandomPlayScope, ...RandomPlayScope[]]; menuRef?: Ref<HTMLButtonElement>; disabled?: boolean }) {
  const dialogOpened = useRef(false)
  const [first] = scopes
  const title = [`무작위 재생 (${first.label})`, ...scopes.filter(scope => scope.shortcut).map(scope => `${scope.label} ${scope.shortcut}`)].join(" · ")
  return <ButtonGroup aria-label="무작위 재생">
    <Button size="sm" variant="outline" title={title} disabled={disabled} onClick={() => first.onSelect()}><Dices aria-hidden="true" />무작위 재생</Button>
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button ref={menuRef} size="icon-sm" variant="outline" aria-label="무작위 재생 범위" title="무작위 재생 범위" disabled={disabled}><ChevronDown aria-hidden="true" /></Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" onCloseAutoFocus={event => { if (dialogOpened.current) event.preventDefault(); dialogOpened.current = false }}>
        {scopes.map(scope => <DropdownMenuItem key={scope.key} textValue={scope.label} aria-label={scope.shortcut ? `${scope.label} · ${scope.shortcut}` : undefined}
          onSelect={() => { dialogOpened.current = !!scope.opensDialog; scope.onSelect() }}>
          {scope.label}{scope.shortcut && <DropdownMenuShortcut>{scope.shortcut}</DropdownMenuShortcut>}
        </DropdownMenuItem>)}
      </DropdownMenuContent>
    </DropdownMenu>
  </ButtonGroup>
}
