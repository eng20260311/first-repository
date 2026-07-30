# MGD 데이터 정제·통합 파이프라인 (모듈형)

MGDB · MGTbind · TPDdb 세 데이터베이스를 하나의 학습용 라벨 테이블로 정제·통합합니다.
지금까지의 프로파일링에서 발견한 모든 데이터 병리(등급 체계, 구간 검열, ±오차,
컬럼 밀림, wide 포맷, H2/H3 맥락 분기 등)를 모듈별로 반영했습니다.

## 폴더 구조

```
mgd_pipeline/
├── run_mgd.py          ← 진입점 (이걸 실행)
└── mgd/
    ├── config.py       설정·어휘 (E3 별칭·단위·등급·헤드 규칙)  ← 값을 바꾸려면 여기만
    ├── io_utils.py     인코딩/구분자/quoting 자동 로더 + STACK/JOIN 판별
    ├── values.py       활성값 파서 (±오차·구간·등급·배수·센티넬)
    ├── entities.py     리간드(InChIKey/scaffold)·단백질·E3·세포주 정규화
    ├── schema.py       canonical 컬럼·타입정규화·맥락판별·헤드라우팅
    ├── normalize.py    한 DB → canonical 테이블 (wide melt·컬럼 자동탐지)
    ├── integrate.py    통합 (중복제거·충돌화해·cold-split·커버리지)
    └── cli.py          커맨드라인
```

## 설치

```python
!pip install rdkit pandas --break-system-packages -q
```
RDKit이 없어도 동작하지만 고유 리간드 수가 해시 근사가 됩니다(정확한 dedup엔 필수).

## 사용법 (Colab: 앞에 `!` 붙여 셸 실행)

### 1) 각 DB를 canonical로 정규화

```python
# TPDdb — main_table + activity는 서로 다른 표라 JOIN이 필요 (자동 감지)
!python run_mgd.py normalize --input MG_main_table.txt MG_activity.txt --db TPDdb

# MGDB — CSV. 컬럼명에 assay가 박힌 wide 포맷이면 자동 melt
!python run_mgd.py normalize --input mgdb.csv --db MGDB

# MGTbind — 조각 CSV 여러 개 가능
!python run_mgd.py normalize --input complexes.csv compounds.csv --db MGTbind
```

실행 직후 출력에서 **반드시 확인**:
- `=== 원문 컬럼 ===` + 컬럼별 값 → 밀림/깨짐 없는지 눈으로
- `=== 탐지된 컬럼 ===` → `None`이면 `--map map.json`으로 지정
- `[context]` → **MGDB에서 `ternary`가 잡히는지 = 이번 통합의 성패** (안 잡히면 H3 없음)

컬럼 탐지가 틀리면:
```python
# map.json 예
{"value": "Affinity", "type": "Assay Type", "poi_id": "UniProt ID"}
```
```python
!python run_mgd.py normalize --input mgdb.csv --db MGDB --map map.json
```

여러 파일 관계가 애매하면 스크립트가 **멈추고** 두 파일 컬럼을 보여줍니다. 그때:
```python
!python run_mgd.py normalize --input a.csv b.csv --db MGTbind --join-on "compound_id"
```

### 2) 통합

```python
!python run_mgd.py merge --inputs canon_TPDdb.tsv canon_MGDB.tsv canon_MGTbind.tsv
```
→ `unified_measurements.tsv` (학습용 라벨) + `integration_report.md` (진단).

## 산출물 스키마 (canonical 주요 컬럼)

| 컬럼 | 의미 |
|---|---|
| `ligand_key` | InChIKey 앞 14자 (중복제거 키) |
| `head` | H2/H3/H4/H5/AMBIG_EC50/OTHER |
| `complex_context` | binary_target / binary_e3 / ternary |
| `label_type` | numeric / interval / ordinal / fold / unusable |
| `pX`, `pX_lo`, `pX_hi` | -log10(M). 구간은 lo/hi 보존 |
| `pct` | Dmax 등 퍼센트 |
| `ordinal_rank`, `grade` | 문자·기호 등급 (A~G, +++) |
| `fold_shift` | 배수(협동성 후보, 친화도 아님) |
| `error`, `secondary` | ±오차, 괄호 속 2차 측정 |
| `combo`, `cell_ko` | 병용·KO 조건 플래그 |
| `spread_flag` | DB 간 값 불일치(통합 후) |
| `split_scaffold/poi/e3/complex` | cold-split 버킷 |

## 어떤 교훈이 어디에 들어갔나

| 발견한 문제 | 반영 위치 |
|---|---|
| `3.2±0.5μM` (±가 단위보다 먼저) | `values.py` 7단계 |
| `0.5uM<x≤1uM` 구간 → 하한 오인 | `values.py` 5단계 (lo/hi 보존) |
| `A~G`, `+++` 등급 | `values.py` 2~3단계 (ordinal) |
| `3.3×` 배수 = 친화도 아님 | `values.py` 8단계 (fold) |
| `ND`/`N/A` 센티넬 | `values.py` 1단계 |
| μ/µ 2종, `nmol/L` | `values.py` `_norm`·`UNIT_MAP` |
| CSV 인용부호 안 쉼표 → 컬럼 밀림 | `io_utils.py` quoting 자동판정 |
| main+activity를 concat하면 소실 | `io_utils.py` STACK/JOIN 판별 |
| wide 포맷(`Ternary Kd`가 컬럼명) | `normalize.py` + `config.WIDE_TOKENS` |
| ternary→H3, binary→H2 | `schema.py` `route_head` |
| CRBN 편중 → novel-E3 불가 | `integrate.py` split 그룹수 경고 |
| DB 간 값 충돌 | `integrate.py` 충돌 화해 + spread_flag |
| β-TrCP·CK1α·SEPT6 | `config.py` 어휘 + `entities.py` |
| UBE2(E2)·DDB1(어댑터)·TIR1(식물) | `entities.norm_e3` flag |

## 성공 판정

`integration_report.md`의 **H3 고유 리간드 ≥ 200**이면 H1→H3→H4 물리 사슬 학습 가능.
미달이면 데이터 확장보다 소규모 설계(강한 정규화·순위손실·사전학습)로 전환.
