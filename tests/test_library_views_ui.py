"""카드 크기 전환 후 실제 WebEngine 가상 행·키보드 scrollToIndex 회귀."""
from contextlib import closing
import json
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from test_web_library_data import core
from test_web_library_page import window_factory
from test_web_statistics import wait_for
from my_video_manager.library_views import default_options


def test_card_resize_rebuilds_virtual_offsets_and_keyboard_scroll(window_factory, core):
    with closing(sqlite3.connect(core.database)) as db, db:
        for i in range(300):
            db.execute('''INSERT INTO videos(fingerprint,title,duration,format,thumbnail,registered_at,resolution_checked)
                VALUES(?,?,100,'mp4','demo.640.jpg','2026-01-01T00:00:00+00:00',1)''', (f'demo-{i}', f'video-{i:04d}'))
    window = window_factory()
    page, host = window.library_page, window.web_host
    def js(code):
        result = []
        host.engine_page.runJavaScript(code, result.append)
        wait_for(lambda: bool(result))
        return result[0]
    wait_for(lambda: js("!!document.getElementById('library-grid')"))
    for size in ('medium', 'large', 'medium', 'small'):
        page.bridge.view(json.dumps({**default_options(), 'mode': 'folders', 'card_size': size}))
        page.selection_changed()
        wait_for(lambda: js("document.querySelector('select[aria-label=\"카드 크기\"]').value") == size)
        QTest.qWait(80)
        target = page.visible_ids[120]
        js("(()=>{const g=document.getElementById('library-grid');const row=parseFloat(getComputedStyle(g).getPropertyValue('--grid-row-height'))*parseFloat(getComputedStyle(document.documentElement).fontSize);g.scrollTop=Math.floor(120/Number(g.getAttribute('aria-colcount')))*row})()")
        wait_for(lambda: js(f"!!document.getElementById('video-{target}')"))
        js(f"document.getElementById('video-{target}').click()")
        wait_for(lambda: page.selected_id == target)
        columns = int(js("document.getElementById('library-grid').getAttribute('aria-colcount')"))
        host.view.setFocus()
        js("document.getElementById('library-grid').focus()")
        for step in range(1, 5):
            QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Down)
            next_id = page.visible_ids[120 + columns * step]
            wait_for(lambda: page.selected_id == next_id)
            wait_for(lambda: js(f"!!document.getElementById('video-{next_id}')"))
        assert js("document.getElementById('library-grid').scrollTop") > 0
