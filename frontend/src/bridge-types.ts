// scripts/generate_web_types.py로 생성. web_contract.py의 페이지 계약을 수정하세요.

export type Reply = (json: string) => void
export type Signal<T> = { connect: (handler: (value: T) => void) => void; disconnect: (handler: (value: T) => void) => void }
export interface ShellData {
  tab: string
  status: string
}

export type Tab = "library" | "reel" | "search" | "queue" | "statistics" | "folders" | "settings"
export const tabs = [["library", "라이브러리"], ["reel", "모아보기"], ["search", "검색"], ["queue", "자막 대기열"], ["statistics", "통계"], ["folders", "폴더 관리"], ["settings", "설정"]] as const
export interface ShellBridge {
  ready: (reply: Reply) => void
  shellSnapshot: (reply: Reply) => void
  navigate: (tab: Tab, reply: Reply) => void
  shellChanged: Signal<string>
  shellStatusChanged: Signal<string>
  shellFocusRequested: Signal<string>
}
export function publicShellBridge(raw: ShellBridge): ShellBridge {
  return Object.freeze({
    ready: raw.ready.bind(raw),
    shellSnapshot: raw.shellSnapshot.bind(raw),
    navigate: raw.navigate.bind(raw),
    shellChanged: Object.freeze({ connect: raw.shellChanged.connect.bind(raw.shellChanged), disconnect: raw.shellChanged.disconnect.bind(raw.shellChanged) }),
    shellStatusChanged: Object.freeze({ connect: raw.shellStatusChanged.connect.bind(raw.shellStatusChanged), disconnect: raw.shellStatusChanged.disconnect.bind(raw.shellStatusChanged) }),
    shellFocusRequested: Object.freeze({ connect: raw.shellFocusRequested.connect.bind(raw.shellFocusRequested), disconnect: raw.shellFocusRequested.disconnect.bind(raw.shellFocusRequested) }),
  })
}

export interface TagData {
  id: number
  name: string
}

export interface VideoData {
  id: number
  title: string
  duration: number
  thumbnail: string | null
  missing: boolean
  locationCount: number
  finished: boolean
  abandoned: boolean
  favorite: boolean
  resumePoint: number | null
  stoppedPercent: number | null
  tags: Array<TagData>
  series: string
  viewingCount: number
  watchedSeconds: number
  lastViewedAt: string | null
  hasSubtitles: boolean
}

export interface GemData {
  videoId: number
  reason: string
}

export interface DetailsData {
  has_transcript: boolean
  spoken_language: string | null
  original_lines: number
  translated_lines: number
  subtitle_state: string | null
  translation_state: string | null
  highlight_count: number
}

export interface HighlightData {
  id: number
  start: number
  end: number | null
  note: string
  tags: Array<TagData>
}

export interface LibraryData {
  videos: Array<VideoData>
  tags: Array<TagData>
  gems: Array<GemData>
  gemError: string
  visibleIds: Array<number>
  selectedId: number | null
  scanning: boolean
}

