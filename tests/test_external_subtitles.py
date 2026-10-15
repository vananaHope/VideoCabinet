from datetime import datetime, timezone
from concurrent.futures import CancelledError
from asyncio import CancelledError as AsyncCancelledError
import os
from pathlib import Path
import sqlite3

import pytest

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.search import SOURCE_LABELS
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment


class Media:
    def read(self, path):
        return MediaInfo(120, "matroska") if path.suffix.lower() == ".mkv" else None

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"thumbnail")


def make_core(tmp_path):
    return AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc),
                   database=tmp_path / "data/library.sqlite3")


@pytest.fixture
def library(tmp_path):
    folder = tmp_path / "videos"
    folder.mkdir()
    video = folder / "lesson.mkv"
    video.write_bytes(b"video")
    return make_core(tmp_path), video


def srt(text="체중 이동", start="00:00:12,250"):
    return f"1\n{start} --> 00:00:15,000\n<b>{text}</b>\n둘째 줄\n"


@pytest.mark.parametrize("encoding,bom,expected", [
    ("utf-8", b"", "utf-8"), ("utf-8", b"\xef\xbb\xbf", "utf-8-sig"),
    ("utf-16-le", b"\xff\xfe", "utf-16-le"), ("utf-16-be", b"\xfe\xff", "utf-16-be"),
    ("utf-16-le", b"", "utf-16-le"), ("utf-16-be", b"", "utf-16-be"),
    ("cp949", b"", "cp949"), ("euc-kr", b"", "cp949"),
])
def test_encodings_and_detection_precedence(library, encoding, bom, expected):
    core, video = library
    subtitle = video.with_suffix(".ko.srt")
    subtitle.write_bytes(bom + srt().encode(encoding))
    assert core.add_file(video).added == 1
    item, = core.external_subtitles(core.videos()[0].id)
    assert (item.path, item.encoding, item.warning) == (subtitle, expected, None)
    track, = item.subtitles
    assert track.language == "ko"
    line, = track.lines
    assert (line.start, line.end, line.text) == (12.25, 15, "체중 이동\n둘째 줄")
    result, = core.search("체중이동").results
    assert (result.video_id, result.source, result.start, result.language) == (item.video_id, "external", 12.25, "ko")
    assert SOURCE_LABELS[result.source] == "외부 자막"
    core.switch_to(result.video_id, start=result.start)
    assert core.playback.session.video_id == item.video_id
    assert core.playback.position == 12.25


@pytest.mark.parametrize("suffix,language", [(".kor", "ko"), (".KOREAN", "ko"), (".ENG", "en"),
                                            (".en-US", "en"), ("", None), (".unknown", None)])
def test_filename_languages_and_prefix_discovery(library, suffix, language):
    core, video = library
    video.with_suffix(f"{suffix}.SRT").write_text(srt(), encoding="utf-8")
    (video.parent / "other.ko.srt").write_text(srt("불일치"), encoding="utf-8")
    nested = video.parent / "nested"
    nested.mkdir()
    (nested / "lesson.srt").write_text(srt("하위 폴더"), encoding="utf-8")
    core.add_file(video)
    item, = core.external_subtitles(core.videos()[0].id)
    assert item.subtitles[0].language == language
    assert not core.search("불일치").results
    assert not core.search("하위폴더").results


