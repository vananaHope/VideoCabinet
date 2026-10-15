import { useEffect, useRef, useState } from 'react'
import type { DialogRow, DialogsBridge } from '@/bridge-types'
import { request } from '@/bridge'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

export function TagEntry({ bridge, add, composing }: { bridge: DialogsBridge; add: (name: string) => Promise<boolean>; composing: { current: boolean } }) {
  const [text, setText] = useState('')
  const [rows, setRows] = useState<DialogRow[]>([])
  const [candidate, setCandidate] = useState<number | null>(null)
  const [open, setOpen] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => {
    let live = true
    request<{ rows: DialogRow[] }>(reply => bridge.candidates(text, reply)).then(result => { if (live) setRows(result.rows) }).catch(() => { if (live) setRows([]) })
    return () => { live = false }
  }, [bridge, text])
  async function submit(name: string) {
    if (!name.trim() || composing.current) return
    if (await add(name)) { setText(''); setCandidate(null); setOpen(false); input.current?.focus() }
  }
  return <div className="space-y-2"><div className="flex gap-2">
    <Input ref={input} aria-label="태그 이름" role="combobox" aria-expanded={open && rows.length > 0} aria-controls="tag-candidates"
      aria-activedescendant={candidate !== null && open ? `tag-candidate-${candidate}` : undefined} aria-autocomplete="list"
      placeholder="새 태그 또는 기존 태그 이름" value={text} onChange={event => { setText(event.target.value); setCandidate(null); setOpen(true) }}
      onBlur={() => setOpen(false)} onKeyDown={event => {
        if (composing.current || event.nativeEvent.isComposing || event.keyCode === 229) return
        const keys = ['ArrowDown', 'ArrowUp', 'PageDown', 'PageUp', 'Home', 'End']
        if (keys.includes(event.key) && (open || event.key === 'ArrowDown') && rows.length) {
          event.preventDefault(); setOpen(true)
          let next = candidate ?? (event.key === 'ArrowUp' ? rows.length : -1)
          if (event.key === 'Home') next = 0
          else if (event.key === 'End') next = rows.length - 1
          else if (event.key === 'PageDown' || event.key === 'PageUp') next = Math.max(0, Math.min(rows.length - 1, (candidate ?? 0) + (event.key === 'PageDown' ? 5 : -5)))
          else next = (next + (event.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length
          setCandidate(next)
          document.getElementById(`tag-candidate-${next}`)?.scrollIntoView({ block: 'nearest' })
        } else if (event.key === 'Enter') {
          event.preventDefault(); event.stopPropagation(); void submit(open && candidate !== null ? rows[candidate].title : text)
        } else if (event.key === 'Escape' && open) { event.preventDefault(); event.stopPropagation(); setOpen(false); setCandidate(null) }
      }} />
    <Button onClick={() => void submit(text)}>추가</Button>
  </div>
    {open && rows.length > 0 && <div id="tag-candidates" role="listbox" aria-label="태그 자동 완성" className="max-h-32 overflow-auto rounded-md border bg-popover">
      {rows.map((row, index) => <div key={row.id} id={`tag-candidate-${index}`} role="option" aria-selected={index === candidate}
        className="cursor-default break-words px-3 py-2 text-sm hover:bg-accent aria-selected:bg-accent" onMouseDown={event => event.preventDefault()} onClick={() => void submit(row.title)}>{row.title}</div>)}
    </div>}
  </div>
}
