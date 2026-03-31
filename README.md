# G-Bot 2.0 - 智能 LINE 聊天機器人

[![Deploy Status](https://img.shields.io/badge/deploy-zeabur-blue)](https://zeabur.com)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## 📋 專案概述

G-Bot 是一個功能豐富的 LINE 聊天機器人，整合了 Google Gemini AI、即時資訊查詢、餐廳推薦、提醒功能等多項服務。支援部署到 Zeabur 雲端平台，提供穩定可靠的服務。

## ✨ 主要功能

### 🤖 AI 對話
- 基於 Google Gemini AI (gemma-3-27b-it) 的智能對話
- 支援繁體中文回應
- 對話歷史記錄與上下文理解
- 智能溫度控制與回應調整

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
- **#都回**：恢復所有回應
- **#狀態**：查看當前狀態
- **#功能**：查看功能列表
- **#清除**：清除對話歷史

### 🔍 其他功能
- 地震監控與通知（每30秒檢查，4.0級以上地震）
- 排程通知系統
- 效能監控與指標收集
- 速率限制保護（30次/分鐘）
- 錯誤處理與自動重試機制
- **Loading 動畫**：處理長時間請求時顯示「正在輸入」指示器

## 🚀 快速開始

### 前置需求
- Python 3.11+
- PostgreSQL 資料庫
- LINE Developer Account
- Google AI Studio API Key

### 本地開發安裝

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
創建 `.env` 檔案並設定以下環境變數：
```env
LINE_CHANNEL_ACCESS_TOKEN=your_line_channel_access_token
LINE_CHANNEL_SECRET=your_line_channel_secret
GEMINI_API_KEY=your_gemini_api_key
DATABASE_URL=postgresql://username:password@localhost:5432/gbot_db
GOOGLE_MAPS_API_KEY=your_google_maps_api_key
WEATHER_API_KEY=your_weather_api_key
MENTION_KEYWORDS=@G-bot
ENABLE_LOADING_ANIMATION=true
DEFAULT_LOADING_DURATION=5
MAX_LOADING_DURATION=20
```

4. **資料庫設定**
確保 PostgreSQL 資料庫正在運行，並在 `.env` 中設定正確的 `DATABASE_URL`。

5. **啟動應用程式**
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8787 --reload
```

### Zeabur 雲端部署

1. **推送代碼到 GitHub**
2. **登入 [Zeabur](https://zeabur.com)**
3. **建立新專案並連接 GitHub 倉庫**
4. **設定環境變數**
5. **部署完成，機器人即可運行**

### Docker 部署

```bash
# 建立映像檔
docker build -t g-bot .

# 啟動容器
docker run -d \
  --name g-bot \
  -p 8787:8787 \
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
| `ENABLE_LOADING_ANIMATION` | 可選 | 啟用 Loading 動畫（預設：true） |
| `DEFAULT_LOADING_DURATION` | 可選 | 預設 Loading 持續時間（秒，預設：5，最少5秒） |
| `MAX_LOADING_DURATION` | 可選 | 最大 Loading 持續時間（秒，預設：20，最多60秒） |

## 🏗️ 專案架構

```
app/
├── main.py                 # FastAPI 主應用程式
├── database.py             # 資料庫連線與 Session 管理
├── config.py               # 配置管理
├── line_bot.py             # LINE Bot Webhook 進入點
├── gemini_engine.py        # Gemini AI 整合與動態摘要記憶
├── realtime_search.py      # 即時資訊查詢
├── earthquake.py           # 地震監控
├── schedule_notification.py # APScheduler 背景排程
├── models/                 # 資料庫實體模型
│   ├── base.py
│   ├── user.py
│   ├── message.py
│   ├── restaurant.py
│   └── notification.py
├── repositories/           # 資料庫存取層 Repository
│   ├── user_repository.py
│   ├── message_repository.py
│   ├── restaurant_repository.py
│   └── notification_repository.py
├── handlers/               
│   ├── command_handler.py  # 文字命令處理器 (Command Pattern)
│   └── events/             # 事件處理器 (Event Route)
│       ├── message_event.py
│       └── location_event.py
├── views/                  # UI 元件建置
│   └── line_menus.py       # 快速回覆選單生成
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
- **速率限制**：防止 API 濫用（30次/分鐘）
- **效能監控**：即時效能指標追蹤
- **裝飾器錯誤處理**：修復函數參數傳遞問題
- **Loading 動畫**：智能顯示處理狀態，提升用戶體驗

### 程式碼品質
- **模組化設計**：清晰的程式碼結構與分層
- **類型提示**：完整的 Python 類型註解
- **日誌系統**：結構化日誌記錄
- **配置管理**：集中化的設定管理
- **裝飾器模式**：可重用的功能裝飾器
- **錯誤復原**：自動錯誤恢復機制

### 安全性
- **輸入驗證**：嚴格的使用者輸入驗證
- **API 金鑰保護**：環境變數安全管理
- **速率限制**：防止濫用攻擊

## 🔍 API 端點

- `GET /` - 基本健康檢查
- `GET /health` - 詳細健康狀態
- `GET /metrics` - 效能指標
- `POST /callback` - LINE Bot webhook

**預設運行端口：8787**

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

### 錯誤處理
- 使用 `@handle_exceptions` 裝飾器處理錯誤
- 函數定義時使用 `*args, **kwargs` 以避免參數衝突
- 檢查日誌文件以診斷問題

## 🐛 常見問題解決

### 函數參數錯誤
如果遇到 "takes 1 positional argument but 2 were given" 錯誤：
1. 檢查函數是否使用了 `@handle_exceptions` 裝飾器
2. 將函數參數改為 `*args, **kwargs`
3. 從 `args[0]` 提取實際參數

### 部署問題
- 確保所有環境變數正確設定
- 檢查資料庫連線是否正常
- 驗證 API 金鑰有效性

## 📝 更新日誌

### v2.1.0 (2026-03-31)
- 🏗️ **架構重構**：導入 Clean Architecture，拆分 `models` 與 `repositories`
- 🧠 **AI 升級**：導入動態摘要記憶機制，取代字元數硬截斷，實現無限對話上下文
- ⏰ **排程升級**：導入 `APScheduler` 取代 `asyncio.sleep`，提升背景任務穩定性
- 🧩 **模組化**：徹底解耦 `line_bot.py`，分為 Views 與 Message/Location 事件處理器

### v2.0.2 (2025-08-13)
- ✨ **新功能**：添加 Loading 動畫功能
- 🎯 **改進**：AI 對話、餐廳搜尋、即時查詢顯示「正在輸入」指示器
- ⚙️ **配置**：支援 Loading 動畫開關與時長設定
- 📚 **文檔**：更新功能說明與環境變數配置

### v2.0.1 (2025-08-13)
- 🐛 **修復**：解決裝飾器函數參數傳遞錯誤
- 🔧 **改進**：優化錯誤處理機制
- 📚 **文檔**：更新 README.md 與部署指南
- 🚀 **部署**：支援 Zeabur 雲端平台部署

### v2.0.0
- 🎉 **新功能**：完整重構，採用 FastAPI 框架
- 🤖 **AI升級**：整合 Google Gemini AI
- 📍 **定位服務**：餐廳推薦與地理位置功能
- ⏰ **提醒系統**：智能提醒與排程功能
- 🔍 **即時查詢**：新聞、天氣、NBA 等即時資訊
- 🏗️ **架構優化**：模組化設計與效能提升

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

## 📊 部署狀態

- **生產環境**：部署於 Zeabur 雲端平台
- **監控**：24/7 服務監控
- **備份**：定期資料庫備份
- **更新**：自動部署 CI/CD

---

**G-Bot 2.0** - 讓你的 LINE 群組更智能、更有趣！ 🚀
