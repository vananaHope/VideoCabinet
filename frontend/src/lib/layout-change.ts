import { useLayoutEffect } from "react"

/**
 * 페이지가 “내 고정 조작 요소의 배치가 바뀌었다”를 알리는 신호. 셸 안내 묶음(NoticeLayer)이 받아서
 * 지금 모서리가 툴바·작업 단추를 가리게 됐는지 다시 잰다.
 * 분류·구역 전환, 비동기 준비 완료, 페이지 안내가 생기고 사라짐처럼 단추 자리가 바뀌는 때에만 보낸다.
 * 공용 안내(Notice·NoticeStack)는 생기고 사라질 때와 펼치기·접기·더 보기에서 스스로 보낸다(목록 행의 InlineNotice는 보내지 않는다).
 * 목록 스크롤·가상 격자 다시 그리기처럼 고정 조작 요소가 그대로인 변화에는 보내지 않는다.
 */
const event = "mvm:layout-change"

export function announceLayoutChange() {
  window.dispatchEvent(new Event(event))
}

/** deps 중 하나가 바뀐 그리기가 DOM에 반영된 직후 신호를 보낸다(처음 붙을 때 포함). */
export function useLayoutChange(...deps: unknown[]) {
  useLayoutEffect(announceLayoutChange, deps)
}

/** 붙을 때와 떨어질 때 신호를 보낸다. 어느 부품의 로컬 상태로든 생기고 사라지는 공용 부품(안내)이 쓴다. */
export function useLayoutPresence() {
  useLayoutEffect(() => { announceLayoutChange(); return announceLayoutChange }, [])
}

export function onLayoutChange(listener: () => void) {
  window.addEventListener(event, listener)
  return () => window.removeEventListener(event, listener)
}
