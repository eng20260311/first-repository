# -*- coding: utf-8 -*-
"""
canonical 스키마 — 컬럼 정의, 활성타입 정규화, 맥락 판별, 헤드 라우팅.
세 DB가 이 공통 포맷으로 수렴한다.
"""

import re

from .config import (TYPE_ALIAS, ASSAY_CANON, DEG_TYPES, BIND_TYPES, LOG_TYPES,
                     AMBIG_TYPES, COOP_TYPES, CTX_TERNARY, CTX_E3, CTX_TARGET)

# 통합 테이블의 표준 컬럼 순서
CANON_COLS = [
    "source_db", "source_id",
    # 리간드
    "ligand_key", "inchikey_full", "smiles_std", "scaffold", "subtype",
    # 단백질/E3
    "poi_symbols", "poi_uniprot", "e3_name", "e3_flag",
    # 세포/맥락
    "cell_raw", "cell_base", "combo", "cell_ko", "complex_context",
    # assay
    "assay_raw", "base_type", "replicate", "condition", "head",
    # 라벨
    "label_type", "relation", "pX", "pX_lo", "pX_hi", "pct", "error",
    "ordinal_rank", "grade", "fold_shift", "secondary",
    # 원본/provenance
    "value_raw", "reference", "quality_flags",
]


def _extract_assay_token(b):
    """컬럼명형 'MGTARGETKD' → 'KD', 'TERNARYKD' → 'KD'."""
    if not b:
        return None
    for t in ASSAY_CANON:
        if t in b:
            return TYPE_ALIAS.get(t, t)
    return None


def norm_type(raw):
    """
    활성타입 정규화 → (base_type, replicate, condition).
    'Dmax_1(5μM)' → ('DMAX', '1', '5μM')
    'MG-Target Kd' → ('KD', None, None)  [컬럼명형]
    """
    if raw is None:
        return None, None, None
    s = str(raw).replace("\u00a0", " ").strip()
    cond = None
    m = re.search(r"\(([^)]*)\)", s)
    if m:
        cond, s = m.group(1).strip(), re.sub(r"\([^)]*\)", "", s).strip()
    rep = None
    m = re.match(r"^(.*?)[_\-\s](\d+)$", s)
    if m and len(m.group(1)) >= 2:
        s, rep = m.group(1).strip(), m.group(2)
    b = re.sub(r"[\s\-]+", "", s).upper()
    b = TYPE_ALIAS.get(b, b)
    known = DEG_TYPES | BIND_TYPES | LOG_TYPES | AMBIG_TYPES | COOP_TYPES
    if b not in known:
        b = _extract_assay_token(b) or b
    return b, rep, cond


def detect_context(*texts):
    """assay 텍스트에서 binary_target / binary_e3 / ternary 판별.
    ★ 엔티티명(CRBN 등)은 넣지 말 것 — 항상 존재해 오탐을 부른다."""
    blob = " ".join(str(t or "").lower() for t in texts)
    if any(k in blob for k in CTX_TERNARY):
        return "ternary"
    if any(k in blob for k in CTX_E3):
        return "binary_e3"
    if any(k in blob for k in CTX_TARGET):
        return "binary_target"
    return None


def route_head(base_type, context):
    """
    (base_type, complex_context) → 헤드.
    ★ 결합(binding)은 맥락이 H2(binary)/H3(ternary)를 가른다.
    """
    if base_type is None:
        return "UNKNOWN"
    if base_type in DEG_TYPES:
        return "H4"
    if base_type in COOP_TYPES:
        return "H5"
    if base_type in BIND_TYPES or base_type in LOG_TYPES:
        return "H3" if context == "ternary" else "H2"
    if base_type in AMBIG_TYPES:               # EC50: 맥락 없으면 미정
        if context == "ternary":
            return "H3"
        if context in ("binary_e3", "binary_target"):
            return "H2"
        return "AMBIG_EC50"
    return "OTHER"
