import type { Tab } from "@/bridge-types"

/**
 * 키보드 초점 규칙(#264). 탭 전환·재생 복귀·트레이·긴급 탈출 복귀·대화상자 닫기 뒤 초점이 어디로 가는지는 여기서만 정한다.
 * - 탭마다 기본 초점이 있다(targets의 첫 줄). 셸이 보내는 대상 키(Python default_focus 등 브리지 계약 값)는 여기서 실제 요소로 푼다.
 *   페이지 상태에 따라 달라지는 기본 초점은 페이지가 setDefaultFocus로 해석 함수를 등록한다.
 * - 셸의 초점 요청은 그 탭이 보이고 렌더가 끝난 뒤(두 프레임) 처리한다. 같은 탭에 더 새 요청이 오면 앞 요청은 버린다.
 * - 탭이 보인 뒤 사용자가 페이지 안에서 키·포인터로 이미 초점을 옮겼으면 늦게 온 요청은 건너뛴다(#257 점검).
 *   셸의 탭 단추·탭 전환 키는 탭을 보이게 하는 입력이라 세지 않는다.
 * - "restore"는 다시 보인 탭에 남은 초점(#265), "resume"은 트레이·긴급 탈출 복귀처럼 숨기기 전 초점을 그대로 둔다.
 * - 대화상자·키 안내를 닫으면 연 자리로, 그 자리가 사라졌거나 숨었으면 메뉴를 연 단추로, 그것도 없으면 탭의 기본 초점으로 간다.
 * - 보이지 않는(숨은·inert·비활성·문서에서 빠진) 요소에는 초점을 두지 않고 다음 후보로 넘어간다.
 */

type Target = HTMLElement | null | undefined
type Resolve = () => Target

const byId = (id: string): Resolve => () => document.getElementById(id)
const select = (selector: string): Resolve => () => document.querySelector<HTMLElement>(selector)

/** 탭마다 셸이 이름으로 부르는 초점 대상. 첫 줄이 그 탭의 기본 초점(셸의 default_focus)이다. 구역·분류를 바꾸는 일은 페이지가 먼저 한다. */
const targets: Record<Tab, Record<string, Resolve>> = {
  library: { grid: byId("library-grid") },
  recommend: { recommendations: byId("recommendations") },
  reel: { "reel-list": byId("reel-list") },
  // 결과가 있으면 결과 목록, 없으면 검색 칸.
  search: { "search-content": () => document.querySelector('#search-results [role="option"]') ? document.getElementById("search-results") : document.getElementById("search-query") },
  // 규칙 탭을 보고 있으면 규칙 목록, 아니면 처리 상태 목록.
  queue: { "queue-list": () => [document.getElementById("queue-rules"), document.getElementById("queue-list")].find(focusable) },
  statistics: { "statistics-period": select('[data-page="statistics"] nav[aria-label="통계 기간"] button[aria-current="page"]') },
  folders: {
    "folders-add": byId("folders-add"),
    "folders-folders": byId("folders-section"), "folders-excluded": byId("folders-section"), "folders-dismissed": byId("folders-section"),
  },
  settings: { "settings-category": select('#settings-category [aria-current="true"]') },
}
const stateful = new Map<string, Resolve>()

/** 페이지 상태에 따라 달라지는 기본 초점을 등록한다. 돌려준 함수로 해제한다. */
export function setDefaultFocus(page: Tab, resolve: Resolve) {
  stateful.set(page, resolve)
  return () => { if (stateful.get(page) === resolve) stateful.delete(page) }
}

function defaultFocus(page: string): Target {
  return (stateful.get(page) ?? Object.values(targets[page as Tab] ?? {})[0])?.()
}

/** 초점을 둘 수 있는 보이는 요소. 문서에서 빠졌거나 숨거나(display:none·hidden) inert·비활성이면 아니다. */
export function focusable(element: Element | null | undefined): element is HTMLElement {
  return element instanceof HTMLElement && element !== document.body && element.isConnected
    && element.getClientRects().length > 0 && !element.closest("[inert]") && !element.matches(":disabled")
}

/** 후보를 차례로 보고 처음으로 초점을 받은 요소에서 멈춘다. 함수 후보는 차례가 와야 부른다(기본 초점의 부수 효과는 그때만). */
function focusFirst(candidates: readonly (Target | Resolve)[]) {
  for (const candidate of candidates) {
    const element = typeof candidate === "function" ? candidate() : candidate
    if (!focusable(element)) continue
    element.focus({ preventScroll: true })
    if (document.activeElement === element) return true
  }
  return false
}

function pageOf(element: EventTarget | null | undefined) {
  return element instanceof Element ? element.closest<HTMLElement>("[data-page]")?.dataset.page : undefined
}

/** 보이는 대화상자(키 안내·확인·셸 대화상자)가 열려 있는지. */
function modalOpen() {
  return Array.from(document.querySelectorAll('[role="dialog"], [role="alertdialog"]'))
    .some(element => element.getAttribute("data-state") !== "closed" && element.getClientRects().length > 0)
}

/** 지금 보이는 탭. */
function shownPage() {
  return document.querySelector<HTMLElement>("[data-page]:not([hidden])")?.dataset.page
}

// 페이지마다 마지막으로 초점을 받은 요소(#265). 대화상자·메뉴처럼 페이지 밖 요소는 기억하지 않는다.
const remembered = new Map<string, HTMLElement>()
// 탭이 보인 뒤 페이지 안에서 사용자 입력(키·포인터)이 있었는지.
const touched = new Map<string, boolean>()
// 메뉴 밖에서 마지막으로 초점을 받은 요소. 초점이 메뉴로 들어가면 그 메뉴를 연 단추(aria-labelledby)다.
// 메뉴 항목에서 연 대화상자를 닫을 때 메뉴를 연 단추로 돌아가는 데 쓴다. 포인터로 연 메뉴는 단추가 초점을 받지 않는다.
let lastFocus: HTMLElement | null = null

