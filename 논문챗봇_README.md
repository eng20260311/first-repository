# 📄 논문 번역·요약·Q&A 챗봇

PDF 논문을 업로드하면 **한국어 요약 · 영→한 번역 · 멀티턴 질의응답**을 제공하는 서비스입니다.
단일 인스트럭트 LLM(`Qwen2.5-Instruct`) 하나로 세 작업을 모두 처리합니다.

> 이 문서는 [`논문챗봇_파이프라인.ipynb`](논문챗봇_파이프라인.ipynb)을 **로컬 환경에서 처음부터 끝까지 실행**하기 위한 안내서입니다.

---

## 🧱 아키텍처

```
[Streamlit UI]  PDF 업로드 + 채팅          (http://localhost:8501)
      │  HTTP (JSON / 파일 + X-API-Key 헤더)
      ▼
[FastAPI]  인증 → 텍스트 추출 → 청크 분할 → (요약/번역/Q&A 프롬프트) → 생성  (http://localhost:8000)
      ▼
[Transformers]  Qwen2.5-Instruct  (CPU: 0.5B / GPU: 1.5B 자동 선택)
```

전체 흐름: **코드 파일 생성 → 서버 기동 → API 파이프라인 테스트 → UI 실행**. 노트북을 위에서부터 차례로 실행하면 이 순서를 그대로 따라갑니다.

---

## 📁 프로젝트 구조

노트북이 의존하는 파일은 두 종류입니다.

### 1) 노트북이 자동 생성하는 파일 (`%%writefile`)
노트북의 **2번 섹션 셀들을 실행하면** 아래 파일이 자동으로 만들어집니다. 저장소에 없어도 됩니다.

| 파일 | 역할 |
|------|------|
| `app/paper_utils.py` | PDF 텍스트 추출 + 청크 분할 |
| `app/paper_schemas.py` | Pydantic 요청/응답 스키마 |
| `app/paper_model.py` | 단일 LLM 요약·번역·Q&A (`PaperBot`) |
| `app/paper_api.py` | FastAPI 서버 (인증·업로드·비동기) |
| `frontend/app_paper.py` | Streamlit UI |

### 2) 저장소에 **반드시 함께 있어야 하는** 재사용 파일
Day 3/6에서 만든 공통 모듈입니다. 노트북이 생성하지 않으므로, 깃허브에 **이 파일들도 함께 커밋**되어 있어야 합니다.

| 파일 | 역할 |
|------|------|
| `app/__init__.py` | 패키지 인식용 (비어 있어도 됨) |
| `app/auth.py` | API Key 인증 (`verify_api_key`) |
| `app/logger_config.py` | 로거 설정 |
| `app/error_handlers.py` | 전역 예외 핸들러 |
| `app/middleware.py` | 요청 로깅 미들웨어 |

> ⚠️ 팀원이 클론한 뒤 `ModuleNotFoundError: app.auth` 같은 오류가 난다면, 위 5개 파일이 `app/`에 들어 있는지 먼저 확인하세요.

---

## ⚙️ 사전 요구사항

- **Python 3.10 이상** (`list[str]` 등 최신 타입 문법 사용)
- OS: Windows / macOS / Linux 모두 가능
- GPU 없어도 동작합니다 (CPU에서는 0.5B 모델이 자동 선택됨)
- 최초 실행 시 Hugging Face에서 모델을 자동 다운로드합니다 (수백 MB, **인터넷 연결 필요**)

---

## 🚀 로컬 실행 방법

### 1. 저장소 클론

```bash
git clone <레포지토리_URL>
cd model_serving
```

### 2. 가상환경 생성 및 활성화

