import { useMemo, useState, type KeyboardEvent, type CSSProperties } from "react"
import { ChevronDown, ChevronRight, Folder } from "lucide-react"
import { cva } from "class-variance-authority"
import type { LibraryFolder } from "@/bridge-types"

const row = cva("folder-tree-row flex w-full min-w-0 items-center gap-1 rounded-md py-2 pr-2 text-left text-xs", {
  variants: { selected: { true: "bg-accent text-accent-foreground", false: "text-muted-foreground hover:bg-muted" } },
})
export function LibraryFolders({ folders, selected, onSelect }: { folders: LibraryFolder[]; selected: string; onSelect: (id: string) => void }) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const all = useMemo(() => [{ id: '', parent: '', name: '모든 폴더', path: '모든 폴더', count: 0, depth: -1 }, ...folders], [folders])
  const positions = useMemo(() => new Map(all.map((node, index) => [node.id, index])), [all])
  const visible = useMemo(() => {
    const hidden = new Set<string>()
    return all.filter(node => {
      if (node.parent && (collapsed.has(node.parent) || hidden.has(node.parent))) { hidden.add(node.id); return false }
      return true
    })
  }, [all, collapsed])
  const parents = useMemo(() => new Set(folders.filter(n => n.parent).map(n => n.parent)), [folders])
  function toggle(id: string, collapse: boolean) {
    if (collapse) {
      let node = all.find(n => n.id === selected)
      while (node?.parent) {
        if (node.parent === id) { onSelect(id); break }
        node = all.find(n => n.id === node?.parent)
      }
    }
    setCollapsed(previous => { const next = new Set(previous); if (collapse) next.add(id); else next.delete(id); return next })
  }
  function choose(id: string) {
    onSelect(id)
    requestAnimationFrame(() => document.getElementById(`folder-${positions.get(id)}`)?.scrollIntoView({ block: 'nearest' }))
  }
  function keyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.altKey || event.ctrlKey || event.metaKey || event.nativeEvent.isComposing) return
    const index = Math.max(0, visible.findIndex(node => node.id === selected))
    const node = visible[index]
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      choose(visible[Math.max(0, Math.min(visible.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)))].id)
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault()
      if (parents.has(node.id) && !collapsed.has(node.id)) toggle(node.id, true)
      else choose(node.parent)
    } else if (event.key === 'ArrowRight') {
      event.preventDefault()
      if (parents.has(node.id)) {
        if (collapsed.has(node.id)) toggle(node.id, false)
        else choose(visible[index + 1].id)
      }
    } else if (event.key === 'Enter' || (event.key === 'Tab' && !event.shiftKey)) {
      event.preventDefault()
      document.getElementById('library-grid')?.focus()
    }
  }
  return <aside className="flex w-48 shrink-0 flex-col gap-2 rounded-lg border p-2">
    <h2 className="text-xs font-semibold">폴더 · 하위 폴더 포함</h2>
    <div id="library-folders" role="tree" aria-label="라이브러리 폴더" aria-activedescendant={`folder-${positions.get(selected)}`} tabIndex={0} onKeyDown={keyDown} className="min-h-0 flex-1 overflow-y-auto rounded-md focus-visible:outline-2 focus-visible:outline-ring">
      {visible.map(node => <button id={`folder-${positions.get(node.id)}`} key={node.id} role="treeitem" aria-level={Math.max(1, node.depth + 1)} aria-selected={selected === node.id} aria-expanded={parents.has(node.id) ? !collapsed.has(node.id) : undefined} tabIndex={-1}
        className={row({ selected: selected === node.id })} style={{ '--folder-depth': Math.min(Math.max(0, node.depth), 5) } as CSSProperties} title={node.path}
        onClick={e => { choose(node.id); e.currentTarget.closest<HTMLElement>('[role="tree"]')?.focus() }} onDoubleClick={() => toggle(node.id, !collapsed.has(node.id))}>
        {parents.has(node.id) ? <span onClick={e => { e.stopPropagation(); toggle(node.id, !collapsed.has(node.id)) }}>{collapsed.has(node.id) ? <ChevronRight className="size-3" /> : <ChevronDown className="size-3" />}</span> : <Folder className="size-3 shrink-0" />}
        <span className="min-w-0 flex-1 truncate">{node.name}</span>{node.id && <span className="shrink-0 tabular-nums">{node.count}</span>}
      </button>)}
    </div>
    <p className="text-xs text-muted-foreground">↑↓ 이동 · ←→ 접기/펴기<br />Enter·Tab 영상 격자</p>
  </aside>
}
