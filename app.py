import os
import hashlib
import hmac
import base64
import logging
from fastapi import FastAPI, Request, Header
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv
from openai import OpenAI, APITimeoutError, APIError
from linebot import LineBotApi, WebhookParser
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import TextSendMessage, MessageEvent, TextMessage

# ---------- 日誌與環境變數 ----------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
load_dotenv()

# 從 Render 環境變數取得憑證
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# ---------- 初始化 ----------
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com/v1",
    timeout=25.0, # 稍微拉長等待時間，避免 Reply Token 過期
    max_retries=1
)

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN) if LINE_CHANNEL_ACCESS_TOKEN else None
parser = WebhookParser(LINE_CHANNEL_SECRET) if LINE_CHANNEL_SECRET else None

BASE_SYSTEM_PROMPT = "你是一位在台灣植生牆界打滾超過 20 年的傳奇導師..." # 此處省略原 Prompt 以節省長度

# ---------- 輔助函數 ----------
def verify_signature(body: bytes, signature: str) -> bool:
    if not LINE_CHANNEL_SECRET: return False
    hash = hmac.new(LINE_CHANNEL_SECRET.encode('utf-8'), body, hashlib.sha256).digest()
    return base64.b64encode(hash).decode() == signature

def decide_response_params(user_msg: str):
    length = len(user_msg)
    if length < 20: return 150, "極簡回答。"
    return 500, "正常回答。"

# ---------- FastAPI 應用 ----------
app = FastAPI()

@app.post("/webhook")
async def webhook(request: Request, x_line_signature: str = Header(None)):
    body = await request.body()
    if not verify_signature(body, x_line_signature):
        return PlainTextResponse("OK")

    try:
        events = parser.parse(body.decode('utf-8'), x_line_signature)
    except Exception as e:
        logger.error(f"解析錯誤: {e}")
        return PlainTextResponse("OK")

    for event in events:
        if isinstance(event, MessageEvent) and isinstance(event.message, TextMessage):
            user_msg = event.message.text
            # 修改重點：獲取此次事件的 reply_token
            reply_token = event.reply_token 

            max_tokens, length_instruction = decide_response_params(user_msg)
            
            try:
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": BASE_SYSTEM_PROMPT + length_instruction},
                        {"role": "user", "content": user_msg}
                    ],
                    max_tokens=max_tokens,
                )
                reply = response.choices[0].message.content
            except Exception:
                reply = "拎北腦袋打結，等下再問！"

            # ---------- 核心修改：改用 reply_message (免費) ----------
            try:
                line_bot_api.reply_message(
                    reply_token, # 使用 Token 回覆
                    TextSendMessage(text=reply[:4800]) # 限制長度
                )
                logger.info("✅ 已使用 Reply 免費回覆")
            except LineBotApiError as e:
                logger.error(f"❌ Reply 失敗: {e}")

    return PlainTextResponse("OK")

@app.get("/")
async def root(): return {"status": "running"}