```bash
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 3. 패키지 설치

```bash
pip install torch transformers pypdf fastapi uvicorn streamlit requests matplotlib jupyter
```

> `torch`는 환경에 따라 설치 방법이 다릅니다. GPU(CUDA)를 쓰려면 [PyTorch 공식 안내](https://pytorch.org/get-started/locally/)의 명령을 사용하세요. CPU만 쓸 경우 위 명령 그대로면 됩니다.

### 4. 노트북 실행

```bash
jupyter notebook 논문챗봇_파이프라인.ipynb
# 또는 VS Code에서 .ipynb 파일을 열어 셀을 실행
```

노트북을 **맨 위 셀부터 순서대로** 실행하세요. 각 섹션의 역할은 아래와 같습니다.

| 섹션 | 내용 | 비고 |
|------|------|------|
| 0 | 서버 실행 도우미 정의 (`serve_in_thread`, `stop_server`) | 맨 처음 한 번 |
| 1 | 환경 확인 (torch/transformers 버전, GPU 여부) | |
| 2 | 서비스 코드 파일 생성 (`app/`, `frontend/`) | `%%writefile` 셀 전부 실행 |
| 3 | (선택) 모델 단독 테스트 | 모델 다운로드/로드 발생 |
| 4 | 백엔드 서버 실행 (8000 포트) | 모델 로드로 최대 5분 |
| 5 | API 파이프라인 테스트 (업로드→요약→번역→Q&A→인증) | |
| 6 | Streamlit UI 실행 (8501 포트) | |
| 7 | 서버/UI 종료 | 실습 후 정리 |

---

## 🔑 API Key (인증)

모든 API 호출에는 `X-API-Key` 헤더가 필요합니다. 학습용으로 키가 하드코딩되어 있습니다 ([`app/auth.py`](app/auth.py)).

| API Key | 사용자 |
|---------|--------|
| `test-key-001` | 사용자A |
| `test-key-002` | 사용자B |

- 노트북의 테스트 셀과 Streamlit 사이드바 기본값은 모두 `test-key-001`입니다.
- 키 없이 호출하면 의도적으로 **401 (인증 실패)** 가 반환됩니다 (5.5 셀에서 확인).

---

## 🌐 접속 주소

| 서비스 | URL | 설명 |
|--------|-----|------|
| FastAPI 서버 | http://localhost:8000 | 백엔드 API |
| API 문서 (Swagger) | http://localhost:8000/docs | 엔드포인트 확인·테스트 |
| 헬스 체크 | http://localhost:8000/health | 모델 로드 상태 |
| Streamlit UI | http://localhost:8501 | 웹 채팅 화면 |

### 주요 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/upload` | PDF 업로드 → `doc_id` 발급 (최대 10MB) |
| `POST` | `/summarize` | 한국어 요약 (map-reduce) |
| `POST` | `/translate` | 영→한 번역 (앞부분 청크) |
| `POST` | `/chat` | 논문 기반 멀티턴 Q&A |
| `GET` | `/health` | 상태 확인 |

---

## 🧪 빠른 동작 확인

직접 업로드할 PDF가 없으면, 노트북 **5.0 셀**이 샘플 `test_paper.pdf`를 만들어 줍니다.
서버(8000)가 떠 있는 상태에서 터미널로도 테스트할 수 있습니다.

```bash
# 업로드 → doc_id 발급
curl -X POST http://localhost:8000/upload \
  -H "X-API-Key: test-key-001" \
  -F "file=@test_paper.pdf;type=application/pdf"
```

---

## ❗ 자주 겪는 문제

| 증상 | 원인 / 해결 |
|------|-------------|
| `ModuleNotFoundError: app.auth` 등 | 재사용 파일(위 "2)" 표) 5개가 `app/`에 없음 → 저장소에 커밋되었는지 확인 |
| 서버가 5분 내 안 뜸 | 최초 모델 다운로드 지연. 인터넷 연결 확인 후 4번 셀 재실행 |
| `⚠️ 포트 8000을 다른 프로세스가 사용 중` | 기존 서버를 끄거나, `stop_server(8000)` 실행 후 재시도 |
| Streamlit에서 `🔴 서버 연결 실패` | 백엔드(8000)가 먼저 떠 있어야 함. 노트북 4번 셀 먼저 실행 |
| `401 인증 실패` | `X-API-Key` 헤더 누락 또는 잘못된 키. `test-key-001` 사용 |
| 텍스트 추출 실패 | 스캔(이미지) PDF는 텍스트가 없음. 텍스트 기반 PDF 사용 |
| 번역/요약 결과가 이상함 | CPU·소형(0.5B) 모델 한계. `max_chunks`로 범위를 줄여 사용 |

---

## 📌 참고

- 업로드한 문서는 서버 메모리(`DOCS` 딕셔너리)에만 보관됩니다. 서버를 재시작하면 사라집니다 (데모용).
- CPU 환경에서는 요약/번역에 수십 초 이상 걸릴 수 있습니다. `max_chunks` 값을 낮추면 빨라집니다.
- 개선 방향: 번역 전용 모델(NLLB) 추가, 임베딩 기반 검색(RAG)으로 Q&A 정확도 향상.
