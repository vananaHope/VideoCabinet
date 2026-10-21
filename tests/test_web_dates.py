"""#232: 화면의 날짜 모양은 공용 모듈 한 곳에서 만들고 컴퓨터 시간대를 따른다."""
from test_web_highlight_rendering import check_rendering


def test_date_formats_follow_computer_time_zone():
    check_rendering(r"""
      const {formatDate, formatDateTime, formatShortDate} = load('@/lib/dates');
      const moment = '2026-10-21T06:04:00+00:00';
      process.env.TZ = 'Asia/Seoul';
      assert.strictEqual(formatDate(moment), '2026. 10. 21.');
      assert.strictEqual(formatDateTime(moment), '2026. 10. 21. 15:04');
      assert.strictEqual(formatShortDate(moment), '10. 21.');
      assert.strictEqual(formatDateTime('2026-01-05T23:59:00+09:00'), '2026. 01. 05. 23:59');
      process.env.TZ = 'America/New_York';
      assert.strictEqual(formatDateTime(moment), '2026. 10. 21. 02:04');
      assert.strictEqual(formatDate('2026-10-21T02:00:00+00:00'), '2026. 10. 20.');
      // 날짜만 있는 값은 시간대와 상관없이 그 달력 날짜다.
      assert.strictEqual(formatDate('2026-10-21'), '2026. 10. 21.');
      assert.strictEqual(formatShortDate('2026-10-21'), '10. 21.');
      for (const format of [formatDate, formatDateTime, formatShortDate])
        assert.strictEqual(format('not a date'), '시각 정보 없음');
    """)


def test_custom_date_range_chip_uses_date_format():
    check_rendering(r"""
      const {LibraryFilterChips} = load('@/components/library-filters');
      const chip = (label, range) => ({key: label, label, range, reset: {}});
      const html = renderToStaticMarkup(React.createElement(LibraryFilterChips, {
        options: {}, onChange() {}, chips: [
          chip('수정한 날짜', {start: '2026-10-01', end: null}),
          chip('추가일', {start: null, end: '2027-01-05'}),
          chip('마지막 시청: 최근 7일', null),
        ]}));
      for (const text of ['수정한 날짜: 2026. 10. 01. ~ 끝 없음', '추가일: 처음 ~ 2027. 01. 05.', '마지막 시청: 최근 7일'])
        assert(html.includes(`title="${text}"`) && html.includes(`aria-label="${text} 지우기"`), text);
    """)
