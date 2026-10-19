/** 태그 고르기 검사 전용 번들. 제품 진입점에는 포함하지 않는다.
 * 즉시 실행·뺄 태그를 쓰는 화면(#191·#205)이 아직 없어 여기서 띄운다. 검색 key 함수도 코어와 비교하도록 내보낸다. */
import { createRoot } from 'react-dom/client'
import { TagPicker } from '../src/components/tag-picker'
import { tagChoices } from '../src/lib/tag-search'
import { tagNameKey } from '../src/lib/tag-name-key'
import type { TagUsageData } from '../src/bridge-types'

const element = document.createElement('div')
element.dataset.tagPickerProbe = ''
document.body.append(element)
const root = createRoot(element)
const picks: number[] = []
// 고르면 붙인 것으로 보고 뺄 태그에 더한다(#191 태그 편집과 같은 쓰임).
function show(tags: TagUsageData[] | null, exclude: number[] = []) {
  if (!tags) root.render(null)
  else root.render(<TagPicker tags={tags} label="붙일 태그" mode="immediate" exclude={exclude} emptyText="붙일 태그가 없습니다."
    onPick={async tag => { picks.push(tag.id); show(tags, [...exclude, tag.id]); return true }} />)
}
Object.assign(window, { tagPickerProbe: show, tagPickerPicks: picks, tagChoicesProbe: tagChoices, tagNameKeyProbe: tagNameKey })
