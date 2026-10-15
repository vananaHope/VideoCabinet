import { useEffect } from 'react'
import { connectBridge, request } from '@/bridge'

/** 모든 Radix 모달을 감지한다. 페이지와 ConfirmDialog는 이 연결을 몰라도 된다. */
export default function ShellModals() {
  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(({ shell }) => {
      if (disposed) return
      let previous: boolean | undefined
      const update = () => {
        const opened = Array.from(document.querySelectorAll('[role="dialog"], [role="alertdialog"]'))
          .some(element => element.getAttribute('data-state') !== 'closed' && element.getClientRects().length > 0)
        if (opened !== previous) { previous = opened; void request(reply => shell.modalState(opened, reply)) }
      }
      const observer = new MutationObserver(update)
      observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['data-state', 'hidden', 'style'] })
      const navigation = () => { previous = undefined; requestAnimationFrame(update) }
      shell.shellChanged.connect(navigation)
      update()
      disconnect = () => { observer.disconnect(); shell.shellChanged.disconnect(navigation); void request(reply => shell.modalState(false, reply)) }
    })
    return () => { disposed = true; disconnect() }
  }, [])
  return null
}
