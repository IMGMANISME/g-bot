# Railway 部署指南

這份文件說明如何將 G-Bot 部署到 Railway，並連接 Railway PostgreSQL 與 LINE Developers webhook。

## 專案內建設定

這個專案已包含 Railway 需要的設定：

- `Dockerfile`：使用 Railway 注入的 `PORT` 啟動 Uvicorn
- `railway.json`：設定 `/health` 健康檢查與失敗重啟策略

## 部署步驟

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

## PostgreSQL 設定

Railway 的 `DATABASE_URL` 不可以是 `localhost`。Web Service 和 PostgreSQL 是不同服務，請在 Web Service 的 Variables 中引用 Railway PostgreSQL 提供的連線字串，例如：

```text
${{Postgres.DATABASE_URL}}
```

也可以直接貼上 PostgreSQL 服務提供的完整 `DATABASE_URL`。

## LINE Developers 設定

1. 開啟 LINE Developers Console。
2. 進入你的 Messaging API Channel。
3. 將 Webhook URL 設為 Railway domain 加 `/callback`。
4. 開啟 `Use webhook`。
5. 按 Verify 確認 LINE 可以連到服務。
6. 對 Bot 傳送訊息測試。

## 注意事項

- 只跑一個 Web Service instance，避免 APScheduler 造成提醒或地震通知重複推播。
- 不要把 `.env.example` 當 production `.env` 使用。
- 如果健康檢查失敗，先看 `DATABASE_URL`、LINE token、Gemini key 是否設定完整。
- Railway 會提供 `PORT`，不需要手動固定成 `8787`。

## 疑難排解

### 顯示 `localhost:5432 connection refused`

代表 Web Service 正在用 localhost 連 PostgreSQL。請到 Railway Web Service 的 Variables 檢查 `DATABASE_URL`，改成 Railway PostgreSQL 提供的連線字串。

### `/health` 回 503

通常是資料庫無法連線。先檢查：

- `DATABASE_URL` 是否存在
- PostgreSQL 服務是否啟動
- Web Service 是否引用到正確的 PostgreSQL 變數

### LINE Verify 失敗

先確認：

- Webhook URL 是否為 `https://.../callback`
- 部署 domain 是否可以開啟 `/health`
- `LINE_CHANNEL_SECRET` 是否正確
- 部署 log 是否有啟動錯誤

### Bot 收到訊息但沒有回覆

檢查：

- `LINE_CHANNEL_ACCESS_TOKEN`
- `GEMINI_API_KEY`
- 部署 log 裡的 webhook 錯誤
- LINE Developers 是否開啟 `Use webhook`
