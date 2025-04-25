#app/search_modules/news.py
import feedparser
import logging
from urllib.parse import quote_plus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_latest_news(keyword: str = "台灣", limit: int = 10) -> str:
    try:
        encoded_keyword = quote_plus(keyword)
        url = f"https://news.google.com/rss/search?q={encoded_keyword}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        feed = feedparser.parse(url)

        if not feed.entries:
            return f"⚠️ 查無「{keyword}」的新聞"

        messages = [f"🔍 查詢關鍵字：「{keyword}」"]

        for entry in feed.entries[:limit]:
            title = entry.get("title", "（無標題）")
            link = entry.get("link", "")
            source = (entry.get("source") or {}).get("title") or entry.get("publisher") or "未知來源"
            messages.append(f"\n📰 {title}\n📎 來源：{source}\n🔗 {link}")

        return "\n".join(messages)

    except Exception as e:
        logger.error(f"News fetch error: {e}")
        return f"⚠️ 新聞查詢失敗：{str(e)}"
