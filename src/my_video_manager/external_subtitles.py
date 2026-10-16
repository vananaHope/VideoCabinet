"""영상 옆의 읽기 전용 자막 파일을 찾고, 언어별 줄과 읽기 경고를 보관한다."""

from bisect import bisect_left
from collections import Counter
from concurrent.futures import CancelledError
from dataclasses import dataclass
import errno
from html import unescape
from html.parser import HTMLParser
from itertools import islice
import math
import os
from pathlib import Path
import re


EXTENSIONS = {".srt", ".vtt", ".smi"}
WARNING_PREFIX = "외부 자막: "
LANGUAGES = {
    "ko": "ko", "kor": "ko", "korean": "ko", "krcc": "ko",
    "en": "en", "eng": "en", "english": "en", "encc": "en",
    "ja": "ja", "jpn": "ja", "japanese": "ja", "jpcc": "ja",
    "zh": "zh", "zho": "zh", "chi": "zh", "chinese": "zh", "cncc": "zh",
}


@dataclass(frozen=True)
class ExternalSubtitleLine:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class ExternalSubtitle:
    language: str | None
    language_class: str
    lines: tuple[ExternalSubtitleLine, ...]


@dataclass(frozen=True)
class ExternalSubtitleFile:
    id: int
    video_id: int
    path: Path
    encoding: str | None
    warning: str | None
    subtitles: tuple[ExternalSubtitle, ...]


@dataclass(frozen=True)
class ExternalSubtitleTrackSummary:
    language: str | None
    language_class: str
    line_count: int


@dataclass(frozen=True)
class ExternalSubtitleFileSummary:
    id: int
    name: str
    warning: str | None
    subtitles: tuple[ExternalSubtitleTrackSummary, ...]
    parent_parts: tuple[str, ...] = ()


class _ReadError(ValueError):
    """파서에서 사용자를 위해 작성한 읽기 실패 문구."""


def _read_error_message(error, *, folder=False):
    if isinstance(error, _ReadError):
        return str(error)
    if isinstance(error, UnicodeError):
        return "자막의 문자 인코딩이 올바르지 않습니다. UTF-8, UTF-16, CP949/EUC-KR 파일인지 확인해 주세요."
    if isinstance(error, OSError):
        target = "자막 폴더를" if folder else "자막 파일을"
        winerror = getattr(error, "winerror", None)
        if isinstance(error, PermissionError) and winerror in (None, 5):
            message = f"{target} 읽을 권한이 없습니다. 접근 권한을 확인해 주세요."
        elif isinstance(error, FileNotFoundError):
            message = f"{target} 찾을 수 없습니다. 다시 검사해 주세요."
        else:
            subject = "폴더와" if folder else "파일과"
            message = f"{target} 읽지 못했습니다. {subject} 저장 장치 상태를 확인해 주세요."
        if winerror is None and error.errno in (errno.EACCES, errno.ENOENT):
            return message
        # str(error)는 filename을 포함한다. strerror에도 경로를 넣는 공급자가 있어 가린다.
        detail = error.strerror or type(error).__name__
        for filename in (error.filename, error.filename2):
            if isinstance(filename, (str, bytes, os.PathLike)) and filename:
                detail = detail.replace(os.fsdecode(filename), "[경로 생략]")
        detail = re.sub(r'''(?:[A-Za-z]:[\\/]|\\\\|(?<![\w.])(?:~/|/)(?=[\w.]))[^\r\n"'<>]*''', "[경로 생략]", detail)
        return f"{message} (원인: {detail})"
    return ("자막 형식을 해석하지 못했습니다. 파일 내용과 자막 시각을 확인해 주세요. "
            f"(원인: {type(error).__name__})")


def _language(value):
    return next((LANGUAGES[token] for token in re.split(r"[^a-z]+", value.casefold())
                 if token in LANGUAGES), None)


