"""번역 작업의 용어집 값. 저장 방식과 무관하게 첫 번역과 최근 사용 순서를 유지한다."""

from dataclasses import dataclass


GLOSSARY_LIMIT = 200


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
                 and all(isinstance(item[key], str) and item[key].strip() for key in ('source', 'target')))


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
            if source in text:
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