def test_vtt_settings_styles_notes_and_inline_timestamps(library):
    core, video = library
    video.with_suffix(".eng.vtt").write_text(
        "WEBVTT\n\nSTYLE\n::cue { color: red; }\n\nNOTE ignored\nprivate note\n\n"
        "REGION\nid:fred\n\ncue-1\n00:12.250 --> 00:15.000 line:90% position:50%\n"
        "<v Speaker><c.green>Hello</c> <00:13.000><i>WORLD</i> &amp; friends</v>\n", encoding="utf-8")
    core.add_file(video)
    file, = core.external_subtitles(core.videos()[0].id)
    line, = file.subtitles[0].lines
    assert (line.start, line.end, line.text) == (12.25, 15, "Hello WORLD & friends")
    assert file.subtitles[0].language == "en"
    assert not core.search("private note").results


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "cp949"])
def test_multilingual_smi_empty_syncs_and_final_duration(library, encoding):
    core, video = library
    video.with_suffix(".smi").write_bytes((
        '<SAMI><HEAD><STYLE>.KRCC {Name: Korean; lang: ko-KR;} '
        '.English {Name: English; lang: en-US;}</STYLE></HEAD><BODY>'
        '<SYNC Start=1000><P Class=KRCC><b>한글</b><br>첫 줄<P Class=English>Hello &amp; world'
        '<SYNC Start=2500><P Class=KRCC>&nbsp;<P Class=English>&nbsp;'
        '<SYNC Start=4000><P Class=KRCC>마지막<P Class=English>Final'
        '</BODY></SAMI>').encode(encoding))
    core.add_file(video)
    file, = core.external_subtitles(core.videos()[0].id)
    assert file.warning is None
    korean, english = file.subtitles
    assert (korean.language, english.language) == ("ko", "en")
    assert [(line.start, line.end, line.text) for line in korean.lines] == [(1, 2.5, "한글\n첫 줄"), (4, 120, "마지막")]
    assert [(line.start, line.end, line.text) for line in english.lines] == [(1, 2.5, "Hello & world"), (4, 120, "Final")]
    assert core.search("Hello").results[0].language == "en"


def test_smi_last_sync_at_video_end_is_not_a_line(library):
    core, video = library
    video.with_suffix(".smi").write_text('<SYNC Start=120000><P Class=KRCC>영상 밖', encoding="utf-8")
    core.add_file(video)
    file, = core.external_subtitles(core.videos()[0].id)
    assert file.subtitles == ()
    assert file.warning
    assert not core.search("영상밖").results


def test_all_copy_locations_updates_removal_and_reopen(library, tmp_path):
    core, video = library
    video.with_suffix(".ko.srt").write_text(srt("원본 위치"), encoding="utf-8")
    other = tmp_path / "copies"
    other.mkdir()
    copy = other / "copy.mkv"
    copy.write_bytes(video.read_bytes())
    sidecar = copy.with_suffix(".en.srt")
    sidecar.write_text(srt("Copy location"), encoding="utf-8")
    core.add_watched_folder(video.parent)
    core.add_watched_folder(other)
    assert core.scan().added == 1
    item, = core.videos()
    assert len(core.external_subtitles(item.id)) == 2
    assert core.search("Copy location").results[0].video_id == item.id
    sidecar.write_text(srt("Updated location", "00:00:13,500"), encoding="utf-8")
    core.scan()
    assert not core.search("Copy location").results
    assert core.search("Updated location").results[0].start == 13.5
    core = make_core(tmp_path)
    assert len(core.external_subtitles(item.id)) == 2
    assert core.search("Updated location").results[0].language == "en"
    sidecar.unlink()
    core.scan()
    assert not core.search("Updated location").results
    assert len(core.external_subtitles(item.id)) == 1