def _decode(data):
    # BOM을 우선한다. BOM 없는 UTF-16은 ASCII 타임코드의 NUL 바이트로 판별한다.
    # 짧은 CP949의 유효 UTF-8 바이트나 NUL 위치가 치우친 UTF-16은 오판할 수 있다.
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig"), "utf-8-sig"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16-le" if data.startswith(b"\xff\xfe") else "utf-16-be"
        return data[2:].decode(encoding), encoding
    if b"\x00" in data:
        sample = data[:512]
        encoding = "utf-16-le" if sample[1::2].count(0) > sample[::2].count(0) else "utf-16-be"
        return data.decode(encoding), encoding
    for encoding in ("utf-8", "cp949", "euc-kr"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    raise _ReadError("지원 인코딩(UTF-8, UTF-16, CP949/EUC-KR)으로 읽을 수 없습니다.")


def _plain(value):
    value = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", "", value, flags=re.I | re.S)
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]*>", "", value)
    return "\n".join(line for raw in unescape(value).splitlines() if (line := " ".join(raw.split())))


_TIME = r"(?:\d+:)?\d{2}:\d{2}[.,]\d{3}"
_CUE = re.compile(rf"^\s*({_TIME})\s*-->\s*({_TIME})(?:\s+.*)?$")


def _seconds(value):
    parts = value.replace(",", ".").split(":")
    if float(parts[-1]) >= 60 or (len(parts) == 3 and int(parts[-2]) >= 60):
        raise ValueError("자막 시각의 분·초가 잘못되었습니다.")
    return sum(float(part) * 60 ** index for index, part in enumerate(reversed(parts)))


def _timed_text(text, language):
    lines = []
    skipped = 0
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    # Metadata belongs to the header, but some writers omit its blank terminator.
    if re.match(r"^WEBVTT(?:\s|$)", text):
        rows = text.splitlines()
        index = 1
        while index < len(rows) and rows[index].strip() and "-->" not in rows[index]:
            index += 1
        text = "\n".join(rows[index:]).lstrip()
    for block in re.split(r"\n\s*\n", text):
        rows = block.splitlines()
        if not rows or re.match(r"^(WEBVTT|NOTE|STYLE|REGION)(?:\s|$)", rows[0]):
            continue
        index = 0 if _CUE.match(rows[0]) else 1
        match = _CUE.match(rows[index]) if index < len(rows) else None
        if not match:
            skipped += 1
            continue
        try:
            start, end = map(_seconds, match.groups())
        except ValueError:
            skipped += 1
            continue
        if end <= start:
            skipped += 1
            continue
        value = _plain("\n".join(rows[index + 1:]))
        if value:
            lines.append(ExternalSubtitleLine(start, end, value))
    return (ExternalSubtitle(language, "", tuple(lines)),), skipped


