"""스크린샷만 얻으려고 검사 스크립트의 단언 몇 개를 print로 바꾼 사본을 만든다(원본은 그대로).

    python relax.py <저장소> <사본 폴더>

바꾸는 단언은 화면 배치와 무관한 것(live region 개수, #415)이다. 바꾼 줄을 찾지 못하면 멈춘다.
필터 팝오버 높이 28rem 한도와 준비 진행률 aria 값 단언은 #416에서 원본 스크립트를 고쳐 여기서 뺐다.
"""
import sys
from pathlib import Path

repo, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
ROOT = ("Path(__file__).resolve().parents[1]", f"Path({str(repo)!r})")
EDITS = {
    'check_web_scan_notice.py': [ROOT, ("    assert live == 1, live", "    print('live', live)"),
        ("    assert list_box[0] < list_box[1] and list_box[0] <= 128, list_box", "    print('list_box', list_box)")],
}
for name, edits in EDITS.items():
    text = (repo / 'scripts' / name).read_text(encoding='utf-8')
    for old, new in edits:
        if text.count(old) != 1:
            sys.exit(f'{name}: 바꿀 줄을 찾지 못했다: {old.strip()[:60]}')
        text = text.replace(old, new)
    (out / name).write_text(text, encoding='utf-8')
    print('사본', out / name)
