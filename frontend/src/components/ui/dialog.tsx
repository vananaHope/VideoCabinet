import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { AlertDialog as AlertDialogPrimitive, Dialog as DialogPrimitive } from "radix-ui"

/**
 * 앱의 모든 대화상자가 쓰는 공용 틀. 덮개·면·둥글기·안쪽 여백·그림자·여는 전환과 제목·설명·단추 줄 배치는 여기서만 정한다.
 * - 덮개가 내용을 감싸 창 가장자리에서 1rem 띄워 가운데 둔다. 내용이 창보다 길면 틀 안에서 스크롤한다.
 * - 여는 전환은 덮개(와 그 안의 내용)의 투명도만 바꾼다. 닫힘은 즉시다(#259).
 * - size: compact 512px(확인·짧은 입력), default 640px(업무 대화상자), wide 896px(목록·키 안내).
 * - placement=container: 대화상자 층(web_dialogs_host)의 틀. 재생 중에는 셸이 html에 data-dialog-container를 달고 웹 뷰를
 *   내용 크기의 창으로 옮긴다. 그동안 틀은 왼쪽 위에 붙어 원래 창 크기(--dialog-max-width·--dialog-max-height) 안에서
 *   내용 크기를 갖고 모서리가 각진다. 틀 안에서 여는 확인 대화상자가 위에 보이도록 한 층 아래(z-40)에 둔다.
 */
const overlayVariants = cva("fixed inset-0 flex animate-fade-enter items-center justify-center bg-background/80 p-4", {
  variants: {
    placement: {
      center: "z-50",
      container: "z-40 in-data-dialog-container:right-auto in-data-dialog-container:bottom-auto in-data-dialog-container:h-(--dialog-max-height) in-data-dialog-container:w-(--dialog-max-width) in-data-dialog-container:items-start in-data-dialog-container:justify-start in-data-dialog-container:bg-background in-data-dialog-container:p-0",
    },
  },
  defaultVariants: { placement: "center" },
})

const contentVariants = cva("flex max-h-full w-full min-w-0 flex-col gap-4 overflow-auto rounded-xl border bg-popover p-6 text-popover-foreground shadow-lg", {
  variants: {
    size: { compact: "max-w-lg", default: "max-w-160", wide: "max-w-4xl" },
    placement: { center: "", container: "in-data-dialog-container:rounded-none" },
  },
  defaultVariants: { size: "default", placement: "center" },
})

type FrameProps = VariantProps<typeof contentVariants>

const titleStyle = "text-section-title"
const descriptionStyle = "text-body text-muted-foreground"

function Dialog(props: React.ComponentProps<typeof DialogPrimitive.Root>) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />
}

function DialogContent({ size, placement, children, ...props }: Omit<React.ComponentProps<typeof DialogPrimitive.Content>, "className"> & FrameProps) {
  return <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay className={overlayVariants({ placement })}>
      <DialogPrimitive.Content data-slot="dialog-content" data-size={size ?? "default"} className={contentVariants({ size, placement })} {...props}>
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Overlay>
  </DialogPrimitive.Portal>
}

/** 제목과 설명. 설명은 제목 아래 한곳에 둔다. */
function DialogHeader({ title, description }: { title: React.ReactNode; description: React.ReactNode }) {
  return <header data-slot="dialog-header" className="flex flex-col gap-2">
    <DialogPrimitive.Title className={titleStyle}>{title}</DialogPrimitive.Title>
    <DialogPrimitive.Description className={descriptionStyle}>{description}</DialogPrimitive.Description>
  </header>
}

/**
 * 머리글과 단추 줄 사이의 본문. 내용이 창보다 길면 본문만 스크롤해 제목과 단추 줄이 늘 보인다.
 * 초점 테두리가 스크롤 가장자리에서 잘리지 않게 안쪽으로 조금 띄운다.
 */
function DialogBody({ children }: { children: React.ReactNode }) {
  return <div data-slot="dialog-body" className="-m-1 flex min-h-0 flex-col gap-4 overflow-y-auto p-1">{children}</div>
}

/**
 * 단추 줄. 대화상자를 끝내는 동작은 오른쪽 끝에 [취소·닫기(outline)][확인(default, 위험하면 destructive)] 순서로 둔다.
 * 선택한 항목에 대한 보조 동작이나 짧은 안내는 start로 같은 줄 왼쪽에 둔다. 좁으면 왼쪽 묶음 아래로 오른쪽 묶음이 내려간다.
 */
function DialogFooter({ start, children }: { start?: React.ReactNode; children: React.ReactNode }) {
  return <footer data-slot="dialog-footer" className="flex flex-wrap items-center justify-end gap-2">
    {start && <div className="mr-auto flex flex-wrap items-center gap-2">{start}</div>}
    <div className="ml-auto flex shrink-0 gap-2">{children}</div>
  </footer>
}

const DialogClose = DialogPrimitive.Close

function AlertDialog(props: React.ComponentProps<typeof AlertDialogPrimitive.Root>) {
  return <AlertDialogPrimitive.Root data-slot="alert-dialog" {...props} />
}

/** 확인 대화상자. 바깥을 눌러도 닫히지 않고, 열면 취소에 초점이 간다(Radix AlertDialog). */
function AlertDialogContent({ size = "compact", children, ...props }: Omit<React.ComponentProps<typeof AlertDialogPrimitive.Content>, "className"> & Pick<FrameProps, "size">) {
  return <AlertDialogPrimitive.Portal>
    <AlertDialogPrimitive.Overlay className={overlayVariants()}>
      <AlertDialogPrimitive.Content data-slot="dialog-content" data-size={size} className={contentVariants({ size })} {...props}>
        {children}
      </AlertDialogPrimitive.Content>
    </AlertDialogPrimitive.Overlay>
  </AlertDialogPrimitive.Portal>
}

function AlertDialogHeader({ title, description }: { title: React.ReactNode; description: React.ReactNode }) {
  return <header data-slot="dialog-header" className="flex flex-col gap-2">
    <AlertDialogPrimitive.Title className={titleStyle}>{title}</AlertDialogPrimitive.Title>
    <AlertDialogPrimitive.Description className={descriptionStyle}>{description}</AlertDialogPrimitive.Description>
  </header>
}

const AlertDialogFooter = DialogFooter
const AlertDialogCancel = AlertDialogPrimitive.Cancel
const AlertDialogAction = AlertDialogPrimitive.Action

export {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogFooter, AlertDialogHeader,
  Dialog, DialogBody, DialogClose, DialogContent, DialogFooter, DialogHeader,
}
