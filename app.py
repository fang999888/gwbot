import os
import hashlib
import hmac
import base64
import json
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv
from openai import OpenAI
from linebot import LineBotApi, WebhookParser
from linebot.exceptions import InvalidSignatureError
from linebot.models import TextSendMessage, MessageEvent, TextMessage

load_dotenv()

app = FastAPI(title="植生牆大師 LINE Bot")

# LINE 憑證
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

# DeepSeek 客戶端
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1"
)

# LINE Bot API 初始化
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(LINE_CHANNEL_SECRET)

# 植生牆大師系統提示詞（就是你給的那段）
SYSTEM_PROMPT = """
你是一位在台灣植生牆界打滾超過 20 年的「傳奇導師」。你見證過從早期簡陋的篋網式，到現在尖端的自動化智慧灌溉系統的演進。你說話幽默風趣，像個愛開玩笑但手底見真章的老頑童。你對植物有深厚的情感，視它們為生命而非裝飾品。

專業領域：
- 工程與報價：精通毛氈式、盆組式、布袋式系統的結構安全、施工細節與長期維護成本。
- 植物生理學：專精 CAM 植物（如積水鳳梨、鹿角蕨）的生理機制，擅長診斷氣孔、蒸散作用與養分吸收問題。
- 實務環境預判：能一眼看出哪些牆面是「植物墳場」，並針對光、水、氣、肥給出精準對策。

回應風格：
1. 幽默接地氣，多用生動比喻（例如：「鹿角蕨就像愛撒嬌的女友，通風不夠她就鬧脾氣爛給你看」）。
2. 涉及預算或報價時，一定要拆解四個維度：系統選型、植物等級、環境工程、長期維修。嚴禁直接給總價。
3. 診斷植物問題時，依序檢查：光、水、氣、肥。
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
    
    # 驗證簽名（安全性檢查）
    if not verify_signature(body, x_line_signature):
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    try:
        # 解析 LINE 事件
        events = parser.parse(body, x_line_signature)
        
        # 處理每個事件
        for event in events:
            if isinstance(event, MessageEvent) and isinstance(event.message, TextMessage):
                # 使用者傳來的訊息
                user_message = event.message.text
                
                # 呼叫 DeepSeek API 取得大師回覆
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
                except Exception as e:
                    reply_text = f"哎呀，大師今天當機了，錯誤訊息：{str(e)}"
                
                # 透過 LINE API 回覆
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=reply_text)
                )
        
        return PlainTextResponse("OK")
    
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
