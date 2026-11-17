// scripts/generate_web_types.py로 생성. 페이지별 web_<name>_contract.py와 조립 지점 web_contract.py를 수정하세요.

export type Reply = (json: string) => void
export type Signal<T> = { connect: (handler: (value: T) => void) => void; disconnect: (handler: (value: T) => void) => void }
export interface GenerationData {
  generation: number
}

export interface ShellData {
  tab: string
  status: string
}

export interface ShellEntryData {
  tab: string
}

export interface KeyGuideEntryData {
  keys: Array<string>
  label: string
  detail: string
}

export interface KeyGuideData {
  app: Array<KeyGuideEntryData>
}

export interface UpdateNoticeData {
  version: string
  kind: string
  downloadSize: number
  releaseNotes: string | null
}

export interface UpdateInstallResultData {
  tone: string
  title: string
  message: string
  retry: string | null
  logPath: string | null
}

export interface UpdateInstallData {
  phase: string
  version: string | null
  kind: string | null
  received: number
  total: number | null
  confirmation: string
  failureMessage: string
  canRetry: boolean
  readyDismissed: boolean
  result: UpdateInstallResultData | null
}

export interface ShellUpdateData {
  notice: UpdateNoticeData | null
  install: UpdateInstallData
}

export type Tab = "library" | "recommend" | "reel" | "search" | "queue" | "statistics" | "folders" | "settings"
export type UpdateChoice = "update" | "later" | "skip" | "unskip"
export type UpdateAction = "cancel" | "install" | "later" | "retry" | "dismiss"
export const tabs = [["library", "라이브러리"], ["recommend", "추천"], ["reel", "모아보기"], ["search", "검색"], ["queue", "자막 대기열"], ["statistics", "통계"], ["folders", "폴더 관리"], ["settings", "설정"]] as const
export const appName = "VideoCabinet" as const
export interface ShellBridge {
  ready: (reply: Reply) => void
  shellSnapshot: (reply: Reply) => void
  navigate: (tab: Tab, reply: Reply) => void
  returnReady: (token: number, reply: Reply) => void
  returnFailed: (token: number, reply: Reply) => void
  updateSnapshot: (reply: Reply) => void
  updateChoice: (name: UpdateChoice, version: string, reply: Reply) => void
  updateAction: (name: UpdateAction, reply: Reply) => void
  keyGuide: (reply: Reply) => void
  shellChanged: Signal<string>
  shellStatusChanged: Signal<string>
  shellFocusRequested: Signal<string>
  shellPrepareReturn: Signal<number>
  shellUpdateChanged: Signal<string>
  shellUpdateInstallChanged: Signal<string>
  shellKeyGuideRequested: Signal<string>
}
export function publicShellBridge(raw: ShellBridge): ShellBridge {
  return Object.freeze({
    ready: raw.ready.bind(raw),
    shellSnapshot: raw.shellSnapshot.bind(raw),
    navigate: raw.navigate.bind(raw),
    returnReady: raw.returnReady.bind(raw),
    returnFailed: raw.returnFailed.bind(raw),
    updateSnapshot: raw.updateSnapshot.bind(raw),
    updateChoice: raw.updateChoice.bind(raw),
    updateAction: raw.updateAction.bind(raw),
    keyGuide: raw.keyGuide.bind(raw),
    shellChanged: Object.freeze({ connect: raw.shellChanged.connect.bind(raw.shellChanged), disconnect: raw.shellChanged.disconnect.bind(raw.shellChanged) }),
    shellStatusChanged: Object.freeze({ connect: raw.shellStatusChanged.connect.bind(raw.shellStatusChanged), disconnect: raw.shellStatusChanged.disconnect.bind(raw.shellStatusChanged) }),
    shellFocusRequested: Object.freeze({ connect: raw.shellFocusRequested.connect.bind(raw.shellFocusRequested), disconnect: raw.shellFocusRequested.disconnect.bind(raw.shellFocusRequested) }),
    shellPrepareReturn: Object.freeze({ connect: raw.shellPrepareReturn.connect.bind(raw.shellPrepareReturn), disconnect: raw.shellPrepareReturn.disconnect.bind(raw.shellPrepareReturn) }),
    shellUpdateChanged: Object.freeze({ connect: raw.shellUpdateChanged.connect.bind(raw.shellUpdateChanged), disconnect: raw.shellUpdateChanged.disconnect.bind(raw.shellUpdateChanged) }),
    shellUpdateInstallChanged: Object.freeze({ connect: raw.shellUpdateInstallChanged.connect.bind(raw.shellUpdateInstallChanged), disconnect: raw.shellUpdateInstallChanged.disconnect.bind(raw.shellUpdateInstallChanged) }),
    shellKeyGuideRequested: Object.freeze({ connect: raw.shellKeyGuideRequested.connect.bind(raw.shellKeyGuideRequested), disconnect: raw.shellKeyGuideRequested.disconnect.bind(raw.shellKeyGuideRequested) }),
  })
}

