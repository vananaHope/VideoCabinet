import type { ComponentType } from "react"
import type { Tab } from "@/bridge-types"
import type { KeyGuideGroup } from "@/lib/key-guide"
import LibraryPage from "./LibraryPage"
import RecommendPage from "./RecommendPage"
import QueuePage from "./QueuePage"
import StatisticsPage from "./StatisticsPage"
import ReelPage from "./ReelPage"
import SearchPage from "./SearchPage"
import FoldersPage from "./FoldersPage"
import SettingsPage from "./SettingsPage"
import { keyGuide as libraryKeys } from "./LibraryPage"
import { keyGuide as recommendKeys } from "./RecommendPage"
import { keyGuide as queueKeys } from "./QueuePage"
import { keyGuide as statisticsKeys } from "./StatisticsPage"
import { keyGuide as reelKeys } from "./ReelPage"
import { keyGuide as searchKeys } from "./SearchPage"
import { keyGuide as foldersKeys } from "./FoldersPage"
import { keyGuide as settingsKeys } from "./SettingsPage"

// 웹 페이지만 추가한다. Python 등록부와의 불일치는 계약 테스트가 검출한다.
export const pages = {
  library: LibraryPage,
  recommend: RecommendPage,
  queue: QueuePage,
  statistics: StatisticsPage,
  reel: ReelPage,
  search: SearchPage,
  folders: FoldersPage,
  settings: SettingsPage,
} satisfies Partial<Record<Tab, ComponentType>>

// 키 안내 '지금 화면'. 위 pages의 모든 페이지가 자기 키 목록을 한 줄로 등록한다. 빠지면 typecheck가 실패한다.
export const pageKeyGuides = {
  library: libraryKeys,
  recommend: recommendKeys,
  queue: queueKeys,
  statistics: statisticsKeys,
  reel: reelKeys,
  search: searchKeys,
  folders: foldersKeys,
  settings: settingsKeys,
} satisfies Record<keyof typeof pages, readonly KeyGuideGroup[]>