def test_unchanged_files_are_not_read_again_but_mtime_or_size_change_is(library, monkeypatch):
    core, video = library
    sidecar = video.with_suffix(".srt")
    sidecar.write_text(srt("첫째"), encoding="utf-8")
    core.add_file(video)
    original = Path.read_bytes
    reads = []

    def read(path):
        if path == sidecar:
            reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    core.scan()
    core.add_file(video)
    assert reads == []
    stamp = sidecar.stat()
    sidecar.write_text(srt("둘째"), encoding="utf-8")
    os.utime(sidecar, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000_000))
    core.scan()
    assert len(reads) == 1
    assert core.search("둘째").results
    stamp = sidecar.stat()
    sidecar.write_text(srt("길이가 바뀜"), encoding="utf-8")
    os.utime(sidecar, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    core.scan()
    assert len(reads) == 2
    assert core.search("길이가바뀜").results


@pytest.mark.parametrize("broken", [b"\xff", b"\xef\xbb\xbf\xff", b"\xff\xfeX", b"not a subtitle",
                                    b"1\n00:99:00,000 --> 00:00:02,000\nbad"])
def test_broken_file_warns_without_blocking_good_file(library, broken):
    core, video = library
    broken_path = video.with_suffix(".bad.srt")
    broken_path.write_bytes(broken)
    video.with_suffix(".ko.srt").write_text(srt(), encoding="utf-8")
    result = core.add_file(video)
    assert result.added == 1
    assert any(issue.path == broken_path and issue.failed for issue in result.issues)
    files = core.external_subtitles(core.videos()[0].id)
    bad = next(file for file in files if file.path == broken_path)
    assert bad.warning and bad.subtitles == ()
    assert core.search("체중이동").results
    assert core.transcript(core.videos()[0].id) is None


def test_failed_update_removes_search_rows_then_recovers(library):
    core, video = library
    sidecar = video.with_suffix(".srt")
    sidecar.write_text(srt(), encoding="utf-8")
    core.add_file(video)
    assert core.search("체중이동").results
    sidecar.write_bytes(b"broken")
    core.scan()
    assert not core.search("체중이동").results
    assert core.external_subtitles(core.videos()[0].id)[0].warning
    sidecar.write_text(srt("복구 완료"), encoding="utf-8")
    core.scan()
    assert core.external_subtitles(core.videos()[0].id)[0].warning is None
    assert core.search("복구완료").results


def test_external_and_generated_subtitles_are_independent_and_searchable(library):
    core, video = library
    video.with_suffix(".srt").write_text(srt("공통검색 외부"), encoding="utf-8")
    core.add_file(video)
    video_id = core.videos()[0].id

    class Transcriber:
        def transcribe(self, path, spoken_language, *, cancellation, progress=None):
            return TranscriberResult("ko", (TranscriptSegment(7, 9, "공통검색 원어"),))

    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=core.database,
                   transcriber=Transcriber())
    core.request_subtitles(video_id)
    assert core.process_next_subtitle().state == "completed"
    results = core.search("공통검색").results
    assert [(row.source, row.start) for row in results] == [("transcript", 7), ("external", 12.25)]
    assert results[0].language is None
    assert len(core.transcript(video_id).lines) == 1
    assert core.subtitle_queue() == ()
    from my_video_manager.library import LIBRARY_DB_VERSION
    with sqlite3.connect(core.database) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == LIBRARY_DB_VERSION


def test_external_search_short_query_limit_and_exclusion(library):
    core, video = library
    video.with_suffix(".srt").write_text("\n\n".join(
        f"{index}\n00:00:01,000 --> 00:00:02,000\n자막 공통 {index}" for index in range(501)), encoding="utf-8")
    core.add_file(video)
    response = core.search("막")
    assert response.truncated and len(response.results) == 500
    assert all(row.source == "external" for row in response.results)
    core.exclude_video(core.videos()[0].id)
    assert not core.search("공통").results


def test_one_directory_listing_per_scan(library, monkeypatch):
    core, video = library
    for index in range(20):
        path = video.parent / f"other{index:03}.mkv"
        path.write_bytes(str(index).encode())
        path.with_suffix(".srt").write_text(srt(), encoding="utf-8")
        core.add_file(path)
    calls = []
    scandir = os.scandir

    def count(path):
        calls.append(Path(path))
        return scandir(path)

    monkeypatch.setattr(os, "scandir", count)
    core.scan()
    assert calls.count(video.parent) == 1
    assert len(core.search("체중이동").results) == 20


@pytest.mark.parametrize("failure", [PermissionError, TimeoutError, RuntimeError])
def test_transient_read_failure_is_retried_even_without_signature_change(library, monkeypatch, failure):
    core, video = library
    sidecar = video.with_suffix(".srt")
    sidecar.write_text(srt(), encoding="utf-8")
    read = Path.read_bytes

    def denied(path):
        if path == sidecar:
            raise failure("읽기 실패")
        return read(path)

    monkeypatch.setattr(Path, "read_bytes", denied)
    core.add_file(video)
    assert core.external_subtitles(core.videos()[0].id)[0].warning
    monkeypatch.setattr(Path, "read_bytes", read)
    core.scan()
    assert core.external_subtitles(core.videos()[0].id)[0].warning is None
    assert core.search("체중이동").results


def test_content_change_during_read_is_not_published(library, monkeypatch):
    core, video = library
    sidecar = video.with_suffix(".srt")
    sidecar.write_text(srt(), encoding="utf-8")
    read = Path.read_bytes

    def changing(path):
        content = read(path)
        if path == sidecar:
            path.write_text(srt("읽는 동안 변경"), encoding="utf-8")
        return content

    monkeypatch.setattr(Path, "read_bytes", changing)
    result = core.add_file(video)
    assert any("변경" in issue.message for issue in result.issues)
    assert not core.search("체중이동").results
    monkeypatch.setattr(Path, "read_bytes", read)
    core.scan()
    assert core.search("읽는동안변경").results


