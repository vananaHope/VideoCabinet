import type { TagData } from "@/bridge-types"

export function VideoTags({ tags }: { tags: TagData[] }) {
  return <span aria-label="태그" className="flex min-w-0 items-center gap-1" title={tags.map(tag => tag.name).join(", ")}>
    {tags.slice(0, 2).map(tag => <span key={tag.id} className="min-w-0 max-w-24 truncate rounded-md bg-secondary px-2 py-0.5 text-xs text-secondary-foreground">{tag.name}</span>)}
    {tags.length > 2 && <span className="shrink-0 text-xs text-muted-foreground">+{tags.length - 2}</span>}
  </span>
}
