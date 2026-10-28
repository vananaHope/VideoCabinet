"""웹 페이지 rAF 프레임 기록기 끝내기."""
import json

from qt_wait import wait_for


def _js(window, source):
    result = []
    window.web_host.engine_page.runJavaScript(source, result.append)
    wait_for(lambda: bool(result))
    return result[0]


def stop_recording(window, name, done):
    """window.__{name}Frames의 마지막 프레임이 done을 만족할 때까지 기다린 뒤 기록을 멈추고 모든 프레임을 돌려준다.

    결과 DOM이 바뀐 시점과 rAF 기록기가 그 상태를 표본으로 담는 시점은 다르다. DOM만 보고 바로 멈추면
    마지막 표본이 아직 이전 상태(자리 표시 등)일 수 있다. 기록 중지 플래그는 window.__stop{Name}Frames다.
    """
    last = f'JSON.stringify(window.__{name}Frames.at(-1) ?? null)'
    wait_for(lambda: (frame := json.loads(_js(window, last))) is not None and done(frame))
    _js(window, f'window.__stop{name[0].upper()}{name[1:]}Frames = true')
    return json.loads(_js(window, f'JSON.stringify(window.__{name}Frames)'))