def test_search_backfill_and_function_free_external_writes(library, tmp_path):
    core, video = library
    video.with_suffix(".srt").write_text(srt(), encoding="utf-8")
    core.add_file(video)
    core.prepare_search()
    # 검색 설치 전부터 외부 자막이 있었던 DB를 재현한다. 검증은 공개 검색으로 한다.
    with sqlite3.connect(core.database) as db:
        db.execute("DELETE FROM search_subtitle_lines WHERE source='external'")
        db.execute("DELETE FROM search_backfill_sources WHERE source='external'")
    core = make_core(tmp_path)
    assert core.search("체중이동").results
    # 앱 전용 함수가 없는 SQLite 클라이언트의 변경도 트리거에 반영된다.
    with sqlite3.connect(core.database) as db:
        db.execute("UPDATE external_subtitle_lines SET text='외부 연결 변경', start=20")
    assert not core.search("체중이동").results
    assert core.search("외부연결변경").results[0].start == 20
    with sqlite3.connect(core.database) as db:
        db.execute("DELETE FROM external_subtitle_lines")
    assert not core.search("외부연결변경").results


def test_unknown_video_has_clear_error(library):
    core, _ = library
    with pytest.raises(ValueError, match="영상"):
        core.external_subtitles(999)


def test_missing_video_detaches_external_subtitles_and_reappearance_imports_them(library):
    core, video = library
    sidecar = video.with_suffix(".srt")
    sidecar.write_text(srt(), encoding="utf-8")
    core.add_watched_folder(video.parent)
    core.scan()
    video_id = core.videos()[0].id
    content = video.read_bytes()
    video.unlink()
    core.scan()
    assert core.video(video_id).missing
    assert core.external_subtitles(video_id) == ()
    assert not core.search("체중이동").results
    assert sidecar.is_file()
    video.write_bytes(content)
    core.scan()
    assert core.search("체중이동").results[0].video_id == video_id


def test_video_content_replacement_moves_sidecar_to_new_video(library):
    core, video = library
    video.with_suffix(".srt").write_text(srt(), encoding="utf-8")
    core.add_file(video)
    original_id = core.videos()[0].id
    video.write_bytes(b"new video content")
    core.scan()
    assert core.external_subtitles(original_id) == ()
    result, = core.search("체중이동").results
    assert result.video_id != original_id
    assert core.video(original_id).missing


def test_removed_copy_only_detaches_its_own_sidecars(library, tmp_path):
    core, video = library
    video.with_suffix(".srt").write_text(srt("남은 위치"), encoding="utf-8")
    copy = tmp_path / "copy.mkv"
    copy.write_bytes(video.read_bytes())
    copy.with_suffix(".srt").write_text(srt("사라진 위치"), encoding="utf-8")
    core.add_file(video)
    core.add_file(copy)
    copy.unlink()
    core.scan()
    assert core.search("남은위치").results
    assert not core.search("사라진위치").results


def test_unreadable_directory_is_not_treated_as_missing(library, monkeypatch):
    core, video = library
    video.with_suffix(".srt").write_text(srt(), encoding="utf-8")
    core.add_file(video)

    def denied(path):
        raise PermissionError("폴더 접근 거부")

    monkeypatch.setattr(os, "scandir", denied)
    result = core.scan()
    assert any("폴더 접근 거부" in issue.message for issue in result.issues)
    assert core.search("체중이동").results


def test_cp949_extended_hangul_and_smi_class_alias(library):
    core, video = library
    video.with_suffix(".smi").write_bytes(
        '<SYNC Start=1000><P Class=KRCC>뷁<P Class=ENCC>Hello<SYNC Start=2500><P>&nbsp;'.encode("cp949"))
    core.add_file(video)
    assert core.search("뷁").results[0].language == "ko"
    assert core.search("Hello").results[0].language == "en"


def test_filename_prefix_requires_a_separator(library):
    core, video = library
    (video.parent / "lesson2.en.srt").write_text(srt(), encoding="utf-8")
    core.add_file(video)
    assert not core.search("체중이동").results


