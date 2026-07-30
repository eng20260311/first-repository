# -*- coding: utf-8 -*-
"""
파일 로딩 — CSV/TSV를 인코딩·구분자·quoting 자동 판정으로 안전하게 읽고,
여러 파일을 STACK(페이지 이어붙이기) vs JOIN(다른 표 병합)으로 구분한다.

핵심 교훈:
  · QUOTE_NONE을 CSV에 쓰면 인용부호 안 쉼표에서 값이 조용히 밀린다
    → quoting을 자동 판정(행 손실·인용부호 잔류로 점수화).
  · main_table + activity 처럼 '다른 표'를 concat하면 공유 컬럼만 남고 소실된다
    → 컬럼 겹침으로 STACK/JOIN 자동 구분, 애매하면 멈추고 --join-on 요청.
"""

import csv
import os

import pandas as pd

from .config import ASSAY_TOKENS

_NULLS = {"nan": None, "": None, ".": None, "None": None, "NULL": None,
          "N/A": None}


def _count_lines(path):
    try:
        with open(path, "rb") as f:
            return sum(1 for ln in f if ln.strip())
    except OSError:
        return None


def _score(df, raw_lines):
    """파싱 품질 점수: 컬럼 수는 +, 행손실·인용부호잔류·Unnamed는 큰 감점."""
    ncol = df.shape[1]
    if ncol < 2 or len(df) == 0:
        return -1e9
    unnamed = sum(1 for c in df.columns
                  if str(c).startswith("Unnamed") or not str(c).strip())
    loss = max(0, (raw_lines - 1) - len(df)) if raw_lines else 0
    samp = [str(v) for v in df.head(200).values.ravel()]
    pol = sum(1 for v in samp if v.startswith('"') or v.endswith('"'))
    pol = pol / max(len(samp), 1)
    return min(ncol, 60) - unnamed * 200 - loss * 50 - pol * 1000


def load_table(path, sep=None, want_quote=None, verbose=True):
    """한 파일을 최적 파싱 조합으로 읽는다."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"파일을 찾을 수 없음: {path}  (!ls 로 실제 파일명을 확인하세요. "
            f"파일명에 공백이 있으면 따옴표로 감싸세요.)")
    raw_lines = _count_lines(path)
    ext = os.path.splitext(path)[1].lower()
    seps = [sep] if sep else ([",", "\t", ";"] if ext == ".csv"
                              else ["\t", ",", ";"])
    quotes = ([(csv.QUOTE_MINIMAL, "minimal")] if want_quote == "minimal"
              else [(csv.QUOTE_NONE, "none")] if want_quote == "none"
              else [(csv.QUOTE_MINIMAL, "minimal"), (csv.QUOTE_NONE, "none")])
    best = None
    for enc in ("utf-8-sig", "utf-8", "cp949", "gbk", "latin-1"):
        for sp in seps:
            for q, qn in quotes:
                try:
                    df = pd.read_csv(path, sep=sp, dtype=str, encoding=enc,
                                     engine="python", on_bad_lines="skip",
                                     quoting=q)
                except Exception:
                    continue
                sc = _score(df, raw_lines)
                if best is None or sc > best[0]:
                    best = (sc, df, enc, sp, qn)
    if best is None:
        raise RuntimeError(f"로드 실패(모든 조합 실패): {path}")
    _, df, enc, sp, qn = best
    df.columns = [str(c).strip().strip('"') for c in df.columns]
    for c in df.columns:
        df[c] = (df[c].astype(str).str.replace("\u00a0", " ", regex=False)
                 .str.strip().str.strip('"').str.strip().replace(_NULLS))
    lost = (raw_lines - 1 - len(df)) if raw_lines else 0
    if verbose:
        warn = f"  ⚠️ 행손실 {lost}" if lost and lost > 5 else ""
        print(f"[load] {os.path.basename(path)} enc={enc} sep={sp!r} "
              f"quote={qn} -> {df.shape}{warn}")
    return df


def _is_fact_table(df):
    """측정값(assay/value) 성격의 표인지 — JOIN 시 base가 된다."""
    cols = " ".join(str(c) for c in df.columns).lower()
    return any(t in cols for t in ASSAY_TOKENS + ("value", "activity", "affinity"))


def load_many(paths, sep=None, want_quote=None, join_on=None, verbose=True):
    """
    여러 파일을 하나로. STACK vs JOIN 자동 구분.
    join_on 이 주어지면 무조건 그 컬럼으로 JOIN.
    """
    dfs = []
    for p in paths:
        d = load_table(p, sep, want_quote, verbose)
        if verbose:
            print(f"        컬럼({len(d.columns)}): {list(d.columns)}")
        dfs.append(d)
    if len(dfs) == 1:
        return dfs[0]

    acc = dfs[0]
    for i, d in enumerate(dfs[1:], start=1):
        shared = [c for c in acc.columns if c in d.columns]
        overlap = len(shared) / max(min(len(acc.columns), len(d.columns)), 1)

        if join_on:
            keys = [join_on] if isinstance(join_on, str) else list(join_on)
            miss = [k for k in keys if k not in acc.columns or k not in d.columns]
            if miss:
                raise RuntimeError(f"--join-on 컬럼 {miss} 이 파일에 없습니다.")
            mode = "JOIN(지정)"
        elif overlap >= 0.5:
            keys, mode = None, "STACK"
        elif 1 <= len(shared) <= 3:
            keys, mode = shared, "JOIN(자동)"
        else:
            print(f"\n⚠️ 파일 {i}과의 관계 판단 불가 (공유 {len(shared)}: {shared})")
            print(f"   A: {list(acc.columns)}")
            print(f"   B: {list(d.columns)}")
            raise RuntimeError("자동판단 실패 — --join-on '<공통컬럼>' 로 지정하세요.")

        if mode == "STACK":
            acc = pd.concat([acc, d], ignore_index=True).drop_duplicates()
            if verbose:
                print(f"  [{i}] STACK (컬럼 {overlap*100:.0f}% 일치) -> {len(acc):,}행")
        else:
            base, attr = (acc, d) if (_is_fact_table(acc) and not _is_fact_table(d)) \
                else (d, acc) if (_is_fact_table(d) and not _is_fact_table(acc)) \
                else (acc, d) if len(acc) >= len(d) else (d, acc)
            n0 = len(base)
            acc = base.merge(attr, on=keys, how="left", suffixes=("", "_dim"))
            matched = base[keys[0]].isin(attr[keys[0]]).sum()
            if verbose:
                print(f"  [{i}] JOIN(on {keys}) base={n0:,} -> {len(acc):,}행 · "
                      f"매칭 {matched:,}/{n0:,} ({matched/max(n0,1)*100:.0f}%)")
                if n0 and matched / n0 < 0.5:
                    print("      ⚠️ 매칭률 낮음 — join key 재확인 필요")
    return acc
