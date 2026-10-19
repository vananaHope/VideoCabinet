import { useId, useRef, useState } from "react"
import { cva } from "class-variance-authority"
import { Check, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { getTagSearchKey } from "@/bridge"
import { tagChoices } from "@/lib/tag-search"
import type { TagUsageData } from "@/bridge-types"

// 여러 개 고름: 고른 태그를 다시 고르면 뺀다. 즉시 실행: 고를 때마다 onPick을 부른다.
type Choice =
  | { mode: "multiple"; selected: readonly number[]; onChange: (ids: number[]) => void; chips?: boolean }
  | { mode: "immediate"; onPick: (tag: TagUsageData) => void }
type Searched = { query: string; key: string }
const NOT_SEARCHED: Searched = { query: "", key: "" }

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
  // 질의 key는 코어가 만든다. 지금 질의보다 늦게 온 옛 응답은 버린다.
  const [searched, setSearched] = useState(NOT_SEARCHED)
  const latest = useRef("")
  const [showAll, setShowAll] = useState(false)
  const [activeId, setActiveId] = useState<number | null>(null)
  const composing = useRef(false)
  const input = useRef<HTMLInputElement>(null)
  const multiple = choice.mode === "multiple"
  const selected = multiple ? choice.selected : []
  const key = query ? searched.key : ""
  const choices = tagChoices(tags, key, showAll, exclude)
  const active = choices.findIndex(tag => tag.id === activeId)
  const available = exclude.length ? tags.filter(tag => !exclude.includes(tag.id)).length : tags.length
  const searching = !!key
  const listId = `${id}-list`, statusId = `${id}-status`
  const optionId = (tag: TagUsageData) => `${id}-tag-${tag.id}`
  const chipId = (tag: TagUsageData) => `${id}-chip-${tag.id}`

  function changeQuery(value: string) {
    latest.current = value
    setQuery(value)
    setActiveId(null)
    if (!value) setSearched(NOT_SEARCHED)
    else getTagSearchKey(value).then(key => { if (latest.current === value) setSearched({ query: value, key }) }).catch(console.error)
  }
  function toggle(tag: TagUsageData) {
    if (choice.mode === "multiple") choice.onChange(choice.selected.includes(tag.id) ? choice.selected.filter(other => other !== tag.id) : [...choice.selected, tag.id])
    else choice.onPick(tag)
  }
  // 목록에서 고르면 검색어를 지운다. 칩 ×는 검색어를 두고 포커스를 다음 칩(없으면 검색 입력)으로 옮긴다.
  function pick(tag: TagUsageData) {
    toggle(tag)
    if (query) changeQuery("")
  }
  function unchip(index: number) {
    const next = chips[index + 1]
    toggle(chips[index])
    const target = next ? document.getElementById(chipId(next)) : input.current
    target?.focus()
  }
  // 활성 후보가 없는 Enter는 이름의 key가 질의 key와 같은 태그만 고른다.
  function pickExact(text: string) {
    const exact = (key: string) => tags.find(tag => tag.key === key && !exclude.includes(tag.id))
    if (searched.query === text) {
      const target = exact(searched.key)
      if (target) pick(target)
    } else getTagSearchKey(text).then(key => {
      const target = exact(key)
      if (target && latest.current === text) pick(target)
    }).catch(console.error)
  }
  function move(step: number) {
    if (!choices.length) return
    const next = choices[((active < 0 ? (step > 0 ? -1 : choices.length) : active) + step + choices.length) % choices.length]
    setActiveId(next.id)
    document.getElementById(optionId(next))?.scrollIntoView({ block: "nearest" })
  }

  const chips = choice.mode === "multiple" && choice.chips ? selected.flatMap(tagId => tags.filter(tag => tag.id === tagId)) : []
  const layout = searching || showAll ? "row" : "chip"
  // Esc는 포커스가 칩·입력·모두 보기 어디에 있든 활성 후보 → 검색어 → 모두 보기 순으로 먼저 처리한다.
  return <div className="min-w-0 space-y-2" data-keeps-escape={active >= 0 || !!query || showAll} onKeyDown={event => {
    if (event.key !== "Escape" || composing.current || event.nativeEvent.isComposing || event.keyCode === 229) return
    if (active >= 0) setActiveId(null)
    else if (query) changeQuery("")
    else if (showAll) setShowAll(false)
  }}>
    {!!chips.length && <div role="group" aria-label={`고른 ${label}`} className="flex max-h-16 flex-wrap gap-1 overflow-y-auto">
      {chips.map((tag, index) => <Button key={tag.id} id={chipId(tag)} variant="secondary" size="xs" title={tag.name} aria-label={`${tag.name} 빼기`} onClick={() => unchip(index)}><span className="max-w-48 truncate">{tag.name}</span><X /></Button>)}
    </div>}
    <Input ref={input} role="combobox" aria-label={`${label} 검색`} aria-expanded={!!choices.length} aria-controls={choices.length ? listId : undefined}
      aria-describedby={choices.length ? undefined : statusId} aria-autocomplete="list"
      aria-activedescendant={active >= 0 ? optionId(choices[active]) : undefined}
      placeholder="태그 이름 일부로 찾기" value={query}
      onChange={event => changeQuery(event.target.value)}
      onCompositionStart={() => { composing.current = true }}
      // Windows IME는 조합을 확정한 Enter의 keydown을 compositionend 뒤에 보낼 수 있다. 한 틱 뒤에 푼다.
      onCompositionEnd={() => { setTimeout(() => { composing.current = false }, 0) }}
      onBlur={() => setActiveId(null)}
      onKeyDown={event => {
        if (composing.current || event.nativeEvent.isComposing || event.keyCode === 229) return
        if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); move(event.key === "ArrowDown" ? 1 : -1) }
        else if (event.key === "Enter") {
          event.preventDefault()
          if (active >= 0) pick(choices[active])
          else pickExact(query)
        }
      }} />
    {available <= 0 ? <p id={statusId} className="text-xs text-muted-foreground">{emptyText}</p>
      : !choices.length ? <p id={statusId} className="text-xs wrap-anywhere text-muted-foreground">‘{query.trim()}’이(가) 들어간 태그가 없습니다.</p>
      : <div id={listId} role="listbox" aria-label={searching ? `${label} 검색 결과` : showAll ? `모든 ${label}` : `자주 쓴 ${label}`} aria-multiselectable={multiple || undefined}
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
    {!searching && (showAll || choices.length < available) && <Button variant="link" size="xs" aria-expanded={showAll} aria-controls={listId} onClick={() => setShowAll(!showAll)}>
      {showAll ? "자주 쓴 태그만 보기" : `모두 보기 (${available}개)`}</Button>}
  </div>
}
