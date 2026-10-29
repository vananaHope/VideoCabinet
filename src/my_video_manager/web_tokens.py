"""웹 및 후속 Qt 재생 화면이 공유하는 디자인 값."""
import json
from pathlib import Path

# 글자 역할마다 정하는 값. 크기는 typography의 글자 단계 이름(text-sm 등)으로 적는다.
TYPE_ROLE_FIELDS = ('size', 'line-height', 'weight', 'letter-spacing')


def web_tokens():
    return json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))


def type_roles(tokens=None):
    """글자 역할(큰 숫자·페이지 제목·구역 제목·본문·라벨과 강조 변형)별 크기·줄 높이·굵기·자간. 크기는 rem 값으로 푼다.

    굵기는 번들 글꼴에 파일이 있는 굵기만 쓴다. 없는 굵기를 적으면 브라우저와 Qt가 굵기를 흉내 내므로 실패로 처리한다.
    """
    tokens = tokens or web_tokens()
    typography, weights = tokens['typography'], tokens['bundled-font']['weights']
    roles = {}
    for name, role in typography['roles'].items():
        if tuple(role) != TYPE_ROLE_FIELDS:
            raise ValueError(f'글자 역할 {name}의 항목은 {", ".join(TYPE_ROLE_FIELDS)} 순서여야 합니다: {list(role)}')
        if role['weight'] not in weights:
            raise ValueError(f'글자 역할 {name}의 굵기 {role["weight"]}는 번들 글꼴 굵기({", ".join(weights)})가 아닙니다.')
        roles[name] = {**role, 'size': typography[role['size']]}
    return roles
