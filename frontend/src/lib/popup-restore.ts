import { useEffect, useId, useRef } from "react"
import { connectBridge, request } from "@/bridge"

// 긴급 탈출로 창이 숨으면 선택 목록·후보 목록·메뉴는 창 blur로 스스로 닫힌다.
// 열린 목록을 셸에 알려 두면 셸이 숨기기 직전 것을 기억했다가 복귀 때 다시 열게 한다.
const reopeners = new Map<string, () => void>()
let opened = ""
let listening: Promise<void> | undefined
// 복귀 직후에는 창 활성화가 비동기로 이어지며 blur·resize가 다시 올 수 있다.
// 사용자가 키나 포인터를 쓰기 전까지 잠깐은 그렇게 닫힌 목록을 다시 연다.
const GRACE_MS = 1000
const GRACE_REOPENS = 3
let restoring: { id: string; until: number; left: number } | null = null

function userActed() { restoring = null }

function listen() {
  listening ??= connectBridge().then(({ dialogs }) => {
    document.addEventListener("keydown", userActed, true)
    document.addEventListener("pointerdown", userActed, true)
    dialogs.popupRestore.connect(id => {
      restoring = { id, until: performance.now() + GRACE_MS, left: GRACE_REOPENS }
      reopeners.get(id)?.()
    })
  }).catch(() => {})
}

function report(id: string, open: boolean) {
  if (open) opened = id
  else if (opened === id) opened = ""
  else return
  const current = opened
  void connectBridge().then(({ dialogs }) => request(reply => dialogs.popupState(current, reply))).catch(() => {})
}

function closedDuringRestore(id: string) {
  if (restoring?.id !== id || performance.now() > restoring.until || restoring.left <= 0) return false
  restoring.left -= 1
  return true
}

/** 열린 동안 셸에 알리고, 긴급 탈출에서 복귀하면 reopen으로 다시 연다. */
export function useRestorablePopup(open: boolean, reopen: () => void) {
  const id = useId()
  const latest = useRef(reopen)
  useEffect(() => { latest.current = reopen })
  useEffect(() => {
    listen()
    reopeners.set(id, () => latest.current())
    return () => { reopeners.delete(id); report(id, false) }
  }, [id])
  useEffect(() => {
    report(id, open)
    if (!open && closedDuringRestore(id)) latest.current()
  }, [id, open])
}
