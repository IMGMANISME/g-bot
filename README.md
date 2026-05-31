# G-Bot

G-Bot 是一個部署在 Railway 的 LINE Bot。它使用 FastAPI 接收 LINE webhook，整合 Gemini 對話、即時搜尋、天氣、NBA、餐廳推薦、提醒與地震通知。

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
- Railway

## 專案結構

```text
app/
├── main.py                  # FastAPI 入口、生命週期與 API route
├── config.py                # 環境變數與設定驗證
├── database.py              # SQLAlchemy engine、session、資料表初始化
├── line_bot.py              # LINE webhook 事件註冊
├── gemini_engine.py         # Gemini 對話與上下文處理
├── realtime_search.py       # 即時查詢路由
├── earthquake.py            # 地震資料查詢與通知
├── schedule_notification.py # APScheduler 提醒與背景任務
├── handlers/                # LINE 事件與指令處理
├── models/                  # SQLAlchemy models
├── repositories/            # 資料庫存取層
├── search_modules/          # 天氣、NBA、Tavily、Google Maps 等查詢模組
├── utils/                   # logger、cache、decorators、LINE 工具
└── views/                   # LINE quick reply / menu 建立
```

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

```env
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

## Railway 部署

這個專案已包含 Railway 需要的設定：

- `Dockerfile`：使用 Railway 注入的 `PORT` 啟動 Uvicorn
- `railway.json`：設定 `/health` 健康檢查與失敗重啟策略

### 部署步驟

1. 將程式碼推送到 GitHub。
2. 到 Railway 建立 Project。
3. 從 GitHub repo 建立 Web Service。
4. 在同一個 Project 新增 PostgreSQL 服務。
5. 到 Web Service 的 Variables 設定 `DATABASE_URL`。
6. 設定 LINE、Gemini 與其他外部 API key。
7. 等待部署完成，確認 `/health` 回傳 healthy。
8. 到 LINE Developers 設定 Webhook URL。

Webhook URL 格式：

```text
https://your-service.up.railway.app/callback
```

Railway 的 `DATABASE_URL` 不可以是 `localhost`。Web Service 和 PostgreSQL 是不同服務，請在 Web Service 的 Variables 中引用 Railway PostgreSQL 提供的連線字串，例如：

```text
${{Postgres.DATABASE_URL}}
```

也可以直接貼上 PostgreSQL 服務提供的完整 `DATABASE_URL`。

### Railway 注意事項

- 只跑一個 Web Service instance，避免 APScheduler 造成提醒或地震通知重複推播。
- 不要把 `.env.example` 當 production `.env` 使用。
- 如果健康檢查失敗，先看 `DATABASE_URL`、LINE token、Gemini key 是否設定完整。
- Railway 會提供 `PORT`，不需要手動固定成 `8787`。

## LINE Developers 設定

1. 開啟 LINE Developers Console。
2. 進入你的 Messaging API Channel。
3. 將 Webhook URL 設為 Railway domain 加 `/callback`。
4. 開啟 `Use webhook`。
5. 按 Verify 確認 LINE 可以連到服務。
6. 對 Bot 傳送訊息測試。

## 群組對話記憶

在一對一聊天中，G-Bot 會用使用者 ID 保存對話記憶。

在群組或聊天室中，G-Bot 會用群組 ID 保存共同對話記憶，並把使用者訊息記錄成：

```text
使用者名稱：訊息內容
```

這樣 Gemini 在讀取歷史訊息時可以分辨不同群組成員，不會把不同人的發言當成同一個人。

## API 端點

| Method | Path | 說明 |
|---|---|---|
| `GET` | `/` | 基本服務狀態 |
| `GET` | `/health` | 健康檢查，包含資料庫連線 |
| `GET` | `/metrics` | 效能指標 |
| `POST` | `/callback` | LINE webhook |

## 環境變數

### 必要

| 變數 | 說明 |
|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot 存取權杖 |
| `LINE_CHANNEL_SECRET` | LINE Bot Channel Secret |
| `GEMINI_API_KEY` | Google Gemini API key |
| `DATABASE_URL` | PostgreSQL 連線字串 |

### AI

| 變數 | 預設值 | 說明 |
|---|---:|---|
| `GEMINI_MODEL` | `gemma-4-26b-a4b-it` | Gemini 模型名稱 |
| `GEMINI_TEMPERATURE` | `0.7` | 回覆溫度 |
| `GEMINI_MAX_TOKENS` | `2048` | 最大輸出 token |

### LINE Bot

| 變數 | 預設值 | 說明 |
|---|---:|---|
| `MENTION_KEYWORDS` | `@G-bot` | 標記模式使用的關鍵字，逗號分隔 |
| `ADMIN_USERS` | 空值 | 管理員 LINE user ID，逗號分隔 |
| `ENABLE_LOADING_ANIMATION` | `true` | 是否顯示 LINE loading 動畫 |
| `LINE_LOADING_SECONDS` | `20` | loading 動畫秒數 |

### 外部服務

| 變數 | 說明 |
|---|---|
| `CWA_API_KEY` | 中央氣象署 API key，用於天氣與地震 |
| `GOOGLE_MAPS_API_KEY` | Google Maps API key，用於餐廳推薦 |
| `WEATHER_API_KEY` | 天氣 API key |
| `TAVILY_API_KEY` | Tavily API key，用於即時搜尋 |

### 搜尋與快取

| 變數 | 預設值 | 說明 |
|---|---:|---|
| `TAVILY_SEARCH_MAX_RESULTS` | `5` | Tavily 搜尋結果數 |
| `TAVILY_SEARCH_DEPTH` | `basic` | Tavily 搜尋深度 |
| `TAVILY_SEARCH_TOPIC` | `general` | Tavily 搜尋主題 |
| `TAVILY_INCLUDE_ANSWER` | `true` | 是否包含 Tavily 摘要答案 |
| `TAVILY_CACHE_TTL` | `600` | 搜尋快取秒數 |

### 餐廳推薦

| 變數 | 預設值 | 說明 |
|---|---:|---|
| `DEFAULT_SEARCH_RADIUS` | `1500` | 預設搜尋半徑，單位公尺 |
| `NEAR_RADIUS` | `500` | 「附近」搜尋半徑 |
| `FAR_RADIUS` | `2500` | 「遠一點」搜尋半徑 |

### 地震通知

| 變數 | 預設值 | 說明 |
|---|---:|---|
| `EARTHQUAKE_CHECK_INTERVAL` | `20` | 地震檢查間隔，單位秒 |
| `EARTHQUAKE_MIN_MAGNITUDE` | `4.0` | 預設推播最低規模 |
| `EARTHQUAKE_MAX_LATENCY` | `900` | 地震資料最大延遲秒數 |

### 系統

| 變數 | 預設值 | 說明 |
|---|---:|---|
| `PORT` | `8787` | 本地或容器服務端口；Railway 會自動注入 |
| `LOG_LEVEL` | `INFO` | 日誌等級 |
| `CORS_ALLOW_ORIGINS` | 空值 | 允許的 CORS origins，逗號分隔 |

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

```text
提醒我 開會 14:30
提醒我 喝水 09:00 每天
取消提醒 1
```

### 地震通知

```text
地震通知開
地震通知關
地震門檻 4.5
```

### 即時查詢

```text
台北天氣
NBA戰績
查一下 台灣最新新聞
附近餐廳
```

## 疑難排解

### Railway 顯示 `localhost:5432 connection refused`

代表 Web Service 正在用 localhost 連 PostgreSQL。請到 Railway Web Service 的 Variables 檢查 `DATABASE_URL`，改成 Railway PostgreSQL 提供的連線字串。

### `/health` 回 503

通常是資料庫無法連線。先檢查：

- `DATABASE_URL` 是否存在
- PostgreSQL 服務是否啟動
- Railway Web Service 是否引用到正確的 PostgreSQL 變數

### LINE Verify 失敗

先確認：

- Webhook URL 是否為 `https://.../callback`
- Railway domain 是否可以開啟 `/health`
- `LINE_CHANNEL_SECRET` 是否正確
- Railway 部署 log 是否有啟動錯誤

### Bot 收到訊息但沒有回覆

檢查：

- `LINE_CHANNEL_ACCESS_TOKEN`
- `GEMINI_API_KEY`
- Railway log 裡的 webhook 錯誤
- LINE Developers 是否開啟 `Use webhook`

## 維護建議

- Railway 上維持單一 instance。
- 外部 API key 不要提交到 Git。
- 更新環境變數後重新部署。
- 大改資料表結構前先備份 PostgreSQL。
- 若未來多人使用，建議導入正式 migration 工具，例如 Alembic。

## 授權

MIT
