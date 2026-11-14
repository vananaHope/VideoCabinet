import { RotateCcw } from 'lucide-react'
import { useState } from 'react'
import type { DialogValues, TranslationModelData, TranslationSettingsData } from '@/bridge-types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Notice, NoticeStack } from '@/components/ui/notice'
import { formatDate } from '@/lib/dates'
import { Choice } from './dialog-parts'

const rows = (items: { id: string; label: string }[]) => items.map(item => ({ id: item.id, title: item.label, detail: '', status: '', start: 0, end: null }))
// OpenCode Go는 키로 직접 번역하므로 목록 조회만 쓰고, 이어받기는 구독 CLI 방식에만 있다.
const DIRECT_PROVIDER = 'opencode_go'
const keyDraft = (form: Pick<DialogValues, 'key' | 'key_action'>) => `${form.key_action}:${form.key}`
const policyText = (model: TranslationModelData) => [model.policy,
  model.valid_until && `무보존 계약 만료: ${formatDate(model.valid_until)} (매월 갱신 확인 필요)`, model.policy_warning].filter(Boolean).join(' · ')

export function TranslationForm({ data, form, update, act, busy, request }: {
  data: TranslationSettingsData; form: Pick<DialogValues, 'choice' | 'selections' | 'fallback' | 'key' | 'key_action'>;
  update: (patch: Partial<DialogValues>) => void; act: (action: string) => Promise<boolean>; busy: boolean;
  /** 키 확인·모델 목록 조회의 진행과 결과. 대화상자 공용 안내 대신 키 입력 아래 한 자리에 보인다. */
  request: { pending: boolean; information: string; warning: string };
}) {
  const [notice, setNotice] = useState('')
  // 결과는 요청할 때의 키 초안에 대한 것이다. 키를 고치거나 지우면 지난 결과를 숨긴다.
  const [requested, setRequested] = useState(() => keyDraft(form))
  const selected = data.providers.find(p => p.id === form.choice)!
  const current = form.selections.find(s => s.provider === form.choice)!
  const model = selected.models.find(m => m.id === current.model) ?? selected.unknown_model
  const efforts = model.efforts
  const direct = form.choice === DIRECT_PROVIDER
  function selectModel(value: string) {
    const next = selected.models.find(m => m.id === value) ?? selected.unknown_model
    const effort = next.efforts.includes(current.effort) ? current.effort : ''
    setNotice(effort !== current.effort ? '지원하지 않는 추론 강도를 기본으로 되돌렸습니다.' : '')
    update({ selections: form.selections.map(s => s.provider === form.choice ? { ...s, model: value, effort } : s) })
  }
  function send(action: string) {
    setRequested(keyDraft(form))
    void act(action)
  }
  const registered = !!data.key_masked && form.key_action !== 'delete'
  const hasKey = registered || (form.key_action === 'replace' && !!form.key)
  const fresh = keyDraft(form) === requested
  return <div className="space-y-3" data-translation-form onKeyDown={event => {
    // 모델 직접 입력·키 편집의 Enter는 전체 대화상자를 저장하지 않는다.
    if (event.key === 'Enter' && event.target instanceof HTMLInputElement) event.stopPropagation()
  }}>
    {/* 읽는 순서대로 묶는다: 방식과 전송 안내 → 모델·추론 강도와 정책 → OpenCode Go 키와 확인 결과·이어받기. 대화상자가 스크롤되므로 안내는 접지 않는다. */}
    <fieldset disabled={busy || request.pending} className="space-y-3">
      <div className="space-y-2">
        <Choice label="번역 방식" rows={rows(data.providers)} value={form.choice} onChange={choice => { update({ choice }); setNotice('') }} />
        {selected.notice && <Notice tone="info" role="note" clamp={false}>{selected.notice}</Notice>}
      </div>
      <div className="space-y-2 border-t pt-3">
        <div className="grid grid-cols-2 gap-3">
          <p className="col-start-1 row-start-1 self-center text-body-strong">모델</p>
          <Choice label="모델 목록" rows={rows([
            ...(selected.cli_default ? [{ id: '', label: '기본(CLI 기본값)' }] : []),
            ...selected.models,
            ...(!selected.models.some(m => m.id === current.model) && current.model ? [{ id: current.model, label: current.model }] : []),
          ])} value={current.model} onChange={selectModel} />
          <label className="flex flex-col gap-2 text-body">모델 직접 입력<Input aria-label="모델 직접 입력" value={current.model} title={current.model} onChange={event => selectModel(event.target.value)} /></label>
          {efforts.length > 0 && <Choice label="추론 강도" rows={rows([{ id: '', label: '기본(모델 기본값)' }, ...efforts.map(id => ({ id, label: id }))])}
            value={current.effort} onChange={effort => update({ selections: form.selections.map(s => s.provider === form.choice ? { ...s, effort } : s) })} />}
          {/* 기본값 버튼은 제공자와 관계없이 묶음 머리 행 오른쪽 끝에 보인다. Tab은 입력 칸 다음에 오도록 DOM에서는 맨 뒤에 둔다. */}
          <Button variant="outline" size="xs" className="col-start-2 row-start-1 self-center justify-self-end" onClick={() => { setNotice(''); update({ selections: form.selections.map(s => s.provider === form.choice ? { ...s, model: selected.default_model, effort: '' } : s) }) }}>
            <RotateCcw aria-hidden="true" />모델·강도 기본값</Button>
        </div>
        {model.policy && <Notice tone={model.warning ? 'warning' : 'info'} role="note" aria-label="모델 정책" clamp={false}
          title={(model.training_warning || model.expired_warning) && <>
            {model.training_warning && <p>학습 사용 주의</p>}
            {model.expired_warning && <p>무보존 계약 만료 · 갱신 확인 필요</p>}
          </>}>{policyText(model)}</Notice>}
        {selected.expensive_efforts.includes(current.effort) && <Notice tone="warning" role="note" clamp={false}>{selected.effort_notice}</Notice>}
        {notice && <Notice tone="warning" clamp={false}>{notice}</Notice>}
      </div>
      <section className="space-y-2 border-t pt-3" aria-label="OpenCode Go 키">
        <p className="text-body-strong">OpenCode Go 키 · {form.key_action === 'delete' ? '삭제 예정' : form.key_action === 'replace' ? '교체 예정' : registered ? `등록됨 (${data.key_masked})` : '없음'}</p>
        <Input type="password" autoComplete="off" aria-label="OpenCode Go 키 입력" placeholder="새 키 입력 (확인할 때 저장)" value={form.key} onChange={event => update({ key: event.target.value, key_action: event.target.value ? 'replace' : 'keep', fallback: !data.key_masked && !form.key && !!event.target.value ? true : form.fallback })} />
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => send('check-key')}>키 확인</Button>
          {direct && <Button variant="outline" onClick={() => send('load-models')}>모델 목록 조회</Button>}
          <div className="ml-auto flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => update({ key: '', key_action: 'delete', fallback: false })}>키 지우기</Button>
            <Button variant="ghost" disabled={form.key_action === 'keep'} onClick={() => update({ key: '', key_action: 'keep' })}>키 편집 취소</Button>
          </div>
        </div>
        {/* 저장된 키 상태와 확인 결과는 이 한 자리에서 확인 중(정보) → 성공 · 실패(오류)로 바뀐다. */}
        <NoticeStack data-key-result clamp={false} items={[
          data.key_error && { tone: 'error', message: data.key_error },
          request.pending ? { tone: 'info', title: request.information, message: '취소하면 요청도 중단합니다.' }
            : fresh && request.warning ? { tone: 'error', message: request.warning }
            : fresh && request.information && { tone: 'success', message: request.information },
        ]} />
        {!direct && <>
          <label className="flex items-center gap-2 pt-1 text-body"><input type="checkbox" disabled={!hasKey} checked={hasKey && form.fallback} onChange={event => update({ fallback: event.target.checked })} />실패하면 OpenCode Go로 이어서</label>
          {data.fallback_notice && <Notice tone="info" size="compact" role="note">{data.fallback_notice}</Notice>}
        </>}
      </section>
    </fieldset>
    {busy && <Notice tone="info" clamp={false}>요청 처리 중… 취소하면 요청도 중단합니다.</Notice>}
  </div>
}
