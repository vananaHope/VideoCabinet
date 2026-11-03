import { useEffect } from 'react'
import { connectBridge, request } from '@/bridge'

/** 모든 Radix 모달을 감지한다. 페이지와 ConfirmDialog는 이 연결을 몰라도 된다. */
export default function ShellModals() {
  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(({ shell, dialogs }) => {
      if (disposed) return
      let previous: boolean | undefined
      const update = () => {
        // Radix modal DismissableLayer만 body 포인터를 잠근다. role만으로는 Popover도 잡힌다.
        const opened = document.body.style.pointerEvents === 'none' && Array.from(document.querySelectorAll('[role="dialog"], [role="alertdialog"]'))
          .some(element => element.getAttribute('data-state') !== 'closed' && element.getClientRects().length > 0)
        if (opened !== previous) { previous = opened; void request(reply => dialogs.modalState(Number(opened), reply)) }
      }
      const observer = new MutationObserver(update)
      observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['data-state', 'hidden', 'style'] })
      // Qt는 숨김 중에도 상태를 기록한다. 복귀 때 현재 DOM을 다시 알려 마지막 수신 상태와 맞춘다.
      const resync = () => { previous = undefined; requestAnimationFrame(update) }
      const reshown = () => { if (document.visibilityState === 'visible') resync() }
      shell.shellChanged.connect(resync)
      document.addEventListener('visibilitychange', reshown)
      update()
      disconnect = () => {
        observer.disconnect()
        shell.shellChanged.disconnect(resync)
        document.removeEventListener('visibilitychange', reshown)
        void request(reply => dialogs.modalState(0, reply))
      }
    })
    return () => { disposed = true; disconnect() }
  }, [])
  return null
}
