// 누름 축소(index.css의 :active 규칙)의 기준점을 지금 포인터 자리로 둔다.
// 가운데를 기준으로 줄이면 원래 영역 가장자리 안쪽의 점이 줄어든 면 밖으로 밀려, 거기서 놓으면 바깥 요소가 click을 받는다.
// 기준점이 포인터 자리면, 포인터가 원래 영역 안일 때는 줄어든 면 안에도 있고(누른 그 요소가 click을 받는다),
// 원래 영역 밖이면 줄어든 면 밖에도 있다(지금처럼 놓아도 취소). 누르고 있는 동안 포인터가 움직일 때마다 옮긴다.
export const PRESSABLE = "button, [role=option], [role=row][aria-selected], [role=treeitem], [role=menuitem], [role=menuitemcheckbox], [role=menuitemradio]"

/** 줄기 전 상자 기준의 포인터 좌표를 기준점으로 둔다. 이미 걸린 축소는 지금 기준점과 배율로 되돌려 잰다. */
function follow(element: HTMLElement, clientX: number, clientY: number) {
  const rect = element.getBoundingClientRect()
  const style = getComputedStyle(element)
  const [originX, originY] = style.transformOrigin.split(" ").map(parseFloat)
  const { a: scaleX, d: scaleY } = new DOMMatrixReadOnly(style.transform === "none" ? undefined : style.transform)
  const left = rect.left - originX * (1 - scaleX), top = rect.top - originY * (1 - scaleY)
  element.style.setProperty("--press-origin", `${clientX - left}px ${clientY - top}px`)
}

export function trackPressOrigin(root: Document) {
  let pressed: HTMLElement | null = null
  // 키보드(Space)로 눌린 상태는 기준점이 없어 가운데로 줄어든다. 손을 떼면 기준점을 지운다.
  const release = () => { pressed?.style.removeProperty("--press-origin"); pressed = null }
  root.addEventListener("pointerup", release, true)
  root.addEventListener("pointercancel", release, true)
  root.addEventListener("pointerdown", event => {
    const element = event.target instanceof Element ? event.target.closest(PRESSABLE) : null
    if (!(element instanceof HTMLElement)) return
    pressed = element
    follow(element, event.clientX, event.clientY)
  }, true)
  // 누르고 있을 때만 계산한다. 쉬는 동안의 포인터 이동에는 아무것도 하지 않는다.
  root.addEventListener("pointermove", event => {
    if (pressed && event.buttons) follow(pressed, event.clientX, event.clientY)
  }, true)
}
