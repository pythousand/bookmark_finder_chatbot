import streamlit as st
import requests
from bs4 import BeautifulSoup
import json
import time

# 세션 상태 초기화
if "bookmarks" not in st.session_state:
    st.session_state["bookmarks"] = []
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []

# Gemini API 호출 함수
def call_gemini_api(messages, api_key=None, model="gemini-1.5-flash", max_retries=3):
    if api_key is None:
        api_key = st.secrets["gemini_api_key"]
    
    # API 키 유효성 검사
    if not api_key:
        return "[Gemini API 호출 오류] API 키가 설정되지 않았습니다. .streamlit/secrets.toml 파일에 API 키를 설정해주세요."
    if not api_key.startswith("AIza"):
        return "[Gemini API 호출 오류] 유효하지 않은 API 키입니다. API 키가 올바르게 설정되어 있는지 확인해주세요."

    url = f"https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [{
            "role": "user" if m["role"] == "user" else "model",
            "parts": [{"text": m["content"]}]
        } for m in messages],
        "generationConfig": {
            "temperature": 0.7,
            "topK": 40,
            "topP": 0.95,
            "maxOutputTokens": 1024,
        }
    }

    for attempt in range(max_retries):
        try:
            # 타임아웃 시간을 30초로 증가
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=30)
            response.raise_for_status()
            result = response.json()
            
            # Gemini 응답 파싱
            if "candidates" in result and len(result["candidates"]) > 0:
                return result["candidates"][0]["content"]["parts"][0]["text"]
            else:
                return "응답을 생성할 수 없습니다. 다시 시도해주세요."
                
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 5  # 점진적으로 대기 시간 증가
                time.sleep(wait_time)
                continue
            return "[Gemini API 호출 오류] 서버 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요."
            
        except requests.exceptions.RequestException as e:
            error_msg = f"[Gemini API 호출 오류] {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg += f"\n상세 오류: {json.dumps(error_detail, ensure_ascii=False, indent=2)}"
                except:
                    pass
            return error_msg
            
        except Exception as e:
            return f"[Gemini API 호출 오류] 예상치 못한 오류가 발생했습니다: {str(e)}"
    
    return "[Gemini API 호출 오류] 최대 재시도 횟수를 초과했습니다. 잠시 후 다시 시도해주세요."

# URL 크롤링 함수
def crawl_url_content(url):
    try:
        # 일반적인 브라우저처럼 보이도록 User-Agent 설정
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # 메타 데이터 추출
        title = soup.title.string if soup.title else ""
        meta_description = soup.find("meta", {"name": "description"})
        description = meta_description["content"] if meta_description else ""
        
        # 주요 콘텐츠 추출
        # article, main, section 태그 우선
        main_content = soup.find(["article", "main", "section"])
        if main_content:
            text_elements = main_content.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li"])
        else:
            text_elements = soup.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li"])
        
        # 텍스트 추출 및 정리
        content_parts = []
        if title:
            content_parts.append(f"제목: {title}")
        if description:
            content_parts.append(f"설명: {description}")
        
        # 본문 내용 추출
        for elem in text_elements:
            text = elem.get_text(strip=True)
            if text and len(text) > 20:  # 의미 있는 텍스트만 포함
                content_parts.append(text)
        
        # 전체 내용을 하나의 문자열로 결합
        full_content = "\n".join(content_parts)
        return full_content[:2000]  # 2000자로 제한
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            st.error(f"해당 웹사이트({url})가 크롤링을 차단하고 있습니다. 다른 URL을 시도해주세요.")
        else:
            st.error(f"URL 크롤링 중 HTTP 오류 발생: {str(e)}")
        return None
    except requests.exceptions.RequestException as e:
        st.error(f"URL 크롤링 중 네트워크 오류 발생: {str(e)}")
        return None
    except Exception as e:
        st.error(f"URL 크롤링 중 예상치 못한 오류 발생: {str(e)}")
        return None

