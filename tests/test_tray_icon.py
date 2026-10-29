"""트레이 아이콘: Qt 기본 아이콘이 아니라 빌드 산출물(tray.ico)이고, 긴급 탈출 중에도 그대로다."""
import importlib
from pathlib import Path
import sys

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QStyle
import pytest

from test_emergency_hide_ui import app, window

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def icon():
    sys.path.insert(0, str(ROOT / 'scripts'))
    try:
        yield importlib.import_module('app_icon')
    finally:
        sys.path.remove(str(ROOT / 'scripts'))


def tray_digests(icon, tray_icon):
    return {size: icon.pixel_digest(tray_icon.pixmap(QSize(size, size)).toImage()) for size in icon.TRAY_SIZES}


def test_tray_icon_is_the_built_artifact_at_every_tray_size(icon, window):
    tray_icon = window.tray.icon.icon()
    assert not tray_icon.isNull()
    assert {size.width() for size in tray_icon.availableSizes()} == set(icon.TRAY_SIZES)
    built = icon.decode_ico((ROOT / icon.TRAY_ICO).read_bytes())
    for size, digest in tray_digests(icon, tray_icon).items():
        assert digest == icon.pixel_digest(built[size]), size
        assert digest == icon.pixel_digest(icon.read_png(ROOT / icon.tray_source_for(size))), size


def test_tray_icon_is_not_the_qt_standard_play_icon(icon, window):
    standard = window.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
    ours = tray_digests(icon, window.tray.icon.icon())
    for size in icon.TRAY_SIZES:
        assert ours[size] != icon.pixel_digest(standard.pixmap(QSize(size, size)).toImage()), size


def test_tray_icon_stays_the_same_while_hidden_by_emergency_hide(icon, window, app):
    before = tray_digests(icon, window.tray.icon.icon())
    window.tray.hide_window()
    app.processEvents()
    assert not window.isVisible() and window.tray.icon.isVisible()
    assert tray_digests(icon, window.tray.icon.icon()) == before
    window.tray.open()
    app.processEvents()
    assert window.isVisible()
    assert tray_digests(icon, window.tray.icon.icon()) == before
