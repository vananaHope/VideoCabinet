import { Fragment } from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Popover } from "radix-ui"
import { SlidersHorizontal, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { SelectField } from "@/components/ui/select"
import { Input } from "@/components/ui/input"
import { PendingStatus } from "@/components/ui/pending-status"
import { TagPicker } from "@/components/tag-picker"
import { tagPickerKeepsEscape } from "@/lib/tag-search"
import { libraryChoices, libraryFilterDefaults, type LibraryViewOptions, type TagUsageData, type LibraryChip } from "@/bridge-types"
import { formatDate } from "@/lib/dates"

type Change = (value: Partial<LibraryViewOptions>) => void
// inline: 툴바처럼 라벨과 선택 목록이 한 줄에 붙는다. row: 필터 패널의 두 열 격자에서 라벨은 라벨 열, 선택 목록은 값 열에 놓인다.
const choiceVariants = cva("text-label text-muted-foreground", {
  variants: { layout: { inline: "flex min-w-0 items-center gap-2", row: "contents" } },
  defaultVariants: { layout: "inline" },
})
export function LibraryChoice({ name, label, options, disabled, onChange, layout }: { name: keyof typeof libraryChoices; label: string; options: LibraryViewOptions; disabled?: boolean; onChange: Change } & VariantProps<typeof choiceVariants>) {
  return <label className={choiceVariants({ layout })}><span className="shrink-0">{label}</span>
    <SelectField aria-label={label} value={options[name]} options={libraryChoices[name]} disabled={disabled} onValueChange={value => onChange({ [name]: value })} className="max-w-48" />
  </label>
}

export function clearLibraryFilters(options: LibraryViewOptions): LibraryViewOptions {
  return { ...options, ...libraryFilterDefaults, tags: [...libraryFilterDefaults.tags] }
}

const dateFilters = [['added', '추가일'], ['modified', '수정한 날짜'], ['viewed', '마지막 시청']] as const
/**
 * 필터 패널. 라벨 열과 값 열이 줄마다 맞는 두 열 격자이고, 높이는 화면에 남은 높이(가장자리 1rem)까지 쓴다.
 * 머리 줄과 "조건 모두 지우기" 줄은 고정이고 그 사이 조건만 패널 안에서 스크롤하므로, 내용이 잘린 채로 보이지 않는다.
 */
export function LibraryFilters({ options, tags, disabled, onChange }: { options: LibraryViewOptions; tags: TagUsageData[]; disabled?: boolean; onChange: Change }) {
  return <Popover.Root><Popover.Trigger asChild><Button variant="outline" size="sm" disabled={disabled}><SlidersHorizontal />필터</Button></Popover.Trigger>
    <Popover.Portal><Popover.Content aria-label="라이브러리 필터 패널" align="end" sideOffset={8} collisionPadding={16} onEscapeKeyDown={event => { if (tagPickerKeepsEscape(event)) event.preventDefault() }}
      className="z-50 flex max-h-(--radix-popover-content-available-height) w-128 origin-(--radix-popover-content-transform-origin) animate-layer-enter flex-col overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-lg">
      <div className="flex shrink-0 items-center justify-between px-4 pt-4 pb-3"><h2 className="text-body-strong">검색 조건</h2><Popover.Close asChild><Button size="icon-xs" variant="ghost" aria-label="필터 닫기"><X /></Button></Popover.Close></div>
      <div className="definition-list min-h-0 flex-1 items-center gap-x-4 gap-y-3 overflow-y-auto px-4 pb-4">
        <LibraryChoice layout="row" name="viewing" label="시청 상태" options={options} onChange={onChange} />
        <LibraryChoice layout="row" name="original" label="원어" options={options} onChange={onChange} />
        <LibraryChoice layout="row" name="translated" label="번역·다듬기" options={options} onChange={onChange} />
        {dateFilters.map(([prefix, label]) => <Fragment key={prefix}>
          <LibraryChoice layout="row" name={`${prefix}_preset`} label={label} options={options} onChange={onChange} />
          {options[`${prefix}_preset`] === "custom" && <div className="col-start-2 flex items-center gap-2">
            <Input type="date" aria-label={`${label} 시작`} value={options[`${prefix}_from`]} onChange={e => onChange({ [`${prefix}_from`]: e.target.value })} />
            <span>~</span><Input type="date" aria-label={`${label} 끝`} value={options[`${prefix}_to`]} onChange={e => onChange({ [`${prefix}_to`]: e.target.value })} />
          </div>}
        </Fragment>)}
        <span id="library-filter-flags" className="text-label text-muted-foreground">그 밖의 조건</span>
        <div role="group" aria-labelledby="library-filter-flags" className="flex flex-wrap gap-2">{([['external', '외부 자막 있음'], ['highlights', '하이라이트 있음'], ['missing', '파일 없음만']] as const).map(([key, label]) =>
          <Button key={key} size="sm" variant={options[key] ? "default" : "outline"} aria-pressed={options[key]} onClick={() => onChange({ [key]: !options[key] })}>{label}</Button>)}</div>
        <fieldset className="col-span-2 min-w-0 space-y-2"><legend className="text-label text-muted-foreground">태그 · 모두 포함(AND)</legend>
          <TagPicker tags={tags} label="태그" mode="multiple" chips selected={options.tags} onChange={ids => onChange({ tags: ids })} />
        </fieldset>
      </div>
      <div className="flex shrink-0 justify-end border-t px-4 py-2"><Button variant="ghost" size="sm" onClick={() => onChange(clearLibraryFilters(options))}>조건 모두 지우기</Button></div>
    </Popover.Content></Popover.Portal>
  </Popover.Root>
}

/** 칩 글자. 직접 지정한 날짜 범위는 날짜 모양을 화면에서 만든다. */
function chipText({ label, range }: LibraryChip) {
  return range ? `${label}: ${range.start ? formatDate(range.start) : "처음"} ~ ${range.end ? formatDate(range.end) : "끝 없음"}` : label
}

/**
 * 적용한 조건 칩 줄. 칩이 없어도 한 줄 높이(위 여백 0.125rem + 칩 높이 1.25rem + 초점 링 + 가로 스크롤바 자리 0.5rem = 2rem)를 늘 차지해, 칩이 생기고 사라져도 아래 목록이 밀리지 않는다.
 * 칩이 많으면 이 한 줄 안에서 가로로 넘긴다. 바꾼 조건의 결과를 오래 기다리면 줄 끝에 공용 기다림 표시를 둔다(칩은 그대로 둔다).
 */
export function LibraryFilterChips({ chips, options, onChange, pending = false }: { chips: LibraryChip[]; options: LibraryViewOptions; onChange: Change; pending?: boolean }) {
  return <div aria-label="적용한 검색 조건" className="flex h-8 shrink-0 items-start gap-2 overflow-x-auto overflow-y-hidden px-0.5 pt-0.5">
    {chips.map(chip => { const text = chipText(chip); return <Chip key={chip.key} asChild interactive><button type="button" title={text} aria-label={`${text} 지우기`} onClick={() => onChange(chip.reset)}><span className="max-w-60 truncate">{text}</span><X /></button></Chip> })}
    {chips.length > 0 && <Chip asChild interactive><button type="button" onClick={() => onChange(clearLibraryFilters(options))}>모두 지우기</button></Chip>}
    <PendingStatus pending={pending} className="ml-auto shrink-0 self-center" />
  </div>
}
