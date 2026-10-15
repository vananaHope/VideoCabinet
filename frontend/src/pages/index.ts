import type { ComponentType } from "react"
import type { Tab } from "@/bridge-types"
import LibraryPage from "./LibraryPage"
import QueuePage from "./QueuePage"
import StatisticsPage from "./StatisticsPage"

// 웹 페이지만 추가한다. Python 등록부와의 불일치는 계약 테스트가 검출한다.
export const pages = {
  library: LibraryPage,
  queue: QueuePage,
  statistics: StatisticsPage,
} satisfies Partial<Record<Tab, ComponentType>>
