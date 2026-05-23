import json
import re
import logging
from json_repair import repair_json  # pip install json-repair

logger = logging.getLogger(__name__)

async def insert_diary_and_parse(content: str, user_id: str, word_count: int):
    diary_id = None
    try:
        async with httpx.AsyncClient() as client:
            
            # ==================== 1. 插入原始日記 ====================
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
            diary_data = response.json()[0]
            diary_id = diary_data["id"]
            
            logger.info(f"日記已儲存 - ID: {diary_id}, 字數: {word_count}")

            # ==================== 2. 呼叫 Claude API (Token 優化版) ====================
            optimized_prompt = f"""你是一位專業日記分析助手。請嚴格只回傳純JSON，不要有任何其他文字、解釋或markdown。

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

            claude_response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "claude-3-5-sonnet-20241022",   # 正確 model name
                    "max_tokens": 350,                        # 大幅降低
                    "temperature": 0.3,
                    "messages": [{
                        "role": "user",
                        "content": optimized_prompt
                    }]
                },
                timeout=30.0
            )
            claude_response.raise_for_status()
            
            claude_data = claude_response.json()
            parsed_text = claude_data["content"][0]["text"]
            
            # 記錄 Token 使用量（重要！）
            usage = claude_data.get("usage", {})
            logger.info(f"Claude Token 使用 - Input: {usage.get('input_tokens')} | "
                       f"Output: {usage.get('output_tokens')} | "
                       f"Total: {usage.get('input_tokens', 0) + usage.get('output_tokens', 0)}")

            # ==================== 3. 強健 JSON 解析 ====================
            try:
                # 先清理文字
                cleaned_text = parsed_text.strip()
                if cleaned_text.startswith("```"):
                    cleaned_text = cleaned_text.split("```")[1]
                    if cleaned_text.startswith("json"):
                        cleaned_text = cleaned_text[4:].strip()
                
                # 使用 json-repair 增強容錯
                parsed = repair_json(cleaned_text)
                parsed = json.loads(parsed) if isinstance(parsed, str) else parsed

            except Exception as e:
                logger.error(f"JSON 解析失敗 - Raw: {parsed_text[:300]}...")
                raise ValueError(f"JSON 解析失敗: {str(e)}")

            # ==================== 4. 插入摘要 ====================
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
            summary_res.raise_for_status()

            # ==================== 5. 更新處理狀態 ====================
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

            logger.info(f"日記處理完成 - ID: {diary_id}")

    except httpx.TimeoutException:
        logger.error(f"請求超時 - diary_id: {diary_id}")
        await mark_diary_as_failed(diary_id, "timeout")
    except Exception as e:
        logger.exception(f"處理日記失敗 - diary_id: {diary_id}")
        await mark_diary_as_failed(diary_id, "error", str(e))

async def mark_diary_as_failed(diary_id: str = None, reason: str = "unknown", error_msg: str = None):
    if not diary_id:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{SUPABASE_URL}/rest/v1/diaries?id=eq.{diary_id}",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "is_processed": True,
                    "process_failed": True,
                    "fail_reason": reason
                }
            )
    except:
        pass  # 避免錯誤處理函數本身出錯