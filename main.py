from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from dotenv import load_dotenv
import os
import httpx
import json
import asyncio

# 載入 .env 的金鑰
load_dotenv()

# 初始化 FastAPI
app = FastAPI()

# 讀取環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# 檢查必要環境變數
if not LINE_CHANNEL_ACCESS_TOKEN:
    raise RuntimeError("Missing LINE_CHANNEL_ACCESS_TOKEN")
if not LINE_CHANNEL_SECRET:
    raise RuntimeError("Missing LINE_CHANNEL_SECRET")
if not SUPABASE_URL:
    raise RuntimeError("Missing SUPABASE_URL")
if not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_KEY")
if not ANTHROPIC_API_KEY:
    raise RuntimeError("Missing ANTHROPIC_API_KEY")

# 初始化 LINE Bot
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


async def insert_diary_and_parse(content: str, user_id: str, word_count: int):
    """插入日記，然後呼叫 Claude 解析摘要"""
    async with httpx.AsyncClient() as client:

        # 第一步：插入原始日記，取得 id
        response = await client.post(
            f"{SUPABASE_URL}/rest/v1/diaries",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=representation"
            },
            json={
                "content": content,
                "line_user_id": user_id,
                "word_count": word_count,
                "is_processed": False,
                "diary_date": None
            }
        )
        response.raise_for_status()
        diary_id = response.json()[0]["id"]

        # 第二步：呼叫 Claude API 解析
        claude_response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-5",
                "max_tokens": 1000,
                "messages": [{
                    "role": "user",
                    "content": f"""請分析以下日記內容，只回傳 JSON 格式，不要其他文字：
{{
  "diary_date": "日記描述的日期 YYYY-MM-DD，無法判斷填 null",
  "location": "地點，無則填 null",
  "people": "提到的人物用逗號分隔，無則填 null",
  "emotion": "從以下選一個：開心、難過、平靜、興奮、焦慮、憤怒、感恩、其他",
  "keywords": "3-5個關鍵詞用逗號分隔",
  "summary": "一句話摘要20字以內"
}}

日記內容：
{content}"""
                }]
            },
            timeout=30.0
        )
        print("Claude response:", claude_response.status_code, claude_response.text)
        claude_response.raise_for_status()
        parsed_text = claude_response.json()["content"][0]["text"]
        parsed = json.loads(parsed_text)

        # 第三步：插入摘要
        await client.post(
            f"{SUPABASE_URL}/rest/v1/diary_summaries",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            },
            json={
                "diary_id": diary_id,
                "diary_date": parsed.get("diary_date"),
                "location": parsed.get("location"),
                "people": parsed.get("people"),
                "emotion": parsed.get("emotion"),
                "keywords": parsed.get("keywords"),
                "summary": parsed.get("summary")
            }
        )

        # 第四步：更新 is_processed
        await client.patch(
            f"{SUPABASE_URL}/rest/v1/diaries?id=eq.{diary_id}",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json"
            },
            json={"is_processed": True}
        )


# LINE Webhook 接收端點
@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()

    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    return "OK"


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    user_id = event.source.user_id

    if user_message.startswith("/日記"):
        content = user_message[3:].strip()
        word_count = len(content)

        # 背景執行：存日記 + Claude 解析
        asyncio.create_task(
            insert_diary_and_parse(content, user_id, word_count)
        )

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="✅ 日記已收到，AI 正在解析中...")
        )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="🚧 功能開發中")
        )