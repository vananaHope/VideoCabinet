"""새 버전 알림의 코어 규칙: 알릴 결과, 건너뛴 버전 기억, 서명되지 않은 릴리스 노트 요약."""
from datetime import timedelta

import pytest

from my_video_manager.update_check import (
    LAST_CHECK_KEY, RELEASE_NOTES_LIMIT, RELEASE_NOTES_LINES, SKIPPED_VERSION_KEY, release_notes_summary,
)
from test_update_check import FakeHttp, NOW, check, clock, core, http, installed, key, reopen  # noqa: F401


def test_patch_and_full_results_are_announced_but_none_and_failure_are_not(core, key):
    assert core.update_to_announce() is None
    assert check(core, FakeHttp(key)).kind == 'patch'
    assert core.update_to_announce() == core.last_update_check()
    assert check(core, FakeHttp(key, patch=False)).kind == 'full'
    assert core.update_to_announce().kind == 'full'
    assert check(core, FakeHttp(key), version='1.2.3').kind == 'none'
    assert core.update_to_announce() is None
    failing = FakeHttp(key)
    failing.failure = OSError('offline')
    assert check(core, failing).kind == 'failed'
    assert core.update_to_announce() is None


def test_stale_history_is_not_announced(core, clock, http):
    assert check(core, http).kind == 'patch'
    # 1.2.3을 설치한 뒤에는 1.0.0에서 확인한 "1.2.3 있음" 기록으로 알리지 않는다.
    reopened = reopen(core, clock, installed('1.2.3'))
    assert reopened.last_update_check().stale
    assert reopened.update_to_announce() is None


def test_skipped_version_is_remembered_and_newer_version_is_announced_again(core, clock, key):
    assert check(core, FakeHttp(key, version='1.2.3')).latest_version == '1.2.3'
    core.skip_update_version('1.2.3')
    assert core.update_to_announce() is None
    # 다시 시작하고 같은 버전을 다시 확인해도 알리지 않는다.
    clock.now += timedelta(days=2)
    reopened = reopen(core, clock)
    assert reopened.skipped_update_version() == '1.2.3'
    assert check(reopened, FakeHttp(key, version='1.2.3')).kind == 'patch'
    assert reopened.update_to_announce() is None
    # 더 새 버전이 나오면 건너뛴 기록이 남아 있어도 알린다.
    newer = check(reopened, FakeHttp(key, version='1.3.0'))
    assert reopened.update_to_announce() == newer
    assert reopened.skipped_update_version() == '1.2.3'


def test_skipping_clears_and_rejects_bad_versions(core, http):
    check(core, http)
    core.skip_update_version('1.2.3')
    core.clear_skipped_update_version()
    assert core.skipped_update_version() is None
    assert core.update_to_announce().latest_version == '1.2.3'
    for bad in ('', 'v1.2.3', '1.2', None, 123):
        with pytest.raises(ValueError):
            core.skip_update_version(bad)
    assert core.skipped_update_version() is None


@pytest.mark.parametrize('saved', ['1.2', 'garbage', 12, None, ['1.2.3']])
def test_damaged_skipped_version_is_ignored(core, http, saved):
    check(core, http)
    core.settings.set(SKIPPED_VERSION_KEY, saved)
    assert core.skipped_update_version() is None
    assert core.update_to_announce() is not None


def test_release_notes_come_from_the_same_release_response(core, http):
    http.release['body'] = '## 수정\n\n- **재생** 문제를 고쳤습니다 (#1)'
    result = check(core, http)
    assert result.release_notes == '수정\n· 재생 문제를 고쳤습니다 (#1)'
    assert len(http.calls) == 3  # 노트를 위해 따로 요청하지 않는다.
    assert reopen(core, None).last_update_check().release_notes == result.release_notes


def test_release_notes_are_kept_only_for_an_available_update(core, http):
    http.release['body'] = '노트'
    assert check(core, http, version='1.2.3').release_notes is None
    assert check(core, http).release_notes == '노트'
    http.signature = b'bad'
    failed = check(core, http)
    assert failed.kind == 'failed' and failed.release_notes is None
    assert core.last_update_check().release_notes is None


@pytest.mark.parametrize('body', [None, 12, ['notes'], {'a': 1}, '', '   \n\n'])
def test_missing_release_notes_still_announce(core, http, body):
    http.release['body'] = body
    result = check(core, http)
    assert result.kind == 'patch' and result.release_notes is None
    assert core.update_to_announce() == result


