import type { ReactNode } from "react"
import { ContextMenu, ContextMenuTrigger, ContextMenuContent, ContextMenuItem } from "@/components/ui/context-menu"
import { actions, lockedDuringScan, type Action } from "@/bridge"

export function VideoMenu({ id, gem = false, scanning, onAction, children }: { id: number; gem?: boolean; scanning: boolean; onAction: (action: Action, id: number) => void; children: ReactNode }) {
  return <ContextMenu>
    <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
    <ContextMenuContent>
      {gem ? <ContextMenuItem onSelect={() => onAction("dismiss", id)}>관심 없음</ContextMenuItem> : actions.map(([name, title]) =>
        <ContextMenuItem key={name} variant={name === "exclude" ? "destructive" : "default"} disabled={scanning && lockedDuringScan(name)} onSelect={() => onAction(name, id)}>{title}</ContextMenuItem>)}
    </ContextMenuContent>
  </ContextMenu>
}
