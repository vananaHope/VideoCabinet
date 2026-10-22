"""실제 mpv 목록 복귀를 앱 클라이언트 영역만 60fps로 기록한다.

python ~/.agent-orchestra/bin/desktop_lock.py run --owner issue-250 -- \
    .venv/Scripts/python.exe scripts/check_return_transition.py --kind dialog --count 10 --output .local/return-window

--maximized를 더해 최대화를 검사한다. 일반/키/정렬은 --kind plain/esc/sorted.
자료는 합성 자홍색 영상과 청록색 썸네일 전용이다. 일반 영상의 검은 장면 판정기가 아니다.
녹화의 PTS, phases.json의 wall_time, capture.log의 입력 start 시각을 함께 비교한다.
--analyze-only는 창을 띄우지 않고 기존 녹화에서 판정 후보와 contact sheet를 만든다.
"""

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import faulthandler
import json
import os
from pathlib import Path
import re
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--kind', choices=('dialog', 'plain', 'esc', 'sorted'), default='dialog')
    parser.add_argument('--count', type=int, default=10)
    parser.add_argument('--maximized', action='store_true')
    parser.add_argument('--analyze-only', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.count <= 20:
        parser.error('--count는 잠금의 15분 상한 안에 끝나도록 1~20으로 지정하세요.')
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.analyze_only else 'windows'
    from PySide6.QtWidgets import QApplication
    from my_video_manager.ui import MainWindow
    app = QApplication([])
    if args.analyze_only:
        analyze(args.output)
    else:
        faulthandler.dump_traceback_later(600, exit=True)
        try:
            capture(args, app, MainWindow)
        finally:
            faulthandler.cancel_dump_traceback_later()


def capture(args, app, window_type):
    from PySide6.QtCore import QEventLoop, QTimer, Qt
    from PySide6.QtGui import QImage, QColor
    from PySide6.QtQuickWidgets import QQuickWidget
    from PySide6.QtTest import QTest
    from my_video_manager.adapters import FFmpegMediaReader
    from my_video_manager.core import AppCore, MediaInfo
    from my_video_manager import web_return_frame

    def settle(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait(predicate, label):
        deadline = time.monotonic() + 12
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError(f'조건 대기 시간 초과: {label}')
            settle(10)

    def javascript(code):
        values = []
        window.web_host.engine_page.runJavaScript(code, values.append)
        wait(lambda: bool(values), 'JavaScript 응답')
        return values[0]

    media = FFmpegMediaReader()
    data = args.output / 'data'
    data.mkdir(exist_ok=True)
    source = data / 'source.mp4'
    subprocess.run([media.ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                    'color=c=0xcc44aa:s=640x360:r=30', '-t', '60', '-c:v', 'libx264',
                    '-preset', 'ultrafast', '-y', str(source)], check=True)

    class DemoMedia:
        def read(self, path):
            return MediaInfo(60, 'mp4')

        def capture(self, path, destination, seconds):
            image = QImage(320, 180, QImage.Format.Format_RGB32)
            image.fill(QColor('#22ccdd'))
            image.save(str(destination), 'JPG')

    core = AppCore(media=DemoMedia(), clock=lambda: datetime.now(timezone.utc), database=data / 'library.sqlite3')
    content = source.read_bytes()
    for index in range(61):
        path = data / f'card-{index:03}.mp4'
        # 끝의 식별자는 mp4 재생에 영향을 주지 않고 내용 기반 중복 등록만 피한다.
        path.write_bytes(content + f'fixture {index}'.encode())
        core.add_file(path)
    window = window_type(core)
    window.resize(1100, 720)
    window.move(40, 40)
    window.showMaximized() if args.maximized else window.show()
    user32 = ctypes.windll.user32
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetWindowPos(int(window.winId()), -1, 0, 0, 0, 0, 0x13)
    window.activateWindow()
    assert QTest.qWaitForWindowActive(window, 5000)
    wait(lambda: javascript("!!document.getElementById('library-grid')"), '라이브러리')
    settle(300)
    phases, results, images = [], [], []
    current = [None]

    def log(name, **values):
        phases.append(dict(time=time.perf_counter(), wall_time=time.time(), run=current[0], name=name, **values))

    for target, name in ((window.web_host, 'finish_return'), (window.web_host, 'commit_return'),
                         (window.web_host, 'fail_return'), (window.web_host.dialogs, 'attach')):
        original = getattr(target, name)
        def traced(*args, _original=original, _name=name, **kwargs):
            log(_name + ':start')
            result = _original(*args, **kwargs)
            log(_name + ':end')
            return result
        setattr(target, name, traced)
    original_check = web_return_frame.has_frame_content
    def checked(image):
        started = time.perf_counter()
        result = original_check(image)
        log('frame-content', ready=result, check_ms=(time.perf_counter() - started) * 1000)
        images.append(image)
        return result
    web_return_frame.has_frame_content = checked
    process = None
    try:
        for index in range(args.count):
            current[0] = f'{args.kind}-{index:02}'
            run = args.output / current[0]
            run.mkdir(exist_ok=True)
            images.clear()
            selected = core.videos()[25 if args.kind == 'sorted' else 0].id
            if args.kind == 'sorted':
                library = window.library_page
                library.set_view({**library.options, 'sort': 'viewed', 'descending': True})
                library.selected_id = selected
                library.refresh()
                settle(100)
                javascript("document.getElementById('library-grid').scrollTop=1800")
                javascript("document.getElementById('library-grid').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))")
            else:
                window.play_video(selected, start=0)
            wait(lambda: core.playback.session is not None and core.playback.position > .5, '실제 mpv 재생')
            settle(200)
            rect, point = wintypes.RECT(), wintypes.POINT(0, 0)
            user32.GetClientRect(int(window.winId()), ctypes.byref(rect))
            user32.ClientToScreen(int(window.winId()), ctypes.byref(point))
            assert user32.GetForegroundWindow() == int(window.winId()), '활성 창 불일치'
            assert user32.GetWindowLongW(int(window.winId()), -20) & 8, 'TOPMOST 아님'
            with (run / 'capture.log').open('w') as stream:
                process = subprocess.Popen([media.ffmpeg, '-hide_banner', '-y', '-f', 'gdigrab',
                    '-framerate', '60', '-draw_mouse', '0', '-offset_x', str(point.x), '-offset_y', str(point.y),
                    '-video_size', f'{rect.right}x{rect.bottom}', '-i', 'desktop', '-c:v', 'ffv1',
                    str(run / 'window.mkv')], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=stream)
                log('capture:start', rect=[point.x, point.y, rect.right, rect.bottom])
                settle(550)
                javascript("""window.returnFrames=[];window.returnTrace=true;
                    function trace(t){if(!window.returnTrace)return;
                    window.returnFrames.push({time:performance.timeOrigin+t,
                        root:getComputedStyle(document.getElementById('root')).visibility,
                        scroll:document.getElementById('library-grid')?.scrollTop});requestAnimationFrame(trace)}
                    requestAnimationFrame(trace)""")
                if args.kind == 'dialog':
                    def close_dialog():
                        log('dialog:escape')
                        QTest.keyClick(window.web_host.view.focusProxy(), Qt.Key.Key_Escape)
                    deadline = QTimer()
                    deadline.setSingleShot(True)
                    deadline.timeout.connect(window.web_host.dialogs.pop)
                    deadline.start(8000)
                    QTimer.singleShot(400, close_dialog)
                    window.show_highlights()
                    assert deadline.isActive(), '대화상자 Esc 닫기 실패'
                    deadline.stop()
                    log('dialog:closed')
                control = 'esc' if args.kind == 'esc' or (args.kind == 'dialog' and index % 2) else 'button'
                log('return:start', control=control)
                if control == 'esc':
                    QTest.keyClick(window.playback_page, Qt.Key.Key_Escape)
                else:
                    window.playback_page.back_button.click()
                log('return:end')
                wait(lambda: not window.web_host.return_pending, '복귀 완료')
                settle(500)
                raf = json.loads(javascript('window.returnTrace=false;JSON.stringify(window.returnFrames)'))
                process.communicate(b'q', timeout=10)
                assert process.returncode == 0, 'FFmpeg 녹화 실패'
                process = None
            if images:
                images[0].save(str(run / 'first-fbo.png'))
                images[-1].save(str(run / 'last-fbo.png'))
            results.append(dict(run=current[0], control=control, raf=raf,
                                playback_visible=window.playback_page.isVisible()))
            (args.output / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
            (args.output / 'phases.json').write_text(json.dumps(phases, indent=2), encoding='utf-8')
            print(current[0], flush=True)
    finally:
        if process is not None:
            try:
                process.communicate(b'q', timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        web_return_frame.has_frame_content = original_check
        window.tray.quit()
        (args.output / 'phases.json').write_text(json.dumps(phases, indent=2), encoding='utf-8')


def analyze(directory):
    import av
    import numpy as np
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QImage, QPainter
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    if os.name == 'nt':
        # Windows의 offscreen 플러그인은 설치된 글꼴을 자동으로 열거하지 않는다.
        font_id = QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / 'consola.ttf'))
        if font_id >= 0:
            font = QFont(QFontDatabase.applicationFontFamilies(font_id)[0])
    font.setPointSize(10)
    if not all(QFontMetrics(font).inFont(char) for char in '0123456789. videolibraryinspectmx'):
        raise RuntimeError('contact sheet의 ASCII 라벨을 표시할 글꼴이 없습니다.')
    summary = {}
    phases = json.loads((directory / 'phases.json').read_text(encoding='utf-8'))
    for movie in directory.glob('*/window.mkv'):
        start = float(re.search(r'start: ([0-9.]+)', (movie.parent / 'capture.log').read_text()).group(1))
        request = next(item['wall_time'] for item in phases if item['run'] == movie.parent.name and item['name'] == 'return:start')
        frames, pictures = [], []
        with av.open(str(movie)) as container:
            for index, frame in enumerate(container.decode(video=0)):
                rgb = np.ascontiguousarray(frame.to_ndarray(format='rgb24'))
                sample = rgb[::4, ::4].astype(int)
                red, green, blue = sample[:, :, 0], sample[:, :, 1], sample[:, :, 2]
                video = float(((red > 150) & (blue > 110) & (green < 110)).mean())
                library = float(((red < 80) & (green > 140) & (blue > 150)).mean())
                kind = 'video' if video > .08 else 'library' if library > .025 else 'inspect'
                if video > .08 and library > .025:
                    kind = 'mixed'
                pts = float(frame.pts * frame.time_base)
                frames.append(dict(frame=index, pts=pts, kind=kind, video=video, library=library,
                                   after_request=start + pts >= request))
                pictures.append(QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy())
        transitions = [i for i, frame in enumerate(frames) if i and frame['kind'] != frames[i-1]['kind'] and frame['after_request']]
        indices = sorted({j for i in transitions for j in range(max(0, i-2), min(len(frames), i+4))})
        if not indices:
            indices = [0, len(frames)-1]
        sheet = QImage(1320, 240*((len(indices)+3)//4), QImage.Format.Format_RGB32)
        sheet.fill(QColor('#555555'))
        painter = QPainter(sheet)
        painter.setFont(font)
        for order, index in enumerate(indices):
            x, y = order % 4 * 330, order // 4 * 240
            painter.drawImage(x, y, pictures[index].scaled(330, 215, Qt.AspectRatioMode.KeepAspectRatio))
            painter.setPen(QColor('white'))
            painter.drawText(x+3, y+232, f"{index} {frames[index]['pts']:.3f} {frames[index]['kind']}")
        painter.end()
        sheet.save(str(movie.parent / 'contact.png'))
        summary[movie.parent.name] = dict(transitions=[frames[i] for i in transitions], frames=frames)
        print(movie.parent.name, json.dumps(summary[movie.parent.name]['transitions']))
    (directory / 'frame-analysis.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
