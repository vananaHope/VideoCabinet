import { cva } from 'class-variance-authority'
import { Dialog } from 'radix-ui'
import { useRef, type ReactNode } from 'react'
import type { DialogRow } from '@/bridge-types'

export function DialogFrame({ title, description, children, onClose, composing }: { title: string; description: string; children: ReactNode; onClose: () => void; composing: { current: boolean } }) {
  return <Dialog.Root open onOpenChange={open => { if (!open) onClose() }}><Dialog.Portal>
    <Dialog.Overlay className="fixed inset-0 z-40 bg-background/80" />
    <Dialog.Content className="fixed inset-4 z-40 m-auto flex h-fit max-h-full w-auto max-w-4xl flex-col gap-4 overflow-auto rounded-xl border bg-popover p-6 text-popover-foreground shadow-lg"
      onInteractOutside={event => event.preventDefault()}
      onEscapeKeyDown={event => { if (composing.current) event.preventDefault() }}>
      <header className="space-y-2"><Dialog.Title className="text-xl font-semibold">{title}</Dialog.Title>
        <Dialog.Description className="text-sm text-muted-foreground">{description || '입력한 내용을 확인한 뒤 저장하세요.'}</Dialog.Description></header>
      {children}
    </Dialog.Content>
  </Dialog.Portal></Dialog.Root>
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
  return <div className="min-h-0 min-w-0 flex-1">
    <p className="mb-2 text-sm font-medium">{label} · {rows.length}</p>
    <div ref={ref} role="listbox" aria-label={label} tabIndex={0} aria-activedescendant={selected ? `${label}-${selected}` : undefined}
      className="max-h-72 min-h-24 overflow-auto rounded-md border focus-visible:outline-2 focus-visible:outline-ring"
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
          <p className="whitespace-pre-wrap break-all">{row.title}</p><p className="whitespace-pre-wrap break-all text-muted-foreground">{row.detail}</p>
        </div> : <><p className={highlights ? marker({ range: row.end !== null }) : 'break-all font-medium'}>{row.title}</p>
          {row.detail && <p className="line-clamp-3 whitespace-pre-wrap break-all text-muted-foreground" title={row.detail}>{row.detail}</p>}
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
  return <label className="flex flex-col gap-2 text-sm">{label}<select aria-label={label} value={value} onChange={event => onChange(event.target.value)}
    className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-2 focus-visible:outline-ring">
    {rows.map(row => <option key={row.id} value={row.id}>{row.title}</option>)}
  </select></label>
}
