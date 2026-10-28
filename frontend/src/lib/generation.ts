import { useState } from "react"
import type { GenerationData } from "@/bridge-types"

/**
 * 페이지 상태 메시지의 공용 세대 가드(#265). 브리지는 페이지마다 밀어 보내는 changed와 요청 응답에
 * 하나씩 올라가는 세대를 붙인다. 마지막으로 반영한 세대보다 오래된 메시지는 늦게 도착한 것이므로 버린다.
 * 요청을 보낸 뒤 더 새 세대의 changed를 먼저 반영했으면 그 응답도 같은 규칙으로 버린다.
 * 세대는 그 메시지가 담은 상태마다 비교한다. 한 페이지가 상태 일부만 담은 응답도 보내면(라이브러리의 보기 응답)
 * 담은 상태마다 가드를 따로 두어, 더 새 일부 응답 때문에 그보다 앞선 전체 상태의 나머지를 버리지 않게 한다.
 * 검색어 비교·검사 안내 revision·재생 복귀 토큰처럼 뜻이 있는 규칙은 각 페이지에 그대로 둔다.
 */
export function generationGuard() {
  let applied = 0
  return (message: GenerationData) => {
    if (message.generation <= applied) return false
    applied = message.generation
    return true
  }
}

/** 페이지가 사는 동안 유지되는 가드. 같은 상태를 담는 신호 연결과 요청 응답이 같은 것을 쓴다. 반영할 메시지면 true. */
export function useGenerationGuard() {
  return useState(generationGuard)[0]
}
