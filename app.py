import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = FastAPI(title="植生牆大師 API")

# DeepSeek 客戶端設定
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1"  # DeepSeek 官方端點
)

# 系統提示詞（就是你給的那段，完整保留大師人設）
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

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    reply: str

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        # 呼叫 DeepSeek API
        response = client.chat.completions.create(
            model="deepseek-chat",  # 或其他你訂閱的模型
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": request.message}
            ],
            temperature=0.8,
            max_tokens=1024
        )
        reply = response.choices[0].message.content
        return ChatResponse(reply=reply)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    return {"message": "植生牆大師 在此，有啥問題放馬過來！"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
