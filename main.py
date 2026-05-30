from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from dotenv import load_dotenv
from json_repair import repair_json
import os
import httpx
import json
import asyncio
import logging
import voyageai

load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY")

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

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

async def rag_query_and_reply(question: str, user_id: str, reply_token: str):
    try:
        # 第一步：把問題轉成向量
        voyage_client = voyageai.Client(api_key=VOYAGE_API_KEY)
        result = voyage_client.embed([question], model="voyage-3-lite")
        query_embedding = result.embeddings[0]

        # 第二步：搜尋相關日記
        async with httpx.AsyncClient() as client:
            search_res = await client.post(
                f"{SUPABASE_URL}/rest/v1/rpc/match_diaries",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "query_embedding": query_embedding,
                    "match_count": 5
                },
                timeout=15.0
            )
            search_res.raise_for_status()
            matches = search_res.json()
            print(f"找到 {len(matches)} 筆相關日記")

            if not matches:
                line_bot_api.reply_message(
                    reply_token,
                    TextSendMessage(text="還沒有足夠的日記資料來回答這個問題 🤔")
                )
                return

            # 第三步：組合日記內容
            diary_context = "\n\n".join([
                f"日記（{m.get('diary_date', '日期不明')}）：{m['content']}"
                for m in matches
            ])

            # 第四步：呼叫 Claude 回答
            claude_res = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "claude-sonnet-4-5",
                    "max_tokens": 500,
                    "messages": [{
                        "role": "user",
                        "content": f"""你是一個幫助用戶回顧日記的助手。根據以下日記內容回答用戶的問題，用溫暖親切的語氣，回答盡量簡短。

日記內容：
{diary_context}

用戶問題：{question}"""
                    }]
                },
                timeout=30.0
            )
            claude_res.raise_for_status()
            answer = claude_res.json()["content"][0]["text"]

            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text=answer)
            )

    except Exception as e:
        print(f"RAG 查詢失敗: {e}")
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text="查詢日記時發生錯誤，請稍後再試 🙏")
        )


async def insert_diary_and_parse(content: str, user_id: str, word_count: int):
    diary_id = None
    try:
        async with httpx.AsyncClient() as client:

            # 第一步：插入原始日記
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
                },
                timeout=10.0
            )
            response.raise_for_status()
            diary_id = response.json()[0]["id"]
            print(f"日記已儲存 - ID: {diary_id}")

            # 第二步：呼叫 Claude API
            claude_response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "claude-sonnet-4-5",
                    "max_tokens": 350,
                    "messages": [{
                        "role": "user",
                        "content": f"""你是一位專業日記分析助手。請嚴格只回傳純JSON，不要有任何其他文字、解釋或markdown。

{{
  "diary_date": "YYYY-MM-DD 或 null",
  "location": "地點或 null",
  "people": "人物用逗號分隔或 null",
  "emotion": "開心/難過/平靜/興奮/焦慮/憤怒/感恩/其他",
  "keywords": "3-5個關鍵詞用逗號分隔",
  "summary": "20字以內摘要"
}}

日記內容：
{content}"""
                    }]
                },
                timeout=30.0
            )
            claude_response.raise_for_status()
            parsed_text = claude_response.json()["content"][0]["text"]

            # 第三步：解析 JSON
            cleaned_text = parsed_text.strip()
            if cleaned_text.startswith("```"):
                cleaned_text = cleaned_text.split("```")[1]
                if cleaned_text.startswith("json"):
                    cleaned_text = cleaned_text[4:].strip()
            parsed = repair_json(cleaned_text)
            parsed = json.loads(parsed) if isinstance(parsed, str) else parsed

            # 第四步：插入摘要
            summary_res = await client.post(
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
                },
                timeout=10.0
            )
            print(f"摘要插入: {summary_res.status_code}")

            # 第五步：更新 is_processed
            await client.patch(
                f"{SUPABASE_URL}/rest/v1/diaries?id=eq.{diary_id}",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json"
                },
                json={"is_processed": True},
                timeout=10.0
            )
            print(f"日記處理完成 - ID: {diary_id}")

            # 第六步：產生向量嵌入
            voyage_client = voyageai.Client(api_key=VOYAGE_API_KEY)
            result = voyage_client.embed([content], model="voyage-3-lite")
            embedding = result.embeddings[0]
            print(f"embedding type: {type(embedding)}, length: {len(embedding)}, sample: {embedding[:3]}")

            await client.post(
                f"{SUPABASE_URL}/rest/v1/diary_embeddings",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal"
                },
                json={
                    "diary_id": diary_id,
                    "embedding": embedding
                },
                timeout=10.0
            )
            print(f"向量嵌入完成 - ID: {diary_id}")


    except Exception as e:
        print(f"處理日記失敗 - diary_id: {diary_id}, error: {e}")



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

        asyncio.create_task(
            insert_diary_and_parse(content, user_id, word_count)
        )

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="✅ 日記已收到，AI 正在解析中...")
        )
    else:
        # line_bot_api.reply_message(
        #     event.reply_token,
        #     TextSendMessage(text="🚧 功能開發中")
        # )
        # 啟動 RAG 問答
        asyncio.create_task(
            rag_query_and_reply(user_message, user_id, event.reply_token)
        )