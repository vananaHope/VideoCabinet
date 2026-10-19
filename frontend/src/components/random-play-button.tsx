import { useRef, type Ref } from "react"
import { ChevronDown, Dices } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ButtonGroup } from "@/components/ui/button-group"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"

/** ▾ 메뉴의 범위 항목. 범위마다 하나씩 더한다. 창을 여는 항목(opensDialog)은 메뉴가 닫혀도 ▾로 초점을 되돌리지 않는다. */
export type RandomPlayScope = { key: string; label: string; onSelect: () => void; opensDialog?: boolean }

/** '무작위 재생' 버튼과 범위 메뉴(▾)의 묶음. 버튼은 첫 범위로 바로 재생한다. */
export function RandomPlayButton({ scopes, menuRef }: { scopes: readonly [RandomPlayScope, ...RandomPlayScope[]]; menuRef?: Ref<HTMLButtonElement> }) {
  const dialogOpened = useRef(false)
  return <ButtonGroup aria-label="무작위 재생">
    <Button size="sm" variant="outline" title={`무작위 재생 (${scopes[0].label})`} onClick={() => scopes[0].onSelect()}><Dices aria-hidden="true" />무작위 재생</Button>
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button ref={menuRef} size="icon-sm" variant="outline" aria-label="무작위 재생 범위" title="무작위 재생 범위"><ChevronDown aria-hidden="true" /></Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" onCloseAutoFocus={event => { if (dialogOpened.current) event.preventDefault(); dialogOpened.current = false }}>
        {scopes.map(scope => <DropdownMenuItem key={scope.key} onSelect={() => { dialogOpened.current = !!scope.opensDialog; scope.onSelect() }}>{scope.label}</DropdownMenuItem>)}
      </DropdownMenuContent>
    </DropdownMenu>
  </ButtonGroup>
}
