from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from dotenv import load_dotenv
import os
import httpx

# 載入 .env 的金鑰
load_dotenv()

# 初始化 FastAPI
app = FastAPI()

# 讀取環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# 檢查必要環境變數是否存在
if not LINE_CHANNEL_ACCESS_TOKEN:
    raise RuntimeError("Missing LINE_CHANNEL_ACCESS_TOKEN environment variable")

if not LINE_CHANNEL_SECRET:
    raise RuntimeError("Missing LINE_CHANNEL_SECRET environment variable")

if not SUPABASE_URL:
    raise RuntimeError("Missing SUPABASE_URL environment variable")

if not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_KEY environment variable")

# 初始化 LINE Bot
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


async def insert_diary(content: str, user_id: str, word_count: int):
    """用 httpx 直接呼叫 Supabase REST API 插入日記"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{SUPABASE_URL}/rest/v1/diaries",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
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

    # 判斷是否為日記指令
    if user_message.startswith("/日記"):
        content = user_message[3:].strip()
        word_count = len(content)

        # 使用 httpx 異步插入資料
        import asyncio
        asyncio.create_task(
            insert_diary(content, user_id, word_count)
        )

        line_bot_api.reply_message(
            event.reply_token,
            [
                TextSendMessage(text="✅ 智能體已經把主人餵的資料通通吃光光，現在進化中！"),
                TextSendMessage(text="✅ 自動部署測試成功！")
            ]
        )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="🚧 功能開發中 ")
        )