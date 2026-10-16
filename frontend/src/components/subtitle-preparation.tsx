import { useEffect, useState } from 'react'
import { connectBridge, request } from '@/bridge'
import type { PreparationData, QueueBridge } from '@/bridge-types'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Notice, NoticeStack } from '@/components/ui/notice'

export default function SubtitlePreparation() {
  const [bridge, setBridge] = useState<QueueBridge | null>(null)
  const [data, setData] = useState<PreparationData | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let disposed = false
    let disconnect = () => {}
    connectBridge().then(async ({ queue }) => {
      if (disposed) return
      const changed = (json: string) => setData(JSON.parse(json))
      queue.preparationChanged.connect(changed)
      disconnect = () => queue.preparationChanged.disconnect(changed)
      const initial = await request<PreparationData>(reply => queue.preparationSnapshot(reply))
      if (!disposed) { setBridge(queue); setData(initial) }
    }).catch(error => setError(String(error)))
    return () => { disposed = true; disconnect() }
  }, [])
  if (!data || data.state === 'idle' || data.state === 'ready') return null
  function action(name: string) {
    setError('')
    if (bridge) request(reply => bridge.preparationAction(name, reply)).catch(error => setError(String(error)))
  }
  // 사용자가 취소한 준비는 실패가 아니라 다시 시도를 기다리는 상태다. 낭독 강도(role)는 위계를 따른다(오류만 alert).
  const failed = data.state === 'failed'
  const tone = failed ? data.kind === 'cancelled' ? 'warning' : 'error' : 'info'
  return <section aria-label="자막 기능 준비" className="flex flex-col gap-2 border-b px-4 py-2">
    <Notice tone={tone} title="자막 기능 준비" clamp={false}
      action={failed ? <Button size="sm" onClick={() => action('retry')}>다시 시도</Button> : <Button size="sm" variant="outline" disabled={data.state === 'cancelling'} onClick={() => action('cancel')}>취소</Button>}>
      <div className="flex min-w-0 items-start gap-3"><p className="line-clamp-2 min-w-0 flex-1" title={data.message}>{data.message}</p>{data.percent !== null && <span className="shrink-0 tabular-nums">{data.percentLabel}</span>}</div>
      {data.state === 'preparing' && <><p className="text-xs text-muted-foreground">{data.summary}</p><Progress value={data.percent} aria-label="자막 기능 준비 진행률" /></>}
      {data.guidance && <p className="text-xs text-muted-foreground">{data.guidance}</p>}
    </Notice>
    <NoticeStack items={[error && { tone: 'error', message: error, onDismiss: () => setError('') }]} />
  </section>
}