export interface TagData {
  id: number
  name: string
}

export interface TagUsageData {
  id: number
  name: string
  key: string
  videoCount: number
}

export interface TagCandidatesData {
  id: number
  videoIds: Array<number>
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
  modifiedAt: string | null
  hasSubtitles: boolean
}

export interface LibraryViewOptions {
  query: string
  mode: string
  folder: string
  tags: Array<number>
  viewing: string
  original: string
  translated: string
  external: boolean
  highlights: boolean
  missing: boolean
  added_preset: string
  added_from: string
  added_to: string
  modified_preset: string
  modified_from: string
  modified_to: string
  viewed_preset: string
  viewed_from: string
  viewed_to: string
  sort: string
  descending: boolean
  card_size: string
  collapsed_folders: Array<string>
}

export interface LibraryFolder {
  id: string
  parent: string
  name: string
  path: string
  count: number
  depth: number
}

export interface LibraryChipRange {
  start: string | null
  end: string | null
}

export interface LibraryChip {
  key: string
  label: string
  range: LibraryChipRange | null
  reset: LibraryViewOptions
}

export interface ExternalSubtitleTrackData {
  language: string | null
  languageLabel: string
  languageClass: string
  lineCount: number
}

export interface ExternalSubtitleFileData {
  id: number
  name: string
  folderLabel: string | null
  warning: string | null
  subtitles: Array<ExternalSubtitleTrackData>
}

export interface DetailsData {
  has_transcript: boolean
  spoken_language: string | null
  original_lines: number
  translated_lines: number
  taskLabel: string
  subtitleLabel: string
  subtitle_state: string | null
  translation_state: string | null
  highlight_count: number
  no_speech: boolean
  translation_skip_reason: string | null
  externalSubtitles: Array<ExternalSubtitleFileData>
}

export interface HighlightData {
  id: number
  start: number
  end: number | null
  note: string
  tags: Array<TagData>
}

export interface LibraryKeyBindingsData {
  randomPlay: string
  highlightGuidance: string
}

export interface LibraryData {
  generation: number
  videos: Array<VideoData>
  staleIds: Array<number>
  videoCount: number
  tags: Array<TagUsageData>
  visibleIds: Array<number>
  selectedId: number | null
  preserveSelection: boolean
  scanning: boolean
  options: LibraryViewOptions
  folders: Array<LibraryFolder>
  chips: Array<LibraryChip>
  keyBindings: LibraryKeyBindingsData
}

export interface LibraryVideosData {
  generation: number
  videos: Array<VideoData>
}

export interface LibraryEntryData {
  options: LibraryViewOptions
  chips: Array<LibraryChip>
}

