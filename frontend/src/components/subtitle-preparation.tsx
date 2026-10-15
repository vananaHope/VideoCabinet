import { useEffect, useState } from 'react'
import { connectBridge, request } from '@/bridge'
import type { PreparationData, QueueBridge } from '@/bridge-types'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'

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
  return <section aria-label="자막 기능 준비" className="shrink-0 space-y-2 border-b bg-card px-4 py-3">
    <div className="flex items-center justify-between gap-4"><h2 className="text-sm font-semibold">자막 기능 준비</h2>
      {data.state === 'failed' ? <Button size="sm" onClick={() => action('retry')}>다시 시도</Button> : <Button size="sm" variant="outline" disabled={data.state === 'cancelling'} onClick={() => action('cancel')}>취소</Button>}
    </div>
    <div className="flex min-w-0 items-center gap-3"><p role={data.state === 'failed' ? 'alert' : 'status'} className="min-w-0 flex-1 truncate text-sm text-muted-foreground" title={data.message}>{data.message}</p>{data.percent !== null && <span className="shrink-0 text-sm tabular-nums">{data.percentLabel}</span>}</div>
    {data.state === 'preparing' && <><p className="text-xs text-muted-foreground">{data.summary}</p><Progress value={data.percent} aria-label="자막 기능 준비 진행률" /></>}
    {data.guidance && <p className="text-xs text-muted-foreground">{data.guidance}</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </section>
}
