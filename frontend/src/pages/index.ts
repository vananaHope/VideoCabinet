import type { ComponentType } from "react"
import type { Tab } from "@/bridge-types"
import LibraryPage from "./LibraryPage"
import StatisticsPage from "./StatisticsPage"

// null은 기존 Qt 화면으로 열리는 탭이다. 누락/오타는 typecheck에서 실패한다.
export const pages = {
  library: LibraryPage,
  reel: null,
  search: null,
  queue: null,
  statistics: StatisticsPage,
  folders: null,
  settings: null,
} satisfies Record<Tab, ComponentType | null>
