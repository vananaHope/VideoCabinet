import { cva } from 'class-variance-authority'
import { selectableItem } from '@/components/ui/selectable-item'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import type { DialogData, DialogValues } from '@/bridge-types'
import { RandomTagFields, tagCandidateCount } from '@/components/random-tag-dialog'

type ScopeValues = Pick<DialogValues, 'choice' | 'members'>

const optionStyle = cva('flex min-w-0 items-start gap-3 rounded-md border px-3 py-2 text-body', {
  variants: {
    selected: { true: selectableItem({ selected: true, ring: true }), false: selectableItem({ selected: false }) },
    disabled: { true: 'opacity-50', false: '' },
  },
})

function chosenTags(data: DialogData, values: ScopeValues) {
  return values.members.map(Number).filter(id => data.tags.some(tag => tag.id === id))
}

function candidatesByTag(data: DialogData) {
  return new Map(data.tag_candidates.map(tag => [tag.id, tag.videoIds]))
}

/** 확인할 수 있는 범위인지. 후보 수는 코어가 센 범위별 후보와 태그별 후보로만 판단하고, 확인할 때 코어가 다시 센다. */
export function randomScopeReady(data: DialogData, values: ScopeValues) {
  const option = data.choices.find(row => row.id === values.choice)
  if (!option || option.status) return false
  return values.choice !== 'tags' || tagCandidateCount(candidatesByTag(data), chosenTags(data, values)) > 0
}

/** 무작위 이어 재생 범위 고르기: 영상 전체 / 재생을 시작한 목록 / 태그 고르기. 후보가 없는 범위는 고를 수 없다. */
export function RandomScopeForm({ data, values, update }: {
  data: DialogData; values: ScopeValues; update: (patch: Partial<ScopeValues>) => void
}) {
  const chosen = chosenTags(data, values)
  // 창을 열 때 첫 초점은 고른 범위에 간다(묶음이 고른 항목 하나만 Tab에 둔다). 화살표 키는 고를 수 있는 범위 사이를 옮기며 고른다.
  return <>
    <RadioGroup aria-label="범위" value={values.choice} onValueChange={choice => update({ choice })}>
      {data.choices.map(row => {
        const disabled = !!row.status
        return <label key={row.id} className={optionStyle({ selected: values.choice === row.id, disabled })}>
          <RadioGroupItem value={row.id} disabled={disabled} className="mt-0.5" />
          <span className="min-w-0 flex-1">
            <span className="block text-body-strong">{row.title}</span>
            <span className="block break-words text-muted-foreground">{row.detail}</span>
            {row.status && <span className="block text-label text-muted-foreground">{row.status}</span>}
          </span>
        </label>
      })}
    </RadioGroup>
    {values.choice === 'tags' && <RandomTagFields tags={data.tags} selected={chosen}
      onChange={ids => update({ members: ids.map(String) })}
      count={tagCandidateCount(candidatesByTag(data), chosen)} />}
  </>
}
