import { cva } from "class-variance-authority"

// 하이라이트 시각 글자. 글자 역할은 label-strong(DESIGN.md Typography)이고 색은 지점 highlight, 구간 highlight-range다.
// 영상 하이라이트 대화상자·상세 패널·모아보기가 모두 이 하나를 쓴다.
export const highlightTime = cva("text-label-strong tabular-nums", { variants: { range: { true: "text-highlight-range", false: "text-highlight" } } })
