# -*- coding: utf-8 -*-
"""
canonical 테이블들 → 통합.
교차 중복제거 · 충돌 화해 · 엔티티 cold-split · 라벨 커버리지.
"""

import hashlib

import pandas as pd

from .config import SPLIT_RATIOS, SPLIT_SEED, MIN_GROUPS_FOR_SPLIT, \
    CONFLICT_LOG_THRESHOLD


def _bucket(key, axis, ratios=SPLIT_RATIOS):
    """결정적 해시 → train/valid/test. 같은 키는 항상 같은 버킷."""
    h = int(hashlib.md5(f"{SPLIT_SEED}|{axis}|{key}".encode()).hexdigest()[:8],
            16) / 0xFFFFFFFF
    if h < ratios[0]:
        return "train"
    if h < ratios[0] + ratios[1]:
        return "valid"
    return "test"


def integrate(paths, out="unified_measurements.tsv",
              report="integration_report.md", verbose=True):
    frames = []
    for p in paths:
        d = pd.read_csv(p, sep="\t", dtype=str)
        db = d["source_db"].iloc[0] if len(d) else "?"
        if verbose:
            print(f"[load] {p} -> {d.shape}  db={db}")
        frames.append(d)
    m = pd.concat(frames, ignore_index=True)
    m["pX_num"] = pd.to_numeric(m["pX"], errors="coerce")
    m["usable"] = m["label_type"].isin(["numeric", "interval", "ordinal"])

    L = ["# MGD 통합 리포트", "", f"입력 {len(paths)}개 · 총 레코드 **{len(m):,}**"]

    # 1. DB별 규모
    L.append("\n## 1. DB별 규모")
    for db, g in m.groupby("source_db"):
        L.append(f"- **{db}**: 레코드 {len(g):,} · 고유 리간드 "
                 f"{g['ligand_key'].nunique():,} · 헤드 " +
                 ", ".join(f"{k}={v}" for k, v in g["head"].value_counts().items()))

    # 2. 교차 중복 (통합의 실익)
    L.append("\n## 2. ★ 교차 중복 — 통합의 실익")
    sets = {db: set(g["ligand_key"].dropna()) for db, g in m.groupby("source_db")}
    for db, s in sets.items():
        L.append(f"- {db}: 고유 리간드 {len(s):,}")
    dbs = list(sets)
    for i in range(len(dbs)):
        for j in range(i + 1, len(dbs)):
            a, b = sets[dbs[i]], sets[dbs[j]]
            inter, union = a & b, a | b
            L.append(f"- {dbs[i]} ∩ {dbs[j]} = **{len(inter):,}** "
                     f"(Jaccard {len(inter)/max(len(union),1):.3f})")
    allu = set().union(*sets.values()) if sets else set()
    simple = sum(len(s) for s in sets.values())
    L.append(f"\n→ 단순합 {simple:,} → **통합 고유 리간드 {len(allu):,}** "
             f"(중복 {simple-len(allu):,} 제거)")

    # 3. 헤드별 실질 규모 (성공 판정)
    L.append("\n## 3. ★ 헤드별 실질 규모 (고유 리간드)")
    for h, g in m.groupby("head"):
        u = g[g["usable"]]
        L.append(f"- **{h}**: 리간드 {u['ligand_key'].nunique():,} / "
                 f"사용가능 레코드 {len(u):,} / 전체 {len(g):,}")
    h3 = m[(m["head"] == "H3") & m["usable"]]["ligand_key"].nunique()
    L.append(f"\n→ ★ **H3(ternary 친화도) 고유 리간드 = {h3:,}** "
             f"({'성공 (≥200)' if h3 >= 200 else '목표 미달 (<200)'})")

    # 4. 충돌 화해
    L.append("\n## 4. 충돌 화해 (동일 시스템·다른 값)")
    m["sys"] = (m["ligand_key"].astype(str) + "|" + m["poi_uniprot"].astype(str)
                + "|" + m["base_type"].astype(str) + "|" + m["cell_base"].astype(str))
    valid = m[m["pX_num"].notna()]
    agg = valid.groupby("sys")["pX_num"].agg(["count", "median", "min", "max"])
    dup = agg[agg["count"] > 1]
    L.append(f"- 중복 측정 시스템 = **{len(dup):,}**")
    if len(dup):
        spread = dup["max"] - dup["min"]
        big = (spread > CONFLICT_LOG_THRESHOLD).sum()
        L.append(f"- ⚠️ {CONFLICT_LOG_THRESHOLD} log 초과 불일치 = **{big:,}** · "
                 f"불일치 중앙 {spread.median():.2f} log · 최대 {spread.max():.2f}")
    m["pX_reconciled"] = m["sys"].map(agg["median"])
    m["spread_flag"] = m["sys"].map((agg["max"] - agg["min"]) > CONFLICT_LOG_THRESHOLD)

    # 5. cold-split 4축
    L.append("\n## 5. cold-split (엔티티 단위, 80/10/10)")
    for axis, col in [("scaffold", "scaffold"), ("poi", "poi_uniprot"),
                      ("e3", "e3_name"), ("complex", "sys")]:
        m[f"split_{axis}"] = m[col].fillna("(NA)").map(lambda k: _bucket(k, axis))
        ng = m[col].nunique()
        vc = m[f"split_{axis}"].value_counts(normalize=True)
        warn = "" if ng >= MIN_GROUPS_FOR_SPLIT else "  ⚠️ 그룹 부족(평가 신뢰도↓)"
        L.append(f"- {axis}: 그룹 {ng:,} · " +
                 " ".join(f"{k}={v*100:.0f}%" for k, v in vc.items()) + warn)

    # 6. 커버리지 매트릭스
    L.append("\n## 6. 라벨 커버리지 (리간드 × 헤드)")
    piv = (m[m["usable"]].pivot_table(index="ligand_key", columns="head",
                                      values="value_raw", aggfunc="count").notna())
    if len(piv):
        L.append("- 헤드별 리간드: " +
                 ", ".join(f"{c}={int(piv[c].sum()):,}" for c in piv.columns))
        multi = piv.sum(axis=1)
        L.append("- 보유 헤드 수: " +
                 ", ".join(f"{k}개={v:,}" for k, v in
                           multi.value_counts().sort_index().items()))
        L.append(f"- **2개 이상 헤드 보유 = {(multi>=2).sum():,}** "
                 "(멀티태스크 시너지 근거)")

    # 저장
    m.drop(columns=["pX_num", "usable", "sys"]).to_csv(out, sep="\t", index=False)
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    if verbose:
        print("\n".join(L))
        print(f"\n[done] -> {out}\n[done] -> {report}")
    return m