export type Action = "play" | "tags" | "subtitles" | "review" | "series" | "rename" | "reconnect" | "exclude" | "playGem" | "dismiss"
export const actions = [["play", "재생"], ["tags", "태그 편집"], ["subtitles", "자막 만들기 / 원어 지정"], ["review", "자막 검수 / SRT 내보내기"], ["series", "시리즈 편집"], ["rename", "제목 변경"], ["reconnect", "파일 다시 연결"], ["exclude", "제외"]] as const
export const scanLockedActions: readonly Action[] = ["rename", "reconnect", "exclude"]
export interface LibraryBridge {
  ready: (reply: Reply) => void
  snapshot: (reply: Reply) => void
  filter: (query: string, tag: number, reply: Reply) => void
  select: (id: number, reply: Reply) => void
  details: (id: number, reply: Reply) => void
  action: (name: Action, id: number, reply: Reply) => void
  highlights: (videoId: number, reply: Reply) => void
  playHighlight: (videoId: number, highlightId: number, reply: Reply) => void
  editHighlight: (videoId: number, highlightId: number, reply: Reply) => void
  libraryChanged: Signal<string>
  libraryDetailsChanged: Signal<number>
  libraryFocusRequested: Signal<string>
  libraryError: Signal<string>
}
export function publicLibraryBridge(raw: LibraryBridge): LibraryBridge {
  return Object.freeze({
    ready: raw.ready.bind(raw),
    snapshot: raw.snapshot.bind(raw),
    filter: raw.filter.bind(raw),
    select: raw.select.bind(raw),
    details: raw.details.bind(raw),
    action: raw.action.bind(raw),
    highlights: raw.highlights.bind(raw),
    playHighlight: raw.playHighlight.bind(raw),
    editHighlight: raw.editHighlight.bind(raw),
    libraryChanged: Object.freeze({ connect: raw.libraryChanged.connect.bind(raw.libraryChanged), disconnect: raw.libraryChanged.disconnect.bind(raw.libraryChanged) }),
    libraryDetailsChanged: Object.freeze({ connect: raw.libraryDetailsChanged.connect.bind(raw.libraryDetailsChanged), disconnect: raw.libraryDetailsChanged.disconnect.bind(raw.libraryDetailsChanged) }),
    libraryFocusRequested: Object.freeze({ connect: raw.libraryFocusRequested.connect.bind(raw.libraryFocusRequested), disconnect: raw.libraryFocusRequested.disconnect.bind(raw.libraryFocusRequested) }),
    libraryError: Object.freeze({ connect: raw.libraryError.connect.bind(raw.libraryError), disconnect: raw.libraryError.disconnect.bind(raw.libraryError) }),
  })
}

export interface QueueRowData {
  videoId: number
  title: string
  state: string
  progress: number
  message: string
}

export interface QueueCountData {
  state: string
  label: string
  count: number
}

export interface QueueDeltaData {
  rows: Array<QueueRowData>
  removed: Array<number>
  order: Array<number> | null
  counts: Array<QueueCountData> | null
}

export interface QueueTargetData {
  key: string
  label: string
}

export interface QueueRuleData {
  id: number
  target: string
  label: string
  language: string
}

export interface QueueRulesData {
  targets: Array<QueueTargetData>
  rules: Array<QueueRuleData>
}

export type QueueAction = "promote" | "remove" | "retryFailed" | "retryHeld"
export const queueStates = [["queued", "대기"], ["transcribing", "받아쓰는 중"], ["translating", "번역 중"], ["held", "보류"], ["completed", "완료"], ["failed", "실패"]] as const
export interface QueueBridge {
  ready: (reply: Reply) => void
  snapshot: (reply: Reply) => void
  rulesSnapshot: (reply: Reply) => void
  action: (name: QueueAction, videoId: number, reply: Reply) => void
  candidates: (target: string, reply: Reply) => void
  saveRule: (target: string, language: string, includeExisting: boolean, reply: Reply) => void
  removeRule: (ruleId: number, reply: Reply) => void
  queueChanged: Signal<string>
  rulesChanged: Signal<string>
  queueFocusRequested: Signal<string>
  queueDeactivated: Signal<string>
}
export function publicQueueBridge(raw: QueueBridge): QueueBridge {
  return Object.freeze({
    ready: raw.ready.bind(raw),
    snapshot: raw.snapshot.bind(raw),
    rulesSnapshot: raw.rulesSnapshot.bind(raw),
    action: raw.action.bind(raw),
    candidates: raw.candidates.bind(raw),
    saveRule: raw.saveRule.bind(raw),
    removeRule: raw.removeRule.bind(raw),
    queueChanged: Object.freeze({ connect: raw.queueChanged.connect.bind(raw.queueChanged), disconnect: raw.queueChanged.disconnect.bind(raw.queueChanged) }),
    rulesChanged: Object.freeze({ connect: raw.rulesChanged.connect.bind(raw.rulesChanged), disconnect: raw.rulesChanged.disconnect.bind(raw.rulesChanged) }),
    queueFocusRequested: Object.freeze({ connect: raw.queueFocusRequested.connect.bind(raw.queueFocusRequested), disconnect: raw.queueFocusRequested.disconnect.bind(raw.queueFocusRequested) }),
    queueDeactivated: Object.freeze({ connect: raw.queueDeactivated.connect.bind(raw.queueDeactivated), disconnect: raw.queueDeactivated.disconnect.bind(raw.queueDeactivated) }),
  })
}

