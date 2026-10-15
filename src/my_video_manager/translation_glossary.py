"""번역 작업의 용어집 값. 저장 방식과 무관하게 첫 번역과 최근 사용 순서를 유지한다."""

from dataclasses import dataclass
import json
import re


GLOSSARY_LIMIT = 200
GLOSSARY_TERM_LENGTH = 60
GLOSSARY_PROMPT_BYTES = 24 * 1024


@dataclass(frozen=True)
class GlossaryEntry:
    source: str
    target: str


def parse_glossary(value) -> tuple[GlossaryEntry, ...]:
    """잘못된 항목만 버린다. 번역 줄의 성공 여부에는 영향을 주지 않는다."""
    if not isinstance(value, list):
        return ()
    return tuple(GlossaryEntry(item['source'].strip(), item['target'].strip())
                 for item in value if isinstance(item, dict) and set(item) == {'source', 'target'}
                 and all(isinstance(item[key], str) and item[key].strip()
                         and len(item[key]) <= GLOSSARY_TERM_LENGTH
                         and not any(c in item[key] for c in '\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029') for key in ('source', 'target')))


def prompt_glossary(entries):
    """UTF-8 JSON 예산 안에 최근 항목부터 담고 저장 순서로 반환한다."""
    valid = parse_glossary([{'source': e.source, 'target': e.target} for e in entries])
    selected = []
    size = 2  # JSON 배열의 대괄호
    for entry in reversed(valid[-GLOSSARY_LIMIT:]):
        item = {'source': entry.source, 'target': entry.target}
        cost = len(json.dumps(item, ensure_ascii=False).encode('utf-8')) + (2 if selected else 0)
        if size + cost > GLOSSARY_PROMPT_BYTES:
            break
        selected.append(item)
        size += cost
    return list(reversed(selected))


@dataclass(frozen=True)
class Glossary:
    # 오래 사용하지 않은 항목부터. 이 순서를 저장하면 재시작 후에도 정책을 유지할 수 있다.
    entries: tuple[GlossaryEntry, ...] = ()

    def updated(self, lines, additions=()):
        entries = {entry.source: entry for entry in self.entries}
        for entry in additions:
            # 기존 대응을 바꾸지 않되 다시 보고된 용어는 최근 사용으로 센다.
            original = entries.pop(entry.source, entry)
            entries[entry.source] = original
        text = '\n'.join(line.text for line in lines)
        for source in tuple(entries):
            if re.search(r'\b' + re.escape(source) + r'\b', text):
                entries[source] = entries.pop(source)
        return Glossary(tuple(entries.values())[-GLOSSARY_LIMIT:])


class GlossaryStore:
    """진행 저장 트랜잭션을 빌려 쓰는 작업 단위 저장소. 완료·삭제는 FK로 정리한다."""

    @staticmethod
    def load(db, queue_id):
        return Glossary(tuple(GlossaryEntry(*row) for row in db.execute(
            'SELECT source, target FROM translation_glossary WHERE queue_id=? ORDER BY ordinal', (queue_id,))))

    @staticmethod
    def save(db, queue_id, glossary):
        db.execute('DELETE FROM translation_glossary WHERE queue_id=?', (queue_id,))
        db.executemany('INSERT INTO translation_glossary VALUES (?, ?, ?, ?)',
                       [(queue_id, entry.source, entry.target, i) for i, entry in enumerate(glossary.entries)])
