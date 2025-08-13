# G-Bot 2.0 - 智能 LINE 聊天機器人

## 📋 專案概述

G-Bot 是一個功能豐富的 LINE 聊天機器人，整合了 Google Gemini AI、即時資訊查詢、餐廳推薦、提醒功能等多項服務。

## ✨ 主要功能

### 🤖 AI 對話
- 基於 Google Gemini AI 的智能對話
- 支援繁體中文回應
- 對話歷史記錄與上下文理解

### 📍 餐廳推薦
- 基於地理位置的餐廳推薦
- 支援價格篩選（便宜/普通/貴）
- 支援距離篩選（附近/遠一點/指定公里數）

### 📰 即時資訊查詢
- **新聞查詢**：輸入「XXX新聞」取得最新相關新聞
- **天氣查詢**：輸入「XXX天氣」取得五日天氣預報
- **NBA 資訊**：輸入「NBA戰績」或「NBA比賽」取得最新賽事資訊
- **時間查詢**：取得當前時間資訊

### ⏰ 提醒功能
- 設定每日重複提醒或一次性提醒
- 自然語言解析：「提醒我開會 14:30 每天」
- 提醒列表管理與刪除功能

### 🔧 機器人控制
- **#安靜**：啟用靜音模式
- **#說話**：恢復回應
- **#標記**：只在被標記時回覆
- **#狀態**：查看當前狀態
- **#功能**：查看功能列表
- **#清除**：清除對話歷史

### 🔍 其他功能
- 地震監控與通知
- 排程通知系統
- 效能監控

## 🚀 快速開始

### 前置需求
- Python 3.11+
- PostgreSQL 資料庫
- LINE Developer Account
- Google AI Studio API Key

### 安裝步驟

1. **克隆專案**
```bash
git clone https://github.com/IMGMANISME/G-Bot.git
cd G-Bot
```

2. **安裝依賴**
```bash
pip install -r requirements.txt
```

3. **環境設定**
```bash
cp .env.example .env
# 編輯 .env 檔案，填入必要的 API 金鑰和設定
```

4. **資料庫設定**
確保 PostgreSQL 資料庫正在運行，並在 `.env` 中設定正確的 `DATABASE_URL`。

5. **啟動應用程式**
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker 部署

```bash
# 建立映像檔
docker build -t g-bot .

# 啟動容器
docker run -d \
  --name g-bot \
  -p 8000:8000 \
  --env-file .env \
  g-bot
```

## 📝 環境變數設定

| 變數名稱 | 必要性 | 說明 |
|---------|--------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | 必要 | LINE Bot 存取權杖 |
| `LINE_CHANNEL_SECRET` | 必要 | LINE Bot 頻道密鑰 |
| `GEMINI_API_KEY` | 必要 | Google Gemini AI API 金鑰 |
| `DATABASE_URL` | 必要 | PostgreSQL 資料庫連接字串 |
| `GOOGLE_MAPS_API_KEY` | 可選 | Google Maps API 金鑰（餐廳推薦功能） |
| `WEATHER_API_KEY` | 可選 | 天氣 API 金鑰 |
| `MENTION_KEYWORDS` | 可選 | 標記關鍵字（預設：@G-bot） |

## 🏗️ 專案架構

```
app/
├── main.py                 # FastAPI 主應用程式
├── config.py              # 配置管理
├── line_bot.py            # LINE Bot 事件處理
├── gemini_engine.py       # Gemini AI 整合
├── memory.py              # 資料庫模型與操作
├── realtime_search.py     # 即時資訊查詢
├── earthquake.py          # 地震監控
├── schedule_notification.py # 通知排程
├── handlers/
│   └── command_handler.py # 命令處理器
├── search_modules/
│   ├── weather.py         # 天氣查詢
│   ├── news.py           # 新聞查詢
│   ├── nba.py            # NBA 資訊
│   ├── time.py           # 時間查詢
│   └── google_maps.py    # 地圖與餐廳查詢
└── utils/
    ├── logger.py         # 日誌系統
    ├── decorators.py     # 裝飾器工具
    ├── cache.py          # 快取系統
    └── performance.py    # 效能監控
```

## 🔧 最佳化功能

### 效能改進
- **連接池管理**：資料庫連接池最佳化
- **快取系統**：記憶體快取減少重複查詢
- **錯誤處理**：統一的例外處理與重試機制
- **速率限制**：防止 API 濫用
- **效能監控**：即時效能指標追蹤

### 程式碼品質
- **模組化設計**：清晰的程式碼結構與分層
- **類型提示**：完整的 Python 類型註解
- **日誌系統**：結構化日誌記錄
- **配置管理**：集中化的設定管理
- **裝飾器模式**：可重用的功能裝飾器

## 🔍 API 端點

- `GET /` - 基本健康檢查
- `GET /health` - 詳細健康狀態
- `GET /metrics` - 效能指標
- `POST /callback` - LINE Bot webhook

## 📊 監控與日誌

### 效能監控
訪問 `/metrics` 端點可取得：
- 系統資源使用情況
- API 回應時間統計
- 資料庫查詢效能
- 函數調用次數

### 日誌記錄
- 彩色控制台輸出
- 檔案日誌記錄
- 結構化日誌格式
- 不同等級的日誌過濾

## 🛠️ 開發指南

### 新增自定義命令
1. 在 `app/handlers/command_handler.py` 中建立新的處理器類
2. 繼承 `BaseCommandHandler`
3. 實作 `can_handle()` 和 `handle()` 方法
4. 在 `CommandProcessor` 中註冊處理器

### 新增搜尋模組
1. 在 `app/search_modules/` 中建立新模組
2. 在 `realtime_search.py` 中註冊觸發詞彙
3. 實作查詢函數並返回結果

## 🤝 貢獻指南

1. Fork 專案
2. 建立功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交變更 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 開啟 Pull Request

## 📄 授權

此專案採用 MIT 授權 - 詳見 [LICENSE](LICENSE) 檔案

## 🙋‍♂️ 支援

如有任何問題或建議，請：
1. 開啟 GitHub Issue
2. 聯繫專案維護者

---

**G-Bot 2.0** - 讓你的 LINE 群組更智能、更有趣！ 🚀