export interface ReelEntryData {
  id: number
  videoId: number
  title: string
  thumbnail: string | null
  start: number
  end: number | null
  lastRevisited: string | null
  note: string
  tags: Array<TagData>
  playable: boolean
  missing: boolean
}

export interface ReelData {
  entries: Array<ReelEntryData>
  tags: Array<TagData>
  tagId: number
  selectedId: number | null
  emptyTitle: string
  emptyDescription: string
  status: string
}

export interface ReelBridge {
  ready: (reply: Reply) => void
  snapshot: (reply: Reply) => void
  refresh: (reply: Reply) => void
  filter: (tagId: number, reply: Reply) => void
  select: (highlightId: number, reply: Reply) => void
  play: (highlightId: number, reply: Reply) => void
  changed: Signal<string>
  focusRequested: Signal<string>
  error: Signal<string>
}
export function publicReelBridge(raw: ReelBridge): ReelBridge {
  return Object.freeze({
    ready: raw.ready.bind(raw),
    snapshot: raw.snapshot.bind(raw),
    refresh: raw.refresh.bind(raw),
    filter: raw.filter.bind(raw),
    select: raw.select.bind(raw),
    play: raw.play.bind(raw),
    changed: Object.freeze({ connect: raw.changed.connect.bind(raw.changed), disconnect: raw.changed.disconnect.bind(raw.changed) }),
    focusRequested: Object.freeze({ connect: raw.focusRequested.connect.bind(raw.focusRequested), disconnect: raw.focusRequested.disconnect.bind(raw.focusRequested) }),
    error: Object.freeze({ connect: raw.error.connect.bind(raw.error), disconnect: raw.error.disconnect.bind(raw.error) }),
  })
}

export interface SearchTextData {
  text: string
  matched: boolean
}

export interface SearchResultData {
  videoId: number
  title: Array<SearchTextData>
  source: string
  text: Array<SearchTextData>
  start: number | null
  missing: boolean
}

export interface SearchData {
  query: string
  results: Array<SearchResultData>
  selectedIndex: number
  state: string
  truncated: boolean
  error: string
  limit: number
}

export interface SearchBridge {
  ready: (reply: Reply) => void
  snapshot: (reply: Reply) => void
  find: (query: string, reply: Reply) => void
  select: (index: number, reply: Reply) => void
  play: (index: number, reply: Reply) => void
  changed: Signal<string>
  focusRequested: Signal<string>
  error: Signal<string>
}
export function publicSearchBridge(raw: SearchBridge): SearchBridge {
  return Object.freeze({
    ready: raw.ready.bind(raw),
    snapshot: raw.snapshot.bind(raw),
    find: raw.find.bind(raw),
    select: raw.select.bind(raw),
    play: raw.play.bind(raw),
    changed: Object.freeze({ connect: raw.changed.connect.bind(raw.changed), disconnect: raw.changed.disconnect.bind(raw.changed) }),
    focusRequested: Object.freeze({ connect: raw.focusRequested.connect.bind(raw.focusRequested), disconnect: raw.focusRequested.disconnect.bind(raw.focusRequested) }),
    error: Object.freeze({ connect: raw.error.connect.bind(raw.error), disconnect: raw.error.disconnect.bind(raw.error) }),
  })
}

export interface Bridges {
  readonly shell: ShellBridge
  readonly library: LibraryBridge
  readonly queue: QueueBridge
  readonly reel: ReelBridge
  readonly search: SearchBridge
}
export function publicBridges(raw: Bridges): Bridges {
  return Object.freeze({
    shell: publicShellBridge(raw.shell),
    library: publicLibraryBridge(raw.library),
    queue: publicQueueBridge(raw.queue),
    reel: publicReelBridge(raw.reel),
    search: publicSearchBridge(raw.search),
  })
}
