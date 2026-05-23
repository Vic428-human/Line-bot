# Line Bot 專案啟用指南

> 本指南記錄從 `git clone` 到 Railway 部署的完整流程，避免下次踩同樣的坑。

---

## 📋 技術架構

| 技術 | 用途 |
|------|------|
| FastAPI | Web 框架，提供 Webhook 接收端點 |
| LINE Bot SDK | 與 LINE Messaging API 互動 |
| Supabase | PostgreSQL 資料庫（儲存日記內容） |
| python-dotenv | 讀取環境變數 |
| httpx | 直接呼叫 Supabase REST API（避免 supabase 套件依賴地獄） |
| Railway | 雲端部署平台 |

---

## 🚀 第一次啟用步驟

### 1. Clone 專案

```bash
git clone https://github.com/Vic428-human/Line-bot.git
cd Line-bot
```

### 2. 安裝 Python

確認系統已安裝 Python 3.8+：

```bash
python --version
# 或
python3 --version
```

**沒有安裝的話：**
- **macOS**: `brew install python` 或 [官網下載](https://www.python.org/downloads/macos/)
- **Windows**: [官網下載](https://www.python.org/downloads/)，**務必勾選「Add Python to PATH」**
- **Linux**: `sudo apt install python3 python3-venv python3-pip`

### 3. 建立虛擬環境

```bash
python -m venv venv
```

> 執行成功時**不會有任何輸出**，這是正常的。

### 4. 啟動虛擬環境

| 終端機 | 指令 |
|--------|------|
| **macOS / Linux** | `source venv/bin/activate` |
| **Windows cmd** | `venv\Scripts\activate.bat` |
| **Windows PowerShell** | `venv\Scripts\Activate.ps1` |
| **Git Bash** | `source venv/Scripts/activate` |

成功後提示字元前面會出現 `(venv)`：
```
(venv) user@mac Line-bot %
```

### 5. 安裝依賴套件

```bash
pip install fastapi uvicorn line-bot-sdk python-dotenv httpx
```

> ⚠️ **不要使用 `supabase` 套件！** 它會帶入 `pyiceberg` 等重型依賴，在 Windows 需要 Microsoft C++ Build Tools 才能編譯，極容易出錯。改用 `httpx` 直接呼叫 Supabase REST API。

### 6. 設定環境變數

在專案根目錄建立 `.env` 檔案：

```bash
touch .env
```

填入以下內容：

```env
LINE_CHANNEL_ACCESS_TOKEN=你的_LINE_Channel_Access_Token
LINE_CHANNEL_SECRET=你的_LINE_Channel_Secret
SUPABASE_URL=你的_Supabase_Project_URL
SUPABASE_KEY=你的_Supabase_Service_Role_Key
```

**金鑰取得位置：**

| 金鑰 | 去哪裡找 |
|------|---------|
| `LINE_CHANNEL_ACCESS_TOKEN` | [LINE Developers](https://developers.line.biz/console/) → Channel → Messaging API → Channel access token |
| `LINE_CHANNEL_SECRET` | 同一頁面 → Basic settings → Channel secret |
| `SUPABASE_URL` | [Supabase Dashboard](https://supabase.com/dashboard) → Project Settings → API → Project URL |
| `SUPABASE_KEY` | 同一頁面 → `service_role key` |

> `.env` 已加入 `.gitignore`，**絕對不要上傳到 GitHub！**

### 7. 建立 Supabase 資料表

進入 Supabase Dashboard → SQL Editor → New query，執行：

```sql
create table diaries (
  id uuid default gen_random_uuid() primary key,
  content text not null,
  line_user_id text not null,
  word_count integer not null,
  is_processed boolean default false,
  diary_date date,
  created_at timestamp with time zone default timezone('utc'::text, now())
);
```

### 8. 啟動本地伺服器

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

看到 `Uvicorn running on http://0.0.0.0:8000` 即成功。

### 9. 本地測試 Webhook（可選）

LINE 需要 HTTPS，本地開發用 ngrok：

```bash
ngrok http 8000
```

取得 `https://xxxx.ngrok-free.app` 網址，貼到 LINE Developers → Webhook URL：
```
https://xxxx.ngrok-free.app/webhook
```

---

## 🚂 Railway 部署

### 部署方式

**推薦：GitHub 自動部署**

1. [Railway Dashboard](https://railway.app/dashboard) → `New Project` → `Deploy from GitHub repo`
2. 選擇 `Vic428-human/Line-bot`
3. Railway 自動偵測 `requirements.txt` 並部署

### 設定環境變數

Railway **不會讀取 `.env`**，必須在 Dashboard 手動設定：

Railway Dashboard → 專案 → `Variables` → `New Variable`

| 變數名稱 | 值 |
|---------|-----|
| `LINE_CHANNEL_ACCESS_TOKEN` | 你的 Token |
| `LINE_CHANNEL_SECRET` | 你的 Secret |
| `SUPABASE_URL` | 你的 Supabase URL |
| `SUPABASE_KEY` | 你的 Supabase Key |

### LINE Webhook 設定

部署成功後，Railway 會給一個網址：
```
https://line-bot-production-xxxx.up.railway.app
```

到 LINE Developers → Messaging API → Webhook URL：
```
https://line-bot-production-xxxx.up.railway.app/webhook
```

開啟 **Use webhook**

### 自動部署

GitHub 連結成功後，每次 `git push origin main` Railway 會自動重新部署，約 1-2 分鐘完成。

---

## ⚠️ 常見錯誤與解法

### 1. `python --version` 沒反應
**原因**：沒安裝 Python，或沒加入 PATH。  
**解法**：重新安裝 Python，Windows 務必勾選「Add Python to PATH」。

### 2. `python -m venv venv` 沒輸出
**原因**：這是正常的，成功時不會有輸出。  
**確認**：`ls venv/`（或 `dir venv`）看是否有 `bin/`、`lib/` 資料夾。

### 3. `source venv/Scripts/activate` 報錯
**原因**：Git Bash 路徑要用 `/` 而不是 `\`。  
**正確指令**：`source venv/Scripts/activate`

### 4. `pip install supabase` 失敗，出現 `Microsoft Visual C++ 14.0 is required`
**原因**：`supabase` 套件依賴 `pyiceberg`，需要 C 編譯器。  
**解法**：**不要裝 `supabase` 套件**，改用 `httpx` 直接呼叫 REST API（見下方程式碼）。

### 5. LINE Bot 已讀不回
**排查步驟**：
1. 檢查 Railway Logs 有無紅字錯誤
2. 確認 Webhook URL 正確且已開啟 Use webhook
3. 確認 Railway Variables 四個金鑰都正確設定
4. 檢查 `reply_message` 是否只傳了一個訊息物件（或 list）


## 🔗 參考連結

- [LINE Developers Console](https://developers.line.biz/console/)
- [Supabase Dashboard](https://supabase.com/dashboard)
- [Railway Dashboard](https://railway.app/dashboard)
- [FastAPI 官方文件](https://fastapi.tiangolo.com/)
