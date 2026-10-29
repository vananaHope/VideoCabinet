import type { ShellEntryData, Tab } from "@/bridge-types"

declare global {
  interface Window {
    /** 셸이 문서를 만들 때 넣는 시작 상태(web_shell.update_entry). 페이지 진입 데이터는 pages 아래 탭 이름으로 있다. */
    mvmEntry?: ShellEntryData & { pages?: Partial<Record<Tab, unknown>> }
  }
}

/** 웹을 처음 그릴 때의 탭. 셸이 알려 주지 않으면(개발 서버를 브라우저로 연 경우 등) 라이브러리다. */
export const startTab = (window.mvmEntry?.tab ?? "library") as Tab

/** 첫 데이터가 오기 전에 자리 표시를 그릴 페이지 상태. 셸이 주지 않았으면 undefined다. */
export function entryData<T>(tab: Tab): T | undefined {
  return window.mvmEntry?.pages?.[tab] as T | undefined
}

// 셸이 준비를 알리고 시작 탭이 첫 화면을 그릴 때까지 숨은 탭의 첫 데이터 요청을 미룬다(#267).
// 숨은 탭의 요청이 앞서면 Qt가 그것부터 처리해 첫 화면의 준비 알림이 늦는다. 순서만 바꾸고 각 탭의 요청은 그대로다.
// 숨은 탭은 그 뒤에 받아 두므로 처음 열 때도 데이터가 이미 있다.
let release = () => {}
const startScreenPromise = new Promise<void>(resolve => { release = resolve })
const startScreen = { shell: false, page: false }
function arrive(part: keyof typeof startScreen) {
  if (startScreen[part]) return
  startScreen[part] = true
  // 시작 화면을 한 번 그린 뒤 브라우저가 쉬는 틈에 놓아 준다. 숨은 탭의 요청·그리기(폴더 탭의 제외 목록 등)가
  // 첫 화면 그리기와 준비 알림 처리를 막지 않는다. 보이지 않는 문서는 그릴 화면이 없으므로 바로 놓아 준다.
  if (startScreen.shell && startScreen.page) {
    if (document.hidden) setTimeout(release)
    else requestAnimationFrame(() => requestIdleCallback(release))
  }
}

// 시작 화면보다 먼저 사용자가 연 탭. 기다리던 그 탭의 요청은 바로 놓아 준다.
const openedTabs = new Set<string>([startTab])
const waitingTabs = new Map<string, () => void>()

/** 첫 데이터 요청 전에 기다린다. 시작 탭과 이미 연 탭은 바로, 숨은 탭은 시작 화면이 준비되거나 그 탭을 열 때 풀린다. */
export function waitForStartTab(tab: Tab): Promise<void> {
  if (openedTabs.has(tab)) return Promise.resolve()
  return new Promise(resolve => {
    waitingTabs.set(tab, resolve)
    void startScreenPromise.then(resolve)
  })
}

/** 셸이 탭을 보였다. 그 탭이 첫 데이터를 기다리고 있으면 시작 화면을 기다리지 않고 요청하게 한다. */
export function tabOpened(tab: string) {
  openedTabs.add(tab)
  waitingTabs.get(tab)?.()
  waitingTabs.delete(tab)
}

/** 페이지가 첫 데이터를 그렸거나 읽지 못했다. 시작 탭이면 숨은 탭의 요청을 놓아 줄 조건 하나를 채운다. */
export function startTabShown(tab: Tab) {
  if (tab === startTab) arrive("page")
}

/** 셸이 준비를 알렸거나 셸 상태를 읽지 못했다. 숨은 탭의 요청을 놓아 줄 조건 하나를 채운다. */
export function shellShown() {
  arrive("shell")
}

/** 페이지의 첫 데이터 요청. 숨은 탭이면 시작 탭의 첫 화면 뒤에 보낸다. 시작 탭이면 받든 실패하든 끝날 때 숨은 탭을 놓아 준다. */
export async function firstData<T>(tab: Tab, load: () => Promise<T>): Promise<T> {
  await waitForStartTab(tab)
  try { return await load() } finally { startTabShown(tab) }
}