export type Action = "play" | "tags" | "subtitles" | "review" | "series" | "rename" | "reconnect" | "exclude"
export const actions = [["play", "재생"], ["tags", "태그 편집"], ["subtitles", "자막 만들기 / 원어 지정"], ["review", "자막 검수 / SRT 내보내기"], ["series", "시리즈 편집"], ["rename", "제목 변경"], ["reconnect", "파일 다시 연결"], ["exclude", "제외"]] as const
export const scanLockedActions: readonly Action[] = ["rename", "reconnect", "exclude"]
export const libraryChoices = {"mode": [["all", "영상 전체"], ["folders", "폴더별"]], "viewing": [["", "모든 시청 상태"], ["unwatched", "안 봄"], ["abandoned", "보다 만"], ["finished", "다 봄"], ["favorite", "즐겨 보는 영상"]], "original": [["", "원어 자막 전체"], ["yes", "원어 자막 있음"], ["no", "원어 자막 없음"]], "translated": [["", "번역·다듬은 자막 전체"], ["yes", "번역·다듬은 자막 있음"], ["no", "번역·다듬은 자막 없음"]], "added_preset": [["", "추가일 전체"], ["today", "오늘"], ["7", "최근 7일"], ["30", "최근 30일"], ["custom", "직접 지정"]], "modified_preset": [["", "수정한 날짜 전체"], ["today", "오늘"], ["7", "최근 7일"], ["30", "최근 30일"], ["custom", "직접 지정"]], "viewed_preset": [["", "마지막 시청 전체"], ["today", "오늘"], ["7", "최근 7일"], ["30", "최근 30일"], ["custom", "직접 지정"]], "sort": [["title", "제목"], ["added", "추가일"], ["modified", "수정한 날짜"], ["viewed", "마지막 시청"], ["duration", "길이"], ["count", "시청 횟수"]], "card_size": [["small", "작게"], ["medium", "보통"], ["large", "크게"]]} as const
export const libraryFilterDefaults = {"query": "", "tags": [], "viewing": "", "original": "", "translated": "", "external": false, "highlights": false, "missing": false, "added_preset": "", "added_from": "", "added_to": "", "modified_preset": "", "modified_from": "", "modified_to": "", "viewed_preset": "", "viewed_from": "", "viewed_to": ""} as const
export const libraryViewDefaults: LibraryViewOptions = {"query": "", "mode": "all", "folder": "", "tags": [], "viewing": "", "original": "", "translated": "", "external": false, "highlights": false, "missing": false, "added_preset": "", "added_from": "", "added_to": "", "modified_preset": "", "modified_from": "", "modified_to": "", "viewed_preset": "", "viewed_from": "", "viewed_to": "", "sort": "title", "descending": false, "card_size": "medium", "collapsed_folders": []}
export interface LibraryBridge {
  ready: (reply: Reply) => void
  snapshot: (reply: Reply) => void
  videos: (ids: string, reply: Reply) => void
  filter: (query: string, tag: number, reply: Reply) => void
  view: (options: string, reply: Reply) => void
  select: (id: number, reply: Reply) => void
  clearSelection: (reply: Reply) => void
  details: (id: number, reply: Reply) => void
  action: (name: Action, id: number, reply: Reply) => void
  highlights: (videoId: number, reply: Reply) => void
  playHighlight: (videoId: number, highlightId: number, reply: Reply) => void
  editHighlight: (videoId: number, highlightId: number, reply: Reply) => void
  randomPlay: (reply: Reply) => void
  randomPlayAll: (reply: Reply) => void
  randomTagCandidates: (reply: Reply) => void
  randomPlayTags: (tagIds: string, reply: Reply) => void
  thumbnailsChanged: Signal<string>
  libraryChanged: Signal<string>
  libraryDetailsChanged: Signal<number>
  libraryFocusRequested: Signal<string>
  libraryError: Signal<string>
  libraryKeyBindingsChanged: Signal<string>
}
export function publicLibraryBridge(raw: LibraryBridge): LibraryBridge {
  return Object.freeze({
    ready: raw.ready.bind(raw),
    snapshot: raw.snapshot.bind(raw),
    videos: raw.videos.bind(raw),
    filter: raw.filter.bind(raw),
    view: raw.view.bind(raw),
    select: raw.select.bind(raw),
    clearSelection: raw.clearSelection.bind(raw),
    details: raw.details.bind(raw),
    action: raw.action.bind(raw),
    highlights: raw.highlights.bind(raw),
    playHighlight: raw.playHighlight.bind(raw),
    editHighlight: raw.editHighlight.bind(raw),
    randomPlay: raw.randomPlay.bind(raw),
    randomPlayAll: raw.randomPlayAll.bind(raw),
    randomTagCandidates: raw.randomTagCandidates.bind(raw),
    randomPlayTags: raw.randomPlayTags.bind(raw),
    thumbnailsChanged: Object.freeze({ connect: raw.thumbnailsChanged.connect.bind(raw.thumbnailsChanged), disconnect: raw.thumbnailsChanged.disconnect.bind(raw.thumbnailsChanged) }),
    libraryChanged: Object.freeze({ connect: raw.libraryChanged.connect.bind(raw.libraryChanged), disconnect: raw.libraryChanged.disconnect.bind(raw.libraryChanged) }),
    libraryDetailsChanged: Object.freeze({ connect: raw.libraryDetailsChanged.connect.bind(raw.libraryDetailsChanged), disconnect: raw.libraryDetailsChanged.disconnect.bind(raw.libraryDetailsChanged) }),
    libraryFocusRequested: Object.freeze({ connect: raw.libraryFocusRequested.connect.bind(raw.libraryFocusRequested), disconnect: raw.libraryFocusRequested.disconnect.bind(raw.libraryFocusRequested) }),
    libraryError: Object.freeze({ connect: raw.libraryError.connect.bind(raw.libraryError), disconnect: raw.libraryError.disconnect.bind(raw.libraryError) }),
    libraryKeyBindingsChanged: Object.freeze({ connect: raw.libraryKeyBindingsChanged.connect.bind(raw.libraryKeyBindingsChanged), disconnect: raw.libraryKeyBindingsChanged.disconnect.bind(raw.libraryKeyBindingsChanged) }),
  })
}

