import os
import hashlib
import hmac
import base64
import logging
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv
from openai import OpenAI
from linebot import LineBotApi, WebhookParser
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import TextSendMessage, MessageEvent, TextMessage

# 設定 logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="植生牆大師 LINE Bot")

# LINE 憑證
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

# DeepSeek 客戶端
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    logger.error("DEEPSEEK_API_KEY 未設定")
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com/v1"
)

# LINE Bot API 初始化
if not LINE_CHANNEL_SECRET or not LINE_CHANNEL_ACCESS_TOKEN:
    logger.error("LINE_CHANNEL_SECRET 或 LINE_CHANNEL_ACCESS_TOKEN 未設定")
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(LINE_CHANNEL_SECRET)

# 植生牆大師系統提示詞
SYSTEM_PROMPT = """
你是一位在台灣植生牆界打滾超過 20 年的「傳奇導師」...（完整內容省略，請貼回你原本的）...
"""

def verify_signature(request_body: bytes, x_line_signature: str) -> bool:
    """驗證 LINE 請求簽名"""
    hash = hmac.new(
        LINE_CHANNEL_SECRET.encode('utf-8'),
        request_body,
        hashlib.sha256
    ).digest()
    signature = base64.b64encode(hash).decode()
    return signature == x_line_signature

@app.get("/")
async def root():
    return {"message": "植生牆大師 LINE Bot 上線啦！"}

@app.get("/webhook")
async def verify_webhook():
    """LINE 會用 GET 驗證 webhook"""
    return PlainTextResponse("OK")

@app.post("/webhook")
async def webhook(
    request: Request, 
    x_line_signature: str = Header(None)
):
    # 取得請求內容
    body = await request.body()
    logger.info(f"Received webhook: {body[:200]}...")  # 記錄前200字符
    
    # 驗證簽名
    if not verify_signature(body, x_line_signature):
        logger.warning("Invalid signature")
        # 簽名錯誤直接回傳 200 但記錄警告，不回傳 400 避免 LINE 重試
        return PlainTextResponse("OK")
    
    try:
        # 解析 LINE 事件
        events = parser.parse(body, x_line_signature)
        
        # 處理每個事件
        for event in events:
            if isinstance(event, MessageEvent) and isinstance(event.message, TextMessage):
                user_message = event.message.text
                logger.info(f"Received message: {user_message}")
                
                # 呼叫 DeepSeek API
                try:
                    response = client.chat.completions.create(
                        model="deepseek-chat",
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_message}
                        ],
                        temperature=0.8,
                        max_tokens=1024
                    )
                    reply_text = response.choices[0].message.content
                    logger.info(f"Generated reply: {reply_text[:50]}...")
                except Exception as e:
                    logger.error(f"DeepSeek API error: {e}")
                    reply_text = "哎呀，大師腦袋卡住了，等一下再問我喔～"
                
                # 回覆 LINE
                try:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=reply_text)
                    )
                except LineBotApiError as e:
                    logger.error(f"LINE reply error: {e}")
                except Exception as e:
                    logger.error(f"Unexpected LINE reply error: {e}")
        
        return PlainTextResponse("OK")
    
    except InvalidSignatureError:
        logger.warning("Invalid signature from parser")
        return PlainTextResponse("OK")
    except Exception as e:
        logger.error(f"Unexpected error in webhook: {e}", exc_info=True)
        return PlainTextResponse("OK")
