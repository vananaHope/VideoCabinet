"""웹 대화상자와 네이티브 재생이 공유하는 시각 표시."""


def timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, rest = divmod(milliseconds, 3600000)
    minutes, rest = divmod(rest, 60000)
    return f"{hours:02}:{minutes:02}:{rest / 1000:06.3f}"
