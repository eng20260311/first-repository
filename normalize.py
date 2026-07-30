# -*- coding: utf-8 -*-
"""
한 DB → canonical 테이블.
컬럼 자동탐지 + wide(assay가 컬럼명) 자동 melt + 값 파싱 + 엔티티 정규화.
"""

import json

import pandas as pd

from . import entities as E
from . import schema as S
from .config import ASSAY_TOKENS, WIDE_TOKENS
from .io_utils import load_many
from .values import parse_value

# 논리 컬럼 → 후보 키워드 (부분일치, 위에서부터 우선)
COL_KEYS = {
    "id": ["tpd id", "mg id", "compound id", "cid", "id"],
    "name": ["compound name", "tpd name", "name", "compound"],
    "smiles": ["canonical smiles", "smiles", "structure"],
    "subtype": ["subtype", "modality", "type of", "mg type"],
    "poi_sym": ["target symbol", "target gene", "target name", "poi", "target"],
    "poi_id": ["target id", "target uniprot", "uniprot", "accession"],
    "e3": ["e3 ligase", "ligase", "effector"],
    "cell": ["cell line", "cell"],
    "type": ["activity type", "assay type", "endpoint", "assay"],
    "value": ["activity", "value", "affinity", "potency", "result"],
    "ref": ["reference", "pubmed", "pmid", "doi", "source"],
}


def _find_wide(df, exclude):
    return [c for c in df.columns
            if c not in exclude and any(t in c.lower() for t in WIDE_TOKENS)]


def detect_cols(df, override=None, exclude=None):
    """각 논리 컬럼을 실제 컬럼명에 매핑. 한 컬럼을 두 역할에 배정하지 않는다."""
    ex = set(exclude or ())
    pool = [c for c in df.columns if c not in ex]
    override = override or {}
    claimed = set(override.values())
    out = {}
    for logical, kws in COL_KEYS.items():
        if override.get(logical):
            out[logical] = override[logical]
            continue
        found = None
        for kw in kws:
            for c in pool:
                if c in claimed:
                    continue
                if kw in c.lower():
                    found = c
                    break
            if found:
                break
        out[logical] = found
        if found:
            claimed.add(found)
    return out


def dump_schema(df, n=3):
    """★ 집계 전에 원문을 먼저 본다."""
    print("\n=== 원문 컬럼 ===")
    print(list(df.columns))
    print(f"\n=== 컬럼별 첫 {n}개 값 ===")
    for c in df.columns:
        vals = df[c].dropna().unique()[:n]
        print(f"  {str(c)[:34]:34s} : " + " | ".join(str(v)[:50] for v in vals))


def normalize_db(paths, db, colmap_path=None, sep=None, quote=None,
                 join_on=None, wide=None, out=None, verbose=True):
    """여러 입력 파일 → canonical DataFrame + 저장."""
    df = load_many(paths, sep, quote, join_on, verbose)
    if verbose:
        dump_schema(df)

    override = json.load(open(colmap_path, encoding="utf-8")) if colmap_path else None
    wide_cols = _find_wide(df, exclude=set())
    cm = detect_cols(df, override, exclude=wide_cols)

    if verbose:
        print("\n=== 탐지된 컬럼 ===")
        for k, v in cm.items():
            print(f"  {k:9s}: {v}")
        if wide_cols:
            tag = "-> long melt" if (wide or not cm.get("value")) else "(참고)"
            print(f"\n[wide assay 컬럼 {len(wide_cols)}개 {tag}] {wide_cols[:8]}")

    do_wide = bool(wide_cols) and (wide or not cm.get("value"))

    def base_fields(r):
        sk, ikf, std, scaf, ok = E.ligand_keys(r.get(cm["smiles"]) if cm.get("smiles") else None)
        e3n, e3f = E.norm_e3(r.get(cm["e3"]) if cm.get("e3") else None)
        cb, combo, ko = E.norm_cell(r.get(cm["cell"]) if cm.get("cell") else None)
        return dict(
            source_db=db,
            source_id=r.get(cm["id"]) if cm.get("id") else None,
            ligand_key=sk, inchikey_full=ikf, smiles_std=std, scaffold=scaf,
            subtype=r.get(cm["subtype"]) if cm.get("subtype") else None,
            poi_symbols=E.norm_symbols(r.get(cm["poi_sym"]) if cm.get("poi_sym") else None),
            poi_uniprot=E.norm_symbols(r.get(cm["poi_id"]) if cm.get("poi_id") else None),
            e3_name=e3n, e3_flag=e3f,
            cell_raw=r.get(cm["cell"]) if cm.get("cell") else None,
            cell_base=cb, combo=combo, cell_ko=ko,
            reference=r.get(cm["ref"]) if cm.get("ref") else None,
        )

    recs = []
    for _, r in df.iterrows():
        bf = base_fields(r)
        if do_wide:
            items = [(c, r.get(c)) for c in wide_cols]
        else:
            items = [(r.get(cm["type"]) if cm.get("type") else None,
                      r.get(cm["value"]) if cm.get("value") else None)]
        for assay_raw, val in items:
            if val is None:
                continue
            base, rep, cond = S.norm_type(assay_raw)
            # 맥락은 assay 텍스트에서만 판별. 분해(H4)는 맥락 불필요.
            ctx = (None if base in S.DEG_TYPES
                   else S.detect_context(assay_raw, cond))
            p = parse_value(val, base)
            rec = dict(bf)
            rec.update(
                complex_context=ctx, assay_raw=assay_raw, base_type=base,
                replicate=rep, condition=cond, head=S.route_head(base, ctx),
                label_type=p["label_type"], relation=p["relation"],
                pX=p["pX"], pX_lo=p["pX_lo"], pX_hi=p["pX_hi"], pct=p["pct"],
                error=p["error"], ordinal_rank=p["ordinal_rank"],
                grade=p["grade"], fold_shift=p["fold_shift"],
                secondary=p["secondary"], value_raw=val,
                quality_flags=p["flags"],
            )
            recs.append(rec)

    out_df = pd.DataFrame(recs, columns=S.CANON_COLS)
    path = out or f"canon_{db}.tsv"
    out_df.to_csv(path, sep="\t", index=False)
    if verbose:
        _report(out_df, cm, path)
    return out_df


def _report(o, cm, path):
    print(f"\n=== canonical: {o.shape} ===")
    if not len(o):
        print("⚠️ 결과 0행 — 컬럼 탐지 또는 join/melt 실패. 위 '탐지된 컬럼' 확인.")
        return
    print("[label_type]", dict(o["label_type"].value_counts()))
    print("[head]      ", dict(o["head"].value_counts()))
    ctx = o["complex_context"].dropna()
    if len(ctx):
        print("[context]   ", dict(ctx.value_counts()))
    else:
        print("[context]    ⚠️ 없음 — ternary/binary 구분 불가 → H3 라벨 안 생김. "
              "--map 으로 맥락 컬럼 지정 검토.")
    print("[base_type] ", dict(o["base_type"].value_counts().head(10)))
    if o["e3_flag"].notna().any():
        print("[e3_flag]   ", dict(o["e3_flag"].value_counts()))
    print(f"고유 리간드(skeleton)={o['ligand_key'].nunique():,} · "
          f"scaffold={o['scaffold'].nunique():,}")
    if not E.has_rdkit():
        print("⚠️ RDKit 미설치 — ligand_key가 해시 근사입니다. "
              "`pip install rdkit` 후 재실행 권장.")
    print(f"[done] -> {path}")
