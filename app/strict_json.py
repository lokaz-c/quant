"""
JSON that stays within RFC 8259 in both directions.

Python's json module writes NaN, Infinity and -Infinity as bare tokens by
default. They are not JSON: JSON.parse rejects them and most other parsers
do too, so a client either fails or has to patch the text. The API's
convention is that a value with no finite result is null, with the reason
alongside (docs/api.md#undefined-metrics). This provider enforces it:

- responses: dumps uses allow_nan=False, so a non-finite float raises
  ValueError. The route turns that into a 500 and logs it, and the test
  suite fails, instead of a client receiving invalid JSON.
- requests: loads rejects the NaN and Infinity tokens and numbers that
  overflow a float (1e400 parses as inf), so they can't reach the engine.
  Flask answers 400 for a body that fails to parse.
"""
import math

from flask.json.provider import DefaultJSONProvider


def _reject_constant(token: str):
    raise ValueError(f'{token} is not valid JSON')


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f'{text} is out of range for a double-precision number')
    return value


class StrictJSONProvider(DefaultJSONProvider):
    sort_keys = False  # keep response field order (JSON_SORT_KEYS was removed in Flask 2.3)

    def dumps(self, obj, **kwargs) -> str:
        kwargs.setdefault('allow_nan', False)
        return super().dumps(obj, **kwargs)

    def loads(self, s, **kwargs):
        kwargs.setdefault('parse_constant', _reject_constant)
        kwargs.setdefault('parse_float', _finite_float)
        return super().loads(s, **kwargs)
