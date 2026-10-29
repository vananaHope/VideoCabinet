import { Popover } from "radix-ui"
import { SlidersHorizontal, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { SelectField } from "@/components/ui/select"
import { Input } from "@/components/ui/input"
import { PendingStatus } from "@/components/ui/pending-status"
import { TagPicker } from "@/components/tag-picker"
import { tagPickerKeepsEscape } from "@/lib/tag-search"
import { libraryChoices, libraryFilterDefaults, type LibraryViewOptions, type TagUsageData, type LibraryChip } from "@/bridge-types"
import { formatDate } from "@/lib/dates"

type Change = (value: Partial<LibraryViewOptions>) => void
export function LibraryChoice({ name, label, options, disabled, onChange }: { name: keyof typeof libraryChoices; label: string; options: LibraryViewOptions; disabled?: boolean; onChange: Change }) {
  return <label className="flex min-w-0 items-center gap-2 text-label text-muted-foreground"><span className="shrink-0">{label}</span>
    <SelectField aria-label={label} value={options[name]} options={libraryChoices[name]} disabled={disabled} onValueChange={value => onChange({ [name]: value })} className="max-w-48" />
  </label>
}

export function clearLibraryFilters(options: LibraryViewOptions): LibraryViewOptions {
  return { ...options, ...libraryFilterDefaults, tags: [...libraryFilterDefaults.tags] }
}

const dateFilters = [['added', '추가일'], ['modified', '수정한 날짜'], ['viewed', '마지막 시청']] as const
export function LibraryFilters({ options, tags, disabled, onChange }: { options: LibraryViewOptions; tags: TagUsageData[]; disabled?: boolean; onChange: Change }) {
  return <Popover.Root><Popover.Trigger asChild><Button variant="outline" size="sm" disabled={disabled}><SlidersHorizontal />필터</Button></Popover.Trigger>
    <Popover.Portal><Popover.Content aria-label="라이브러리 필터 패널" align="end" sideOffset={8} onEscapeKeyDown={event => { if (tagPickerKeepsEscape(event)) event.preventDefault() }}
      className="z-50 max-h-112 w-128 origin-(--radix-popover-content-transform-origin) animate-layer-enter overflow-y-auto rounded-xl border bg-popover p-4 text-popover-foreground shadow-lg">
      <div className="mb-3 flex items-center justify-between"><h2 className="text-body-strong">검색 조건</h2><Popover.Close asChild><Button size="icon-xs" variant="ghost" aria-label="필터 닫기"><X /></Button></Popover.Close></div>
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
        <fieldset className="col-span-2 min-w-0 space-y-2"><legend className="text-label text-muted-foreground">태그 · 모두 포함(AND)</legend>
          <TagPicker tags={tags} label="태그" mode="multiple" chips selected={options.tags} onChange={ids => onChange({ tags: ids })} />
        </fieldset>
      </div>
      <div className="mt-3 flex justify-end"><Button variant="ghost" size="sm" onClick={() => onChange(clearLibraryFilters(options))}>조건 모두 지우기</Button></div>
    </Popover.Content></Popover.Portal>
  </Popover.Root>
}

/** 칩 글자. 직접 지정한 날짜 범위는 날짜 모양을 화면에서 만든다. */
function chipText({ label, range }: LibraryChip) {
  return range ? `${label}: ${range.start ? formatDate(range.start) : "처음"} ~ ${range.end ? formatDate(range.end) : "끝 없음"}` : label
}

/**
 * 적용한 조건 칩 줄. 칩이 없어도 한 줄 높이(칩 높이 + 초점 링 + 가로 스크롤바 자리)를 늘 차지해, 칩이 생기고 사라져도 아래 목록이 밀리지 않는다.
 * 칩이 많으면 이 한 줄 안에서 가로로 넘긴다. 바꾼 조건의 결과를 오래 기다리면 줄 끝에 공용 기다림 표시를 둔다(칩은 그대로 둔다).
 */
export function LibraryFilterChips({ chips, options, onChange, pending = false }: { chips: LibraryChip[]; options: LibraryViewOptions; onChange: Change; pending?: boolean }) {
  return <div aria-label="적용한 검색 조건" className="flex h-9 shrink-0 items-start gap-2 overflow-x-auto overflow-y-hidden px-0.5 pt-0.5">
    {chips.map(chip => { const text = chipText(chip); return <Button key={chip.key} variant="secondary" size="xs" title={text} aria-label={`${text} 지우기`} onClick={() => onChange(chip.reset)}><span className="max-w-60 truncate">{text}</span><X /></Button> })}
    {chips.length > 0 && <Button variant="ghost" size="xs" onClick={() => onChange(clearLibraryFilters(options))}>모두 지우기</Button>}
    <PendingStatus pending={pending} className="ml-auto shrink-0 self-center" />
  </div>
}
