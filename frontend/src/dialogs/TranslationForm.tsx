import { useState } from 'react'
import type { DialogValues, TranslationSettingsData } from '@/bridge-types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Choice } from './dialog-parts'

const rows = (items: { id: string; label: string }[]) => items.map(item => ({ id: item.id, title: item.label, detail: '', status: '', start: 0, end: null }))

export function TranslationForm({ data, form, update, act, busy }: {
  data: TranslationSettingsData; form: Pick<DialogValues, 'choice' | 'selections' | 'fallback' | 'key' | 'key_action'>;
  update: (patch: Partial<DialogValues>) => void; act: (action: string) => Promise<boolean>; busy: boolean;
}) {
  const [notice, setNotice] = useState('')
  const selected = data.providers.find(p => p.id === form.choice)!
  const current = form.selections.find(s => s.provider === form.choice)!
  const model = selected.models.find(m => m.id === current.model) ?? selected.unknown_model
  const efforts = model.efforts
  function selectModel(value: string) {
    const next = selected.models.find(m => m.id === value) ?? selected.unknown_model
    const effort = next.efforts.includes(current.effort) ? current.effort : ''
    setNotice(effort !== current.effort ? '지원하지 않는 추론 강도를 기본으로 되돌렸습니다.' : '')
    update({ selections: form.selections.map(s => s.provider === form.choice ? { ...s, model: value, effort } : s) })
  }
  const registered = !!data.key_masked && form.key_action !== 'delete'
  const hasKey = registered || (form.key_action === 'replace' && !!form.key)
  return <div className="space-y-3" data-translation-form onKeyDown={event => {
    // 모델 직접 입력·키 편집의 Enter는 전체 대화상자를 저장하지 않는다.
    if (event.key === 'Enter' && event.target instanceof HTMLInputElement) event.stopPropagation()
  }}>
    <fieldset disabled={busy} className="space-y-3">
      <Choice label="번역 방식" rows={rows(data.providers)} value={form.choice} onChange={choice => { update({ choice }); setNotice('') }} />
      <div className="grid grid-cols-2 gap-3">
        <Choice label="모델 목록" rows={rows([
          ...(selected.cli_default ? [{ id: '', label: '기본(CLI 기본값)' }] : []),
          ...selected.models,
          ...(!selected.models.some(m => m.id === current.model) && current.model ? [{ id: current.model, label: current.model }] : []),
        ])} value={current.model} onChange={selectModel} />
        <label className="space-y-2 text-sm">모델 직접 입력<Input aria-label="모델 직접 입력" value={current.model} title={current.model} onChange={event => selectModel(event.target.value)} /></label>
      </div>
      {efforts.length > 0 && <Choice label="추론 강도" rows={rows([{ id: '', label: '기본(모델 기본값)' }, ...efforts.map(id => ({ id, label: id }))])}
        value={current.effort} onChange={effort => update({ selections: form.selections.map(s => s.provider === form.choice ? { ...s, effort } : s) })} />}
      {selected.expensive_efforts.includes(current.effort) && <p className="text-sm text-muted-foreground">{selected.effort_notice}</p>}
      {notice && <p role="status" className="text-sm text-destructive">{notice}</p>}
      <p className="text-sm text-muted-foreground">{selected.notice}</p>
      {model.policy && <div role="note" className={`space-y-2 whitespace-pre-wrap break-words rounded-md border p-2 text-sm ${model.warning ? 'border-destructive' : ''}`}>
        {model.training_warning && <p className="rounded bg-destructive px-2 py-1 text-destructive-foreground">학습 사용 주의</p>}
        {model.expired_warning && <p className="rounded bg-highlight px-2 py-1 text-highlight-foreground">무보존 계약 만료 · 갱신 확인 필요</p>}
        <p>{model.policy}</p>
      </div>}
      <section className="space-y-2 rounded-md border p-3" aria-label="OpenCode Go 키">
        <p className="text-sm font-medium">OpenCode Go 키 · {form.key_action === 'delete' ? '삭제 예정' : form.key_action === 'replace' ? '교체 예정' : registered ? `등록됨 (${data.key_masked})` : '없음'}</p>
        <Input type="password" autoComplete="off" aria-label="OpenCode Go 키 입력" placeholder="새 키 입력 (확인할 때 저장)" value={form.key} onChange={event => update({ key: event.target.value, key_action: event.target.value ? 'replace' : 'keep', fallback: !data.key_masked && !form.key && !!event.target.value ? true : form.fallback })} />
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => void act('check-key')}>키 확인</Button>
          <Button variant="outline" onClick={() => void act('load-models')}>모델 목록 조회</Button>
          <Button variant="outline" onClick={() => update({ key: '', key_action: 'delete', fallback: false })}>키 지우기</Button>
          <Button variant="ghost" onClick={() => update({ key: '', key_action: 'keep' })}>키 편집 취소</Button>
        </div>
        {data.key_error && <p className="text-sm text-destructive">{data.key_error}</p>}
      </section>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={!hasKey} checked={hasKey && form.fallback} onChange={event => update({ fallback: event.target.checked })} />실패하면 OpenCode Go로 이어서</label>
      <p className="text-xs text-muted-foreground">{data.fallback_notice}</p>
      <Button variant="ghost" onClick={() => { setNotice(''); update({ selections: form.selections.map(s => s.provider === form.choice ? { ...s, model: selected.default_model, effort: '' } : s) }) }}>이 방식의 모델·강도 기본값</Button>
    </fieldset>
    {busy && <p role="status" className="text-sm">요청 처리 중… 취소하면 요청도 중단합니다.</p>}
  </div>
}
