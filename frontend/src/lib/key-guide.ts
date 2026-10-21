// 키 안내의 '지금 화면' 묶음. 각 페이지는 자기 키 목록을 pages/index.ts의 pageKeyGuides에 한 줄로 등록한다.
// 여기에는 키를 바꿀 수 없는 화면 키만 둔다. 바꿀 수 있는 키는 Python의 key_guide.py가 지금 키 배치에서 읽어 넘긴다.
// keys의 키 이름은 하나씩 따로 보인다. 같은 일을 하는 키를 한 줄에 묶는다.
export interface KeyGuideRow {
  keys: readonly string[]
  label: string
}

export interface KeyGuideGroup {
  title: string
  rows: readonly KeyGuideRow[]
}

// 라이브러리 격자·추천 줄이 같은 openKeyboardMenu를 쓴다.
export const menuKeyRow: KeyGuideRow = { keys: ["메뉴 키", "Shift+F10"], label: "작업 메뉴 열기 (우클릭과 같음)" }
