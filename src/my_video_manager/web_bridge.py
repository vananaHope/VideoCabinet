"""브리지의 JSON 응답 인코딩."""
import json


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