if (typeof document !== "undefined") {
  const input = (event: Event) => { const page = pageOf(event.target); if (page) touched.set(page, true) }
  document.addEventListener("keydown", input, true)
  document.addEventListener("pointerdown", input, true)
  document.addEventListener("focusin", event => {
    if (!(event.target instanceof HTMLElement)) return
    const menu = event.target.closest('[role="menu"]')
    const opener = menu && document.getElementById(menu.getAttribute("aria-labelledby") ?? "")
    if (!menu) lastFocus = event.target
    else if (opener && !opener.closest('[role="menu"]')) lastFocus = opener
  }, true)
}

/** 셸이 탭을 보였다(탭 전환·재생 복귀·첫 진입). 그 뒤의 사용자 입력만 늦은 초점 요청을 건너뛰게 한다. */
export function markPageShown(page: string) {
  touched.set(page, false)
}

export function rememberPageFocus(page: string, element: EventTarget) {
  if (element instanceof HTMLElement) remembered.set(page, element)
}

/** 탭이 보인 뒤 사용자가 페이지 안의 보이는 요소로 초점을 이미 옮겼는지. */
function movedByUser(page: string) {
  const active = document.activeElement
  return !!touched.get(page) && focusable(active) && pageOf(active) === page
}

/** 렌더가 끝나 그 탭이 보인 뒤에 run한다. 두 프레임을 기다리고, 아직 숨어 있으면 몇 프레임 더 기다린다. */
function whenShown(page: string, run: () => void) {
  let frames = 0
  const check = () => {
    const element = document.querySelector<HTMLElement>(`[data-page="${page}"]`)
    if (element?.hidden && ++frames < 10) requestAnimationFrame(check)
    else run()
  }
  requestAnimationFrame(() => requestAnimationFrame(check))
}

const pending = new Map<string, number>()
let sequence = 0

/**
 * 셸의 초점 요청을 처리한다. 모든 페이지와 셸이 이 함수 하나로 처리한다.
 * prepare는 렌더 뒤 초점을 두기 직전에 한 번 부른다(스크롤 되살리기 등). 요소를 돌려주면 이번 요청은 그 요소가 먼저다.
 */
export function focusPage(page: string, target: string, prepare?: () => Target | void) {
  // 트레이·긴급 탈출 복귀의 확인은 이미 기다리는 셸 요청(탭 이동 등)을 덮지 않는다.
  if (target === "resume" && pending.has(page)) return
  const id = ++sequence
  pending.set(page, id)
  whenShown(page, () => {
    if (pending.get(page) !== id) return
    pending.delete(page)
    const first = prepare?.() ?? undefined
    if (movedByUser(page)) return
    // 숨기기 전 초점이 아직 보이면(페이지·머리글 어디든) 그대로 둔다. 숨은 탭에 남은 초점은 아니다.
    // 대화상자가 열려 있으면 초점은 그 대화상자의 것이므로 건드리지 않는다(닫을 때 연 자리로 돌아간다).
    const active = document.activeElement
    if (target === "resume" && (modalOpen() || (focusable(active) && (pageOf(active) ?? page) === page))) return
    const kept = remembered.get(page)
    focusFirst([
      first,
      target === "shell" ? select('nav [aria-current="page"]') : undefined,
      (target === "restore" || target === "resume") && pageOf(kept) === page ? kept : undefined,
      targets[page as Tab]?.[target],
      () => defaultFocus(page),
    ])
  })
}

/** 셸 요청이 아닌 페이지 안 동작(검색 뒤 결과 목록 등)이 렌더가 끝난 뒤 초점을 둘 때. 보이지 않는 요소면 두지 않는다. */
export function focusAfterRender(element: Resolve) {
  requestAnimationFrame(() => requestAnimationFrame(() => { focusFirst([element]) }))
}

export type FocusOrigin = { origin: Element | null; trigger: HTMLElement | null }

/**
 * 대화상자가 열리기 직전(Radix가 안으로 초점을 옮기기 전)의 초점과, 메뉴 밖에서 마지막으로 초점을 받은 요소(메뉴를 연 단추).
 * 메뉴 항목은 닫히는 중에 잠깐 남아 있을 뿐이므로 연 자리로 기억하지 않는다.
 */
export function captureFocusOrigin(): FocusOrigin {
  const active = document.activeElement
  return { origin: active?.closest('[role="menu"]') ? null : active, trigger: lastFocus }
}

/**
 * 대화상자를 닫은 뒤 초점을 돌려준다(Esc·닫기·바깥 누르기·F1 모두). 연 자리 → 메뉴를 연 단추 → 탭 기본 초점 순서다.
 * 연 자리가 잠깐 비활성이면(응답을 기다리는 단추) 한 프레임 뒤 다시 본다. 재생 중 대화상자 틀에서는 탭 기본 초점으로 가지 않는다.
 */
export function returnFocus({ origin, trigger }: FocusOrigin) {
  const candidates = [origin instanceof HTMLElement ? origin : null, trigger]
  if (focusFirst(candidates)) return
  requestAnimationFrame(() => {
    if (focusable(document.activeElement) || focusFirst(candidates)) return
    const page = shownPage()
    if (page && !document.documentElement.hasAttribute("data-dialog-container")) focusFirst([() => defaultFocus(page)])
  })
}
