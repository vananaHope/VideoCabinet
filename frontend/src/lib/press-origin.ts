// 누름 축소(index.css의 :active 규칙)의 기준점을 누른 자리로 둔다.
// 가운데를 기준으로 줄이면 가장자리 안쪽을 누른 점이 줄어든 면 밖으로 밀려, 같은 자리에서 놓아도 바깥 요소가 click을 받는다.
// 누른 점을 기준으로 줄이면 그 점은 늘 면 안에 남아 원래 클릭 영역 어디서 누르고 놓아도 그 요소의 동작이 실행된다.
export const PRESSABLE = "button, [role=option], [role=row][aria-selected], [role=treeitem], [role=menuitem], [role=menuitemcheckbox], [role=menuitemradio]"

export function trackPressOrigin(root: Document) {
  let pressed: HTMLElement | null = null
  // 키보드(Space)로 눌린 상태는 기준점이 없어 가운데로 줄어든다. 손을 떼면 기준점을 지운다.
  const release = () => { pressed?.style.removeProperty("--press-origin"); pressed = null }
  root.addEventListener("pointerup", release, true)
  root.addEventListener("pointercancel", release, true)
  root.addEventListener("pointerdown", event => {
    const element = event.target instanceof Element ? event.target.closest(PRESSABLE) : null
    if (!(element instanceof HTMLElement)) return
    // pointerdown을 받을 때는 이미 :active 축소(가운데 기준)가 걸려 있다. 지금 기준점과 배율로 줄기 전 상자의 왼쪽 위를 되찾는다.
    const rect = element.getBoundingClientRect()
    const style = getComputedStyle(element)
    const [originX, originY] = style.transformOrigin.split(" ").map(parseFloat)
    const { a: scaleX, d: scaleY } = new DOMMatrixReadOnly(style.transform === "none" ? undefined : style.transform)
    const left = rect.left - originX * (1 - scaleX), top = rect.top - originY * (1 - scaleY)
    pressed = element
    element.style.setProperty("--press-origin", `${event.clientX - left}px ${event.clientY - top}px`)
  }, true)
}
