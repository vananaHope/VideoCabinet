import { cva } from 'class-variance-authority'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { connectBridge, request } from '@/bridge'
import type { DialogData, DialogSnapshot, DialogsBridge, DialogValues } from '@/bridge-types'
import { Button } from '@/components/ui/button'
import { DialogFooter } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { NoticeStack } from '@/components/ui/notice'
import { ConfirmDialog } from '@/components/page-parts'
import { TagPicker } from '@/components/tag-picker'
import { Choice, DialogFrame, DialogList, TextArea } from './dialog-parts'
import { TranslationForm } from './TranslationForm'
import { RandomScopeForm, randomScopeReady } from './RandomScopeForm'

type FormValues = Omit<DialogValues, 'start' | 'end'> & { start: number | string; end: number | string }
type Draft = { form: FormValues; selected: string; member: string; available: string; scroll: number[] }

// 번역 설정·결과나 무작위 범위의 태그 후보가 늘어나도 본문만 스크롤해 확인/취소 단추는 항상 본문 아래에 남는다.
// 초점 테두리가 스크롤 가장자리에서 잘리지 않게 공용 DialogBody처럼 안쪽으로 조금 띄운다.
const body = cva('flex min-h-0 flex-col gap-4', { variants: { scroll: { true: '-m-1 overflow-y-auto p-1', false: '' } } })

export default function DialogsLayer() {
  const [bridge, setBridge] = useState<DialogsBridge | null>(null)
  const [state, setState] = useState<DialogSnapshot>({ dialog: null })
  const drafts = useRef(new Map<string, Draft>())
  useEffect(() => { if (!state.dialog) drafts.current.clear() }, [state.dialog])
  useEffect(() => {
    let live = true
    let disconnect = () => {}
    connectBridge().then(async ({ dialogs }) => {
      if (!live) return
      const changed = (json: string) => setState(JSON.parse(json))
      dialogs.dialogsChanged.connect(changed)
      disconnect = () => dialogs.dialogsChanged.disconnect(changed)
      const initial = await request<DialogSnapshot>(reply => dialogs.snapshot(reply))
      if (live) { setBridge(dialogs); setState(initial) }
    })
    return () => { live = false; disconnect() }
  }, [])
  return bridge && state.dialog ? <DialogBody key={state.dialog.id} bridge={bridge} data={state.dialog} drafts={drafts.current} /> : null
}

