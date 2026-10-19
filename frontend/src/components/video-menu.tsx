import type { ReactNode } from "react"
import { ContextMenu, ContextMenuTrigger, ContextMenuContent, ContextMenuItem } from "@/components/ui/context-menu"
import { actions, lockedDuringScan, type Action } from "@/bridge"

export function VideoMenu({ id, scanning, onAction, children }: { id: number; scanning: boolean; onAction: (action: Action, id: number) => void; children: ReactNode }) {
  return <ContextMenu>
    <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
    <ContextMenuContent>
      {actions.map(([name, title]) =>
        <ContextMenuItem key={name} variant={name === "exclude" ? "destructive" : "default"} disabled={scanning && lockedDuringScan(name)} onSelect={() => onAction(name, id)}>{title}</ContextMenuItem>)}
    </ContextMenuContent>
  </ContextMenu>
}
