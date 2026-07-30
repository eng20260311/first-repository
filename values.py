# -*- coding: utf-8 -*-
"""
활성값 파서 — 실측에서 나온 모든 형식을 분류한다.

반환하는 label_type (핵심):
  numeric   : 점추정치 (pX 또는 pct 산출)          예: 3.2±0.5μM, 4nM, 85%
  interval  : 구간 검열 (하한/상한 보존)            예: 0.5uM<x≤1uM, <=100nM
  ordinal   : 순서형 등급                           예: A, B, +++, -
  fold      : 배수 (친화도 아님, 협동성 후보)        예: 3.3×
  unusable  : 센티넬/파싱불가                        예: ND, N/A, (숫자없음)

주의: "성공/실패"가 아니라 "무엇인지"를 판별한다. 구간을 점추정치로,
      배수를 친화도로 오인하면 라벨이 조용히 오염된다.
"""

import math
import re

from .config import (UNIT_MAP, UNIT_NM, UNIT_RE, LOG_TYPES, GRADE_ORDER,
                     SENTINELS)


def _norm(s):
    """마이크로 기호 2종(μ U+03BC, µ U+00B5)과 NBSP를 통일."""
    return (str(s).replace("\u00b5", "u").replace("\u03bc", "u")
            .replace("\u00a0", " ").strip())


def _match_unit(rest):
    """잔여 문자열 앞에서 단위 토큰을 떼어낸다. (unit, leftover) 반환."""
    r = re.sub(r"\s+", "", str(rest)).lower()
    for pat, u in UNIT_MAP:
        if r.startswith(pat):
            return u, r[len(pat):]
    return None, r


def _px_from(value, unit):
    """농도(+단위) → pX = 9 - log10(nM). 실패 시 None."""
    if unit not in UNIT_NM:
        return None
    nm = value * UNIT_NM[unit]
    return round(9 - math.log10(nm), 3) if nm > 0 else None


def blank(**kw):
    o = dict(label_type="unusable", relation="=", value=None, error=None,
             lo=None, hi=None, unit=None, pX=None, pX_lo=None, pX_hi=None,
             pct=None, ordinal_rank=None, grade=None, fold_shift=None,
             secondary=None, flags=None)
    o.update(kw)
    return o


def parse_value(raw, base_type=None):
    """활성값 문자열 하나를 구조화된 dict로."""
    if raw is None or str(raw).strip().lower() in ("", "nan", "none", "null"):
        return blank(flags="missing")

    s = _norm(raw)
    up = s.upper()

    # 1) 센티넬 (결측 표기)
    if up in SENTINELS:
        return blank(flags="sentinel")

    # 2) 문자 등급 (A~G, A+, A++)
    if up in GRADE_ORDER:
        return blank(label_type="ordinal", grade=up, ordinal_rank=GRADE_ORDER[up])
    # 3) +/++/+++ 또는 - 등급
    if re.fullmatch(r"\+{1,5}", s):
        return blank(label_type="ordinal", grade=s, ordinal_rank=len(s))
    if re.fullmatch(r"[-–—]", s):
        return blank(label_type="ordinal", grade="-", ordinal_rank=0)

    # 4) 괄호 속 2차 측정값 분리   712±11nM(Ki=89±3nM)
    secondary = None
    m = re.search(r"\(([^)]*)\)\s*$", s)
    if m and re.search(r"\d", m.group(1)):
        secondary = m.group(1).strip()
        s = s[:m.start()].strip()

    # 5) 구간   0.5uM<x≤1uM  /  100<x≤1000  /  10nm≤x<100nm
    flat = re.sub(r"\s+", "", s).lower()
    m = re.fullmatch(
        rf"([\d.]+)({UNIT_RE})?([<≤])x([<≤])([\d.]+)({UNIT_RE})?", flat)
    if m:
        lo_s, u1, _, _, hi_s, u2 = m.groups()
        unit = _match_unit(u2 or u1 or "")[0]
        try:
            lo, hi = float(lo_s), float(hi_s)
        except ValueError:
            return blank(flags="unparsed", secondary=secondary)
        o = blank(label_type="interval", lo=lo, hi=hi, unit=unit,
                  relation="interval", secondary=secondary)
        if unit in UNIT_NM:
            # 농도는 작을수록 강력 → pX 하한/상한이 뒤집힌다
            o["pX_hi"] = _px_from(lo, unit)
            o["pX_lo"] = _px_from(hi, unit)
            o["pX"] = _px_from((lo + hi) / 2, unit)
        elif unit == "PCT":
            o["pct"] = (lo + hi) / 2
        return o

    # 6) 부등호 (<=, >=, ≤, ≥, ~, <, >)
    relation = "="
    m = re.match(r"^(<=|>=|=<|=>|[<>≤≥~≈])\s*", s)
    if m:
        t = m.group(1)
        relation = ("<" if t in ("<", "≤", "<=", "=<")
                    else ">" if t in (">", "≥", ">=", "=>") else "~")
        s = s[m.end():].strip()

    # 7) 값 ± 오차   (v3가 여기서 깨졌던 지점: ±가 단위보다 먼저 온다)
    error = None
    m = re.match(r"^([\d.]+)\s*(?:±|\+/-|\+-)\s*([\d.]+)\s*(.*)$", s)
    if m:
        try:
            value, error = float(m.group(1)), float(m.group(2))
        except ValueError:
            return blank(flags="unparsed", secondary=secondary)
        rest = m.group(3)
    else:
        m = re.match(r"^([\d.]+)\s*(.*)$", s)
        if not m:
            return blank(flags="unparsed", secondary=secondary)
        try:
            value = float(m.group(1))
        except ValueError:
            return blank(flags="unparsed", secondary=secondary)
        rest = m.group(2)

    unit, leftover = _match_unit(rest)

    # 8) 배수 (fold-shift) — 친화도가 아니다
    if unit is None and leftover in ("×", "x", "fold", "-fold"):
        return blank(label_type="fold", fold_shift=value, relation=relation,
                     secondary=secondary)

    flags = None
    if leftover:
        flags = f"left:{leftover[:20]}"

    # 9) 이미 로그값인 타입 (pEC50 등)
    if base_type in LOG_TYPES:
        return blank(label_type="numeric", pX=value, relation=relation,
                     error=error, secondary=secondary, flags=flags)

    o = blank(relation=relation, value=value, error=error, unit=unit,
              secondary=secondary, flags=flags)
    if unit == "PCT":
        o["label_type"], o["pct"] = "numeric", value
    elif unit in UNIT_NM:
        o["label_type"], o["pX"] = "numeric", _px_from(value, unit)
    else:
        o["flags"] = (flags + "|no_unit") if flags else "no_unit"
    return o
