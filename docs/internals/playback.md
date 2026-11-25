# 재생·모아보기·무작위 이어 재생

## 영상 전환

영상 전환은 코어의 `switch_to(video_id)`에서 기존 시청과 열린 하이라이트 구간을 닫고
기존 이어보기 규칙으로 시작 위치를 구해 새 시청을 시작합니다.

## 하이라이트 모아보기

모아보기는 `record_viewing=False`로 시작하므로 시청 기록·다 봄/보다 만·이어볼 위치가 바뀌지 않습니다.

코어의 `AppCore(reel_settings=ReelSettings(point_duration=10, minimum_played=3))`로
기본 길이와 기록 기준을 설정할 수 있습니다(`ReelSettings`는 `reel.py`). 설정 화면은 후속 범위입니다.
`reel_entries(tag_id=None)`는 하이라이트·영상 제목·길이·재생 가능 여부·마지막 복습 시각을 반환합니다.
`start_reel(tag_id=None, highlight_id=None)`로 시작하고 `reel_playback`에서 현재 항목과 재생 범위를,
`reel_repeat`에서 반복 상태를 읽습니다. `ReelPlayback.action`은 첫 시작·영상 전환의 `open` 또는
같은 영상의 항목 이동·반복의 `seek`입니다. 재생 위치는 기존 `core.playback.report()`로 보고하고,
그 호출이 끝난 직후 `advance_reel_if_due()`를 호출해 다음 재생 지시를 반영합니다.
모든 리스너가 이전 위치를 받은 뒤 전환하므로 구독 순서에 의존하지 않습니다.
엔진 EOF는 `advance_reel_if_due(eof=True)`로 전달합니다. 영상 끝에 걸친 항목은 엔진과 DB의 길이가
조금 달라도 끝 도달로 처리합니다. 탐색 직후 첫 위치 보고는 `seeked=True`로 전달합니다.
`last_highlight_revisited_at(highlight_id)`와 `last_video_revisited_at(video_id)`는 마지막 복습 시각을
반환하며, 기록이 없으면 `None`입니다. 영상별 값은 남아 있는 하이라이트들의 가장 최근 복습 시각입니다.
추천(#14·#196)은 영상별 API를 사용합니다.

## 무작위 이어 재생

`random_continuous_play.py`의 `RandomPlayScope(kind, video_ids=(), tag_ids=())`는 불변 범위 값입니다.
`kind`는 `all` / `list` / `tags`이고 태그는 OR입니다. 화면은 내부 상태 대신 다음 `AppCore` 공개 API를 씁니다.

- `random_continuous_enabled`, `random_continuous_scope`: 켜짐 여부와 현재 범위(꺼짐은 `None`).
- `playback_video_ids`: 재생을 시작한 목록의 ID 스냅숏. 목록 범위 선택은 이 값을 사용합니다.
- `set_random_continuous_enabled(bool)`: 일반 재생 중에만 켤 수 있습니다. 켜면 시작 목록 범위와 현재 영상부터 새 기록을 만듭니다.
- `set_random_continuous_scope(RandomPlayScope(...))`: 현재 영상·이동 기록·나온 영상 집합은 유지하고 다음 선택에 적용합니다.
- `execute_video_command(command, visible_video_ids)`: PgUp/PgDn 공용 경로. 반환한 ID는 기존 `switch_to`/`MainWindow.play_video`로 재생합니다.
- `advance_random_if_due(session, eof=True)`: 모든 위치 리스너가 보고를 받은 뒤 호출합니다. 지난 세션의 EOF는 무시합니다.
- `take_random_continuous_notice()`: 이동 경계·후보 없음 안내를 한 번 가져옵니다.
- `end_playback()`: 시청을 닫고 이어 재생 범위·기록·시작 목록을 버립니다.

새 목록 재생은 `switch_to(..., playback_video_ids=시작목록)`로 꺼진 상태에서 시작합니다.
무작위 진입점은 `pick_random_video(...)`로 첫 영상을 고른 뒤 `random_scope=...`도 전달합니다.
진행 중 이전·다음 이동은 두 인자를 생략해 상태를 유지합니다. 난수는 `AppCore(random_choice=...)`로 주입합니다.
무작위 EOF는 `MainWindow`가 이벤트 루프 다음 차례에 엔진·세션을 다시 확인하고 적용하므로,
같은 입력 안에서 먼저 위치를 읽는 PgDn·목록 복귀·탐색과 겹쳐도 중복 전환하지 않습니다.

```powershell
.venv/Scripts/python scripts/check_web_random_continuous.py --offscreen
$env:MVM_REAL_WINDOW_TESTS = '1'
python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner issue-235 -- .venv/Scripts/python scripts/check_web_random_continuous.py --library '<테스트 라이브러리 경로>'
```

offscreen은 1100×720 위젯 이미지만 `.local/issue-235/`에 저장합니다. 실창 검사는 지정 라이브러리를 읽어
짧은 서로 다른 영상 두 편의 실제 mpv 끝 → 다음, PgUp/PgDn, Esc 복귀와 마지막 영상 선택을 검사하며 화면을 캡처하지 않습니다.
