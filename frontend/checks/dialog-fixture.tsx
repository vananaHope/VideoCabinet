/** 실창/offscreen 검사 전용 번들. 제품 진입점에는 포함하지 않는다. */
import { createRoot } from 'react-dom/client'
import { Dialog, Popover } from 'radix-ui'
import { ConfirmDialog } from '../src/components/page-parts'

const element = document.createElement('div')
document.body.append(element)
const root = createRoot(element)
function show(kind: string) {
  const close = () => root.render(null)
  if (kind === 'confirm') root.render(<ConfirmDialog open onOpenChange={close} title="공용 확인 검사" description="모달 동안 셸 동작을 막고 키 전달은 유지합니다." onConfirm={close} />)
  else if (kind === 'dialog' || kind === 'nonmodal') root.render(<Dialog.Root open modal={kind === 'dialog'} onOpenChange={close}><Dialog.Portal><Dialog.Overlay /><Dialog.Content><Dialog.Title>대화상자 검사</Dialog.Title><Dialog.Description>실제 Radix 모달 감지</Dialog.Description><Dialog.Close>닫기</Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>)
  else if (kind === 'popover') root.render(<Popover.Root open><Popover.Anchor /><Popover.Portal><Popover.Content>팝오버 검사</Popover.Content></Popover.Portal></Popover.Root>)
  else close()
}
Object.assign(window, { dialogProbe: show })
