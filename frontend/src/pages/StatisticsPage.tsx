import { EmptyState, PageHeader } from "@/components/page-parts"

export default function StatisticsPage() {
  return <main aria-label="통계" className="flex h-full min-h-0 flex-1 flex-col gap-6 p-6">
    <PageHeader title="통계" description="시청 기록과 라이브러리 현황을 살펴봅니다." />
    <EmptyState title="준비 중" description="통계 화면을 준비하고 있어요." variant="page" />
  </main>
}
