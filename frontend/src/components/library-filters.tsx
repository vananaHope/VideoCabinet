import { Popover } from "radix-ui"
import { SlidersHorizontal, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { SelectField } from "@/components/ui/select"
import { Input } from "@/components/ui/input"
import { TagPicker } from "@/components/tag-picker"
import { tagPickerKeepsEscape } from "@/lib/tag-search"
import { libraryChoices, libraryFilterDefaults, type LibraryViewOptions, type TagUsageData, type LibraryChip } from "@/bridge-types"

type Change = (value: Partial<LibraryViewOptions>) => void
export function LibraryChoice({ name, label, options, onChange }: { name: keyof typeof libraryChoices; label: string; options: LibraryViewOptions; onChange: Change }) {
  return <label className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground"><span className="shrink-0">{label}</span>
    <SelectField aria-label={label} value={options[name]} options={libraryChoices[name]} onValueChange={value => onChange({ [name]: value })} className="max-w-48" />
  </label>
}

export function clearLibraryFilters(options: LibraryViewOptions): LibraryViewOptions {
  return { ...options, ...libraryFilterDefaults, tags: [...libraryFilterDefaults.tags] }
}

const dateFilters = [['added', '추가일'], ['modified', '수정한 날짜'], ['viewed', '마지막 시청']] as const
export function LibraryFilters({ options, tags, onChange }: { options: LibraryViewOptions; tags: TagUsageData[]; onChange: Change }) {
  return <Popover.Root><Popover.Trigger asChild><Button variant="outline" size="sm"><SlidersHorizontal />필터</Button></Popover.Trigger>
    <Popover.Portal><Popover.Content aria-label="라이브러리 필터 패널" align="end" sideOffset={8} onEscapeKeyDown={event => { if (tagPickerKeepsEscape(event)) event.preventDefault() }}
      className="z-50 max-h-112 w-128 overflow-y-auto rounded-xl border bg-popover p-4 text-popover-foreground shadow-lg">
      <div className="mb-3 flex items-center justify-between"><h2 className="font-semibold">검색 조건</h2><Popover.Close asChild><Button size="icon-xs" variant="ghost" aria-label="필터 닫기"><X /></Button></Popover.Close></div>
      <div className="grid grid-cols-2 gap-3">
        <LibraryChoice name="viewing" label="시청 상태" options={options} onChange={onChange} />
        <LibraryChoice name="original" label="원어" options={options} onChange={onChange} />
        <div className="col-span-2"><LibraryChoice name="translated" label="번역·다듬기" options={options} onChange={onChange} /></div>
        <div className="col-span-2 flex flex-wrap gap-2">{([['external', '외부 자막 있음'], ['highlights', '하이라이트 있음'], ['missing', '파일 없음만']] as const).map(([key, label]) =>
          <Button key={key} size="sm" variant={options[key] ? "default" : "outline"} aria-pressed={options[key]} onClick={() => onChange({ [key]: !options[key] })}>{label}</Button>)}</div>
        {dateFilters.map(([prefix, label]) => <div key={prefix} className="col-span-2 space-y-2">
          <LibraryChoice name={`${prefix}_preset`} label={label} options={options} onChange={onChange} />
          {options[`${prefix}_preset`] === "custom" && <div className="flex items-center gap-2">
            <Input type="date" aria-label={`${label} 시작`} value={options[`${prefix}_from`]} onChange={e => onChange({ [`${prefix}_from`]: e.target.value })} />
            <span>~</span><Input type="date" aria-label={`${label} 끝`} value={options[`${prefix}_to`]} onChange={e => onChange({ [`${prefix}_to`]: e.target.value })} />
          </div>}
        </div>)}
        <fieldset className="col-span-2 min-w-0 space-y-2"><legend className="text-xs text-muted-foreground">태그 · 모두 포함(AND)</legend>
          <TagPicker tags={tags} label="태그" mode="multiple" chips selected={options.tags} onChange={ids => onChange({ tags: ids })} />
        </fieldset>
      </div>
      <div className="mt-3 flex justify-end"><Button variant="ghost" size="sm" onClick={() => onChange(clearLibraryFilters(options))}>조건 모두 지우기</Button></div>
    </Popover.Content></Popover.Portal>
  </Popover.Root>
}

export function LibraryFilterChips({ chips, options, onChange }: { chips: LibraryChip[]; options: LibraryViewOptions; onChange: Change }) {
  if (!chips.length) return null
  return <div aria-label="적용한 검색 조건" className="flex shrink-0 items-center gap-2 overflow-x-auto pb-1">
    {chips.map(chip => <Button key={chip.key} variant="secondary" size="xs" title={chip.label} aria-label={`${chip.label} 지우기`} onClick={() => onChange(chip.reset)}><span className="max-w-60 truncate">{chip.label}</span><X /></Button>)}
    <Button variant="ghost" size="xs" onClick={() => onChange(clearLibraryFilters(options))}>모두 지우기</Button>
  </div>
}
