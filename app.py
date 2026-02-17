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

if not all([LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, DEEPSEEK_API_KEY]):
    logger.error("❌ 缺少必要的環境變數！請檢查 .env 或 Render 的 Environment Variables")

# ---------- 初始化客戶端 ----------
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com/v1",
    timeout=15.0,
    max_retries=1
)

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN) if LINE_CHANNEL_ACCESS_TOKEN else None
parser = WebhookParser(LINE_CHANNEL_SECRET) if LINE_CHANNEL_SECRET else None

# ---------- 植生牆大師系統提示詞（已加入長度指南）----------
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
- 如果使用者只問短短一句（例如「多少錢」、「怎麼了」），回答控制在 3 句話以內，約 30~50 字。
- 如果使用者稍微描述情況（例如「我家客廳西曬適合什麼植物」），回答 80~120 字，重點給實用建議。
- 只有當使用者明顯在問詳細分析（例如「請幫我分析三種系統的優缺點」），才給詳細比較。
- 報價時四維度都要提，但每點用一句話帶過，不要長篇大論。
"""

# ---------- 輔助函數 ----------
def verify_signature(body: bytes, signature: str) -> bool:
    if not LINE_CHANNEL_SECRET:
        return False
    hash = hmac.new(
        LINE_CHANNEL_SECRET.encode('utf-8'),
        body,
        hashlib.sha256
    ).digest()
    return base64.b64encode(hash).decode() == signature

def truncate_text(text: str, max_length: int = 4800) -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

def decide_response_params(user_msg: str):
    """根據使用者訊息長度決定 max_tokens 和額外的長度指示"""
    length = len(user_msg)
    if length < 20:
        # 極簡提問
        return 200, "使用者問得很簡單，請用 1~2 句話簡潔回答。"
    elif length < 50:
        # 一般簡短
        return 400, "請用 3~4 句話回答，重點明確。"
    elif length < 150:
        # 中等描述
        return 600, "請適當展開，但不要囉嗦。"
    else:
        # 詳細描述
        return 1024, "使用者提供較多資訊，可以詳細回答。"

# ---------- FastAPI 應用 ----------
app = FastAPI(title="植生牆大師 LINE Bot")

@app.get("/")
async def root():
    return {"message": "植生牆大師 LINE Bot 上線啦！"}

@app.get("/webhook")
async def verify_webhook():
    return PlainTextResponse("OK")

@app.post("/webhook")
async def webhook(request: Request, x_line_signature: str = Header(None)):
    body = await request.body()
    logger.info(f"📨 收到請求，長度：{len(body)}")

    if not verify_signature(body, x_line_signature):
        logger.warning("⚠️ 簽名驗證失敗")
        return PlainTextResponse("OK")

    if not parser or not line_bot_api:
        logger.error("❌ LINE 憑證未正確初始化")
        return PlainTextResponse("OK")

    try:
        body_str = body.decode('utf-8')
        events = parser.parse(body_str, x_line_signature)
    except InvalidSignatureError:
        logger.warning("⚠️ 解析時簽名無效")
        return PlainTextResponse("OK")
    except Exception as e:
        logger.error(f"❌ 解析事件錯誤：{e}")
        return PlainTextResponse("OK")

    for event in events:
        if isinstance(event, MessageEvent) and isinstance(event.message, TextMessage):
            user_msg = event.message.text
            reply_token = event.reply_token
            user_id = event.source.user_id
            logger.info(f"💬 使用者說：{user_msg}")

            # 快速回應
            try:
                line_bot_api.reply_message(
                    reply_token,
                    TextSendMessage(text="🌱 聽到了，今年沒年終肚子有點餓，稍等喔...")
                )
            except Exception as e:
                logger.error(f"❌ 快速回應失敗：{e}")
                continue

            # 根據訊息長度決定回應參數
            max_tokens, length_instruction = decide_response_params(user_msg)
            # 組裝 system prompt（加入長度指示）
            system_content = BASE_SYSTEM_PROMPT + f"\n\n本次回應特別指示：{length_instruction}"

            try:
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": user_msg}
                    ],
                    temperature=0.7 if max_tokens < 500 else 0.8,
                    max_tokens=max_tokens,
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

            final_reply = truncate_text(reply)

            # 推送最終答案
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

    return PlainTextResponse("OK")
