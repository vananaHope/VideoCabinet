"""대화상자와 보조 페이지의 여백·주 작업 표시. 전역 테마는 변경하지 않는다."""

from PySide6.QtWidgets import QDialogButtonBox

from .theme import ACCENT, BORDER, DISABLED_TEXT


def space_layout(layout):
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)
    return layout


def primary_button(button):
    # Enter의 기존 의미를 바꾸지 않고 주 작업만 시각적으로 구분한다.
    button.setObjectName("primaryAction")
    button.setStyleSheet(f"""
        QPushButton#primaryAction {{ color: {ACCENT}; }}
        QPushButton#primaryAction:disabled {{ color: {DISABLED_TEXT}; border-color: {BORDER}; }}
    """)
    return button


def dialog_buttons(accepted, rejected, *, save=False):
    """Windows의 확인/저장 → 취소 순서를 따르는 공통 버튼 줄."""
    action = QDialogButtonBox.StandardButton.Save if save else QDialogButtonBox.StandardButton.Ok
    box = QDialogButtonBox(action | QDialogButtonBox.StandardButton.Cancel)
    primary_button(box.button(action)).setText("저장" if save else "확인")
    box.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
    box.accepted.connect(accepted)
    box.rejected.connect(rejected)
    return box
