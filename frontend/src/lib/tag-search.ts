import type { TagUsageData } from "@/bridge-types"

export const FREQUENT_TAG_COUNT = 12

// 태그 쪽 검색 이름(key)은 코어 tag_name_key가 만들어 보낸다. 입력한 질의에만 같은 정규화를 적용한다.
// Python casefold 대신 대문자→소문자 변환을 써서 ß·ς 같은 경우도 같은 key가 되게 한다.
export function tagSearchKey(text: string): string {
  return text.replace(/[\p{Cc}\p{Cf}]/gu, "").normalize("NFC").trim().split(/\s+/).join(" ")
    .normalize("NFKC").toUpperCase().toLowerCase()
}

// 태그는 코어가 붙은 영상 수가 많은 순(같으면 이름순)으로 보낸다. 그 순서를 그대로 쓴다.
export function tagChoices(tags: TagUsageData[], query: string, showAll: boolean, exclude: readonly number[] = []): TagUsageData[] {
  const available = exclude.length ? tags.filter(tag => !exclude.includes(tag.id)) : tags
  const key = tagSearchKey(query)
  if (key) return available.filter(tag => tag.key.includes(key))
  return showAll ? available : available.slice(0, FREQUENT_TAG_COUNT)
}

// 태그 고르기가 Esc를 먼저 처리할 상태인지. 감싼 팝오버·대화상자는 이때 닫지 않는다.
export function tagPickerKeepsEscape(event: KeyboardEvent): boolean {
  return event.isComposing || (event.target instanceof HTMLElement && event.target.dataset.keepsEscape === "true")
}
