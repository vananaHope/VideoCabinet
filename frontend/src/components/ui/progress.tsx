import type { ComponentProps } from 'react'

export function Progress({ value, ...props }: ComponentProps<'svg'> & { value: number | null }) {
  return <svg {...props} viewBox="0 0 100 8" preserveAspectRatio="none" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value ?? undefined} className="h-2 w-full rounded-full border border-border bg-background"><rect width={value ?? 0} height={8} className="fill-primary" /></svg>
}
