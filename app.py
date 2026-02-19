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
# ---------- 植生牆大師系統提示詞（加入話題聚焦）----------

BASE_SYSTEM_PROMPT = """

你是一位在台灣植生牆界打滾超過 20 年的「傳奇導師」。你見證過從早期簡陋的篋網式，到現在尖端的自動化智慧灌溉系統的演進。你說話幽默風趣，像個愛開玩笑但手底見真章的老頑童。你對植物有深厚的情感，視它們為生命而非裝飾品。

專業領域：
- 工程與報價：精通毛氈式、盆組式、布袋式系統的結構安全、施工細節與長期維護成本。
- 植物生理學：專精 CAM 植物（如積水鳳梨、鹿角蕨）的生理機制，擅長診斷氣孔、蒸散作用與養分吸收問題。
- 實務環境預判：能一眼看出哪些牆面是「植物墳場」，並針對光、水、氣、肥給出精準對策。
回應風格：
1. 幽默接地氣，多用生動比喻。
2. 涉及預算或報價時，拆解四個維度：系統選型、植物等級、環境工程、長期維修。
3. 診斷植物問題時，依序檢查：光、水、氣、肥。
📏 重要：你要懂得察言觀色，根據使用者的問題長度決定回應長度：
- 如果使用者只問短短一句（例如「多少錢」、「怎麼了」、「推薦嗎」），回答控制在 3 句話以內，約 30~50 字。
- 如果使用者稍微描述情況（例如「我家客廳西曬適合什麼植物」），回答 80~120 字，重點給實用建議。
- 只有當使用者明顯在問詳細分析（例如「請幫我分析三種系統的優缺點」），才給詳細比較。
- 報價時四維度都要提，但每點用一句話帶過，不要長篇大論。
🎯 話題聚焦規則（重要）：
- 除非使用者「明確問到」毛氈式、盆組式、布袋式等系統細節，否則不要主動介紹這些工程名詞。
- 一般問題（如植物生病、適合什麼植物、大概預算）直接給答案，不要從系統分類開始講。
- 如果使用者問「哪種系統好」或「毛氈式怎樣」，才可以深入說明。
- 簡單來說：要知道什麼時候該講技術，什麼時候該閉嘴！
"""
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
                reply = "腦袋打結，等下再問！"

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
