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

# ---------- 日誌設定 ----------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------- 載入環境變數 ----------
load_dotenv()

LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# 檢查必要的環境變數
if not all([LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, DEEPSEEK_API_KEY]):
    logger.error("❌ 缺少必要的環境變數！請檢查 .env 或 Render 的 Environment Variables")
    # 不停止程式，但後續會無法正常工作

# ---------- 初始化客戶端 ----------
# DeepSeek (OpenAI 相容)
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com/v1",
    timeout=15.0,          # 超過 15 秒視為超時
    max_retries=1
)

# LINE Bot API
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN) if LINE_CHANNEL_ACCESS_TOKEN else None
parser = WebhookParser(LINE_CHANNEL_SECRET) if LINE_CHANNEL_SECRET else None

# ---------- 植生牆大師系統提示詞（請填上你原本的完整內容）----------
SYSTEM_PROMPT = """
你是一位在台灣植生牆界打滾超過 20 年的「傳奇導師」。你見證過從早期簡陋的篋網式，到現在尖端的自動化智慧灌溉系統的演進。你說話幽默風趣，像個愛開玩笑但手底見真章的老頑童。你對植物有深厚的情感，視它們為生命而非裝飾品。

專業領域：
- 工程與報價：精通毛氈式、盆組式、布袋式系統的結構安全、施工細節與長期維護成本。
- 植物生理學：專精 CAM 植物（如積水鳳梨、鹿角蕨）的生理機制，擅長診斷氣孔、蒸散作用與養分吸收問題。
- 實務環境預判：能一眼看出哪些牆面是「植物墳場」，並針對光、水、氣、肥給出精準對策。

 回應長度指南：
- 使用者問簡單問題（如「多少錢」、「怎麼了」、「推薦嗎」），回答控制在 30-50 字，最多 3 句話。
- 使用者問具體問題（如「我家客廳西曬適合什麼植物」），回答 80-120 字，重點在實用建議。
- 只有當使用者明顯在問詳細分析（如「請幫我分析三種系統的優缺點」），才給詳細比較。
- 報價時四維度仍要提，但每點一句話帶過，例如：「系統方面建議模組化盆組，雖然貴一點但以後好維護；植物用波士頓腎蕨就好，積水鳳梨你預算不夠...」

回應風格：
1. 幽默接地氣，多用生動比喻（例如：「鹿角蕨就像愛撒嬌的女友，通風不夠她就鬧脾氣爛給你看」）。
2. 涉及預算或報價時，一定要拆解四個維度：系統選型、植物等級、環境工程、長期維修。嚴禁直接給總價。
3. 診斷植物問題時，依序檢查：光、水、氣、肥。
"""

# ---------- 輔助函數 ----------
def verify_signature(body: bytes, signature: str) -> bool:
    """驗證 LINE 請求簽名"""
    if not LINE_CHANNEL_SECRET:
        return False
    hash = hmac.new(
        LINE_CHANNEL_SECRET.encode('utf-8'),
        body,
        hashlib.sha256
    ).digest()
    return base64.b64encode(hash).decode() == signature

def truncate_text(text: str, max_length: int = 4800) -> str:
    """LINE 訊息長度限制 5000，保留 200 緩衝"""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

# ---------- FastAPI 應用 ----------
app = FastAPI(title="植生牆大師 LINE Bot")

@app.get("/")
async def root():
    return {"message": "植生牆大師 LINE Bot 上線啦！"}

@app.get("/webhook")
async def verify_webhook():
    """LINE 會用 GET 驗證 webhook 有效性"""
    return PlainTextResponse("OK")

@app.post("/webhook")
async def webhook(request: Request, x_line_signature: str = Header(None)):
    # 讀取請求內容（bytes）
    body = await request.body()
    logger.info(f"📨 收到請求，長度：{len(body)}")

    # 簽名驗證（失敗仍回 200，避免 LINE 重試）
    if not verify_signature(body, x_line_signature):
        logger.warning("⚠️ 簽名驗證失敗")
        return PlainTextResponse("OK")

    # 確認 LINE 相關物件已初始化
    if not parser or not line_bot_api:
        logger.error("❌ LINE 憑證未正確初始化")
        return PlainTextResponse("OK")

    # ---------- 解析事件（注意：parse 需要字串，不是 bytes）----------
    try:
        body_str = body.decode('utf-8')          # 將 bytes 轉為字串
        events = parser.parse(body_str, x_line_signature)
    except InvalidSignatureError:
        logger.warning("⚠️ 解析時簽名無效")
        return PlainTextResponse("OK")
    except Exception as e:
        logger.error(f"❌ 解析事件錯誤：{e}")
        return PlainTextResponse("OK")

    # ---------- 處理每個事件 ----------
    for event in events:
        if isinstance(event, MessageEvent) and isinstance(event.message, TextMessage):
            user_msg = event.message.text
            reply_token = event.reply_token
            user_id = event.source.user_id      # 用於後續 push_message
            logger.info(f"💬 使用者說：{user_msg}")

            # 1. 快速回應（讓使用者知道 Bot 有反應）
            try:
                line_bot_api.reply_message(
                    reply_token,
                    TextSendMessage(text="🌱 拎北聽到了，正在幫你查植生牆的祕訣，稍等喔...")
                )
            except Exception as e:
                logger.error(f"❌ 快速回應失敗：{e}")
                # 快速回應失敗可能 token 已過期，跳過本次事件
                continue

            # 2. 呼叫 DeepSeek API 取得大師回覆
            try:
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg}
                    ],
                    temperature=0.8,
                    max_tokens=1024,
                )
                reply = response.choices[0].message.content
                logger.info(f"✅ DeepSeek 回覆（前50字）：{reply[:50]}")
            except APITimeoutError:
                reply = "哎呀，DeepSeek 今天睡著了，你再問一次看看？"
                logger.error("⏰ DeepSeek 超時")
            except APIError as e:
                reply = f"DeepSeek 出錯了：{e.message}"
                logger.error(f"❌ DeepSeek API 錯誤：{e}")
            except Exception as e:
                reply = "拎北腦袋突然打結，等一下再問啦～"
                logger.error(f"❌ 未知錯誤：{e}")

            # 3. 截斷過長訊息
            final_reply = truncate_text(reply)

            # 4. 推送最終答案（push_message 不受 token 時效限制）
            try:
                line_bot_api.push_message(
                    user_id,
                    TextSendMessage(text=final_reply)
                )
                logger.info("✅ 最終答案已推送")
            except LineBotApiError as e:
                logger.error(f"❌ LINE push 失敗：{e}")
            except Exception as e:
                logger.error(f"❌ 其他發送錯誤：{e}")

    # 無論如何都回傳 200 OK
    return PlainTextResponse("OK")
