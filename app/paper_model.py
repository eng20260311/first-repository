"""
Day 8 - 논문 챗봇 모델 (단일 인스트럭트 LLM으로 번역·요약·Q&A 모두 처리)
Day 7의 ChatbotModel을 확장 — 같은 모델에 '역할(system) + 작업 프롬프트'만 바꿔 재사용한다.
"""
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM


class PaperBot:
    """하나의 LLM으로 논문 요약/번역/질의응답을 수행합니다."""

    def __init__(self, model_name: str = "Qwen/Qwen2.5-0.5B-Instruct"):
        if torch.cuda.is_available():
            self.device = "cuda"
        elif torch.backends.mps.is_available():
            self.device = "mps"
        else:
            self.device = "cpu"

        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        dtype = torch.float16 if self.device in ("cuda", "mps") else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(model_name, dtype=dtype)
        self.model = self.model.to(self.device)
        self.model.eval()
        self.model_name = model_name

    # ---- 핵심 생성기 (모든 작업이 이걸 공유) ----
    def _generate(self, chat: list[dict], max_new_tokens: int = 256,
                  temperature: float = 0.7) -> str:
        # transformers 5.x: return_dict=False 로 텐서를 직접 받는다 (안 하면 BatchEncoding)
        input_ids = self.tokenizer.apply_chat_template(
            chat, add_generation_prompt=True, return_tensors="pt", return_dict=False
        ).to(self.device)

        max_length = getattr(self.model.config, "max_position_embeddings", 2048)
        if input_ids.shape[1] > max_length - max_new_tokens:
            # 입력이 너무 길면 앞부분을 잘라 모델 한계를 넘지 않게 한다
            input_ids = input_ids[:, -(max_length - max_new_tokens):]

        with torch.no_grad():
            output_ids = self.model.generate(
                input_ids,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=0.9,
                do_sample=True,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        return self.tokenizer.decode(
            output_ids[0][input_ids.shape[1]:], skip_special_tokens=True
        ).strip()

    # ---- 요약: 청크별 요약 → 합쳐서 최종 요약 (map-reduce) ----
    def summarize(self, chunks: list[str], max_chunks: int = 6) -> str:
        used = chunks[:max_chunks]
        partial = []
        for i, ch in enumerate(used, 1):
            chat = [
                {"role": "system",
                 "content": "너는 학술 논문을 읽고 핵심을 한국어로 정리하는 전문가야."},
                {"role": "user",
                 "content": f"다음 논문 일부를 한국어로 3문장 이내로 요약해줘.\n\n{ch}"},
            ]
            partial.append(f"[{i}] " + self._generate(chat, max_new_tokens=200, temperature=0.5))

        joined = "\n".join(partial)
        chat = [
            {"role": "system",
             "content": "너는 부분 요약들을 통합해 하나의 매끄러운 한국어 요약으로 만드는 전문가야."},
            {"role": "user",
             "content": f"다음 부분 요약들을 합쳐 논문 전체를 한국어로 5~7문장으로 요약해줘.\n\n{joined}"},
        ]
        return self._generate(chat, max_new_tokens=400, temperature=0.5)

    # ---- 번역: 청크별 영→한 번역 ----
    def translate(self, chunks: list[str], max_chunks: int = 3) -> str:
        out = []
        for ch in chunks[:max_chunks]:
            chat = [
                {"role": "system",
                 "content": "너는 영어 학술 텍스트를 자연스러운 한국어로 번역하는 전문 번역가야. "
                            "전문 용어는 정확히 옮기고, 의미를 보존해."},
                {"role": "user", "content": f"다음 영어 텍스트를 한국어로 번역해줘.\n\n{ch}"},
            ]
            out.append(self._generate(chat, max_new_tokens=512, temperature=0.3))
        return "\n\n".join(out)

    # ---- Q&A: 논문 내용을 컨텍스트로 멀티턴 답변 ----
    def answer(self, context: str, messages: list[dict],
               max_new_tokens: int = 256, temperature: float = 0.7) -> str:
        chat = [
            {"role": "system",
             "content": "너는 주어진 논문 내용에 근거해 한국어로 답하는 助手야. "
                        "논문에 없는 내용은 추측하지 말고 모른다고 말해."},
            {"role": "user", "content": f"[논문 내용]\n{context}\n\n위 내용을 참고해 대화에 답해줘."},
            {"role": "assistant", "content": "네, 논문 내용을 바탕으로 답변하겠습니다."},
        ]
        for m in messages:
            role = "user" if m["role"] == "user" else "assistant"
            chat.append({"role": role, "content": m["content"]})
        return self._generate(chat, max_new_tokens=max_new_tokens, temperature=temperature)
