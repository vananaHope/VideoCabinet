/**
 * 화면의 모든 날짜 표시. 브리지는 ISO 문자열을 넘기고 모양은 여기서만 만든다(#232).
 * 날짜 `2026. 10. 21.`, 날짜와 시각 `2026. 10. 21. 15:04`(24시간제), 짧은 날짜 `10. 21.`.
 * 시각이 있는 값은 컴퓨터 시간대로 바꾸고, 날짜만 있는 값(`2026-10-21`)은 그 달력 날짜 그대로 보인다.
 */
const INVALID = "시각 정보 없음"
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/

function parse(value: string): Date | null {
  const parts = DATE_ONLY.exec(value)
  if (!parts) {
    const parsed = new Date(value)
    return Number.isNaN(parsed.getTime()) ? null : parsed
  }
  // new Date("2026-10-21")은 UTC 자정으로 읽혀 UTC보다 늦은 시간대에서 하루 앞 날짜가 되고,
  // new Date(99, 0, 5)는 0~99년을 1900년대로 바꾼다. 로컬 날짜에 연·월·일을 그대로 넣고 넘친 값은 버린다.
  const [year, month, date] = parts.slice(1).map(Number)
  const parsed = new Date(2000, 0, 1)
  parsed.setFullYear(year, month - 1, date)
  return parsed.getFullYear() === year && parsed.getMonth() === month - 1 && parsed.getDate() === date ? parsed : null
}

const pad = (value: number, width = 2) => String(value).padStart(width, "0")
const fullYear = (date: Date) => pad(date.getFullYear(), 4)
const day = (date: Date) => `${pad(date.getMonth() + 1)}. ${pad(date.getDate())}.`

export function formatDate(value: string): string {
  const date = parse(value)
  return date ? `${fullYear(date)}. ${day(date)}` : INVALID
}

export function formatDateTime(value: string): string {
  const date = parse(value)
  return date ? `${fullYear(date)}. ${day(date)} ${pad(date.getHours())}:${pad(date.getMinutes())}` : INVALID
}

/** 차트 축 눈금처럼 좁은 자리의 날짜. */
export function formatShortDate(value: string): string {
  const date = parse(value)
  return date ? day(date) : INVALID
}
