import { tagKeyAssigned, tagKeyCasefold, tagKeyRemoved, tagKeySpaces } from "@/lib/tag-name-key-data"

// 코어 tags.tag_name_key와 같은 key를 화면에서 동기로 만든다. 규칙과 표의 원본은 코어이고 이 파일은 생성한 표만 적용한다.
const casefold = new Map(tagKeyCasefold)
const spaces = new Set(tagKeySpaces)

function within(ranges: readonly number[], code: number): boolean {
  let low = 0, high = ranges.length / 2 - 1
  while (low <= high) {
    const middle = (low + high) >> 1
    if (code < ranges[middle * 2]) high = middle - 1
    else if (code > ranges[middle * 2 + 1]) low = middle + 1
    else return true
  }
  return false
}
const codeOf = (char: string) => char.codePointAt(0) ?? 0

// 코어의 Unicode 버전이 모르는 글자는 코어처럼 그대로 두고, 그 앞뒤를 따로 정규화한다.
function normalizeKnown(text: string, form: "NFC" | "NFKC"): string {
  let result = "", known = ""
  for (const char of text) {
    if (within(tagKeyAssigned, codeOf(char))) known += char
    else { result += known.normalize(form) + char; known = "" }
  }
  return result + known.normalize(form)
}

// 제어·서식 문자 제거 → NFC → 공백 정리 → NFKC → casefold (tag_name_key와 같은 순서)
export function tagNameKey(name: string): string {
  const kept = [...name].filter(char => !within(tagKeyRemoved, codeOf(char))).join("")
  const words: string[] = []
  let word = ""
  for (const char of normalizeKnown(kept, "NFC")) {
    if (!spaces.has(codeOf(char))) word += char
    else if (word) { words.push(word); word = "" }
  }
  if (word) words.push(word)
  return [...normalizeKnown(words.join(" "), "NFKC")].map(char => casefold.get(codeOf(char)) ?? char).join("")
}