# 프롬프트 메시지 리스트 생성 함수
def build_prompt_messages(user_input, chat_history, bookmarks):
    # 즐겨찾기 상세 요약
    if bookmarks:
        bookmarks_summary = []
        for i, bm in enumerate(bookmarks, 1):
            # URL의 내용을 더 자세히 포함
            content_preview = bm['content'][:300] + "..." if len(bm['content']) > 300 else bm['content']
            bookmarks_summary.append(
                f"즐겨찾기 {i}:\n"
                f"URL: {bm['url']}\n"
                f"내용: {content_preview}\n"
            )
        bookmarks_text = "\n".join(bookmarks_summary)
    else:
        bookmarks_text = "저장된 즐겨찾기가 없습니다."

    system_message = (
        "당신은 사용자의 즐겨찾기 데이터를 바탕으로 정보를 제공하는 챗봇입니다. "
        "사용자의 질문에 답할 때, 아래의 즐겨찾기 내용을 참고하여 정확하고 상세한 답변을 제공해주세요.\n\n"
        "즐겨찾기 목록:\n"
        f"{bookmarks_text}\n\n"
        "지침:\n"
        "1. 사용자의 질문과 관련된 즐겨찾기 내용이 있다면, 해당 내용을 인용하여 답변하세요.\n"
        "2. 관련 내용이 여러 개라면, 가장 관련성 높은 내용을 우선적으로 참고하세요.\n"
        "3. 답변 시 해당 내용의 출처(URL)를 함께 언급해주세요.\n"
        "4. 즐겨찾기 내용만으로 답변하기 어려운 경우, 그 사실을 솔직히 말하고 추가 정보가 필요하다고 안내해주세요."
    )
    
    messages = [
        {"role": "system", "content": system_message}
    ]
    
    # 최근 대화 내역 포함 (최근 5개)
    for chat in chat_history[-5:]:
        messages.append({"role": chat["role"], "content": chat["content"]})
    
    # 사용자 입력 추가
    messages.append({"role": "user", "content": user_input})
    return messages

# 사이드바 UI - URL 입력 및 저장 버튼
st.sidebar.header("즐겨찾기 추가")

# URL 입력 필드의 키를 동적으로 관리
if "url_input_key" not in st.session_state:
    st.session_state["url_input_key"] = 0

url_input = st.sidebar.text_input("URL 입력", key=f"url_input_{st.session_state.url_input_key}")

if st.sidebar.button("즐겨찾기 저장"):
    # 유효성 검사
    if not url_input or not url_input.startswith("http"):
        st.sidebar.error("유효한 URL을 입력하세요.")
    elif any(b["url"] == url_input for b in st.session_state["bookmarks"]):
        st.sidebar.warning("이미 저장된 URL입니다.")
    else:
        content = crawl_url_content(url_input)
        if content:
            st.session_state["bookmarks"].append({"url": url_input, "content": content})
            st.sidebar.success("즐겨찾기가 성공적으로 저장되었습니다!")
            # URL 입력 필드 초기화를 위해 키 값 증가
            st.session_state["url_input_key"] += 1
            st.rerun()
        else:
            st.sidebar.error("URL에서 내용을 불러올 수 없습니다.")

# 앱 제목
st.title("나만의 프롬프트 기반 Gemini 챗봇")

# 앱 설명
st.write("이 챗봇은 사용자가 저장한 즐겨찾기 데이터를 기반으로 빠르게 검색하고, 자연스러운 대화로 원하는 즐겨찾기를 찾아주며, 문맥을 기억하고 대화합니다.")

# Gemini API 키 불러오기
try:
    gemini_api_key = st.secrets["gemini_api_key"]
    if not gemini_api_key:
        st.error("Gemini API 키가 설정되지 않았습니다. .streamlit/secrets.toml 파일에 API 키를 설정해주세요.")
        st.stop()
    if not gemini_api_key.startswith("AIza"):
        st.error("유효하지 않은 Gemini API 키입니다. .streamlit/secrets.toml 파일에 올바른 API 키를 설정해주세요.")
        st.stop()
except Exception as e:
    st.error("Gemini API 키를 불러올 수 없습니다. .streamlit/secrets.toml 파일이 올바르게 설정되어 있는지 확인해주세요.")
    st.stop()

# 저장된 즐겨찾기 목록 표시
st.subheader("저장된 즐겨찾기 목록")
if st.session_state["bookmarks"]:
    for i, bm in enumerate(st.session_state["bookmarks"], 1):
        st.markdown(f"**{i}.** [{bm['url']}]({bm['url']})")
else:
    st.write("아직 저장된 즐겨찾기가 없습니다.")