export interface RecommendationItemData {
  video: VideoData
  reason: string
}

export interface RecommendationRowData {
  key: string
  kind: string
  title: string
  items: Array<RecommendationItemData>
}

export interface RecommendData {
  generation: number
  loaded: boolean
  rows: Array<RecommendationRowData>
  error: string
}

export const recommendRowLimit: number = 20
export interface RecommendBridge {
  ready: (reply: Reply) => void
  snapshot: (reply: Reply) => void
  play: (videoId: number, reply: Reply) => void
  dismiss: (videoId: number, reply: Reply) => void
  restore: (videoId: number, reply: Reply) => void
  showDismissed: (reply: Reply) => void
  changed: Signal<string>
  focusRequested: Signal<string>
  error: Signal<string>
}
export function publicRecommendBridge(raw: RecommendBridge): RecommendBridge {
  return Object.freeze({
    ready: raw.ready.bind(raw),
    snapshot: raw.snapshot.bind(raw),
    play: raw.play.bind(raw),
    dismiss: raw.dismiss.bind(raw),
    restore: raw.restore.bind(raw),
    showDismissed: raw.showDismissed.bind(raw),
    changed: Object.freeze({ connect: raw.changed.connect.bind(raw.changed), disconnect: raw.changed.disconnect.bind(raw.changed) }),
    focusRequested: Object.freeze({ connect: raw.focusRequested.connect.bind(raw.focusRequested), disconnect: raw.focusRequested.disconnect.bind(raw.focusRequested) }),
    error: Object.freeze({ connect: raw.error.connect.bind(raw.error), disconnect: raw.error.disconnect.bind(raw.error) }),
  })
}

export interface PreparationData {
  state: string
  message: string
  phase: string
  asset: string
  completed: number
  total: number
  kind: string
  summary: string
  percent: number | null
  percentLabel: string
  guidance: string
}

export interface QueueRowData {
  key: string
  videoId: number
  queueKind: string
  title: string
  state: string
  progress: number
  message: string
  taskLabel: string
  stateLabel: string
}

export interface QueueCountData {
  state: string
  label: string
  count: number
}

