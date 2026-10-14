// scripts/generate_web_types.py로 생성. Python TypedDict를 수정하세요.

export interface TagData {
  id: number
  name: string
}

export interface ShellData {
  tab: string
  status: string
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

export interface HighlightData {
  id: number
  start: number
  end: number | null
  note: string
  tags: Array<TagData>
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
export type Tab = "library" | "reel" | "search" | "queue" | "statistics" | "folders" | "settings"
export const tabs = [["library", "라이브러리"], ["reel", "모아보기"], ["search", "검색"], ["queue", "자막 대기열"], ["statistics", "통계"], ["folders", "폴더 관리"], ["settings", "설정"]] as const
export const actions = [["play", "재생"], ["tags", "태그 편집"], ["subtitles", "자막 만들기 / 원어 지정"], ["review", "자막 검수 / SRT 내보내기"], ["series", "시리즈 편집"], ["rename", "제목 변경"], ["reconnect", "파일 다시 연결"], ["exclude", "제외"]] as const
export const scanLockedActions: readonly Action[] = ["rename", "reconnect", "exclude"]
export type Reply = (json: string) => void
export type Signal<T> = { connect: (handler: (value: T) => void) => void; disconnect: (handler: (value: T) => void) => void }
export interface Bridge {
  ready: (reply: Reply) => void
  snapshot: (reply: Reply) => void
  filter: (query: string, tag: number, reply: Reply) => void
  select: (id: number, reply: Reply) => void
  details: (id: number, reply: Reply) => void
  action: (name: Action, id: number, reply: Reply) => void
  shellSnapshot: (reply: Reply) => void
  navigate: (tab: Tab, reply: Reply) => void
  highlights: (videoId: number, reply: Reply) => void
  playHighlight: (videoId: number, highlightId: number, reply: Reply) => void
  editHighlight: (videoId: number, highlightId: number, reply: Reply) => void
  libraryChanged: Signal<string>
  libraryDetailsChanged: Signal<number>
  libraryFocusRequested: Signal<string>
  libraryError: Signal<string>
  shellChanged: Signal<string>
  shellStatusChanged: Signal<string>
}
export function publicBridge(raw: Bridge): Bridge {
  return Object.freeze({
    ready: raw.ready.bind(raw),
    snapshot: raw.snapshot.bind(raw),
    filter: raw.filter.bind(raw),
    select: raw.select.bind(raw),
    details: raw.details.bind(raw),
    action: raw.action.bind(raw),
    shellSnapshot: raw.shellSnapshot.bind(raw),
    navigate: raw.navigate.bind(raw),
    highlights: raw.highlights.bind(raw),
    playHighlight: raw.playHighlight.bind(raw),
    editHighlight: raw.editHighlight.bind(raw),
    libraryChanged: Object.freeze({ connect: raw.libraryChanged.connect.bind(raw.libraryChanged), disconnect: raw.libraryChanged.disconnect.bind(raw.libraryChanged) }),
    libraryDetailsChanged: Object.freeze({ connect: raw.libraryDetailsChanged.connect.bind(raw.libraryDetailsChanged), disconnect: raw.libraryDetailsChanged.disconnect.bind(raw.libraryDetailsChanged) }),
    libraryFocusRequested: Object.freeze({ connect: raw.libraryFocusRequested.connect.bind(raw.libraryFocusRequested), disconnect: raw.libraryFocusRequested.disconnect.bind(raw.libraryFocusRequested) }),
    libraryError: Object.freeze({ connect: raw.libraryError.connect.bind(raw.libraryError), disconnect: raw.libraryError.disconnect.bind(raw.libraryError) }),
    shellChanged: Object.freeze({ connect: raw.shellChanged.connect.bind(raw.shellChanged), disconnect: raw.shellChanged.disconnect.bind(raw.shellChanged) }),
    shellStatusChanged: Object.freeze({ connect: raw.shellStatusChanged.connect.bind(raw.shellStatusChanged), disconnect: raw.shellStatusChanged.disconnect.bind(raw.shellStatusChanged) }),
  })
}
