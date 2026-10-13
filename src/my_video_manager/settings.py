"""앱 설정의 작은 영속 저장소. 화면은 AppCore를 통해 사용한다."""


class Settings:
    def __init__(self, connect):
        self._connect = connect
        with connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    @property
    def translation_cli(self) -> str:
        with self._connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key = 'translation_cli'").fetchone()
            return row[0] if row else "codex"

    def set_translation_cli(self, cli: str) -> None:
        if cli not in ("codex", "claude"):
            raise ValueError("번역 CLI는 codex 또는 claude를 고르세요.")
        with self._connect() as db:
            db.execute("INSERT INTO settings VALUES ('translation_cli', ?) "
                       "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (cli,))