@pytest.mark.parametrize("separator", [".", "_", "-", " ", "[", "("])
def test_filename_prefix_accepts_each_separator(library, separator):
    core, video = library
    (video.parent / f"lesson{separator}en.srt").write_text(srt(), encoding="utf-8")
    core.add_file(video)
    assert core.search("체중이동").results[0].language == "en"


def test_episode_number_and_longest_stem_ownership_on_registration_and_scan(library):
    core, video = library
    short = video.with_name("Show.mkv")
    first = video.with_name("Show E1.mkv")
    tenth = video.with_name("Show E10.mkv")
    for path in (short, first, tenth):
        path.write_bytes(path.name.encode())
    tenth.with_suffix(".ko.srt").write_text(srt("열 번째"), encoding="utf-8")
    first.with_suffix(".en.srt").write_text(srt("첫 번째"), encoding="utf-8")
    core.add_file(short)
    core.add_file(first)
    core.add_file(tenth)
    for scan in (False, True):
        if scan:
            core.scan()
        videos = {item.title: item.id for item in core.videos()}
        assert core.external_subtitles(videos["Show"]) == ()
        assert core.search("첫번째").results[0].video_id == videos["Show E1"]
        result, = core.search("열번째").results
        assert result.video_id == videos["Show E10"]


@pytest.mark.parametrize("english_start", [1000, 1500])
@pytest.mark.parametrize("closing", ["<SYNC Start=3000><P Class=KRCC>&nbsp;<SYNC Start=4000><P Class=ENCC>&nbsp;",
                                     "<SYNC Start=3000>"])
def test_smi_next_sync_is_per_language(library, english_start, closing):
    core, video = library
    video.with_suffix(".smi").write_bytes((
        f'<SYNC Start=1000><P Class=KRCC>안녕하세요<SYNC Start={english_start}><P Class=ENCC>Hello'
        + closing).encode("cp949"))
    core.add_file(video)
    file, = core.external_subtitles(core.videos()[0].id)
    assert file.warning is None
    tracks = {track.language: track.lines for track in file.subtitles}
    assert (tracks["ko"][0].start, tracks["ko"][0].end) == (1, 3)
    assert (tracks["en"][0].start, tracks["en"][0].end) == (english_start / 1000, 4 if "ENCC" in closing else 3)
    assert core.search("안녕하세요").results[0].language == "ko"


@pytest.mark.parametrize("bad", [
    "2\n00:00:20,000 --> 00:00:20,000\n버릴 줄",
    "끝 잔여 블록",
    "2\n00:00:20,50 --> 00:00:21,000\n버릴 줄",
    "큐 글자 사이의 빈 줄 뒤 텍스트",
])
def test_malformed_srt_block_preserves_good_cues_and_warning(library, bad, monkeypatch):
    core, video = library
    sidecar = video.with_suffix(".srt")
    sidecar.write_text(srt("정상 줄") + "\n" + bad + "\n\n" + srt("다음 정상 줄"), encoding="utf-8")
    result = core.add_file(video)
    file, = core.external_subtitles(core.videos()[0].id)
    assert file.warning == "외부 자막: 1개 블록을 건너뜀"
    assert len(file.subtitles[0].lines) == 2
    assert any("1개 블록" in issue.message for issue in result.issues)
    assert len(core.search("정상줄").results) == 2
    original = Path.read_bytes
    def no_reread(path):
        assert path != sidecar, "서명이 같은 부분 성공 파일을 다시 읽으면 안 됩니다."
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", no_reread)
    core.scan()
    assert core.external_subtitles(file.video_id)[0].warning == file.warning


@pytest.mark.parametrize("bad", ["<SYNC Start=500>", "<SYNC Start=1000ms>", "<SYNC>"])
def test_malformed_smi_block_preserves_good_syncs(library, bad):
    core, video = library
    video.with_suffix(".smi").write_text(
        '<SYNC Start=1000><P Class=KRCC>정상 줄' + bad + '<P Class=KRCC>버릴 줄'
        '<SYNC Start=3000><P Class=KRCC>&nbsp;<SYNC Start=4000><P Class=KRCC>다음 정상 줄', encoding="utf-8")
    core.add_file(video)
    file, = core.external_subtitles(core.videos()[0].id)
    assert file.warning == "외부 자막: 1개 블록을 건너뜀"
    assert [(line.start, line.end) for line in file.subtitles[0].lines] == [(1, 3), (4, 120)]
    assert not core.search("버릴줄").results
    assert len(core.search("정상줄").results) == 2