function DialogBody({ bridge, data, drafts }: { bridge: DialogsBridge; data: DialogData; drafts: Map<string, Draft> }) {
  const onSize = useCallback((width: number, height: number) => { void request(reply => bridge.contentSize(data.id, width, height, reply)) }, [bridge, data.id])
  const saved = drafts.get(data.id)
  const [form, setForm] = useState<FormValues>(saved?.form ?? data.values)
  const [selected, setSelected] = useState(saved?.selected ?? data.rows[0]?.id ?? '')
  const [member, setMember] = useState(saved?.member ?? form.members[0] ?? '')
  const [available, setAvailable] = useState(saved?.available ?? data.available.find(row => !form.members.includes(row.id))?.id ?? '')
  const content = useRef<HTMLDivElement>(null)
  const draft = useRef({ form, selected, member, available })
  useLayoutEffect(() => { draft.current = { form, selected, member, available } }, [form, selected, member, available])
  useLayoutEffect(() => {
    const lists = Array.from(content.current?.querySelectorAll('[role="listbox"]') ?? [])
    lists.forEach((list, index) => { list.scrollTop = drafts.get(data.id)?.scroll[index] ?? 0 })
    return () => { drafts.set(data.id, { ...draft.current, scroll: lists.map(list => list.scrollTop) }) }
  }, [data.id, drafts])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const composing = useRef(false)
  const currentSelected = data.rows.some(row => row.id === selected) ? selected : data.rows[0]?.id ?? ''
  const kind = data.kind
  useEffect(() => {
    if (kind !== 'range') return
    const timer = setTimeout(() => {
      void request(reply => bridge.act(data.id, 'bounds', JSON.stringify({ start: form.start, end: form.end }), reply)).catch(() => {})
    }, 100)
    return () => clearTimeout(timer)
  }, [bridge, data.id, kind, form.start, form.end])
  const update = (patch: Partial<FormValues>) => setForm(previous => ({ ...previous, ...patch }))
  async function act(action: string, payload: object = {}) {
    if (busyRef.current) return false
    busyRef.current = true; setBusy(true); setError('')
    try {
      await request<DialogSnapshot>(reply => bridge.act(data.id, action, JSON.stringify({ ...form, selected: currentSelected, ...payload }), reply))
      return true
    } catch (error) { setError(String(error)); return false }
    finally { busyRef.current = false; setBusy(false) }
  }
  const button = (label: string, action: string, disabled = false, variant: 'default' | 'outline' | 'destructive' = 'outline') =>
    <Button key={action} variant={variant} disabled={busy || disabled} onClick={() => void act(action, action === 'close' ? { accepted: !editable } : {})}>{label}</Button>
  const editable = ['series', 'tag-rename', 'highlight', 'subtitles', 'line', 'range', 'translation', 'video-rename', 'random-scope', 'onscreen-region'].includes(kind)
  const disabledEdit = data.locked || !currentSelected
  const members = form.members.map(id => data.available.find(row => row.id === id)).filter(row => row !== undefined)
  const others = data.available.filter(row => !form.members.includes(row.id))
  function move(offset: number) {
    const index = form.members.indexOf(member), target = index + offset
    if (index < 0 || target < 0 || target >= form.members.length) return
    const next = [...form.members]; [next[index], next[target]] = [next[target], next[index]]; update({ members: next })
  }
  if (kind === 'video-exclude') return <ConfirmDialog open onOpenChange={open => { if (!open) void act('cancel-confirm') }}
    title={data.confirm_title} description={data.confirmation} variant="destructive" onConfirm={() => void act('confirm')} />
  return <DialogFrame title={data.title} description={data.description} onClose={() => { if (!data.confirmation) void act('close') }} composing={composing} onSize={onSize} wide={['review', 'series', 'highlights'].includes(kind)}>
    <div ref={content} data-dialog-body={kind} className={body({ scroll: kind === 'translation' || kind === 'random-scope' })} onCompositionStart={() => { composing.current = true }} onCompositionEnd={() => { setTimeout(() => { composing.current = false }, 0) }}
      onKeyDown={event => {
        // 태그 고르기 검색 칸처럼 Enter를 먼저 쓴 입력(defaultPrevented)에서는 저장하지 않는다.
        if (editable && event.target instanceof HTMLInputElement && event.target.type !== 'checkbox'
          && event.key === 'Enter' && !event.defaultPrevented && !composing.current && !event.nativeEvent.isComposing && event.keyCode !== 229
          && !data.locked && !data.confirmation) { event.preventDefault(); void act('save') }
      }}>
      {kind === 'tags' && <TagPicker mode="immediate" label="태그" tags={data.tags} exclude={data.rows.map(row => Number(row.id))} listAll
        emptyText={data.tags.length ? '등록한 태그가 모두 붙어 있습니다. 새 이름을 입력해 붙이세요.' : '등록한 태그가 없습니다. 이름을 입력하고 Enter로 새 태그를 만드세요.'}
        onPick={tag => act('add', { name: tag.name })} onCreate={name => act('add', { name })} />}
      {['tags', 'tag-manager', 'highlights', 'review'].includes(kind) && <DialogList label={kind === 'review' ? `원어 · ${data.subtitle_label}` : kind === 'tags' ? '붙은 태그' : '목록'} rows={data.rows} selected={currentSelected} onSelect={setSelected}
        review={kind === 'review'} highlights={kind === 'highlights'} clickActivates={kind === 'review'}
        onActivate={kind === 'review' || kind === 'highlights' ? id => void act(kind === 'review' ? 'jump' : 'edit', { selected: id }) : undefined} />}
      {kind === 'series' && <>
        <Choice label="시리즈" rows={data.choices} value={form.choice} onChange={choice => void act('choose', { choice })} />
        <Input aria-label="시리즈 이름" placeholder="시리즈 이름" value={form.name} onChange={event => update({ name: event.target.value })} />
        <div className="flex min-h-0 min-w-0 gap-3"><DialogList label="시리즈 영상 순서" rows={members} selected={member} onSelect={setMember} />
          <div className="flex shrink-0 flex-col justify-center gap-2">
            <Button variant="outline" disabled={!others.some(row => row.id === available)} onClick={() => { update({ members: [...form.members, available] }); setMember(available); setAvailable(others.find(row => row.id !== available)?.id ?? '') }}>← 넣기</Button>
            <Button variant="outline" disabled={!form.members.includes(member)} onClick={() => { update({ members: form.members.filter(id => id !== member) }); setAvailable(member); setMember(form.members.find(id => id !== member) ?? '') }}>빼기 →</Button>
            <Button variant="outline" disabled={form.members.indexOf(member) <= 0} onClick={() => move(-1)}>위로</Button>
            <Button variant="outline" disabled={!member || form.members.indexOf(member) >= form.members.length - 1} onClick={() => move(1)}>아래로</Button>
          </div><DialogList label="넣을 수 있는 영상" rows={others} selected={available} onSelect={setAvailable} /></div>
      </>}
      {kind === 'tag-rename' && <Input aria-label="새 이름" value={form.name} onChange={event => update({ name: event.target.value })} />}
      {(kind === 'highlight' || kind === 'range') && <div className="grid grid-cols-2 gap-3">
        <label className="space-y-2 text-body">시작(초)<Input type="number" min={0} max={data.maximum} step={0.001} aria-label="시작(초)" value={form.start}
          onChange={event => update({ start: event.target.value })} onBlur={() => { if (form.start !== '') update({ start: Number(Number(form.start).toFixed(3)) }) }} /></label>
        <label className="space-y-2 text-body">끝(초)<Input type="number" min={0} max={data.maximum} step={0.001} aria-label="끝(초)" value={form.end} disabled={kind === 'highlight' && !form.range}
          onChange={event => update({ end: event.target.value })} onBlur={() => { if (form.end !== '') update({ end: Number(Number(form.end).toFixed(3)) }) }} /></label>
        {kind === 'highlight' && <label className="col-span-2 flex items-center gap-2 text-body"><input type="checkbox" checked={form.range} onChange={event => update({ range: event.target.checked })} />구간 하이라이트</label>}
      </div>}
      {(kind === 'highlight' || kind === 'line') && <label className="block space-y-2 text-body">{kind === 'highlight' ? '메모' : '자막 텍스트'}<TextArea value={form.text} onChange={text => update({ text })} /></label>}
      {kind === 'subtitles' && <label className="block space-y-2 text-body">원어<Input aria-label="원어" list="spoken-languages" value={form.choice} onChange={event => update({ choice: event.target.value })} /><datalist id="spoken-languages">{data.choices.map(row => <option key={row.id} value={row.title} />)}</datalist></label>}
      {kind === 'onscreen-region' && <Choice label="읽을 언어" rows={data.choices} value={form.choice} onChange={choice => update({ choice })} />}
      {kind === 'translation' && data.translation && <TranslationForm data={data.translation} form={form} update={update} act={act} busy={busy}
        request={{ pending: data.network_busy, information: data.information, warning: data.warning }} />}
      {kind === 'random-scope' && <RandomScopeForm data={data} values={form} update={update} />}
      {kind === 'video-rename' && <Input aria-label="영상 제목" value={form.name} onChange={event => update({ name: event.target.value })} />}
      {/* 대화상자 안내는 입력 아래 한곳에 쌓는다: 요청 실패(오류) → 확인할 점(경고) → 결과·설명(정보). 대화상자가 스크롤되므로 접지 않는다.
          번역 설정의 경고·정보는 키 확인·목록 조회 결과뿐이라 키 입력 아래에 보인다. */}
      <NoticeStack className="shrink-0" clamp={false} items={[
        error && { tone: 'error', message: error, onDismiss: () => setError('') },
        kind !== 'translation' && data.warning && { tone: 'warning', message: data.warning },
        kind !== 'translation' && data.information && { tone: 'info', message: data.information },
      ]} />
    </div>
    {/* 선택한 행에 대한 작업은 왼쪽, 대화상자를 끝내는 닫기·취소 → 주 작업은 오른쪽 끝에 둔다. 순서는 그대로다. */}
    <DialogFooter start={kind === 'tags' ? <>{button('선택한 태그 떼기', 'remove', !currentSelected)}{button('모든 태그 관리', 'manage')}</>
      : kind === 'tag-manager' ? <>{button('이름 변경', 'rename', !currentSelected, 'default')}{button('태그 삭제', 'delete', !currentSelected, 'destructive')}</>
      : kind === 'highlights' ? <>{button('시각·메모 편집', 'edit', !currentSelected, 'default')}{button('태그 편집', 'tags', !currentSelected)}{button('하이라이트 삭제', 'delete', !currentSelected, 'destructive')}</>
      : kind === 'review' ? <>{data.task_kind === 'refinement' && button(data.task_label, 'refine', data.locked)}{button('원어 줄 수정', 'edit-original', disabledEdit, 'default')}{button(`${data.short_label} 줄 수정`, 'edit-translation', disabledEdit)}{button('구간 다시 생성', 'range', data.locked)}{button('전체 다시 생성', 'regenerate', false, 'destructive')}{button('원어 SRT 저장', 'export-original', !data.rows.length)}{button(`${data.short_label} SRT 저장`, 'export-translation', !data.rows.length)}</>
      : undefined}>
      {button(editable ? '취소' : '닫기', 'close')}
      {editable && button(kind === 'range' ? '다시 생성' : kind === 'subtitles' ? '자막 만들기' : kind === 'onscreen-region' ? '화면 자막 만들기' : kind === 'translation' || kind === 'random-scope' ? '확인' : '저장', 'save',
        data.locked || data.network_busy || kind === 'range' && !!data.warning || kind === 'random-scope' && !randomScopeReady(data, form) || kind === 'onscreen-region' && !form.choice, kind === 'range' ? 'destructive' : 'default')}
    </DialogFooter>
    {data.keep_reviewed && <ConfirmDialog open onOpenChange={open => { if (!open) void act('cancel-confirm') }} title={data.confirm_title} description={data.confirmation}
      confirmLabel={`새 원어로 다시 ${data.task_label}`} cancelLabel="사용자 수정본 유지" onCancel={() => void act('keep-reviewed')}
      variant="destructive" onConfirm={() => void act('confirm')} />}
    <ConfirmDialog open={!!data.confirmation && !data.keep_reviewed} onOpenChange={open => { if (!open) void act('cancel-confirm') }} title={data.confirm_title} description={data.confirmation}
      variant={data.confirm_destructive ? 'destructive' : 'default'} onConfirm={() => void act('confirm')} />
  </DialogFrame>
}
