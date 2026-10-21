"""번역 선택·키와 실행 구성. 화면에는 공개 표시 값만 돌려준다."""
import json
import re
from uuid import uuid4

from .secret_store import Secret, SecretStore, SecretStoreError
from .translation_models import PROVIDERS, DEFAULT_PROVIDER, NON_CHAT_MODELS, EXPENSIVE_EFFORTS, model_choice, provider


class TranslationOptions:
    def __init__(self, settings, connect, directory, clock, *, secret_store=None, transport=None):
        self.settings, self.connect, self.clock = settings, connect, clock
        self._store, self.directory = secret_store, directory
        self._key_cache = None
        self.transport = transport

    @property
    def store(self):
        if self._store is None:
            self._store = SecretStore(self.directory)
        return self._store

    def selection(self, identifier):
        item = provider(identifier)
        model = self.settings.get('translation.model.' + identifier, item.default_model)
        effort = self.settings.get('translation.effort.' + identifier, '')
        if effort not in (model_choice(identifier, model).reasoning_efforts or ()):
            effort = ''
        return dict(provider=identifier, model=model, effort=effort)

    def key_status(self):
        try:
            store = self.store
            try:
                stat = store.path.stat()
                stamp = stat.st_mtime_ns, stat.st_size
            except FileNotFoundError:
                stamp = None
            if self._key_cache is not None and self._key_cache[0] == stamp:
                return self._key_cache[1]
            result = store.masked() or '', ''
            self._key_cache = stamp, result
            return result
        except (SecretStoreError, OSError) as error:
            if isinstance(error, OSError):
                return '', '저장된 키를 읽지 못했습니다. 키를 다시 등록하세요.'
            return '', str(error)

    def fallback_enabled(self):
        masked, _ = self.key_status()
        return bool(masked) and self.settings.get('translation.fallback', True) is True

    def snapshot(self):
        masked, error = self.key_status()
        return dict(provider=self.settings.get('translation.cli', DEFAULT_PROVIDER),
                    selections=[self.selection(p.id) for p in PROVIDERS],
                    providers=[dict(id=p.id, label=p.label, default_model=p.default_model,
                                    notice=p.external_notice, models=[self.model_data(m) for m in p.models],
                                    custom_efforts=list(model_choice(p.id, 'custom').reasoning_efforts or ()),
                                    cli_default=p.id != 'opencode_go',
                                    unknown_model=self.model_data(model_choice(p.id, 'custom')),
                                    expensive_efforts=list(EXPENSIVE_EFFORTS),
                                    effort_notice='번역이 느려지고 구독 사용량을 더 씁니다.') for p in PROVIDERS],
                    key_masked=masked, key_error=error,
                    fallback=self.fallback_enabled(),
                    fallback_notice='이어받기를 켜면 실패한 번역의 남은 자막 텍스트가 OpenCode 서버로 전송됩니다.')

    def model_data(self, choice):
        policy = choice.policy
        messages = []
        if policy:
            messages.append('학습 사용' if policy.training else '학습 미사용' if policy.training is False else '학습 사용 여부 미확인')
            messages.append(f'보존 {policy.retention_days}일' if policy.retention_days is not None else '보존 기간 미확인')
        warning = choice.needs_warning(self.clock().date())
        # 만료일은 ISO 날짜로 넘기고 화면이 정책 문구와 주의 사이에 날짜 모양으로 넣는다.
        return dict(id=choice.model_id, label=choice.label, efforts=list(choice.reasoning_efforts or ()),
                    policy=' · '.join(messages),
                    valid_until=policy.valid_until.isoformat() if policy and policy.valid_until else None,
                    policy_warning='주의: 학습 사용·미확인 또는 만료 정책을 확인하세요.' if warning else '', warning=warning,
                    training_warning=bool(policy and policy.training is True),
                    expired_warning=bool(policy and policy.valid_until and self.clock().date() > policy.valid_until))

    def save(self, identifier, selections, fallback, *, key_action='keep', key=''):
        provider(identifier)
        if not isinstance(fallback, bool) or key_action not in ('keep', 'replace', 'delete'):
            raise ValueError('번역 설정 값을 확인하세요.')
        changes = {'translation.cli': identifier, 'translation.fallback': fallback}
        notices = []
        if not isinstance(selections, list) or len(selections) != len(PROVIDERS) or {s.get('provider') for s in selections} != {p.id for p in PROVIDERS}:
            raise ValueError('방식별 모델 설정이 필요합니다.')
        for selection in selections:
            name, model, effort = selection['provider'], selection['model'], selection['effort']
            provider(name)
            if not isinstance(model, str) or (model and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]*', model)):
                raise ValueError('모델 ID 형식이 올바르지 않습니다.')
            if name == 'opencode_go' and (not model or model in NON_CHAT_MODELS):
                raise ValueError('OpenCode Go는 chat/completions 모델 이름이 필요합니다.')
            if effort and effort not in (model_choice(name, model).reasoning_efforts or ()):
                effort = ''
                notices.append('지원하지 않는 추론 강도를 기본으로 되돌렸습니다.')
            changes['translation.model.' + name] = model
            changes['translation.effort.' + name] = effort
        secret = Secret(key) if key_action == 'replace' else None
        # 입력 검증 후, DB 트랜잭션 안에서 키 저장 실패 시 설정도 롤백한다.
        try:
            previous = self.store.read() if key_action != 'keep' else None
        except SecretStoreError:
            previous = None  # 복호화할 수 없는 키도 교체·삭제할 수 있다.
        changed_key = False
        try:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                for name, value in changes.items():
                    db.execute('INSERT INTO settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                               (name, json.dumps(value, ensure_ascii=False)))
                if key_action == 'replace':
                    self.store.save(secret)
                    changed_key = True
                elif key_action == 'delete':
                    self.store.delete()
                    changed_key = True
        except Exception:
            if changed_key:
                self.store.save(previous) if previous is not None else self.store.delete()
            raise
        finally:
            if key_action != 'keep':
                self._key_cache = None
        return ' '.join(notices)

    def adapter(self, session_id, *, key=None, selection=None):
        from .opencode_go import OpenCodeGoTranslator
        selected = selection if selection is not None else self.selection('opencode_go')
        return OpenCodeGoTranslator(self.store.read if key is None else lambda: key,
                                    session_id=session_id, model=selected['model'], effort=selected['effort'],
                                    transport=self.transport, clock=self.clock)

    def check_key(self, key='', *, delete=False, cancellation=None):
        from .opencode_go import KeyCheckResult
        if delete:
            return KeyCheckResult('missing_key')
        return self.adapter(uuid4().hex, key=Secret(key) if key else None).check_key(cancellation=cancellation)

    def models(self, key='', *, cancellation=None):
        adapter = self.adapter(uuid4().hex, key=Secret(key) if key else None)
        return [self.model_data(m) for m in adapter.models(cancellation=cancellation)]