def test_vtt_without_blank_line_after_header(library):
    core, video = library
    video.with_suffix(".vtt").write_text("WEBVTT\n00:01.000 --> 00:02.000\nHello", encoding="utf-8")
    core.add_file(video)
    assert core.search("Hello").results[0].start == 1


@pytest.mark.parametrize("interruption", [CancelledError, AsyncCancelledError, KeyboardInterrupt])
def test_import_commits_complete_files_and_resumes_after_interruption(library, monkeypatch, interruption):
    core, video = library
    first = video.with_suffix(".a.srt")
    second = video.with_suffix(".b.srt")
    core.add_file(video)
    video_id = core.videos()[0].id
    first.write_text(srt("첫 파일"), encoding="utf-8")
    second.write_text(srt("둘째 파일"), encoding="utf-8")
    original = Path.read_bytes
    def interrupt(path):
        if path == second:
            # Another connection can read and write while the next file is parsed.
            with sqlite3.connect(core.database, timeout=.05) as db:
                assert db.execute("SELECT count(*) FROM external_subtitle_files").fetchone()[0] == 1
                db.execute("UPDATE videos SET title=title WHERE id=?", (video_id,))
            raise interruption("검사 중단")
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", interrupt)
    with pytest.raises(interruption, match="검사 중단"):
        core.scan()
    assert len(core.external_subtitles(video_id)) == 1
    assert core.search("첫파일").results
    monkeypatch.setattr(Path, "read_bytes", original)
    core = make_core(video.parent.parent)
    core.scan()
    assert len(core.external_subtitles(video_id)) == 2
    assert core.search("둘째파일").results


@pytest.mark.parametrize("broken", ["<![x <SYNC Start=1000><P>bad", *[
    "<SYNC Start=" + "9" * digits + "><P>bad" for digits in (309, 312)]])
@pytest.mark.parametrize("operation", ["scan", "add_file"])
def test_smi_parser_exception_is_isolated_to_file(library, broken, operation):
    core, video = library
    bad = video.with_suffix(".a.smi")
    good = video.with_suffix(".z.srt")
    bad.write_text(broken, encoding="utf-8")
    good.write_text(srt(), encoding="utf-8")
    core.add_watched_folder(video.parent)
    for _ in range(2):
        result = core.scan() if operation == "scan" else core.add_file(video)
        assert any(issue.path == bad and issue.failed for issue in result.issues)
        files = {file.path: file for file in core.external_subtitles(core.videos()[0].id)}
        assert files[bad].warning and files[bad].subtitles == ()
        assert files[good].warning is None
        assert core.search("체중이동").results
    bad.write_text('<SYNC Start=1000><P Class=KRCC>복구 완료', encoding="utf-8")
    core.scan()
    assert core.search("복구완료").results
    assert all(file.warning is None for file in core.external_subtitles(core.videos()[0].id))


@pytest.mark.parametrize("header", ["Kind: captions\nLanguage: en", "X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:900000"])
@pytest.mark.parametrize("separator", ["\n", "\n\n"])
def test_vtt_metadata_header_has_no_warning(library, header, separator):
    core, video = library
    video.with_suffix(".vtt").write_text(
        "WEBVTT\n" + header + separator + "00:01.000 --> 00:02.000\nHello", encoding="utf-8")
    for operation in (lambda: core.add_file(video), core.scan):
        result = operation()
        assert not result.issues
        file, = core.external_subtitles(core.videos()[0].id)
        assert file.warning is None
        assert core.search("Hello").results[0].start == 1