class _Sami(HTMLParser):
    """SMI는 P 종료 태그를 생략할 수 있으므로 다음 P/SYNC에서도 문단을 닫는다."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.syncs = []
        self.start = None
        self.paragraphs = {}
        self.language_class = ""
        self.parts = []
        self.in_paragraph = False
        self.hidden = 0
        self.skipped = 0

    def _paragraph(self):
        if self.in_paragraph:
            text = "\n".join(line for raw in "".join(self.parts).splitlines()
                             if (line := " ".join(raw.split())))
            previous = self.paragraphs.get(self.language_class, "")
            self.paragraphs[self.language_class] = "\n".join(filter(None, (previous, text)))
        self.parts = []
        self.in_paragraph = False

    def _sync(self):
        self._paragraph()
        if self.start is not None:
            self.syncs.append((self.start, self.paragraphs))
        self.paragraphs = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("style", "script"):
            self.hidden += 1
        elif not self.hidden and tag == "sync":
            self._sync()
            value = attrs.get("start") or ""
            if not re.fullmatch(r"\d+", value):
                self.skipped += 1
                self.start = None
            else:
                self.start = int(value) / 1000
        elif not self.hidden and tag == "p":
            self._paragraph()
            self.language_class = (attrs.get("class") or "").casefold()
            self.in_paragraph = True
        elif not self.hidden and tag == "br" and self.in_paragraph:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self.hidden = max(0, self.hidden - 1)
        elif tag == "p":
            self._paragraph()

    def handle_data(self, data):
        if self.in_paragraph and not self.hidden:
            self.parts.append(data)


def _sami(text, language, duration):
    parser = _Sami()
    parser.feed(text)
    parser.close()
    parser._sync()
    if not parser.syncs:
        raise _ReadError("SMI SYNC 시각을 찾을 수 없습니다.")
    declared = {}
    for name, body in re.findall(r"\.([\w-]+)\s*\{([^}]+)\}", text):
        match = re.search(r"\blang\s*:\s*([\w-]+)", body, re.I)
        if match:
            declared[name.casefold()] = _language(match[1])
    histories = {}
    skipped = parser.skipped
    for start, paragraphs in parser.syncs:
        # A P-less SYNC closes every active class; a blank P closes only its class.
        paragraphs = paragraphs or dict.fromkeys(histories, "")
        if any(histories.get(name) and start < histories[name][-1][0] for name in paragraphs):
            skipped += 1
            continue
        for name, value in paragraphs.items():
            histories.setdefault(name, []).append((start, value))
    tracks = {}
    for name, syncs in histories.items():
        track = tracks.setdefault(name, [])
        for index, (start, value) in enumerate(syncs):
            end = (syncs[index + 1][0] if index + 1 < len(syncs)
                   else duration if math.isfinite(duration) and duration > 0 else start + 5)
            if value and end > start:
                track.append(ExternalSubtitleLine(start, end, value))
    return tuple(ExternalSubtitle(declared.get(name) or _language(name) or language, name, tuple(lines))
                 for name, lines in tracks.items()), skipped


class ExternalSubtitles:
    def __init__(self, connect):
        self._connect = connect
        with connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS external_subtitle_files (
                id INTEGER PRIMARY KEY, video_id INTEGER NOT NULL REFERENCES videos(id),
                path TEXT NOT NULL, size INTEGER, mtime_ns INTEGER, encoding TEXT, warning TEXT,
                UNIQUE(video_id, path))""")
            db.execute("""CREATE TABLE IF NOT EXISTS external_subtitles (
                id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL REFERENCES external_subtitle_files(id)
                ON DELETE CASCADE, language TEXT, language_class TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS external_subtitles_file ON external_subtitles(file_id)")
            db.execute("""CREATE TABLE IF NOT EXISTS external_subtitle_lines (
                id INTEGER PRIMARY KEY, subtitle_id INTEGER NOT NULL REFERENCES external_subtitles(id)
                ON DELETE CASCADE, start REAL NOT NULL, end REAL NOT NULL, text TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS external_subtitle_lines_track ON external_subtitle_lines(subtitle_id)")

    def files(self, video_id):
        with self._connect() as db:
            db.execute("BEGIN")
            if not db.execute("SELECT 1 FROM videos WHERE id=?", (video_id,)).fetchone():
                raise ValueError("영상을 찾을 수 없습니다.")
            result = []
            for file in db.execute("SELECT * FROM external_subtitle_files WHERE video_id=? ORDER BY path", (video_id,)):
                tracks = []
                for track in db.execute("SELECT * FROM external_subtitles WHERE file_id=? ORDER BY id", (file["id"],)):
                    lines = tuple(ExternalSubtitleLine(row["start"], row["end"], row["text"]) for row in db.execute(
                        "SELECT * FROM external_subtitle_lines WHERE subtitle_id=? ORDER BY start, id", (track["id"],)))
                    tracks.append(ExternalSubtitle(track["language"], track["language_class"], lines))
                result.append(ExternalSubtitleFile(file["id"], video_id, Path(file["path"]),
                                                   file["encoding"], file["warning"], tuple(tracks)))
            return tuple(result)

    def summaries(self, video_id):
        """선택 영상의 파일·언어별 줄 수만 조회하며 자막 본문은 읽지 않는다."""
        with self._connect() as db:
            db.execute("BEGIN")
            if not db.execute("SELECT 1 FROM videos WHERE id=?", (video_id,)).fetchone():
                raise ValueError("영상을 찾을 수 없습니다.")
            rows = db.execute("""SELECT f.id, f.path, f.warning, s.id AS track_id,
                s.language, s.language_class, count(l.id) AS line_count
                FROM external_subtitle_files f
                LEFT JOIN external_subtitles s ON s.file_id=f.id
                LEFT JOIN external_subtitle_lines l ON l.subtitle_id=s.id
                WHERE f.video_id=? GROUP BY f.id, s.id ORDER BY f.path, s.id""", (video_id,))
            files = {}
            for row in rows:
                file = files.setdefault(row["id"], (row, []))
                if row["track_id"] is not None:
                    file[1].append(ExternalSubtitleTrackSummary(
                        row["language"], row["language_class"], row["line_count"]))
            paths = {id: Path(row["path"]) for id, (row, _) in files.items()}
            names = Counter(path.name.casefold() for path in paths.values())
            tails = {id: path.parent.parts[-1:] if names[path.name.casefold()] > 1 else ()
                     for id, path in paths.items()}
            while True:
                counts = Counter((paths[id].name.casefold(), tuple(p.casefold() for p in parts))
                                 for id, parts in tails.items())
                collisions = [id for id, parts in tails.items() if parts and
                              counts[paths[id].name.casefold(), tuple(p.casefold() for p in parts)] > 1
                              and len(parts) < len(paths[id].parent.parts)]
                if not collisions:
                    break
                for id in collisions:
                    tails[id] = paths[id].parent.parts[-len(tails[id]) - 1:]
            return tuple(ExternalSubtitleFileSummary(row["id"],
                         paths[row["id"]].name, row["warning"], tuple(tracks), tails[row["id"]])
                         for row, tracks in files.values())

    def refresh(self, video_ids=None, *, folders=None, skipped_folders=()):
        """한 검사에서 디렉터리별 목록을 한 번만 읽고 크기·mtime이 바뀐 파일만 파싱한다."""
        with self._connect() as db:
            locations = db.execute("""SELECT l.video_id, l.path, v.duration FROM locations l
                JOIN videos v ON v.id=l.video_id""").fetchall()
            old = db.execute("""SELECT f.*, EXISTS(SELECT 1 FROM external_subtitles s WHERE s.file_id=f.id)
                AS has_tracks FROM external_subtitle_files f""").fetchall()
            if folders is not None:
                def in_scope(row):
                    path = Path(row["path"])
                    return (any(path.is_relative_to(folder) for folder in folders)
                            and not any(path.is_relative_to(folder) for folder in skipped_folders))
                locations = [row for row in locations if in_scope(row)]
                old = [row for row in old if in_scope(row)]
            if video_ids is not None:
                # Registering a longer name can take a sidecar away from another
                # video in this directory. Reconcile all its registered siblings.
                affected = {Path(row["path"]).parent for row in (*locations, *old) if row["video_id"] in video_ids}
                locations = [row for row in locations if Path(row["path"]).parent in affected]
                old = [row for row in old if Path(row["path"]).parent in affected]
            previous = {(row["video_id"], row["path"]): row for row in old}
            directories = {}
            found = {}
            warnings = []
            unavailable = set()
            owners = {}
            for location in sorted(locations, key=lambda row: len(Path(row["path"]).stem), reverse=True):
                path = Path(location["path"])
                if path.parent not in directories:
                    try:
                        with os.scandir(path.parent) as entries:
                            candidates = sorted((entry.name.casefold(), Path(entry.path)) for entry in entries
                                                if Path(entry.name).suffix.casefold() in EXTENSIONS
                                                and entry.is_file(follow_symlinks=False))
                        directories[path.parent] = candidates
                    except (FileNotFoundError, NotADirectoryError):
                        directories[path.parent] = []
                    except OSError as error:
                        unavailable.add(path.parent)
                        warnings.append((path.parent, f"{WARNING_PREFIX}{_read_error_message(error, folder=True)}"))
                        directories[path.parent] = []
                candidates = directories[path.parent]
                stem = path.stem.casefold()
                index = bisect_left(candidates, (stem,))
                for name, candidate in islice(candidates, index, None):
                    if not name.startswith(stem):
                        break
                    remainder = candidate.stem[len(path.stem):]
                    if remainder and remainder[0] not in "._- [(":
                        continue
                    if owners.get(candidate, len(stem)) > len(stem):
                        continue
                    owners[candidate] = len(stem)
                    found[(location["video_id"], str(candidate))] = (candidate, _language(candidate.stem[len(path.stem):]),
                                                                    location["duration"])
            for key, (path, language, duration) in found.items():
                saved = previous.get(key)
                size = mtime = encoding = warning = None
                tracks = ()
                try:
                    info = path.stat()
                    size, mtime = info.st_size, info.st_mtime_ns
                    if saved and (saved["size"], saved["mtime_ns"]) == (size, mtime) and (not saved["warning"] or saved["has_tracks"]):
                        if saved["warning"]:
                            warnings.append((path, saved["warning"]))
                        continue
                    text, encoding = _decode(path.read_bytes())
                    if "\x00" in text:
                        raise _ReadError("자막에 NUL 문자가 있습니다.")
                    tracks, skipped = (_sami(text, language, duration) if path.suffix.casefold() == ".smi"
                                       else _timed_text(text, language))
                    if not any(track.lines for track in tracks):
                        raise _ReadError("읽을 수 있는 자막 줄이 없습니다.")
                    if skipped:
                        warning = f"{WARNING_PREFIX}{skipped}개 블록을 건너뜀"
                    after = path.stat()
                    if (after.st_size, after.st_mtime_ns) != (size, mtime):
                        raise _ReadError("검사 중 자막 파일이 변경되었습니다. 다시 검사해 주세요.")
                except CancelledError:
                    raise
                except Exception as error:
                    warning = f"{WARNING_PREFIX}{_read_error_message(error)}"
                    tracks = ()
                if warning:
                    warnings.append((path, warning))
                if saved:
                    file_id = saved["id"]
                    db.execute("DELETE FROM external_subtitles WHERE file_id=?", (file_id,))
                    db.execute("UPDATE external_subtitle_files SET size=?, mtime_ns=?, encoding=?, warning=? WHERE id=?",
                               (size, mtime, encoding, warning, file_id))
                else:
                    file_id = db.execute("""INSERT INTO external_subtitle_files
                        (video_id, path, size, mtime_ns, encoding, warning) VALUES (?, ?, ?, ?, ?, ?)""",
                                         (*key, size, mtime, encoding, warning)).lastrowid
                for track in tracks:
                    track_id = db.execute("INSERT INTO external_subtitles(file_id, language, language_class) VALUES (?, ?, ?)",
                                          (file_id, track.language, track.language_class)).lastrowid
                    db.executemany("INSERT INTO external_subtitle_lines(subtitle_id, start, end, text) VALUES (?, ?, ?, ?)",
                                   [(track_id, line.start, line.end, line.text) for line in track.lines])
                # File signature, warning, tracks and search rows commit together.
                # No write transaction spans reading/parsing the next file.
                db.commit()
            for key, row in previous.items():
                if key not in found and Path(row["path"]).parent not in unavailable:
                    db.execute("DELETE FROM external_subtitle_files WHERE id=?", (row["id"],))
                    db.commit()
            return tuple(warnings)
