"""
Day 8 - 논문 번역·요약·Q&A 챗봇 FastAPI 서버
재사용: auth(Day6) / logger·error·middleware(Day3) / 비동기 추론(Day3) / 업로드(Day6)
"""
import asyncio
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File

from app.paper_schemas import (
    UploadResponse, SummarizeRequest, TranslateRequest, ChatRequest, TextResponse,
)
from app.paper_model import PaperBot
from app.paper_utils import extract_text_from_pdf, chunk_text
from app.auth import verify_api_key
from app.logger_config import setup_logger
from app.error_handlers import register_error_handlers
from app.middleware import RequestLoggingMiddleware

logger = setup_logger("paper_api")
inference_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="paper")

MAX_PDF_BYTES = 10 * 1024 * 1024          # 10MB 업로드 제한 (Day 6 안전장치)
CONTEXT_CHARS = 3000                       # Q&A에 넣을 논문 컨텍스트 길이

bot: PaperBot | None = None
# 업로드된 문서를 메모리에 보관 (간단한 데모용 — 운영에선 DB/스토리지 권장)
DOCS: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot
    import torch
    use_gpu = torch.cuda.is_available() or torch.backends.mps.is_available()
    model_name = "Qwen/Qwen2.5-1.5B-Instruct" if use_gpu else "Qwen/Qwen2.5-0.5B-Instruct"
    logger.info(f"논문 챗봇 모델 로드 중: {model_name}")
    bot = PaperBot(model_name)
    logger.info("모델 로드 완료")
    yield


app = FastAPI(
    title="Paper Chatbot API",
    description="논문 PDF 번역·요약·질의응답 API (인증 필요)",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(RequestLoggingMiddleware)
register_error_handlers(app)


def _get_doc(doc_id: str) -> dict:
    doc = DOCS.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다. 먼저 업로드하세요.")
    return doc


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy" if bot else "loading",
            "model": bot.model_name if bot else None,
            "docs": len(DOCS)}


@app.post("/upload", response_model=UploadResponse, tags=["Paper"])
async def upload(file: UploadFile = File(...), user: str = Depends(verify_api_key)):
    """PDF 논문을 업로드해 텍스트를 추출하고 doc_id를 발급합니다."""
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드할 수 있습니다.")
    data = await file.read()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="파일이 너무 큽니다 (최대 10MB).")

    try:
        text = extract_text_from_pdf(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"PDF 텍스트 추출 실패: {e}")
    if not text:
        raise HTTPException(status_code=400, detail="텍스트를 추출하지 못했습니다 (스캔 PDF일 수 있음).")

    chunks = chunk_text(text)
    doc_id = uuid.uuid4().hex[:8]
    DOCS[doc_id] = {"filename": file.filename, "text": text, "chunks": chunks}
    logger.info(f"업로드 — 사용자:{user} 파일:{file.filename} 청크:{len(chunks)}")
    return UploadResponse(doc_id=doc_id, filename=file.filename, n_chars=len(text),
                          n_chunks=len(chunks), preview=text[:300])


async def _run(fn, *args):
    if bot is None:
        raise HTTPException(status_code=503, detail="모델이 아직 로드되지 않았습니다.")
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(inference_executor, fn, *args)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"추론 실패: {e}")


@app.post("/summarize", response_model=TextResponse, tags=["Paper"])
async def summarize(req: SummarizeRequest, user: str = Depends(verify_api_key)):
    doc = _get_doc(req.doc_id)
    result = await _run(bot.summarize, doc["chunks"], req.max_chunks)
    return TextResponse(success=True, result=result, doc_id=req.doc_id,
                        model_name=bot.model_name, user=user)


@app.post("/translate", response_model=TextResponse, tags=["Paper"])
async def translate(req: TranslateRequest, user: str = Depends(verify_api_key)):
    doc = _get_doc(req.doc_id)
    result = await _run(bot.translate, doc["chunks"], req.max_chunks)
    return TextResponse(success=True, result=result, doc_id=req.doc_id,
                        model_name=bot.model_name, user=user)


@app.post("/chat", response_model=TextResponse, tags=["Paper"])
async def chat(req: ChatRequest, user: str = Depends(verify_api_key)):
    doc = _get_doc(req.doc_id)
    context = doc["text"][:CONTEXT_CHARS]
    msgs = [m.model_dump() for m in req.messages]
    result = await _run(bot.answer, context, msgs, req.max_new_tokens, req.temperature)
    return TextResponse(success=True, result=result, doc_id=req.doc_id,
                        model_name=bot.model_name, user=user)
