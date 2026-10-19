import { useId, useLayoutEffect, useRef, useState } from "react"
import { cva } from "class-variance-authority"
import { Check, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { tagNameKey } from "@/lib/tag-name-key"
import { tagChoices } from "@/lib/tag-search"
import type { TagUsageData } from "@/bridge-types"

// 여러 개 고름: 고른 태그를 다시 고르면 뺀다. 즉시 실행: 고를 때마다 onPick을 부른다.
// onCreate가 있으면 이름이 같은 태그가 없는 입력을 Enter나 '새 태그로 붙이기'로 넘기고, 성공하면 검색어를 지운다.
type Choice =
  | { mode: "multiple"; selected: readonly number[]; onChange: (ids: number[]) => void; chips?: boolean }
  | { mode: "immediate"; onPick: (tag: TagUsageData) => void; onCreate?: (name: string) => Promise<boolean> }

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

// listAll이면 입력이 없을 때 자주 쓴 태그 대신 전체를 자체 스크롤 행 목록으로 늘 펼친다('모두 보기' 없음).
export function TagPicker({ tags, label, exclude = [], emptyText = "등록한 태그가 없습니다.", listAll = false, ...choice }: Choice & {
  tags: TagUsageData[]; label: string; exclude?: readonly number[]; emptyText?: string; listAll?: boolean
}) {
  const id = useId()
  const [query, setQuery] = useState("")
  const [showAll, setShowAll] = useState(false)
  const [activeId, setActiveId] = useState<number | null>(null)
  const composing = useRef(false)
  const input = useRef<HTMLInputElement>(null)
  const multiple = choice.mode === "multiple"
  const selected = multiple ? choice.selected : []
  // 고른 직후 다시 그리기 전에 다음 고르기가 와도 방금 바꾼 선택에 더한다. 그린 뒤에는 쓰는 쪽의 값을 따른다.
  const latestSelected = useRef(selected)
  useLayoutEffect(() => { latestSelected.current = selected })
  const key = tagNameKey(query)
  const choices = tagChoices(tags, key, showAll || listAll, exclude)
  const active = choices.findIndex(tag => tag.id === activeId)
  const available = exclude.length ? tags.filter(tag => !exclude.includes(tag.id)).length : tags.length
  const searching = !!key
  const onCreate = choice.mode === "immediate" ? choice.onCreate : undefined
  const creatable = searching && !tags.some(tag => tag.key === key)
  const listId = `${id}-list`, statusId = `${id}-status`
  const optionId = (tag: TagUsageData) => `${id}-tag-${tag.id}`
  const chipId = (tag: TagUsageData) => `${id}-chip-${tag.id}`

  function changeQuery(value: string) {
    setQuery(value)
    setActiveId(null)
  }
  function toggle(tag: TagUsageData) {
    if (choice.mode === "immediate") return choice.onPick(tag)
    const current = latestSelected.current
    latestSelected.current = current.includes(tag.id) ? current.filter(other => other !== tag.id) : [...current, tag.id]
    choice.onChange([...latestSelected.current])
  }
  // 목록에서 고르면 검색어를 지운다. 칩 ×는 검색어를 두고 포커스를 다음 칩(없으면 검색 입력)으로 옮긴다.
  function pick(tag: TagUsageData) {
    toggle(tag)
    if (query) changeQuery("")
  }
  async function create() {
    if (onCreate && creatable && await onCreate(query.trim())) {
      changeQuery("")
      input.current?.focus()
    }
  }
  function unchip(index: number) {
    const next = chips[index + 1]
    toggle(chips[index])
    const target = next ? document.getElementById(chipId(next)) : input.current
    target?.focus()
  }
  function move(step: number) {
    if (!choices.length) return
    const next = choices[((active < 0 ? (step > 0 ? -1 : choices.length) : active) + step + choices.length) % choices.length]
    setActiveId(next.id)
    document.getElementById(optionId(next))?.scrollIntoView({ block: "nearest" })
  }

  const chips = choice.mode === "multiple" && choice.chips ? selected.flatMap(tagId => tags.filter(tag => tag.id === tagId)) : []
  const layout = searching || showAll || listAll ? "row" : "chip"
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
    {/* 새 태그 버튼은 입력 옆에 늘 두고, 만들 이름이 있을 때만 켠다. */}
    <div className="flex gap-2">
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
            // 활성 후보가 없으면 이름의 key가 질의 key와 같은 태그만 고른다. 그런 태그가 아예 없으면 새로 만든다.
            const target = active >= 0 ? choices[active] : key ? choices.find(tag => tag.key === key) : undefined
            if (target) pick(target)
            else void create()
          }
        }} />
      {onCreate && <Button variant="outline" className="shrink-0" disabled={!creatable} onClick={() => void create()}>새 태그로 붙이기</Button>}
    </div>
    {available <= 0 ? <p id={statusId} className="text-xs text-muted-foreground">{emptyText}</p>
      : !choices.length ? <p id={statusId} className="text-xs wrap-anywhere text-muted-foreground">‘{query.trim()}’이(가) 들어간 태그가 없습니다.</p>
      : <div id={listId} role="listbox" aria-label={searching ? `${label} 검색 결과` : showAll || listAll ? `모든 ${label}` : `자주 쓴 ${label}`} aria-multiselectable={multiple || undefined}
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
    {!searching && !listAll && (showAll || choices.length < available) && <Button variant="link" size="xs" aria-expanded={showAll} aria-controls={listId} onClick={() => setShowAll(!showAll)}>
      {showAll ? "자주 쓴 태그만 보기" : `모두 보기 (${available}개)`}</Button>}
  </div>
}
