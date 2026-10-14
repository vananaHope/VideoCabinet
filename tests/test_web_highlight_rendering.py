"""Qt 창 없이 실제 React 컴포넌트의 응답 경계와 키보드 진입점을 검사한다."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_highlights_only_render_the_selected_video_and_current_revision():
    root = Path(__file__).resolve().parents[1]
    if not shutil.which('node') or not (root / 'frontend/node_modules/typescript').exists():
        pytest.skip('npm ci와 Node가 필요합니다')
    script = r"""
      const ts = require('typescript'), fs = require('fs'), path = require('path');
      const assert = require('assert'), React = require('react');
      const {renderToStaticMarkup} = require('react-dom/server');
      const cache = new Map();
      function load(name) {
        if (!name.startsWith('@/')) return require(name);
        const base = path.resolve('src', name.slice(2));
        const file = ['.tsx', '.ts'].map(ext => base + ext).find(fs.existsSync);
        if (cache.has(file)) return cache.get(file).exports;
        const module = {exports: {}}; cache.set(file, module);
        const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {compilerOptions: {
          module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
          esModuleInterop: true, target: ts.ScriptTarget.ES2022,
        }}).outputText;
        new Function('require', 'module', 'exports', code)(load, module, module.exports);
        return module.exports;
      }
      const {HighlightPanel} = load('@/components/highlight-panel');
      const item = {id: 3, start: 1.125, end: null, note: 'current-scene',
        tags: [{id: 1, name: 'first-tag'}, {id: 2, name: 'second-tag'}]};
      const render = snapshot => renderToStaticMarkup(React.createElement(HighlightPanel, {
        videoId: 7, revision: 4, snapshot, onAction() {},
      }));
      for (const snapshot of [null, {videoId: 6, revision: 4, items: [item]},
                              {videoId: 7, revision: 3, items: [item]}]) {
        const html = render(snapshot);
        assert(html.includes('불러오는 중'));
        assert(!html.includes('current-scene'));
        assert(!html.includes('role="option"'));
      }
      const html = render({videoId: 7, revision: 4, items: [item]});
      assert(html.includes('current-scene'));
      assert(html.includes('first-tag') && html.includes('+1'));
      assert(html.includes('F2 편집'));
      assert(!html.includes('불러오는 중'));
      const buttons = html.match(/<button\b[^>]*>/g);
      assert.equal(buttons.length, 2);
      assert(buttons.every(button => button.includes('tabindex="-1"')));
      assert(render({videoId: 7, revision: 4, items: []}).includes('하이라이트 없음'));
    """
    result = subprocess.run(['node', '-e', script], cwd=root / 'frontend',
                            text=True, encoding='utf-8', capture_output=True)
    assert result.returncode == 0, result.stderr
