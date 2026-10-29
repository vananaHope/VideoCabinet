import { useEffect, useMemo, useRef, useState } from "react"
import { Dices } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogBody, DialogClose, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog"
import { TagPicker } from "@/components/tag-picker"
import { tagPickerKeepsEscape } from "@/lib/tag-search"
import type { TagCandidatesData, TagUsageData } from "@/bridge-types"

type Candidates = { tags: TagUsageData[]; byTag: Map<number, readonly number[]> }

/** 고른 태그 중 하나라도 붙은 후보 영상 수(태그별 후보의 합집합 크기). 후보 규칙은 코어가 태그별 후보로 정한다. */
export function tagCandidateCount(byTag: ReadonlyMap<number, readonly number[]>, chosen: readonly number[]): number {
  return new Set(chosen.flatMap(id => byTag.get(id) ?? [])).size
}

/** 무작위 재생 범위의 태그 고르기와 후보 수 안내. 태그 무작위 창과 무작위 이어 재생 범위 고르기 창이 함께 쓴다.
 * count가 null이면 아직 세는 중이다. */
export function RandomTagFields({ tags, selected, onChange, count, error = "" }: {
  tags: TagUsageData[]; selected: readonly number[]; onChange: (ids: number[]) => void; count: number | null; error?: string
}) {
  return <>
    <TagPicker tags={tags} label="태그" mode="multiple" chips selected={selected} onChange={onChange} />
    <p role="status" className="text-body text-muted-foreground empty:hidden">{error ? `후보를 세지 못했습니다. ${error}`
      : !tags.length ? ""
      : !selected.length ? "태그를 하나 이상 고르세요."
      : count === null ? "후보를 세는 중…"
      : count ? `후보 ${count}개` : "후보 0개 · 고른 태그에 재생할 수 있는 영상이 없습니다."}</p>
  </>
}

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
  // 새로 받는 동안과 받지 못했을 때는 이전 후보로 세지 않는다(재생도 막힌다).
  useEffect(() => {
    if (!open) return
    let current = true
    setCandidates(null)
    setError("")
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
    return tagCandidateCount(candidates.byTag, chosen)
  }, [candidates, chosen, tags])
  const playable = chosen.length > 0 && !error && !!count

  function play() {
    if (!playable) return
    onOpenChange(false)
    onPlay(chosen)
  }

  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent ref={content} size="compact"
      onOpenAutoFocus={event => { event.preventDefault(); content.current?.querySelector<HTMLElement>("[role=combobox]")?.focus() }}
      onCloseAutoFocus={event => { event.preventDefault(); onReturnFocus() }}
      onEscapeKeyDown={event => { if (tagPickerKeepsEscape(event)) event.preventDefault() }}>
      <DialogHeader title="태그에서 무작위 재생" description="고른 태그 중 하나라도 붙은 영상에서 하나를 골라 재생합니다. 후보 수는 파일 없음·제외 영상을 뺀 수라 태그 옆 숫자(붙은 영상 수)보다 적을 수 있습니다." />
      <DialogBody><RandomTagFields tags={tags} selected={chosen} onChange={setSelected} count={count} error={error} /></DialogBody>
      <DialogFooter>
        <DialogClose asChild><Button variant="outline">취소</Button></DialogClose>
        <Button disabled={!playable} onClick={play}><Dices aria-hidden="true" />재생</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
}
