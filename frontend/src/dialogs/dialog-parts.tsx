import { cva } from 'class-variance-authority'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { DialogRow } from '@/bridge-types'
import { Dialog, DialogContent, DialogHeader } from '@/components/ui/dialog'
import { SelectField } from '@/components/ui/select'
import { tagPickerKeepsEscape } from '@/lib/tag-search'

export function DialogFrame({ title, description, children, onClose, composing, onSize, wide }: { title: string; description: string; children: ReactNode; onClose: () => void; composing: { current: boolean }; onSize: (width: number, height: number) => void; wide: boolean }) {
  const [content, setContent] = useState<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!content) return
    const observer = new ResizeObserver(() => {
      const rect = content.getBoundingClientRect()
      if (rect) onSize(Math.ceil(rect.width), Math.ceil(rect.height))
    })
    observer.observe(content)
    return () => observer.disconnect()
  }, [content, onSize])
  // 재생 중에는 셸이 이 틀을 내용 크기의 창으로 옮긴다(공용 틀의 container 배치). 그 창 크기는 이 틀의 크기를 따른다.
  return <Dialog open onOpenChange={open => { if (!open) onClose() }}>
    <DialogContent ref={setContent} data-dialog-frame size={wide ? 'wide' : 'default'} placement="container"
      onInteractOutside={event => event.preventDefault()}
      onEscapeKeyDown={event => {
        // 태그 고르기가 검색어·활성 후보를 먼저 지울 Esc는 대화상자를 닫지 않는다.
        if (composing.current || tagPickerKeepsEscape(event)) event.preventDefault()
      }}>
      <DialogHeader title={title} description={description || '입력한 내용을 확인한 뒤 저장하세요.'} />
      {children}
    </DialogContent>
  </Dialog>
}

const itemStyle = cva('w-full min-w-0 cursor-default border-b px-3 py-2 text-left text-sm last:border-b-0', {
  variants: { selected: { true: 'bg-accent text-accent-foreground ring-1 ring-inset ring-ring', false: 'hover:bg-muted' } },
})
const marker = cva('font-mono text-xs tabular-nums', { variants: { range: { true: 'text-highlight-range', false: 'text-highlight' } } })

export function DialogList({ label, rows, selected, onSelect, onActivate, review = false, highlights = false, clickActivates = false }: {
  label: string; rows: DialogRow[]; selected: string; onSelect: (id: string) => void; onActivate?: (id: string) => void;
  review?: boolean; highlights?: boolean; clickActivates?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null)
  // 목록은 대화상자 최대 높이 안에서 남는 공간을 쓴다. 재생 중 컨테이너에서는 목록이 창 높이까지 자라 영상을 가리지 않게 상한을 둔다.
  return <div className="flex min-h-0 min-w-0 flex-1 flex-col">
    <p className="mb-2 text-sm font-medium">{label} · {rows.length}</p>
    <div ref={ref} role="listbox" aria-label={label} tabIndex={0} aria-activedescendant={selected ? `${label}-${selected}` : undefined}
      data-dialog-list className="min-h-24 flex-1 overflow-auto rounded-md border focus-visible:outline-2 focus-visible:outline-ring in-data-dialog-container:max-h-(--dialog-list-max-height)"
      onKeyDown={event => {
        if (event.nativeEvent.isComposing || event.keyCode === 229) return
        const index = rows.findIndex(row => row.id === selected)
        const steps: Record<string, number> = { ArrowDown: 1, ArrowUp: -1, PageDown: 8, PageUp: -8, Home: -rows.length, End: rows.length }
        if (event.key in steps && rows.length) {
          event.preventDefault()
          const target = rows[Math.max(0, Math.min(rows.length - 1, index + steps[event.key]))]
          onSelect(target.id)
          document.getElementById(`${label}-${target.id}`)?.scrollIntoView({ block: 'nearest' })
        } else if (event.key === 'Enter' && selected && onActivate) { event.preventDefault(); onActivate(selected) }
      }}>
      {!rows.length && <p className="p-6 text-sm text-muted-foreground">항목이 없습니다.</p>}
      {rows.map(row => <div key={row.id} id={`${label}-${row.id}`} role="option" aria-selected={selected === row.id}
        className={itemStyle({ selected: selected === row.id })} onClick={() => { onSelect(row.id); ref.current?.focus(); if (clickActivates) onActivate?.(row.id) }}
        onDoubleClick={() => { if (!clickActivates) onActivate?.(row.id) }}>
        {review ? <div className="grid grid-cols-2 gap-3">
          <span className="col-span-2 font-mono text-xs tabular-nums">{row.start.toFixed(3)}–{row.end?.toFixed(3)}초 · {row.status}</span>
          <p className="whitespace-pre-wrap break-words">{row.title}</p><p className="whitespace-pre-wrap break-words text-muted-foreground">{row.detail}</p>
        </div> : <><p className={highlights ? marker({ range: row.end !== null }) : 'break-words font-medium'}>{row.title}</p>
          {row.detail && <p className="line-clamp-3 whitespace-pre-wrap break-words text-muted-foreground" title={row.detail}>{row.detail}</p>}
          {row.status && <p className="truncate text-xs text-muted-foreground" title={row.status}>{row.status}</p>}</>}
      </div>)}
    </div>
  </div>
}

export function TextArea({ value, onChange }: { value: string; onChange: (text: string) => void }) {
  return <textarea aria-label="텍스트" className="min-h-28 w-full resize-y rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
    value={value} onChange={event => onChange(event.target.value)} />
}

export function Choice({ label, value, rows, onChange }: { label: string; value: string; rows: DialogRow[]; onChange: (value: string) => void }) {
  return <label className="flex flex-col gap-2 text-sm">{label}
    <SelectField aria-label={label} value={value} options={rows.map(row => [row.id, row.title] as const)} onValueChange={onChange} className="w-full" />
  </label>
}
