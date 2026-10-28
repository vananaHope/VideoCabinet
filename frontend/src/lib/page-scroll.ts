/**
 * 다시 보인 탭의 스크롤 유지(#265). 숨긴 페이지(display: none)는 안쪽 스크롤 위치를 잃으므로, 셸이 탭을 떠날 때
 * 그 페이지에서 스크롤된 요소의 위치를 저장했다가 다시 보일 때 되살린다. 그사이 사라진 요소는 건너뛴다.
 */
const saved = new Map<string, Array<[Element, number, number]>>()

export function savePageScroll(page: string) {
  const area = document.querySelector(`[data-page="${page}"]`)
  if (!area) return
  const positions: Array<[Element, number, number]> = []
  for (const element of [area, ...area.querySelectorAll("*")])
    if (element.scrollTop || element.scrollLeft) positions.push([element, element.scrollTop, element.scrollLeft])
  saved.set(page, positions)
}

export function restorePageScroll(page: string) {
  for (const [element, top, left] of saved.get(page) ?? [])
    if (element.isConnected) { element.scrollTop = top; element.scrollLeft = left }
  saved.delete(page)
}
