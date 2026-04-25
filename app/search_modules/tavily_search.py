# app/search_modules/tavily_search.py
import logging
from typing import Any

import requests

from app.config import config

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


def _normalize_search_item(item: dict[str, Any]) -> dict[str, str]:
    score = item.get("score")
    score_text = f"{score:.2f}" if isinstance(score, (int, float)) else "N/A"

    return {
        "title": item.get("title") or "無標題",
        "url": item.get("url") or "",
        "content": item.get("content") or "無摘要",
        "score": score_text,
    }


def get_tavily_search_results(query: str, limit: int | None = None) -> str:
    """Search the web with Tavily and return source-grounded text for the model."""
    query = (query or "").strip()
    if not query:
        return "查詢內容是空的，無法搜尋。"

    if not config.TAVILY_API_KEY:
        return "Tavily Search 尚未設定，請設定 TAVILY_API_KEY。"

    max_results = limit or config.TAVILY_SEARCH_MAX_RESULTS
    max_results = max(1, min(max_results, 20))

    payload = {
        "query": query,
        "topic": config.TAVILY_SEARCH_TOPIC,
        "search_depth": config.TAVILY_SEARCH_DEPTH,
        "max_results": max_results,
        "include_answer": config.TAVILY_INCLUDE_ANSWER,
        "include_raw_content": False,
    }
    headers = {
        "Authorization": f"Bearer {config.TAVILY_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(TAVILY_SEARCH_URL, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else "unknown"
        logger.error("Tavily Search HTTP error: %s", e)
        return f"Tavily 搜尋失敗，HTTP 狀態碼：{status_code}。"
    except requests.exceptions.RequestException as e:
        logger.error("Tavily Search request error: %s", e)
        return "Tavily 搜尋請求失敗，請稍後再試。"
    except ValueError as e:
        logger.error("Tavily Search JSON parse error: %s", e)
        return "Tavily 搜尋回傳格式錯誤，請稍後再試。"

    results = data.get("results") or []
    if not results:
        return f"查無「{query}」的 Tavily 搜尋結果。"

    lines = [f"Tavily 搜尋查詢：{data.get('query') or query}"]

    answer = data.get("answer")
    if answer:
        lines.append(f"搜尋摘要：{answer}")

    response_time = data.get("response_time")
    if response_time:
        lines.append(f"搜尋耗時：{response_time} 秒")

    usage = data.get("usage") or {}
    credits = usage.get("credits")
    if credits is not None:
        lines.append(f"使用額度：{credits} credit")

    for index, item in enumerate(results[:max_results], start=1):
        result = _normalize_search_item(item)
        lines.append(
            "\n".join([
                f"來源 {index}",
                f"標題：{result['title']}",
                f"摘要：{result['content']}",
                f"相關分數：{result['score']}",
                f"網址：{result['url']}",
            ])
        )

    return "\n\n".join(lines)