export interface QueueData {
  generation: number
  canRetryFailed: boolean
  rows: Array<QueueRowData>
  counts: Array<QueueCountData>
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

export type QueueAction = "promote" | "remove" | "retryFailed" | "retryHeld" | "refineExisting" | "previewRefineExisting"
export const queueStates = [["queued", "대기"], ["transcribing", "받아쓰는 중"], ["reading", "읽는 중"], ["translating", "자막 처리 중"], ["held", "보류"], ["completed", "완료"], ["failed", "실패"]] as const
export interface QueueBridge {
  ready: (reply: Reply) => void
  snapshot: (reply: Reply) => void
  rulesSnapshot: (reply: Reply) => void
  preparationSnapshot: (reply: Reply) => void
  preparationAction: (action: string, reply: Reply) => void
  action: (name: QueueAction, videoId: number, queueKind: string, reply: Reply) => void
  candidates: (target: string, reply: Reply) => void
  saveRule: (target: string, language: string, includeExisting: boolean, reply: Reply) => void
  removeRule: (ruleId: number, reply: Reply) => void
  queueChanged: Signal<string>
  rulesChanged: Signal<string>
  queueFocusRequested: Signal<string>
  queueDeactivated: Signal<string>
  preparationChanged: Signal<string>
  bulkFinished: Signal<string>
}
export function publicQueueBridge(raw: QueueBridge): QueueBridge {
  return Object.freeze({
    ready: raw.ready.bind(raw),
    snapshot: raw.snapshot.bind(raw),
    rulesSnapshot: raw.rulesSnapshot.bind(raw),
    preparationSnapshot: raw.preparationSnapshot.bind(raw),
    preparationAction: raw.preparationAction.bind(raw),
    action: raw.action.bind(raw),
    candidates: raw.candidates.bind(raw),
    saveRule: raw.saveRule.bind(raw),
    removeRule: raw.removeRule.bind(raw),
    queueChanged: Object.freeze({ connect: raw.queueChanged.connect.bind(raw.queueChanged), disconnect: raw.queueChanged.disconnect.bind(raw.queueChanged) }),
    rulesChanged: Object.freeze({ connect: raw.rulesChanged.connect.bind(raw.rulesChanged), disconnect: raw.rulesChanged.disconnect.bind(raw.rulesChanged) }),
    queueFocusRequested: Object.freeze({ connect: raw.queueFocusRequested.connect.bind(raw.queueFocusRequested), disconnect: raw.queueFocusRequested.disconnect.bind(raw.queueFocusRequested) }),
    queueDeactivated: Object.freeze({ connect: raw.queueDeactivated.connect.bind(raw.queueDeactivated), disconnect: raw.queueDeactivated.disconnect.bind(raw.queueDeactivated) }),
    preparationChanged: Object.freeze({ connect: raw.preparationChanged.connect.bind(raw.preparationChanged), disconnect: raw.preparationChanged.disconnect.bind(raw.preparationChanged) }),
    bulkFinished: Object.freeze({ connect: raw.bulkFinished.connect.bind(raw.bulkFinished), disconnect: raw.bulkFinished.disconnect.bind(raw.bulkFinished) }),
  })
}

export interface ReelEntryData {
  id: number
  videoId: number
  title: string
  thumbnail: string | null
  start: number
  end: number | null
  lastRevisitedAt: string | null
  note: string
  tags: Array<TagData>
  playable: boolean
  missing: boolean
}

export interface ReelData {
  generation: number
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
  language: string | null
  languageLabel: string | null
  text: Array<SearchTextData>
  start: number | null
  missing: boolean
}

export interface SearchData {
  generation: number
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

export interface DailyViewingStatistics {
  date: string
  watched_seconds: number
  viewing_count: number
}

export interface TopViewedVideo {
  video_id: number
  title: string
  watched_seconds: number
  viewing_count: number
  excluded: boolean
  missing: boolean
}

export interface LibraryStatistics {
  finished_count: number
  abandoned_count: number
  unwatched_count: number
  subtitled_video_count: number
  highlight_count: number
}

export interface ViewingStatistics {
  days: number
  start_date: string
  end_date: string
  watched_seconds: number
  viewing_count: number
  previous_watched_seconds: number
  previous_viewing_count: number
  watched_seconds_change_percent: number | null
  viewing_count_change_percent: number | null
  watched_video_count: number
  watched_day_count: number
  longest_streak_days: number
  added_video_count: number
  average_seconds: number
  daily: Array<DailyViewingStatistics>
  top_videos: Array<TopViewedVideo>
  library: LibraryStatistics
}

export interface DistributionBucket {
  label: string
  video_count: number
}

export interface LibraryInventory {
  video_count: number
  duration_seconds: number
  known_size_bytes: number
  unknown_size_count: number
  all_watched_seconds: number
  korean_subtitled_count: number
  never_played_count: number
  highlighted_video_count: number
  tagged_video_count: number
  duration_distribution: Array<DistributionBucket>
  format_distribution: Array<DistributionBucket>
  resolution_distribution: Array<DistributionBucket>
  resolution_pending_count: number
  resolution_pending_description: string
}

export interface StatisticsDashboard {
  period: ViewingStatistics
  weekday_seconds: Array<number>
  hourly_seconds: Array<number>
  inventory: LibraryInventory
}

export interface StatisticsData {
  generation: number
  days: number
  loading: boolean
  message: string
  result: StatisticsDashboard | null
}

export interface StatisticsBridge {
  ready: (reply: Reply) => void
  snapshot: (reply: Reply) => void
  setPeriod: (days: number, reply: Reply) => void
  playVideo: (videoId: number, reply: Reply) => void
  statisticsChanged: Signal<string>
  statisticsFocusRequested: Signal<string>
}
export function publicStatisticsBridge(raw: StatisticsBridge): StatisticsBridge {
  return Object.freeze({
    ready: raw.ready.bind(raw),
    snapshot: raw.snapshot.bind(raw),
    setPeriod: raw.setPeriod.bind(raw),
    playVideo: raw.playVideo.bind(raw),
    statisticsChanged: Object.freeze({ connect: raw.statisticsChanged.connect.bind(raw.statisticsChanged), disconnect: raw.statisticsChanged.disconnect.bind(raw.statisticsChanged) }),
    statisticsFocusRequested: Object.freeze({ connect: raw.statisticsFocusRequested.connect.bind(raw.statisticsFocusRequested), disconnect: raw.statisticsFocusRequested.disconnect.bind(raw.statisticsFocusRequested) }),
  })
}

export interface TranslationSelectionData {
  provider: string
  model: string
  effort: string
}

export interface TranslationModelData {
  id: string
  label: string
  efforts: Array<string>
  policy: string
  valid_until: string | null
  policy_warning: string
  warning: boolean
  training_warning: boolean
  expired_warning: boolean
}

export interface TranslationProviderData {
  id: string
  label: string
  default_model: string
  notice: string
  models: Array<TranslationModelData>
  custom_efforts: Array<string>
  cli_default: boolean
  unknown_model: TranslationModelData
  expensive_efforts: Array<string>
  effort_notice: string
}

export interface TranslationSettingsData {
  provider: string
  selections: Array<TranslationSelectionData>
  providers: Array<TranslationProviderData>
  key_masked: string
  key_error: string
  fallback: boolean
  fallback_notice: string
}

export interface DialogRow {
  id: string
  title: string
  detail: string
  status: string
  start: number
  end: number | null
}

export interface DialogValues {
  name: string
  text: string
  start: number
  end: number
  range: boolean
  choice: string
  members: Array<string>
  selections: Array<TranslationSelectionData>
  fallback: boolean
  key_action: string
  key: string
  series: boolean
}

export interface DialogData {
  id: string
  kind: string
  title: string
  description: string
  rows: Array<DialogRow>
  tags: Array<TagUsageData>
  tag_candidates: Array<TagCandidatesData>
  available: Array<DialogRow>
  exports: Array<DialogRow>
  choices: Array<DialogRow>
  values: DialogValues
  maximum: number
  locked: boolean
  warning: string
  confirmation: string
  confirm_title: string
  confirm_destructive: boolean
  translation: TranslationSettingsData | null
  network_busy: boolean
  information: string
  task_kind: string
  task_label: string
  subtitle_label: string
  short_label: string
  keep_reviewed: boolean
  series_label: string
  series_note: string
  series_information: string
}

export interface DialogSnapshot {
  dialog: DialogData | null
}

export interface DialogsBridge {
  snapshot: (reply: Reply) => void
  modalState: (open: number, reply: Reply) => void
  contentSize: (id: string, width: number, height: number, reply: Reply) => void
  act: (id: string, action: string, payload: string, reply: Reply) => void
  dialogsChanged: Signal<string>
}
export function publicDialogsBridge(raw: DialogsBridge): DialogsBridge {
  return Object.freeze({
    snapshot: raw.snapshot.bind(raw),
    modalState: raw.modalState.bind(raw),
    contentSize: raw.contentSize.bind(raw),
    act: raw.act.bind(raw),
    dialogsChanged: Object.freeze({ connect: raw.dialogsChanged.connect.bind(raw.dialogsChanged), disconnect: raw.dialogsChanged.disconnect.bind(raw.dialogsChanged) }),
  })
}

export interface RestorableVideoData {
  id: number
  title: string
  missing: boolean
  excluded: boolean
}

export interface ScanIssueData {
  path: string
  message: string
}

export interface ScanReportData {
  revision: number
  dismissible: boolean
  message: string
  failed: boolean
  failures: Array<ScanIssueData>
  subtitleWarnings: Array<ScanIssueData>
  notes: Array<ScanIssueData>
}

export interface FoldersData {
  generation: number
  folders: Array<string>
  excluded: Array<RestorableVideoData>
  dismissed: Array<RestorableVideoData>
  minimum: number
  scanning: boolean
  report: ScanReportData
  automaticDetection: boolean
  unwatched: Array<string>
  watchStartFailed: boolean
}

export type FolderAction = "addFolder" | "removeFolder" | "scan" | "addFile" | "restoreExcluded" | "restoreDismissed" | "manageTags"
export type ScanNoticeGroup = "failures" | "subtitleWarnings" | "summary"
export interface FoldersBridge {
  ready: (reply: Reply) => void
  snapshot: (reply: Reply) => void
  action: (name: FolderAction, target: string, reply: Reply) => void
  setMinimum: (seconds: number, reply: Reply) => void
  dismissReport: (revision: number, group: ScanNoticeGroup, reply: Reply) => void
  foldersChanged: Signal<string>
  foldersFocusRequested: Signal<string>
  foldersError: Signal<string>
}
export function publicFoldersBridge(raw: FoldersBridge): FoldersBridge {
  return Object.freeze({
    ready: raw.ready.bind(raw),
    snapshot: raw.snapshot.bind(raw),
    action: raw.action.bind(raw),
    setMinimum: raw.setMinimum.bind(raw),
    dismissReport: raw.dismissReport.bind(raw),
    foldersChanged: Object.freeze({ connect: raw.foldersChanged.connect.bind(raw.foldersChanged), disconnect: raw.foldersChanged.disconnect.bind(raw.foldersChanged) }),
    foldersFocusRequested: Object.freeze({ connect: raw.foldersFocusRequested.connect.bind(raw.foldersFocusRequested), disconnect: raw.foldersFocusRequested.disconnect.bind(raw.foldersFocusRequested) }),
    foldersError: Object.freeze({ connect: raw.foldersError.connect.bind(raw.foldersError), disconnect: raw.foldersError.disconnect.bind(raw.foldersError) }),
  })
}

export interface UpdateResultData {
  checkedAt: string
  kind: string
  currentVersion: string | null
  latestVersion: string | null
  downloadSize: number | null
  failureReason: string | null
  failureMessage: string
  releaseNotes: string | null
  failureQuiet: boolean
  stale: boolean
}

export interface UpdateStatusData {
  installedVersion: string
  automatic: boolean
  checking: boolean
  error: string
  last: UpdateResultData | null
  skipped: boolean
  noticeVisible: boolean
  updateAllowed: boolean
}

export interface SettingKeyData {
  id: string
  label: string
  keys: Array<string>
  defaults: Array<string>
  display: string
  defaultDisplay: string
  note: string
}

export interface RecommendationPeriodData {
  criterion: string
  label: string
  description: string
  days: number | null
  error: string
  defaultDays: number
  minimumDays: number
  maximumDays: number
}

export interface SettingsData {
  generation: number
  version: string
  releasesUrl: string
  bindings: Array<SettingKeyData>
  minimum: number
  scanning: boolean
  automaticDetection: boolean
  recommendationPeriods: Array<RecommendationPeriodData>
  translationCli: string
  translation: TranslationSettingsData
  heldTranslations: number
  failedTranslations: number
  update: UpdateStatusData
}

export interface CapturedKeyData {
  command: string
  key: string
  display: string
  cancelled: boolean
  error: string
  continuing: boolean
}

export interface BackupMetadataData {
  app_version: string
  db_version: number
  created_at: string
  video_count: number
  includes_thumbnails: boolean
  version_message: string
}

export interface AutomaticBackupData {
  path: string
  created_at: string
  size: number
  reason: string
  error: string
}

export interface BackupStartupData {
  status: string
  error: string
  guidance: string
  safety_backup: string
  rejected_path: string
}

export interface BackupData {
  busy: boolean
  operation: string
  message: string
  failure: string
  preview: BackupMetadataData | null
  previewPath: string
  pending: boolean
  pendingDeferred: boolean
  pendingPath: string
  startup: BackupStartupData | null
  automatic: Array<AutomaticBackupData>
  folder: string
  dbVersion: number
  keep: number
  guidance: string
}

export type SettingsAction = "translation" | "quit" | "releases"
export type BackupAction = "refresh" | "create" | "choose" | "preview" | "schedule" | "discard" | "cancel" | "restart" | "openFolder"
export interface SettingsBridge {
  ready: (reply: Reply) => void
  snapshot: (reply: Reply) => void
  saveKeys: (draft: string, reply: Reply) => void
  beginCapture: (command: string, reply: Reply) => void
  captureKey: (key: string, reply: Reply) => void
  cancelCapture: (reply: Reply) => void
  setMinimum: (seconds: number, reply: Reply) => void
  setAutomaticDetection: (enabled: boolean, reply: Reply) => void
  setRecommendationPeriod: (criterion: string, days: string, reply: Reply) => void
  resetRecommendationPeriod: (criterion: string, reply: Reply) => void
  checkUpdate: (reply: Reply) => void
  setAutomaticUpdateCheck: (enabled: boolean, reply: Reply) => void
  action: (name: SettingsAction, reply: Reply) => void
  backupSnapshot: (reply: Reply) => void
  backupAction: (name: BackupAction, target: string, includeThumbnails: boolean, reply: Reply) => void
  settingsChanged: Signal<string>
  settingsFocusRequested: Signal<string>
  keyCaptured: Signal<string>
  settingsError: Signal<string>
  backupChanged: Signal<string>
}
export function publicSettingsBridge(raw: SettingsBridge): SettingsBridge {
  return Object.freeze({
    ready: raw.ready.bind(raw),
    snapshot: raw.snapshot.bind(raw),
    saveKeys: raw.saveKeys.bind(raw),
    beginCapture: raw.beginCapture.bind(raw),
    captureKey: raw.captureKey.bind(raw),
    cancelCapture: raw.cancelCapture.bind(raw),
    setMinimum: raw.setMinimum.bind(raw),
    setAutomaticDetection: raw.setAutomaticDetection.bind(raw),
    setRecommendationPeriod: raw.setRecommendationPeriod.bind(raw),
    resetRecommendationPeriod: raw.resetRecommendationPeriod.bind(raw),
    checkUpdate: raw.checkUpdate.bind(raw),
    setAutomaticUpdateCheck: raw.setAutomaticUpdateCheck.bind(raw),
    action: raw.action.bind(raw),
    backupSnapshot: raw.backupSnapshot.bind(raw),
    backupAction: raw.backupAction.bind(raw),
    settingsChanged: Object.freeze({ connect: raw.settingsChanged.connect.bind(raw.settingsChanged), disconnect: raw.settingsChanged.disconnect.bind(raw.settingsChanged) }),
    settingsFocusRequested: Object.freeze({ connect: raw.settingsFocusRequested.connect.bind(raw.settingsFocusRequested), disconnect: raw.settingsFocusRequested.disconnect.bind(raw.settingsFocusRequested) }),
    keyCaptured: Object.freeze({ connect: raw.keyCaptured.connect.bind(raw.keyCaptured), disconnect: raw.keyCaptured.disconnect.bind(raw.keyCaptured) }),
    settingsError: Object.freeze({ connect: raw.settingsError.connect.bind(raw.settingsError), disconnect: raw.settingsError.disconnect.bind(raw.settingsError) }),
    backupChanged: Object.freeze({ connect: raw.backupChanged.connect.bind(raw.backupChanged), disconnect: raw.backupChanged.disconnect.bind(raw.backupChanged) }),
  })
}

export interface Bridges {
  readonly shell: ShellBridge
  readonly library: LibraryBridge
  readonly recommend: RecommendBridge
  readonly queue: QueueBridge
  readonly reel: ReelBridge
  readonly search: SearchBridge
  readonly statistics: StatisticsBridge
  readonly dialogs: DialogsBridge
  readonly folders: FoldersBridge
  readonly settings: SettingsBridge
}
export function publicBridges(raw: Bridges): Bridges {
  return Object.freeze({
    shell: publicShellBridge(raw.shell),
    library: publicLibraryBridge(raw.library),
    recommend: publicRecommendBridge(raw.recommend),
    queue: publicQueueBridge(raw.queue),
    reel: publicReelBridge(raw.reel),
    search: publicSearchBridge(raw.search),
    statistics: publicStatisticsBridge(raw.statistics),
    dialogs: publicDialogsBridge(raw.dialogs),
    folders: publicFoldersBridge(raw.folders),
    settings: publicSettingsBridge(raw.settings),
  })
}
