"""
Day 8 - 논문 PDF 텍스트 추출 + 청크 분할 유틸
(Day 6의 파일 업로드/안전장치 개념을 텍스트 추출로 확장)
"""
import io
import re
from pypdf import PdfReader


def extract_text_from_pdf(file_bytes: bytes, max_pages: int = 30) -> str:
    """PDF 바이트에서 텍스트를 추출합니다.

    max_pages: 너무 긴 논문에서 앞쪽 N페이지만 읽어 CPU 부담을 줄입니다.
    """
    reader = PdfReader(io.BytesIO(file_bytes))
    pages = reader.pages[:max_pages]
    texts = []
    for page in pages:
        t = page.extract_text() or ""
        texts.append(t)
    text = "\n".join(texts)
    return _clean(text)


def _clean(text: str) -> str:
    """추출 과정에서 생긴 과도한 공백/줄바꿈을 정리합니다."""
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, max_chars: int = 1500, overlap: int = 100) -> list[str]:
    """긴 텍스트를 문단 경계 기준으로 청크로 나눕니다.

    소형 모델은 컨텍스트가 짧으므로, 한 번에 처리할 만한 크기로 자릅니다.
    overlap: 청크 경계에서 문맥이 끊기지 않도록 약간 겹쳐줍니다.
    """
    if not text:
        return []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paragraphs:
        if len(buf) + len(p) + 2 <= max_chars:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                chunks.append(buf)
            # 문단 하나가 너무 길면 강제로 자른다
            if len(p) > max_chars:
                for i in range(0, len(p), max_chars - overlap):
                    chunks.append(p[i:i + max_chars])
                buf = ""
            else:
                buf = p
    if buf:
        chunks.append(buf)
    return chunks
