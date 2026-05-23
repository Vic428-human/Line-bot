from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from supabase import create_client
from dotenv import load_dotenv
import anthropic
import os

# 載入 .env 的金鑰
load_dotenv()

# 初始化
app = FastAPI()
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

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

# 解析日記摘要
def parse_diary(content: str) -> dict:
    message = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": f"""請分析以下日記內容，並以 JSON 格式回傳以下欄位：
- diary_date: 日記描述的日期（格式 YYYY-MM-DD，如無法判斷則填 null）
- location: 地點（如無則填 null）
- people: 提到的人物，用逗號分隔（如無則填 null）
- emotion: 主要情緒，從以下選一個：開心、難過、平靜、興奮、焦慮、憤怒、感恩、其他
- keywords: 3-5個關鍵詞，用逗號分隔
- summary: 一句話摘要（20字以內）

只回傳 JSON，不要其他文字。

日記內容：
{content}"""
        }]
    )

    import json
    result = json.loads(message.content[0].text)
    return result

# 收到文字訊息時
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    user_id = event.source.user_id

    # 判斷是否為日記指令
    if user_message.startswith("/日記"):
        content = user_message[3:].strip()
        word_count = len(content)

        # 存原始日記
        result = supabase.table("diaries").insert({
            "content": content,
            "line_user_id": user_id,
            "word_count": word_count,
            "is_processed": False,
            "diary_date": None
        }).execute()

        diary_id = result.data[0]["id"]

        # 呼叫 Claude 解析摘要
        try:
            parsed = parse_diary(content)

            supabase.table("diary_summaries").insert({
                "diary_id": diary_id,
                "diary_date": parsed.get("diary_date"),
                "location": parsed.get("location"),
                "people": parsed.get("people"),
                "emotion": parsed.get("emotion"),
                "keywords": parsed.get("keywords"),
                "summary": parsed.get("summary")
            }).execute()

            # 更新 is_processed
            supabase.table("diaries").update({
                "is_processed": True
            }).eq("id", diary_id).execute()

            reply = f"日記已收到 ✅\n情緒：{parsed.get('emotion')}\n摘要：{parsed.get('summary')}"

        except Exception as e:
            reply = "日記已收到 ✅（摘要解析中）"

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="🚧 功能開發中")
        )