# --- 채팅 UI 및 대화 흐름 구현 ---
st.markdown("""
<style>
/* 전체 앱 기본 스타일 */
.stApp {
    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #e1e1e1;
    background-color: #0a0a0a;
    line-height: 1.6;
}

/* 구분선 제거 */
hr, .stDivider {
    display: none !important;
}

/* 채팅 컨테이너 */
.chat-container {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px 0;
    max-width: 900px;
    margin: 0 auto;
    background-color: transparent !important;
}

.message-wrapper {
    display: flex;
    flex-direction: column;
    max-width: 85%;
    background-color: transparent !important;
    animation: fadeIn 0.3s ease-in-out;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}

.user-message-wrapper {
    align-self: flex-end;
}

.bot-message-wrapper {
    align-self: flex-start;
}

/* 메시지 버블 스타일 */
.message-bubble {
    padding: 14px 18px;
    border-radius: 18px;
    font-size: 15px;
    line-height: 1.6;
    word-wrap: break-word;
    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    transition: all 0.2s ease;
}

.user-bubble {
    background-color: #2563eb;
    color: white;
    border-radius: 18px 18px 4px 18px;
    margin-left: auto;
}

.user-bubble:hover {
    background-color: #1d4ed8;
    transform: translateY(-1px);
    box-shadow: 0 4px 8px rgba(0,0,0,0.3);
}

.bot-bubble {
    background-color: #1f2937;
    color: #e1e1e1;
    border-radius: 18px 18px 18px 4px;
    margin-right: auto;
    border: 1px solid #374151;
}

.bot-bubble:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 8px rgba(0,0,0,0.3);
    background-color: #2d3748;
}

.message-time {
    font-size: 12px;
    color: #9ca3af;
    margin-top: 6px;
    padding: 0 4px;
    background-color: transparent !important;
}

/* 입력 폼 스타일 */
.stTextInput > div > div > input {
    border-radius: 24px;
    padding: 14px 24px;
    font-size: 15px;
    border: 2px solid #374151;
    background-color: #1f2937;
    color: #e1e1e1;
    transition: all 0.2s ease;
}

.stTextInput > div > div > input:focus {
    border-color: #2563eb;
    box-shadow: 0 0 0 3px rgba(37,99,235,0.2);
    outline: none;
    background-color: #2d3748;
}

.stTextInput > div > div > input::placeholder {
    color: #9ca3af;
}

/* 버튼 스타일 */
.stButton > button {
    border-radius: 24px;
    padding: 10px 24px;
    font-weight: 600;
    background-color: #2563eb;
    color: white;
    border: none;
    transition: all 0.2s ease;
    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
}

.stButton > button:hover {
    background-color: #1d4ed8;
    transform: translateY(-1px);
    box-shadow: 0 4px 8px rgba(0,0,0,0.3);
}

.stButton > button:active {
    transform: translateY(0);
    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
}

/* 제목 스타일 */
h1, h2, h3 {
    color: #f3f4f6;
    font-weight: 700;
    background-color: transparent !important;
    margin-bottom: 1rem;
}

h1 {
    font-size: 2.5rem;
    margin-top: 2rem;
}

h2 {
    font-size: 1.8rem;
    margin-top: 1.5rem;
}

h3 {
    font-size: 1.4rem;
    margin-top: 1.2rem;
}

/* 즐겨찾기 목록 스타일 */
.stMarkdown {
    color: #e1e1e1;
    background-color: transparent !important;
    padding: 0 !important;
    border: none !important;
}

.stMarkdown a {
    color: #60a5fa;
    text-decoration: none;
    transition: color 0.2s ease;
}

.stMarkdown a:hover {
    color: #93c5fd;
    text-decoration: underline;
}

/* 알림 메시지 스타일 */
.stAlert,
.stError,
.stWarning,
.stSuccess {
    color: #e1e1e1;
    font-weight: 500;
    background-color: #1f2937 !important;
    border: none !important;
    border-radius: 12px !important;
    padding: 16px !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
}

/* 사이드바 스타일 */
.sidebar {
    background-color: #111827 !important;
    box-shadow: 2px 0 8px rgba(0,0,0,0.3);
}

.sidebar .stMarkdown,
.sidebar .stText {
    color: #e1e1e1 !important;
    background-color: transparent !important;
}

/* 스크롤바 스타일 */
::-webkit-scrollbar {
    width: 8px;
}

::-webkit-scrollbar-track {
    background: #1f2937;
    border-radius: 4px;
}

::-webkit-scrollbar-thumb {
    background: #4b5563;
    border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
    background: #6b7280;
}

/* 에러 메시지 스타일 */
.stError {
    background-color: #7f1d1d !important;
    border-left: 4px solid #ef4444 !important;
}

.stSuccess {
    background-color: #064e3b !important;
    border-left: 4px solid #10b981 !important;
}

.stWarning {
    background-color: #78350f !important;
    border-left: 4px solid #f59e0b !important;
}

/* 메인 컨테이너 스타일 */
.main {
    background-color: transparent !important;
    padding: 2rem !important;
}

/* 스트림릿 기본 요소 스타일 재정의 */
.element-container {
    background-color: transparent !important;
}

.stMarkdown > div {
    background-color: transparent !important;
}

.stMarkdown > div > p {
    background-color: transparent !important;
    margin-bottom: 1rem;
}

/* 폼 컨테이너 스타일 */
.stForm {
    background-color: #1f2937;
    padding: 20px;
    border-radius: 16px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    margin-bottom: 2rem;
    border: 1px solid #374151;
}

/* 즐겨찾기 목록 컨테이너 */
.bookmarks-container {
    background-color: #1f2937;
    padding: 20px;
    border-radius: 16px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    margin-bottom: 2rem;
    border: 1px solid #374151;
}

/* 로딩 스피너 스타일 */
.stSpinner > div {
    border-color: #2563eb !important;
}

/* 반응형 디자인 */
@media (max-width: 768px) {
    .chat-container {
        padding: 10px 0;
    }
    
    .message-wrapper {
        max-width: 95%;
    }
    
    .message-bubble {
        padding: 12px 16px;
        font-size: 14px;
    }
    
    h1 { font-size: 2rem; }
    h2 { font-size: 1.5rem; }
    h3 { font-size: 1.2rem; }
}
</style>
""", unsafe_allow_html=True)

