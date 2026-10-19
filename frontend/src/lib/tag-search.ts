import type { TagUsageData } from "@/bridge-types"

export const FREQUENT_TAG_COUNT = 12

// 태그는 코어가 붙은 영상 수가 많은 순(같으면 이름순)으로 보낸다. 그 순서를 그대로 쓴다.
// key는 태그의 key와 같은 규칙(tagNameKey)으로 만든 질의 key다. 빈 문자열이면 검색하지 않는다.
export function tagChoices(tags: TagUsageData[], key: string, showAll: boolean, exclude: readonly number[] = []): TagUsageData[] {
  const available = exclude.length ? tags.filter(tag => !exclude.includes(tag.id)) : tags
  if (key) return available.filter(tag => tag.key.includes(key))
  return showAll ? available : available.slice(0, FREQUENT_TAG_COUNT)
}

// 태그 고르기가 Esc를 먼저 처리할 상태인지. 포커스가 조각 안 어디에 있든 본다. 감싼 팝오버·대화상자는 이때 닫지 않는다.
export function tagPickerKeepsEscape(event: KeyboardEvent): boolean {
  return event.isComposing || (event.target instanceof Element && !!event.target.closest("[data-keeps-escape='true']"))
}
