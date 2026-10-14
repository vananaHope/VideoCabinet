// scripts/generate_web_types.py로 생성. Python TypedDict를 수정하세요.

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