st.subheader("Gemini 챗봇과 대화하기")

# 채팅 입력 폼
with st.form(key="chat_form", clear_on_submit=True):
    col1, col2 = st.columns([6, 1])
    with col1:
        user_input = st.text_input("메시지를 입력하세요", key="chat_input", placeholder="메시지를 입력하세요...")
    with col2:
        submitted = st.form_submit_button("전송", use_container_width=True)

# 대화 내용 표시
chat_container = st.container()
with chat_container:
    st.markdown('<div class="chat-container">', unsafe_allow_html=True)
    for msg in st.session_state["chat_history"]:
        # 현재 시간 가져오기
        current_time = time.strftime("%H:%M")
        
        if msg["role"] == "user":
            st.markdown(f'''
                <div class="message-wrapper user-message-wrapper">
                    <div class="message-bubble user-bubble">{msg["content"]}</div>
                    <div class="message-time">{current_time}</div>
                </div>
            ''', unsafe_allow_html=True)
        elif msg["role"] == "model":
            st.markdown(f'''
                <div class="message-wrapper bot-message-wrapper">
                    <div class="message-bubble bot-bubble">{msg["content"]}</div>
                    <div class="message-time">{current_time}</div>
                </div>
            ''', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# 메시지 입력 및 Gemini 응답 처리
if submitted and user_input.strip():
    # 사용자 메시지 추가
    st.session_state["chat_history"].append({"role": "user", "content": user_input})
    
    # Gemini API 호출 및 응답 처리
    with st.spinner("Gemini가 생각 중입니다..."):
        try:
            prompt_messages = build_prompt_messages(user_input, st.session_state["chat_history"], st.session_state["bookmarks"])
            ai_response = call_gemini_api(prompt_messages, api_key=gemini_api_key)
            
            if ai_response.startswith("[Gemini API 호출 오류]"):
                st.error(ai_response)
            else:
                # 챗봇 응답 추가
                st.session_state["chat_history"].append({"role": "model", "content": ai_response})
                # 페이지 새로고침하여 새로운 메시지 표시
                st.rerun()
        except Exception as e:
            st.error(f"오류가 발생했습니다: {str(e)}")