def test_release_notes_are_plain_text_without_markup_links_or_controls():
    body = ('<script>alert(1)</script><img src=x onerror=alert(1)>\n'
            '### 새 기능\n'
            '* [링크 글자](https://evil.example/) 와 ![그림](https://x/y.png)\n'
            '    - 하위 항목 `code` __굵게__\n'
            '방향‮바꿈​ 문자\x07와\t탭\r\n'
            '<!-- 숨은 주석 -->\n'
            '-\n')
    assert release_notes_summary(body) == ('alert(1)\n새 기능\n· 링크 글자 와 그림\n  · 하위 항목 code 굵게\n'
                                           '방향바꿈 문자와 탭')


@pytest.mark.parametrize('body,expected', [
    ('자세히: https://evil.example/path', '자세히:'),
    ('[글자][1]\n\n[1]: https://evil.example', '글자'),
    ('[a [b] c](https://evil.example)', 'a [b] c'),
    ('[x](https://a.com/(b))', 'x'),
    ('<!--\n숨은 줄 1\n숨은 줄 2\n-->\n본문', '본문'),
    ('<img\nsrc="https://evil/x.png"\nonerror="alert(1)">', None),
    ('<<b>b>굵게', '굵게'),
    ('* Fix by @x in https://github.com/o/r/pull/1\n\n**Full Changelog**: https://github.com/o/r/compare/a...b',
     '· Fix by @x in\nFull Changelog:'),
])
def test_bare_urls_reference_links_nested_brackets_and_multiline_markup_are_removed(body, expected):
    assert release_notes_summary(body) == expected


@pytest.mark.parametrize('body', [
    '## 수정\n- a\n  - b\n    - c `d`', '- [링크](https://x.example) 와 ![그림](https://y.example/a.png)',
    '\n'.join(f'- 항목 {index}' for index in range(RELEASE_NOTES_LINES + 3)), '가' * 5000,
    '  · 이미 요약한 하위 항목\n· 항목', 'a<b>c<<b>b>', '- \n-\n# \n#제목',
    # 줄 안 마크업을 지우면 태그가 생기는 입력: 요약 전체를 안정될 때까지 반복한다.
    'a <**b**> c', '<`x`\ny> b',
])
def test_summary_of_a_summary_is_the_same_so_saved_notes_load(core, body):
    notes = release_notes_summary(body)
    assert release_notes_summary(notes) == notes
    core.settings.set(LAST_CHECK_KEY, {'checked_at': NOW.isoformat(), 'kind': 'patch', 'current_version': '1.0.0',
                                       'latest_version': '1.2.3', 'download_size': 12, 'failure_reason': None,
                                       'release_notes': notes})
    assert core.last_update_check().release_notes == notes


def test_long_release_notes_are_cut_for_display():
    many = '\n'.join(f'- 항목 {index}' for index in range(RELEASE_NOTES_LINES + 3))
    text = release_notes_summary(many)
    assert text.endswith('…') and text.count('\n') == RELEASE_NOTES_LINES - 1
    long = release_notes_summary('가' * 5000)
    assert len(long) == RELEASE_NOTES_LIMIT and long.endswith('…')
    huge = release_notes_summary(('줄\n' * 1_000_000))
    assert len(huge) <= RELEASE_NOTES_LIMIT


@pytest.mark.parametrize('notes', ['', 12, 'x' * (RELEASE_NOTES_LIMIT + 1),
                                   # 설정 DB를 고쳐 넣은 방향 제어 문자·태그·주소: 다시 요약한 값과 다르다.
                                   'A\u202eB<img src=x>', '자세히: https://evil.example/path', '[x](https://a.com)'])
def test_damaged_saved_release_notes_reject_the_record(core, notes):
    core.settings.set(LAST_CHECK_KEY, {'checked_at': NOW.isoformat(), 'kind': 'patch', 'current_version': '1.0.0',
                                       'latest_version': '1.2.3', 'download_size': 12, 'failure_reason': None,
                                       'release_notes': notes})
    assert core.last_update_check() is None


def test_records_saved_before_release_notes_still_load(core):
    core.settings.set(LAST_CHECK_KEY, {'checked_at': NOW.isoformat(), 'kind': 'patch', 'current_version': '1.0.0',
                                       'latest_version': '1.2.3', 'download_size': 12, 'failure_reason': None})
    assert core.last_update_check().release_notes is None
    assert core.update_to_announce().latest_version == '1.2.3'
