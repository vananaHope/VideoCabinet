import { useState } from "react"
import { Dices } from "lucide-react"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import type { TagData } from "@/bridge-types"

export function VideoTags({ tags }: { tags: TagData[] }) {
  return <span aria-label="태그" className="flex min-w-0 items-center gap-1" title={tags.map(tag => tag.name).join(", ")}>
    {tags.slice(0, 2).map(tag => <span key={tag.id} className="min-w-0 max-w-24 truncate rounded-md bg-secondary px-2 py-0.5 text-xs text-secondary-foreground">{tag.name}</span>)}
    {tags.length > 2 && <span className="shrink-0 text-xs text-muted-foreground">+{tags.length - 2}</span>}
  </span>
}

/** 상세 패널의 태그 칩. 클릭·우클릭·메뉴 키로 태그 메뉴를 연다. */
export function TagMenuChips({ tags, onRandomPlay }: { tags: TagData[]; onRandomPlay: (tagId: number) => void }) {
  return <div role="group" aria-label="태그" className="flex flex-wrap items-center gap-1">
    <span>태그:</span>
    {tags.length ? tags.map(tag => <TagMenuChip key={tag.id} tag={tag} onRandomPlay={onRandomPlay} />) : <span>없음</span>}
  </div>
}

function TagMenuChip({ tag, onRandomPlay }: { tag: TagData; onRandomPlay: (tagId: number) => void }) {
  const [open, setOpen] = useState(false)
  return <DropdownMenu open={open} onOpenChange={setOpen}>
    <DropdownMenuTrigger asChild>
      <Button variant="secondary" size="xs" title={tag.name} onContextMenu={event => { event.preventDefault(); setOpen(true) }}>
        <span className="max-w-48 truncate">{tag.name}</span>
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="start">
      <DropdownMenuItem onSelect={() => onRandomPlay(tag.id)}><Dices aria-hidden="true" />이 태그에서 무작위 재생</DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
}
