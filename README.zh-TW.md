[English](./README.md) | 繁體中文
 
# G-Bot
 
> 一個部署於雲端、持續營運中的 LINE Bot 平台。整合 LLM 對話、即時資訊查詢、任務排程與主動推播，採分層架構設計，具備健康檢查與效能監控端點。
 
**Stack:** Python 3.11 · FastAPI · PostgreSQL · SQLAlchemy · APScheduler · Docker · Google Gemini · LINE Messaging API
 
---
 
## 為什麼做這個
 
一般 LINE Bot 多半是「收到訊息 → 回一句話」的單層腳本，功能一多就難以維護。G-Bot 的目標是把它做成一個**可擴充的服務平台**：
 
- **模組化查詢** — 天氣、新聞、餐廳、地震等外部服務都是可獨立抽換的模組，新增一種查詢不需要動到核心邏輯
- **可替換的 Bot 人格** — system prompt 以 profile 資料夾管理，換一個環境變數就能部署成完全不同用途的 bot
- **主動推播而非被動回應** — 以 APScheduler 支援使用者自訂提醒與地震即時監控
- **可維運** — 提供 `/health` 與 `/metrics` 端點，部署後能實際監控服務與資料庫狀態
---
 
## 系統架構
 
```mermaid
flowchart TB
    LINE["LINE Platform"]
 
    subgraph APP["FastAPI Application"]
        direction TB
        MAIN["main.py<br/>lifecycle · routes"]
        HANDLERS["handlers/<br/>事件與指令解析"]
        SERVICES["services/<br/>業務流程"]
        REPOS["repositories/<br/>資料存取層"]
    end
 
    subgraph ENGINES["處理引擎"]
        GEMINI["gemini_engine<br/>對話與上下文"]
        SEARCH["realtime_search<br/>查詢路由"]
        SCHED["APScheduler<br/>提醒 · 地震監控"]
    end
 
    subgraph MODULES["search_modules/"]
        WEATHER["天氣 CWA"]
        MAPS["Google Maps"]
        TAVILY["Tavily 搜尋"]
        NBA["NBA"]
    end
 
    PROMPTS["prompts/profile/<br/>可替換 system prompt"]
    DB[("PostgreSQL<br/>對話紀錄 · 設定 · 排程")]
    OPS["/health · /metrics"]
 
    LINE -->|"webhook /callback"| MAIN
    MAIN --> HANDLERS
    HANDLERS --> SERVICES
    SERVICES --> GEMINI
    SERVICES --> SEARCH
    SERVICES --> REPOS
    SEARCH --> MODULES
    PROMPTS -.設定注入.-> GEMINI
    SCHED --> SERVICES
    REPOS --> DB
    SCHED -->|"主動推播"| LINE
    MAIN --> OPS
    GEMINI -->|"回覆"| LINE
```
 
### 分層設計
 
| 層級 | 責任 | 為什麼這樣切 |
|---|---|---|
| `handlers/` | 解析 LINE 事件與指令 | 隔離 LINE SDK，換通訊平台時只改這層 |
| `services/` | 業務流程編排 | 核心邏輯不依賴框架與資料庫實作 |
| `repositories/` | 資料存取 | 集中資料庫操作，方便測試與替換儲存後端 |
| `search_modules/` | 外部 API 封裝 | 每個外部服務獨立，失效不影響其他功能 |
| `prompts/` | Bot 行為定義 | 以檔案而非硬編碼管理 prompt，可版本控管 |
 
---
 
## 特別的實作
 
**群組對話記憶**
在群組中以群組 ID 保存共同記憶，並將每則訊息記錄為 `使用者名稱：訊息內容`，讓 LLM 讀取歷史時能正確區分發言者，避免多人對話被混為一談。
 
**可抽換的 Prompt Profile**
`SYSTEM_PROMPT_PROFILE` 環境變數指向 `app/prompts/<profile>/`，內含 `conversation.txt`（對話人格）與 `realtime.txt`（即時查詢回答規則）。新增一個資料夾即可衍生出用途完全不同的 bot，不需修改任何程式碼。
 
**服務可觀測性**
`/health` 檢查服務與資料庫連線狀態；`/metrics` 提供效能指標，並以 `METRICS_TOKEN` 保護，未設定時回傳 404。
 
---
 
## 功能
 
- LINE 文字訊息與位置訊息處理
- Gemini AI 對話與對話紀錄
- Tavily 即時搜尋與新聞查詢
- 天氣、NBA、時間查詢
- Google Maps 餐廳推薦
- 每日或一次性提醒
- 地震監控與推播
- 回覆模式控制：安靜、說話、標記、都回
- 群組對話會記錄發言者名稱，避免不同成員的訊息被混在一起
- `/health` 健康檢查與 `/metrics` 效能指標
## 技術架構
 
