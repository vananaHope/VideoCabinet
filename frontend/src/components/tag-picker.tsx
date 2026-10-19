import { useId, useRef, useState } from "react"
import { cva } from "class-variance-authority"
import { Check, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { tagChoices, tagSearchKey } from "@/lib/tag-search"
import type { TagUsageData } from "@/bridge-types"

// 여러 개 고름: 고른 태그를 다시 고르면 뺀다. 즉시 실행: 고를 때마다 onPick을 부른다.
type Choice =
  | { mode: "multiple"; selected: readonly number[]; onChange: (ids: number[]) => void; chips?: boolean }
  | { mode: "immediate"; onPick: (tag: TagUsageData) => void }

const option = cva("flex min-w-0 cursor-default items-center gap-2 text-sm data-active:ring-2 data-active:ring-ring data-active:ring-inset", {
  variants: {
    layout: { chip: "max-w-full rounded-full border px-3 py-1", row: "w-full rounded-md px-3 py-1.5" },
    multiple: {
      true: "hover:bg-accent aria-selected:bg-primary aria-selected:text-primary-foreground",
      false: "hover:bg-accent aria-selected:bg-accent aria-selected:text-accent-foreground",
    },
  },
})
const mark = cva("size-4 shrink-0", { variants: { chosen: { true: "", false: "invisible" } } })
const count = cva("shrink-0 text-xs tabular-nums", { variants: { chosen: { true: "text-primary-foreground", false: "text-muted-foreground" } } })

export function TagPicker({ tags, label, exclude = [], emptyText = "등록한 태그가 없습니다.", ...choice }: Choice & {
  tags: TagUsageData[]; label: string; exclude?: readonly number[]; emptyText?: string
}) {
  const id = useId()
  const [query, setQuery] = useState("")
  const [showAll, setShowAll] = useState(false)
  const [activeId, setActiveId] = useState<number | null>(null)
  const composing = useRef(false)
  const multiple = choice.mode === "multiple"
  const selected = multiple ? choice.selected : []
  const choices = tagChoices(tags, query, showAll, exclude)
  const active = choices.findIndex(tag => tag.id === activeId)
  const available = exclude.length ? tags.filter(tag => !exclude.includes(tag.id)).length : tags.length
  const searching = !!tagSearchKey(query)
  const optionId = (tag: TagUsageData) => `${id}-tag-${tag.id}`

  function pick(tag: TagUsageData) {
    if (choice.mode === "multiple") choice.onChange(choice.selected.includes(tag.id) ? choice.selected.filter(other => other !== tag.id) : [...choice.selected, tag.id])
    else choice.onPick(tag)
    if (query) { setQuery(""); setActiveId(null) }
  }
  function move(step: number) {
    if (!choices.length) return
    const next = choices[((active < 0 ? (step > 0 ? -1 : choices.length) : active) + step + choices.length) % choices.length]
    setActiveId(next.id)
    document.getElementById(optionId(next))?.scrollIntoView({ block: "nearest" })
  }

  const chips = choice.mode === "multiple" && choice.chips ? selected.flatMap(tagId => tags.filter(tag => tag.id === tagId)) : []
  const layout = searching || showAll ? "row" : "chip"
  return <div className="min-w-0 space-y-2">
    {!!chips.length && <div aria-label={`고른 ${label}`} className="flex max-h-16 flex-wrap gap-1 overflow-y-auto">
      {chips.map(tag => <Button key={tag.id} variant="secondary" size="xs" title={tag.name} aria-label={`${tag.name} 빼기`} onClick={() => pick(tag)}><span className="max-w-48 truncate">{tag.name}</span><X /></Button>)}
    </div>}
    <Input role="combobox" aria-label={`${label} 검색`} aria-expanded aria-controls={`${id}-list`} aria-autocomplete="list"
      aria-activedescendant={active >= 0 ? optionId(choices[active]) : undefined} data-keeps-escape={active >= 0 || !!query || showAll}
      placeholder="태그 이름 일부로 찾기" value={query}
      onChange={event => { setQuery(event.target.value); setActiveId(null) }}
      onCompositionStart={() => { composing.current = true }} onCompositionEnd={() => { composing.current = false }}
      onBlur={() => setActiveId(null)}
      onKeyDown={event => {
        if (composing.current || event.nativeEvent.isComposing || event.keyCode === 229) return
        if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); move(event.key === "ArrowDown" ? 1 : -1) }
        else if (event.key === "Enter") {
          event.preventDefault()
          const key = tagSearchKey(query)
          const target = active >= 0 ? choices[active] : choices.find(tag => tag.key === key)
          if (target) pick(target)
        } else if (event.key === "Escape") {
          if (active >= 0) setActiveId(null)
          else if (query) setQuery("")
          else if (showAll) setShowAll(false)
        }
      }} />
    {available <= 0 ? <p className="text-xs text-muted-foreground">{emptyText}</p>
      : !choices.length ? <p className="text-xs text-muted-foreground">‘{query.trim()}’이(가) 들어간 태그가 없습니다.</p>
      : <div id={`${id}-list`} role="listbox" aria-label={searching ? `${label} 검색 결과` : showAll ? `모든 ${label}` : `자주 쓴 ${label}`} aria-multiselectable={multiple || undefined}
        className={layout === "chip" ? "flex flex-wrap gap-1.5" : "max-h-48 space-y-0.5 overflow-y-auto rounded-md border p-1"}>
        {choices.map((tag, index) => {
          const chosen = multiple ? selected.includes(tag.id) : index === active
          return <div key={tag.id} id={optionId(tag)} role="option" aria-selected={chosen} data-active={index === active || undefined} title={tag.name}
            className={option({ layout, multiple })} onMouseDown={event => event.preventDefault()} onClick={() => pick(tag)}>
            {multiple && layout === "row" && <Check aria-hidden className={mark({ chosen })} />}
            <span className="min-w-0 flex-1 truncate">{tag.name}</span>
            <span className={count({ chosen: multiple && chosen })}>{tag.videoCount}</span>
          </div>
        })}
      </div>}
    {!searching && (showAll || choices.length < available) && <Button variant="link" size="xs" aria-expanded={showAll} aria-controls={`${id}-list`} onClick={() => setShowAll(!showAll)}>
      {showAll ? "자주 쓴 태그만 보기" : `모두 보기 (${available}개)`}</Button>}
  </div>
}
