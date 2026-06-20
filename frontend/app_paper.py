"""
Day 8 - 논문 번역·요약·Q&A 챗봇 대시보드 (Streamlit)
재사용: Day 4 파일 업로드/레이아웃 + Day 7 채팅 UI(st.chat_message/st.chat_input)
"""
import streamlit as st
import requests

st.set_page_config(page_title="논문 챗봇", page_icon="📄", layout="centered")
API_BASE = "http://localhost:8000"


def api_post(path, api_key, json=None, files=None, timeout=180):
    try:
        resp = requests.post(f"{API_BASE}{path}",
                             json=json, files=files,
                             headers={"X-API-Key": api_key}, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        st.error("🔌 서버에 연결할 수 없습니다.")
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code
        if code == 401:
            st.error("🔑 인증 실패. API Key를 확인하세요.")
        else:
            detail = e.response.json().get("detail", "")
            st.error(f"❌ 서버 에러 (HTTP {code}) {detail}")
    except Exception as e:
        st.error(f"❌ 오류: {type(e).__name__}")
    return None


# ===== 사이드바 =====
with st.sidebar:
    st.header("⚙️ 설정")
    api_key = st.text_input("API Key", value="test-key-001", type="password")
    st.divider()

    pdf = st.file_uploader("논문 PDF 업로드", type=["pdf"])
    if st.button("📤 업로드 & 분석", disabled=pdf is None):
        with st.spinner("PDF 텍스트 추출 중..."):
            files = {"file": (pdf.name, pdf.getvalue(), "application/pdf")}
            res = api_post("/upload", api_key, files=files)
        if res:
            st.session_state["doc_id"] = res["doc_id"]
            st.session_state["doc_name"] = res["filename"]
            st.session_state["messages"] = []
            st.success(f"✅ 업로드 완료: {res['n_chunks']}개 청크 / {res['n_chars']:,}자")

    if st.session_state.get("doc_id"):
        st.caption(f"📄 현재 문서: {st.session_state['doc_name']} (id={st.session_state['doc_id']})")
    st.divider()

    try:
        h = requests.get(f"{API_BASE}/health", timeout=3).json()
        st.success(f"🟢 서버 연결됨 · 모델 {h.get('model','')}") if h.get("status") == "healthy" \
            else st.warning("🟡 모델 로딩 중...")
    except Exception:
        st.error("🔴 서버 연결 실패")


# ===== 상태 초기화 =====
st.session_state.setdefault("messages", [])

st.title("📄 논문 번역·요약 챗봇")

doc_id = st.session_state.get("doc_id")
if not doc_id:
    st.info("왼쪽 사이드바에서 논문 PDF를 업로드하세요.")
else:
    # ---- 요약 / 번역 버튼 ----
    c1, c2 = st.columns(2)
    if c1.button("📝 전체 요약"):
        with st.spinner("요약 생성 중... (CPU라 다소 걸립니다)"):
            res = api_post("/summarize", api_key, json={"doc_id": doc_id, "max_chunks": 6})
        if res:
            st.subheader("요약 결과")
            st.write(res["result"])
    if c2.button("🌐 영→한 번역 (앞부분)"):
        with st.spinner("번역 중..."):
            res = api_post("/translate", api_key, json={"doc_id": doc_id, "max_chunks": 3})
        if res:
            st.subheader("번역 결과")
            st.write(res["result"])

    st.divider()
    st.caption("논문 내용에 대해 질문해 보세요 (멀티턴).")

    # ---- 대화 기록 표시 ----
    for m in st.session_state["messages"]:
        with st.chat_message(m["role"]):
            st.write(m["content"])

    # ---- 질문 입력 ----
    if q := st.chat_input("논문에 대해 질문하기..."):
        st.session_state["messages"].append({"role": "user", "content": q})
        with st.chat_message("user"):
            st.write(q)
        with st.chat_message("assistant"):
            with st.spinner("답변 생성 중..."):
                api_msgs = [{"role": "user" if m["role"] == "user" else "bot",
                             "content": m["content"]} for m in st.session_state["messages"]]
                res = api_post("/chat", api_key,
                               json={"doc_id": doc_id, "messages": api_msgs})
            if res:
                st.write(res["result"])
                st.session_state["messages"].append(
                    {"role": "assistant", "content": res["result"]})
