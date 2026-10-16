import type { NoticeTone } from "@/components/ui/notice"

/**
 * 셸 작업 알림(Qt 상태 표시줄)은 위계 없는 문자열 계약이다. 앱 코드가 직접 만드는 고정 접두사만 위계를 정하고,
 * 모르는 문자열은 정보로 둔다. 문장 중간의 "실패"(예: 실패 0개, 영상 제목)는 보지 않는다.
 * 출처: library_operations(검사), subtitle_controls(자막), translation_controls(번역·다듬기),
 * resolution_controls(썸네일·해상도). 문구를 바꾸면 이 목록과 tests/test_web_shell.py를 함께 고친다.
 */
const prefixes: readonly (readonly [string, NoticeTone])[] = [
  ["검사 실패: ", "error"],
  ["자막 처리 실패: ", "error"],
  ["자막 실패 — ", "error"],
  ["번역 처리 실패: ", "error"],
  ["번역 실패 · ", "error"],
  ["다듬기 실패 · ", "error"],
  ["썸네일 채우기 실패: ", "error"],
  ["해상도 채우기 실패: ", "error"],
  // 결과는 남았거나 자동으로 다시 시도하는 실패는 경고다.
  ["번역 보류 · ", "warning"],
  ["다듬기 보류 · ", "warning"],
  ["자막은 저장됐지만 표시에 실패했습니다: ", "warning"],
  ["번역 자막은 저장됐지만 표시에 실패했습니다: ", "warning"],
  ["다듬은 자막은 저장됐지만 표시에 실패했습니다: ", "warning"],
  ["썸네일을 만들지 못했습니다: ", "warning"],
  ["해상도를 읽지 못했습니다: ", "warning"],
]

export function shellStatusTone(text: string): NoticeTone {
  return prefixes.find(([prefix]) => text.startsWith(prefix))?.[1] ?? "info"
}
