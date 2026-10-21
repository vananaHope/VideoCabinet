import { useEffect, useState } from "react"
import { Dialog } from "radix-ui"
import { Keyboard } from "lucide-react"
import { request } from "@/bridge"
import { tabs, type KeyGuideData, type KeyGuideEntryData, type ShellBridge } from "@/bridge-types"
import { Button } from "@/components/ui/button"
import { Kbd, KbdGroup } from "@/components/ui/kbd"
import { Notice } from "@/components/ui/notice"
import type { KeyGuideGroup, KeyGuideRow } from "@/lib/key-guide"
import { pageKeyGuides } from "@/pages"

export function KeyGuideButton({ onClick }: { onClick: () => void }) {
  return <Button variant="ghost" size="icon-sm" aria-label="키 안내 (F1)" title="키 안내 (F1)" aria-keyshortcuts="F1" onClick={onClick}><Keyboard aria-hidden="true" /></Button>
}

function KeyRows({ rows }: { rows: readonly (KeyGuideRow | KeyGuideEntryData)[] }) {
  return <dl className="divide-y">{rows.map(row => <div key={`${row.keys.join("+")}:${row.label}`} className="flex gap-3 py-1.5">
    <dt className="w-40 shrink-0">{row.keys.length
      ? <KbdGroup>{row.keys.map(key => <Kbd key={key}>{key}</Kbd>)}</KbdGroup>
      : <span className="text-xs text-muted-foreground">키 미할당</span>}</dt>
    <dd className="min-w-0 flex-1 text-sm break-keep wrap-break-word">{row.label}{"detail" in row && row.detail && <p className="text-xs text-muted-foreground">{row.detail}</p>}</dd>
  </div>)}</dl>
}

function Groups({ groups }: { groups: readonly KeyGuideGroup[] }) {
  if (!groups.length) return <p className="text-sm text-muted-foreground">이 화면에만 쓰는 키는 없습니다. 앱 전체 키와 Tab으로 단추·입력 칸을 오갑니다.</p>
  return <div className="space-y-4">{groups.map(group => <section key={group.title} aria-label={group.title} className="space-y-1">
    <h4 className="text-xs font-semibold text-muted-foreground">{group.title}</h4>
    <KeyRows rows={group.rows} />
  </section>)}</div>
}

/** F1·⌨으로 여는 웹 셸 키 안내. 열 때마다 셸에서 지금 키 배치를 읽는다. */
export function KeyGuideDialog({ bridge, tab, open, onOpenChange }: { bridge: ShellBridge; tab: string; open: boolean; onOpenChange: (open: boolean) => void }) {
  const [app, setApp] = useState<KeyGuideEntryData[] | null>(null)
  const [error, setError] = useState("")
  useEffect(() => {
    if (!open) return
    let current = true
    // 닫혀 있던 동안 바뀐 키 배치를 이전 내용으로 보이지 않는다.
    setApp(null)
    setError("")
    request<KeyGuideData>(reply => bridge.keyGuide(reply))
      .then(data => { if (current) setApp(data.app) })
      .catch(error => { if (current) setError(String(error)) })
    return () => { current = false }
  }, [bridge, open])
  useEffect(() => {
    if (!open) return
    // 셸은 대화상자가 열려 있으면 F1을 웹에 넘긴다. Esc처럼 초점 위치와 상관없이 F1로도 닫는다.
    const close = (event: KeyboardEvent) => {
      if (event.key !== "F1" || event.ctrlKey || event.altKey || event.metaKey || event.shiftKey) return
      event.preventDefault()
      event.stopPropagation()
      if (!event.repeat) onOpenChange(false)
    }
    document.addEventListener("keydown", close, true)
    return () => document.removeEventListener("keydown", close, true)
  }, [open, onOpenChange])
  const label = tabs.find(([value]) => value === tab)?.[1] ?? ""
  const groups = pageKeyGuides[tab as keyof typeof pageKeyGuides] ?? []
  return <Dialog.Root open={open} onOpenChange={onOpenChange}><Dialog.Portal>
    {/* 내용을 오버레이 안에 두어 작은 창에서도 창 안에 맞추고 본문만 스크롤한다. 바깥을 누르면 닫힌다. */}
    <Dialog.Overlay className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4">
      {/* 초점이 뒤 페이지에 남아 있어도 닫기 키가 페이지 키(모아보기 Esc 복귀 등)로 이어지지 않게 한다. */}
      <Dialog.Content className="flex max-h-full w-full max-w-4xl flex-col gap-4 rounded-xl border bg-popover p-6 text-popover-foreground shadow-lg" onEscapeKeyDown={event => event.stopPropagation()}>
        <div className="space-y-1">
          <Dialog.Title className="text-lg font-semibold">키 안내 · {label}</Dialog.Title>
          <Dialog.Description className="text-sm text-muted-foreground">바꿀 수 있는 키는 설정 → 키 배치에서 바꾸며, 여기에는 지금 키 배치가 보입니다.</Dialog.Description>
        </div>
        <div tabIndex={0} aria-label="키 목록" className="grid min-h-0 grid-cols-2 gap-6 overflow-y-auto rounded-md focus-visible:outline-2 focus-visible:outline-ring">
          <section aria-label="앱 전체" className="min-w-0 space-y-2">
            <h3 className="font-semibold">앱 전체</h3>
            {error ? <Notice tone="error">{error}</Notice> : app ? <KeyRows rows={app} /> : <p role="status" className="text-sm text-muted-foreground">키 배치를 읽는 중…</p>}
          </section>
          <section aria-label="지금 화면" className="min-w-0 space-y-2">
            <h3 className="font-semibold">지금 화면 · {label}</h3>
            <Groups groups={groups} />
          </section>
        </div>
        <div className="flex items-center justify-between gap-4">
          <p className="text-xs text-muted-foreground">Esc · F1 · 바깥 누르기로도 닫습니다.</p>
          <Dialog.Close asChild><Button variant="outline">닫기</Button></Dialog.Close>
        </div>
      </Dialog.Content>
    </Dialog.Overlay>
  </Dialog.Portal></Dialog.Root>
}
