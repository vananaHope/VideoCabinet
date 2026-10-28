/**
 * 다시 보인 탭의 초점 유지(#265). 셸은 이번 로드에서 이미 보인 탭을 다시 보일 때 기본 위치 대신 "restore"를 보낸다.
 * 셸은 페이지마다 마지막으로 초점을 받은 요소를 기억하고, 페이지의 초점 처리는 그 요소가 아직 그 페이지에서
 * 보이고 누를 수 있으면 그곳에, 아니면 원래 기본 위치에 초점을 둔다. 대화상자·메뉴처럼 페이지 밖 요소는 기억하지 않는다.
 */
const remembered = new Map<string, HTMLElement>()

export function rememberPageFocus(page: string, element: EventTarget) {
  if (element instanceof HTMLElement) remembered.set(page, element)
}

/** "restore" 요청이고 기억한 요소에 초점을 두었으면 true. 그 밖에는 false라서 페이지가 기본 위치를 쓴다. */
export function restorePageFocus(page: string, target: string) {
  const element = remembered.get(page)
  if (target !== "restore" || !element?.isConnected || !element.closest(`[data-page="${page}"]`)
    || !element.getClientRects().length || element.matches(":disabled")) return false
  element.focus({ preventScroll: true })
  return document.activeElement === element
}
