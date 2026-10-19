import { useEffect, useMemo, useRef, useState } from "react"
import { Dialog } from "radix-ui"
import { Dices } from "lucide-react"
import { Button } from "@/components/ui/button"
import { TagPicker } from "@/components/tag-picker"
import { tagPickerKeepsEscape } from "@/lib/tag-search"
import type { TagCandidatesData, TagUsageData } from "@/bridge-types"

type Candidates = { tags: TagUsageData[]; byTag: Map<number, readonly number[]> }

/** 무작위 재생 범위를 태그로 고르는 창. 고른 태그 중 하나라도 붙은 영상(OR)이 후보다. */
export function RandomTagDialog({ open, onOpenChange, tags, load, onPlay, onReturnFocus }: {
  open: boolean; onOpenChange: (open: boolean) => void; tags: TagUsageData[]
  load: () => Promise<TagCandidatesData[]>; onPlay: (tagIds: number[]) => void; onReturnFocus: () => void
}) {
  // 고른 태그는 창을 닫아도 남겨 같은 범위로 다시 고르기 쉽게 한다. 지워진 태그는 빼고 본다.
  const [selected, setSelected] = useState<number[]>([])
  const [candidates, setCandidates] = useState<Candidates | null>(null)
  const [error, setError] = useState("")
  const content = useRef<HTMLDivElement>(null)

  // 태그별 후보는 창을 열 때와 라이브러리가 갱신될 때(태그 목록이 바뀜)만 받는다.
  // 태그를 바꿀 때는 받은 집합의 합집합 크기만 세어 메인 스레드에 다시 묻지 않는다.
  useEffect(() => {
    if (!open) return
    let current = true
    load().then(value => {
      if (!current) return
      setCandidates({ tags, byTag: new Map(value.map(tag => [tag.id, tag.videoIds])) })
      setError("")
    }).catch(reason => { if (current) setError(reason instanceof Error ? reason.message : String(reason)) })
    return () => { current = false }
  }, [open, tags, load])

  const chosen = useMemo(() => selected.filter(id => tags.some(tag => tag.id === id)), [selected, tags])
  const count = useMemo(() => {
    if (!candidates || candidates.tags !== tags) return null
    return new Set(chosen.flatMap(id => candidates.byTag.get(id) ?? [])).size
  }, [candidates, chosen, tags])
  const playable = chosen.length > 0 && !!count

  function play() {
    if (!playable) return
    onOpenChange(false)
    onPlay(chosen)
  }

  return <Dialog.Root open={open} onOpenChange={onOpenChange}><Dialog.Portal>
    <Dialog.Overlay className="fixed inset-0 z-50 bg-background/80" />
    <Dialog.Content ref={content} className="fixed inset-4 z-50 m-auto flex h-fit max-w-lg flex-col gap-4 overflow-y-auto rounded-xl border bg-popover p-6 text-popover-foreground shadow-lg"
      onOpenAutoFocus={event => { event.preventDefault(); content.current?.querySelector<HTMLElement>("[role=combobox]")?.focus() }}
      onCloseAutoFocus={event => { event.preventDefault(); onReturnFocus() }}
      onEscapeKeyDown={event => { if (tagPickerKeepsEscape(event)) event.preventDefault() }}>
      <header className="space-y-2">
        <Dialog.Title className="text-lg font-semibold">태그에서 무작위 재생</Dialog.Title>
        <Dialog.Description className="text-sm text-muted-foreground">고른 태그 중 하나라도 붙은 영상에서 하나를 골라 재생합니다.</Dialog.Description>
      </header>
      <TagPicker tags={tags} label="태그" mode="multiple" chips selected={chosen} onChange={setSelected} />
      <p role="status" className="text-sm text-muted-foreground empty:hidden">{error ? `후보를 세지 못했습니다. ${error}`
        : !tags.length ? ""
        : !chosen.length ? "태그를 하나 이상 고르세요."
        : count === null ? "후보를 세는 중…"
        : count ? `후보 ${count}개` : "후보 0개 · 고른 태그에 재생할 수 있는 영상이 없습니다."}</p>
      <div className="flex justify-end gap-2">
        <Dialog.Close asChild><Button variant="outline">취소</Button></Dialog.Close>
        <Button disabled={!playable} onClick={play}><Dices aria-hidden="true" />재생</Button>
      </div>
    </Dialog.Content>
  </Dialog.Portal></Dialog.Root>
}
