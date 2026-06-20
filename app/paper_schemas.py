"""
Day 8 - 논문 챗봇 API 스키마
(Day 5/7에서 배운 Pydantic 스키마 설계)
"""
from pydantic import BaseModel, Field
from typing import Optional


class UploadResponse(BaseModel):
    """PDF 업로드 결과"""
    doc_id: str = Field(description="업로드된 문서 식별자")
    filename: str = Field(description="원본 파일명")
    n_chars: int = Field(description="추출된 글자 수")
    n_chunks: int = Field(description="분할된 청크 수")
    preview: str = Field(description="앞부분 미리보기")


class SummarizeRequest(BaseModel):
    """요약 요청"""
    doc_id: str = Field(..., description="업로드한 문서 ID")
    max_chunks: int = Field(default=6, ge=1, le=20,
                            description="요약에 사용할 최대 청크 수 (CPU 속도 조절)")


class TranslateRequest(BaseModel):
    """번역 요청 (영→한 기본)"""
    doc_id: str = Field(..., description="업로드한 문서 ID")
    max_chunks: int = Field(default=3, ge=1, le=20,
                            description="번역할 최대 청크 수")


class Message(BaseModel):
    """단일 대화 메시지"""
    role: str = Field(..., description="역할: 'user' 또는 'bot'")
    content: str = Field(..., min_length=1, description="메시지 내용")


class ChatRequest(BaseModel):
    """논문 내용 기반 멀티턴 Q&A 요청"""
    doc_id: str = Field(..., description="업로드한 문서 ID")
    messages: list[Message] = Field(..., min_length=1,
                                    description="대화 기록 (마지막이 현재 질문)")
    max_new_tokens: int = Field(default=256, ge=10, le=1024)
    temperature: float = Field(default=0.7, gt=0.0, le=2.0)


class TextResponse(BaseModel):
    """요약/번역/답변 공통 응답"""
    success: bool = Field(description="성공 여부")
    result: str = Field(description="생성된 텍스트")
    doc_id: str = Field(description="대상 문서 ID")
    model_name: str = Field(description="사용된 모델")
    user: Optional[str] = Field(default=None, description="인증된 사용자")