- Python 3.11
- FastAPI + Uvicorn
- LINE Messaging API
- Google Gemini API
- PostgreSQL
- SQLAlchemy
- APScheduler
- Docker
## 文件索引
 
- [Railway 部署指南](./Railyway.md)
## 專案結構
 
```
app/
├── main.py                    # FastAPI 入口、生命週期與 API route
├── config.py                  # 環境變數與設定驗證
├── database.py                # SQLAlchemy engine、session、資料表初始化
├── line_bot.py                # LINE webhook 事件註冊
├── gemini_engine.py           # Gemini 對話與上下文處理
├── realtime_search.py         # 即時查詢路由
├── earthquake.py              # 地震資料查詢與通知
├── schedule_notification.py   # APScheduler 提醒與背景任務
├── handlers/                  # LINE 事件與指令處理
├── services/                  # 對話、即時查詢、餐廳推薦等業務流程
├── models/                    # SQLAlchemy models
├── repositories/              # 資料庫存取層
├── prompts/                   # 可替換的 bot system prompt 文字模板
├── search_modules/            # 天氣、NBA、Tavily、Google Maps 等查詢模組
├── utils/                     # logger、cache、decorators、LINE 工具
└── views/                     # LINE quick reply / menu 建立
```
 
## Bot Prompt
 
System prompt 放在 `app/prompts/<profile>/`，預設 profile 是 `gbot`。
 
```
app/prompts/gbot/
├── conversation.txt   # 一般對話人格與限制
└── realtime.txt       # 即時查詢回答規則
```
 
如果要開發另一個 bot，可以新增一個資料夾，例如 `app/prompts/support_bot/`，放入同名的 `conversation.txt` 與 `realtime.txt`，再設定：
 
```
SYSTEM_PROMPT_PROFILE=support_bot
```
 
---
 
## 本地開發
 
### 需求
 
- Python 3.11+
- PostgreSQL
- LINE Developers Channel
- Google AI Studio API key
### 安裝
 
```bash
pip install -r requirements.txt
```
 
### 設定環境變數
 
建立 `.env`，可從 `.env.example` 複製後修改。
 
```
LINE_CHANNEL_ACCESS_TOKEN=your_line_channel_access_token
LINE_CHANNEL_SECRET=your_line_channel_secret
GEMINI_API_KEY=your_gemini_api_key
DATABASE_URL=postgresql://username:password@localhost:5432/gbot_db
```
 
完整變數請看下方「環境變數」。
 
