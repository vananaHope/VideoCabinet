"""Qt 창 없이 실제 React 컴포넌트의 응답 경계와 키보드 진입점을 검사한다."""
from pathlib import Path
import shutil
import subprocess

import pytest


def check_rendering(scenario):
    root = Path(__file__).resolve().parents[1]
    if not shutil.which('node') or not (root / 'frontend/node_modules/typescript').exists():
        pytest.skip('npm ci와 Node가 필요합니다')
    script = r"""
      const ts = require('typescript'), fs = require('fs'), path = require('path');
      const assert = require('assert'), React = require('react');
      const {renderToStaticMarkup} = require('react-dom/server');
      const cache = new Map();
      function load(name, from = 'src') {
        if (!name.startsWith('@/') && !name.startsWith('.')) return require(name);
        const base = name.startsWith('@/') ? path.resolve('src', name.slice(2)) : path.resolve(from, name);
        const file = ['.tsx', '.ts'].map(ext => base + ext).find(fs.existsSync);
        if (cache.has(file)) return cache.get(file).exports;
        const module = {exports: {}}; cache.set(file, module);
        const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {compilerOptions: {
          module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
          esModuleInterop: true, target: ts.ScriptTarget.ES2022,
        }}).outputText;
        new Function('require', 'module', 'exports', code)(next => load(next, path.dirname(file)), module, module.exports);
        return module.exports;
      }
    """
    result = subprocess.run(['node', '-e', script + scenario], cwd=root / 'frontend',
                            text=True, encoding='utf-8', capture_output=True)
    assert result.returncode == 0, result.stderr


def test_highlights_keep_same_video_during_refresh_and_hide_other_video():
    check_rendering(r"""
      const {HighlightPanel} = load('@/components/highlight-panel');
      const item = {id: 3, start: 1.125, end: null, note: 'current-scene',
        tags: [{id: 1, name: 'first-tag'}, {id: 2, name: 'second-tag'}]};
      const render = snapshot => renderToStaticMarkup(React.createElement(HighlightPanel, {
        videoId: 7, revision: 4, snapshot, onAction() {},
      }));
      for (const snapshot of [null, {videoId: 6, revision: 4, items: [item]}]) {
        const html = render(snapshot);
        assert(html.includes('불러오는 중'));
        assert(!html.includes('current-scene'));
        assert(!html.includes('role="option"'));
      }
      const busy = render({videoId: 7, revision: 3, items: [item]});
      assert(busy.includes('current-scene') && busy.includes('aria-busy="true"'));
      assert(!busy.includes('불러오는 중'));
      assert(busy.match(/<button\b[^>]*>/g).every(button => button.includes('disabled=""')));
      const html = render({videoId: 7, revision: 4, items: [item]});
      assert(html.includes('aria-busy="false"') && !html.includes('disabled=""'));
      assert(html.includes('current-scene'));
      assert(html.includes('first-tag') && html.includes('+1'));
      // 키 힌트는 키 칩(kbd) + 글자다.
      assert(/>F2<\/kbd>/.test(html) && html.replace(/<[^>]+>/g, '').includes('F2편집'));
      assert(!html.includes('불러오는 중'));
      const buttons = html.match(/<button\b[^>]*>/g);
      assert.equal(buttons.length, 2);
      assert(buttons.every(button => button.includes('tabindex="-1"')));
      assert(render({videoId: 7, revision: 4, items: []}).includes('하이라이트 없음'));
    """)


def test_card_distinguishes_glance_only_from_viewing_and_no_history():
    check_rendering(r"""
      const {VideoCard} = load('@/components/video-card');
      const base = {id: 1, title: '영상', duration: 100, series: '', tags: [],
                    viewingCount: 0, watchedSeconds: 0, lastViewedAt: null};
      const render = values => renderToStaticMarkup(React.createElement(VideoCard, {
        video: {...base, ...values},
      }));
      const glance = render({lastViewedAt: '2026-10-14T00:00:00Z'});
      assert(glance.includes('마지막 틀어보기'));
      assert(glance.includes('틀어보기는 시청 횟수·시간에 넣지 않습니다'));
      assert(!glance.includes('마지막 시청'));
      assert(glance.includes('0회') && glance.includes('0:00'));
      const viewed = render({viewingCount: 1, watchedSeconds: 35, lastViewedAt: '2026-10-14T00:00:00Z'});
      assert(viewed.includes('마지막 시청') && !viewed.includes('마지막 틀어보기'));
      assert(viewed.includes('1회') && viewed.includes('0:35'));
      const empty = render({});
      assert(empty.includes('마지막 시청') && empty.includes('기록 없음'));
      assert(!empty.includes('마지막 틀어보기'));
    """)


def test_detail_info_shows_modified_date_or_why_it_is_missing():
    check_rendering(r"""
      const {DetailPanel} = load('@/components/detail-panel');
      const base = {id: 1, title: '영상', duration: 100, thumbnail: null, missing: false, locationCount: 1,
                    finished: false, abandoned: false, favorite: false, resumePoint: null, stoppedPercent: null,
                    tags: [], series: '', viewingCount: 0, watchedSeconds: 0, lastViewedAt: null,
                    modifiedAt: null, hasSubtitles: false};
      const render = values => renderToStaticMarkup(React.createElement(DetailPanel, {
        video: {...base, ...values}, details: null, highlights: null, revision: 0, tab: 'info',
        onTabChange() {}, scanning: false, onAction() {}, onHighlight() {}, onRandomTag() {},
      }));
      process.env.TZ = 'Asia/Seoul';
      assert(render({modifiedAt: '2026-09-01T18:00:00+00:00'}).includes('수정한 날짜: 2026. 09. 02.'));
      assert(render({missing: true, locationCount: 0}).includes('수정한 날짜: 파일 없음'));
      assert(render({}).includes('수정한 날짜: 알 수 없음'));
    """)