@pytest.mark.parametrize("operation", ["DELETE", "UPDATE"])
def test_small_subtitle_change_does_not_scan_all_search_rows(library, operation):
    core, video = library
    video.with_suffix(".large.srt").write_text("\n".join(srt("대량 자막") for _ in range(30_000)), encoding="utf-8")
    small = video.with_suffix(".small.srt")
    small.write_text("\n".join(srt("작은 자막") for _ in range(100)), encoding="utf-8")
    core.add_file(video)
    core.prepare_search()
    # Instruction count is stable across machine speeds and detects a trigger
    # scanning 30,000 search rows once for each of the 100 changed lines.
    steps = 0
    def progress():
        nonlocal steps
        steps += 1000
        return steps > 200_000
    with sqlite3.connect(core.database) as db:
        track_id = db.execute("""SELECT s.id FROM external_subtitles s
            JOIN external_subtitle_files f ON f.id=s.file_id WHERE f.path=?""", (str(small),)).fetchone()[0]
        db.set_progress_handler(progress, 1000)
        if operation == "DELETE":
            db.execute("DELETE FROM external_subtitle_lines WHERE subtitle_id=?", (track_id,))
        else:
            db.execute("UPDATE external_subtitle_lines SET text='바뀐 자막' WHERE subtitle_id=?", (track_id,))
        db.set_progress_handler(None, 0)
    assert not core.search("작은자막").results
    assert len(core.search("바뀐자막").results) == (100 if operation == "UPDATE" else 0)
    assert core.search("대량자막").results


@pytest.mark.parametrize("suffix,content", [
    (".srt", "1\n00:00:01,000 --> 00:00:01,000\n버릴 줄"),
    (".vtt", "WEBVTT\n\n끝 잔여 블록"),
    (".smi", "<SYNC Start=1000ms><P Class=KRCC>버릴 줄"),
])
def test_no_recovered_lines_is_a_file_failure(library, suffix, content):
    core, video = library
    video.with_suffix(suffix).write_text(content, encoding="utf-8")
    result = core.add_file(video)
    file, = core.external_subtitles(core.videos()[0].id)
    assert file.warning
    assert file.subtitles == ()
    assert any(issue.failed for issue in result.issues)
    assert not core.search("버릴줄").results


def test_skipped_block_warning_counts_multiple_blocks(library):
    core, video = library
    video.with_suffix(".vtt").write_text("WEBVTT\n" + srt("정상") + "\n잔여 하나\n\n잔여 둘", encoding="utf-8")
    core.add_file(video)
    file, = core.external_subtitles(core.videos()[0].id)
    assert file.warning == "외부 자막: 2개 블록을 건너뜀"
    assert core.search("정상").results


def test_summary_matches_files_without_loading_cue_text(library):
    core, video = library
    video.with_suffix('.smi').write_text(
        '<SYNC Start=1000><P Class=KRCC>한국어<P Class=ENCC>English', encoding='utf-8')
    video.with_suffix('.srt').write_text(srt() + '\n잘못된 블록', encoding='utf-8')
    video.with_suffix('.broken.vtt').write_text('WEBVTT\n\n잘못된 파일', encoding='utf-8')
    core.add_file(video)
    video_id = core.videos()[0].id
    files = core.external_subtitles(video_id)
    summaries = core.external_subtitle_summaries(video_id)
    assert len(summaries) == 3
    for summary, file in zip(summaries, files):
        assert (summary.id, summary.name, summary.warning) == (file.id, file.path.name, file.warning)
        assert [(s.language, s.language_class, s.line_count) for s in summary.subtitles] == [
            (s.language, s.language_class, len(s.lines)) for s in file.subtitles]
        assert all(not hasattr(s, 'lines') for s in summary.subtitles)
    video.with_suffix('.srt').unlink()
    core.scan()
    assert len(core.external_subtitle_summaries(video_id)) == 2
    with pytest.raises(ValueError, match='영상을 찾을 수 없습니다'):
        core.external_subtitle_summaries(-1)


@pytest.mark.parametrize('content,message', [
    (b'\xff\xfeX', '문자 인코딩이 올바르지 않습니다'),
    (b'<![x <SYNC Start=1000><P>bad', '자막 형식을 해석하지 못했습니다'),
    (b'<SYNC Start=' + b'9' * 312 + b'><P>bad', '자막 형식을 해석하지 못했습니다'),
])
def test_parser_exception_warning_is_readable_korean(library, content, message):
    core, video = library
    video.with_suffix('.smi').write_bytes(content)
    result = core.add_file(video)
    file, = core.external_subtitles(core.videos()[0].id)
    assert message in file.warning
    assert any(message in issue.message for issue in result.issues)
    assert file.subtitles == ()