### 啟動
 
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8787 --reload
```
 
健康檢查：
 
```bash
curl http://localhost:8787/health
```
 
### LINE Developers 設定
 
1. 開啟 LINE Developers Console。
2. 進入你的 Messaging API Channel。
3. 將 Webhook URL 設為部署服務的公開 HTTPS domain 加 `/callback`。
4. 開啟 Use webhook。
5. 按 Verify 確認 LINE 可以連到服務。
6. 對 Bot 傳送訊息測試。
---
 
## 群組對話記憶
 
在一對一聊天中，G-Bot 會用使用者 ID 保存對話記憶。
 
在群組或聊天室中，G-Bot 會用群組 ID 保存共同對話記憶，並把使用者訊息記錄成：
 
```
使用者名稱：訊息內容
```
 
這樣 Gemini 在讀取歷史訊息時可以分辨不同群組成員，不會把不同人的發言當成同一個人。
 
## 特級使用者
 
如果不知道 LINE sender ID，可以用 `PRIORITY_MENTION_NAMES` 設定特級使用者名稱：
 
```
PRIORITY_MENTION_NAMES=王小明,陳小美
```
 
G-Bot 會用 LINE 顯示名稱比對這份清單。命中時，AI 會用更禮貌、尊重、客氣的語氣回覆，但仍維持自然口語。
 
名稱比對會忽略大小寫與空白，但仍建議使用和 LINE 顯示名稱一致的文字。
 
---
 
## API 端點
 
| Method | Path | 說明 |
|---|---|---|
| GET | `/` | 基本服務狀態 |
| GET | `/health` | 健康檢查，包含資料庫連線 |
| GET | `/metrics` | 效能指標 |
| POST | `/callback` | LINE webhook |
 
## 環境變數
 
### 必要
 
| 變數 | 說明 |
|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot 存取權杖 |
| `LINE_CHANNEL_SECRET` | LINE Bot Channel Secret |
| `GEMINI_API_KEY` | Google Gemini API key |
| `DATABASE_URL` | PostgreSQL 連線字串 |
 
### 資料庫
 
| 變數 | 預設值 | 說明 |
|---|---|---|
| `DB_POOL_SIZE` | 2 | PostgreSQL 連線池大小 |
| `DB_MAX_OVERFLOW` | 3 | 連線池額外允許連線數 |
| `DB_POOL_TIMEOUT` | 30 | 取得資料庫連線的逾時秒數 |
| `DB_POOL_RECYCLE` | 3600 | 連線回收秒數 |
 
### AI
 
| 變數 | 預設值 | 說明 |
|---|---|---|
| `GEMINI_MODEL` | gemma-4-26b-a4b-it | Gemini 模型名稱 |
| `GEMINI_TEMPERATURE` | 0.7 | 回覆溫度 |
| `GEMINI_MAX_TOKENS` | 2048 | 最大輸出 token |
| `SYSTEM_PROMPT_PROFILE` | gbot | 使用 `app/prompts/<profile>/` 中的 prompt 模板 |
 
### LINE Bot
 
| 變數 | 預設值 | 說明 |
|---|---|---|
| `MENTION_KEYWORDS` | @G-bot | 標記模式使用的關鍵字，逗號分隔 |
| `ADMIN_USERS` | 空值 | 管理員 LINE user ID，逗號分隔 |
| `PRIORITY_MENTION_NAMES` | 空值 | 特級使用者的 LINE 顯示名稱，逗號分隔；命中時 AI 會更禮貌回覆 |
| `ENABLE_LOADING_ANIMATION` | true | 是否顯示 LINE loading 動畫 |
| `LINE_LOADING_SECONDS` | 20 | loading 動畫秒數 |
 
### 外部服務
 
| 變數 | 說明 |
|---|---|
| `CWA_API_KEY` | 中央氣象署 API key，用於天氣與地震 |
| `GOOGLE_MAPS_API_KEY` | Google Maps API key，用於餐廳推薦 |
| `WEATHER_API_KEY` | 天氣 API key |
| `TAVILY_API_KEY` | Tavily API key，用於即時搜尋 |
 
### 搜尋與快取
 
| 變數 | 預設值 | 說明 |
|---|---|---|
| `TAVILY_SEARCH_MAX_RESULTS` | 5 | Tavily 搜尋結果數 |
| `TAVILY_SEARCH_DEPTH` | basic | Tavily 搜尋深度 |
| `TAVILY_SEARCH_TOPIC` | general | Tavily 搜尋主題 |
| `TAVILY_INCLUDE_ANSWER` | true | 是否包含 Tavily 摘要答案 |
| `TAVILY_CACHE_TTL` | 600 | 搜尋快取秒數 |
 
### 餐廳推薦
 
| 變數 | 預設值 | 說明 |
|---|---|---|
| `DEFAULT_SEARCH_RADIUS` | 1500 | 預設搜尋半徑（公尺） |
| `NEAR_RADIUS` | 500 | 「附近」搜尋半徑 |
| `FAR_RADIUS` | 2500 | 「遠一點」搜尋半徑 |
 
### 地震通知
 
| 變數 | 預設值 | 說明 |
|---|---|---|
| `EARTHQUAKE_CHECK_INTERVAL` | 20 | 地震檢查間隔（秒） |
| `EARTHQUAKE_MIN_MAGNITUDE` | 4.0 | 預設推播最低規模 |
| `EARTHQUAKE_MAX_LATENCY` | 900 | 地震資料最大延遲秒數 |
 
### 系統
 
| 變數 | 預設值 | 說明 |
|---|---|---|
| `PORT` | 8787 | 本地或容器服務端口 |
| `LOG_LEVEL` | INFO | 日誌等級 |
| `CORS_ALLOW_ORIGINS` | 空值 | 允許的 CORS origins，逗號分隔 |
| `METRICS_TOKEN` | 空值 | `/metrics` 存取權杖；未設定時 `/metrics` 會回傳 404 |
 
---
 
## Docker
 
建立 image：
 
```bash
docker build -t g-bot .
```
 
啟動容器：
 
```bash
docker run -d \
  --name g-bot \
  -p 8787:8787 \
  --env-file .env \
  g-bot
```
 
---
 
## 常用指令
 
### Bot 控制
 
| 指令 | 說明 |
|---|---|
| `#安靜` | 停止主動回覆 |
| `#說話` | 恢復回覆 |
| `#標記` | 只在被標記時回覆 |
| `#都回` | 所有訊息都回覆 |
| `#狀態` | 查看目前狀態 |
| `#功能` | 查看功能列表 |
| `#清除` | 清除對話紀錄 |
| `我的設定` | 查看個人設定 |
 
### 提醒
 
```
提醒我 開會 14:30
提醒我 喝水 09:00 每天
取消提醒 1
```
 
### 地震通知
 
```
地震通知開
地震通知關
地震門檻 4.5
```
 
### 即時查詢
 
```
台北天氣
NBA戰績
查一下 台灣最新新聞
附近餐廳
```
 
---
 
## 維護建議
 
- 外部 API key 不要提交到 Git。
- 更新環境變數後重新部署。
- 大改資料表結構前先備份 PostgreSQL。
- 若未來多人使用，建議導入正式 migration 工具，例如 Alembic。
## 授權
 
MIT