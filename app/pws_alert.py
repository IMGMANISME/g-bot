# app/pws_alert.py
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urljoin

import requests

from app.config import config
from app.utils.logger import setup_logger

logger = setup_logger("pws_alert")

LAST_PWS_ALERT_IDS: set[str] = set()


@dataclass
class PwsAlert:
    alert_id: str
    event: str
    headline: str
    description: str
    area: str
    sent_time: Optional[datetime]
    severity: str = ""
    source: str = ""


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None

    text = str(value).strip()
    if not text:
        return None

    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d,%H:%M",
        "%Y/%m/%d,%H:%M",
    ]
    normalized = text.replace("Z", "+00:00")
    for fmt in formats:
        try:
            dt = datetime.strptime(normalized, fmt)
            if dt.tzinfo:
                return dt.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
            return dt
        except ValueError:
            continue

    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo:
            return dt.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def _now_taipei() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _is_recent_alert(sent_time: Optional[datetime]) -> bool:
    if not sent_time:
        return True

    age_seconds = (_now_taipei() - sent_time).total_seconds()
    return 0 <= age_seconds <= config.PWS_ALERT_MAX_LATENCY


def _matches_pws_earthquake(text: str) -> bool:
    lowered = text.lower()
    return any(keyword and keyword in lowered for keyword in config.PWS_ALERT_KEYWORDS)


def _compact(text: Any, limit: int = 500) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value[:limit].rstrip()


def _request_payload(url: str, params: Optional[dict] = None) -> Optional[Any]:
    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "json" in content_type:
            return response.json()
        try:
            return response.json()
        except ValueError:
            return response.text
    except requests.exceptions.RequestException as e:
        logger.warning(f"PWS API 請求失敗: {e}")
    return None


def _auth_params(extra: Optional[dict] = None) -> dict:
    params = dict(extra or {})
    if config.NCDR_API_KEY:
        params.setdefault(config.NCDR_API_KEY_PARAM, config.NCDR_API_KEY)
    return params


def _iter_candidate_records(payload: Any):
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_candidate_records(item)
        return

    if not isinstance(payload, dict):
        return

    record_keys = {
        "capid", "capId", "identifier", "id", "event", "dataset",
        "headline", "description", "sent", "senderName"
    }
    if record_keys.intersection(payload.keys()):
        yield payload

    for key in ("records", "record", "data", "result", "results", "items", "value", "datastore"):
        if key in payload:
            yield from _iter_candidate_records(payload[key])


def _record_alert_id(record: dict) -> Optional[str]:
    for key in ("capid", "capId", "CAPID", "identifier", "id", "ID"):
        value = record.get(key)
        if value:
            return str(value).strip()
    return None


def _record_text(record: dict) -> str:
    parts = []
    for key in (
        "event", "dataset", "datasetName", "headline", "description",
        "senderName", "sender", "msgType", "message"
    ):
        if record.get(key):
            parts.append(str(record[key]))
    return " ".join(parts)


def _record_to_alert(record: dict) -> Optional[PwsAlert]:
    alert_id = _record_alert_id(record)
    text = _record_text(record)
    if not alert_id or not _matches_pws_earthquake(text):
        return None

    sent_time = _parse_datetime(
        record.get("sent")
        or record.get("effective")
        or record.get("onset")
        or record.get("updateTime")
        or record.get("time")
    )
    return PwsAlert(
        alert_id=alert_id,
        event=_compact(record.get("event") or record.get("dataset") or "地震速報", 80),
        headline=_compact(record.get("headline") or record.get("message") or text, 140),
        description=_compact(record.get("description") or record.get("instruction") or "", 500),
        area=_compact(record.get("areaDesc") or record.get("area") or "", 200),
        sent_time=sent_time,
        severity=_compact(record.get("severity") or "", 40),
        source=_compact(record.get("senderName") or record.get("sender") or "NCDR", 80),
    )


def _xml_text(parent: ET.Element, name: str) -> str:
    for element in parent.iter():
        if element.tag.split("}")[-1] == name and element.text:
            return element.text.strip()
    return ""


def _cap_xml_to_alert(xml_text: str, fallback_id: str) -> Optional[PwsAlert]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning(f"CAP XML 解析失敗: {e}")
        return None

    info = None
    for element in root.iter():
        if element.tag.split("}")[-1] == "info":
            info = element
            break
    info = info or root

    area_text = ""
    for element in info.iter():
        if element.tag.split("}")[-1] == "area":
            area_text = _xml_text(element, "areaDesc")
            break

    event = _xml_text(info, "event")
    headline = _xml_text(info, "headline")
    description = _xml_text(info, "description") or _xml_text(info, "instruction")
    text = " ".join([event, headline, description])
    if not _matches_pws_earthquake(text):
        return None

    alert_id = _xml_text(root, "identifier") or fallback_id
    return PwsAlert(
        alert_id=alert_id,
        event=_compact(event or "地震速報", 80),
        headline=_compact(headline or event or "地震速報", 140),
        description=_compact(description, 500),
        area=_compact(area_text, 200),
        sent_time=_parse_datetime(_xml_text(root, "sent") or _xml_text(info, "effective") or _xml_text(info, "onset")),
        severity=_compact(_xml_text(info, "severity"), 40),
        source=_compact(_xml_text(info, "senderName") or _xml_text(root, "sender") or "NCDR", 80),
    )


def _fetch_alert_detail(record: dict) -> Optional[PwsAlert]:
    alert_id = _record_alert_id(record)
    if not alert_id:
        return None

    detail_url = (
        record.get("url")
        or record.get("link")
        or record.get("href")
        or record.get("downloadUrl")
    )

    if not detail_url and config.NCDR_DUMP_URL:
        detail_url = config.NCDR_DUMP_URL

    if not detail_url:
        dump_base = urljoin(config.NCDR_API_BASE_URL.rstrip("/") + "/", "dump")
        detail_url = dump_base

    try:
        params = _auth_params({"capid": alert_id})
        response = requests.get(detail_url, params=params, timeout=5)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.debug(f"取得 CAP 詳細內容失敗，使用清單資料: {e}")
        return _record_to_alert(record)

    content_type = response.headers.get("Content-Type", "")
    if "json" in content_type:
        try:
            detail_payload = response.json()
        except ValueError:
            detail_payload = None
        for candidate in _iter_candidate_records(detail_payload):
            alert = _record_to_alert(candidate)
            if alert:
                return alert

    return _cap_xml_to_alert(response.text, alert_id) or _record_to_alert(record)


def fetch_pws_alerts() -> list[PwsAlert]:
    if not (config.NCDR_API_KEY or config.NCDR_DATASTORE_URL):
        logger.debug("NCDR_API_KEY 或 NCDR_DATASTORE_URL 未設定，略過 PWS 即時示警")
        return []

    datastore_url = config.NCDR_DATASTORE_URL or urljoin(
        config.NCDR_API_BASE_URL.rstrip("/") + "/",
        "datastore"
    )
    payload = _request_payload(datastore_url, params=_auth_params())
    if payload is None:
        return []

    if isinstance(payload, str):
        alert = _cap_xml_to_alert(payload, "pws-feed")
        return [alert] if alert and _is_recent_alert(alert.sent_time) else []

    alerts = []
    for record in _iter_candidate_records(payload):
        if not _matches_pws_earthquake(_record_text(record)):
            continue

        alert = _fetch_alert_detail(record)
        if alert and _is_recent_alert(alert.sent_time):
            alerts.append(alert)

    return alerts


def create_pws_alert_message(alert: PwsAlert) -> str:
    lines = ["🚨【地震速報】"]

    if alert.headline:
        lines.append(alert.headline)
    if alert.area:
        lines.append(f"影響區域：{alert.area}")
    if alert.sent_time:
        lines.append(f"發布時間：{alert.sent_time.strftime('%m/%d %H:%M:%S')}")
    if alert.description and alert.description != alert.headline:
        lines.append("")
        lines.append(alert.description)

    lines.append("")
    lines.append("來源：災防告警 CAP/PWS")
    return "\n".join(lines)


def check_pws_alert_job():
    global LAST_PWS_ALERT_IDS

    try:
        alerts = fetch_pws_alerts()
        if not alerts:
            return

        from app.repositories.user_repository import get_earthquake_subscriber_ids

        subscribers = get_earthquake_subscriber_ids()
        if not subscribers:
            logger.warning("沒有用戶可推播 PWS 地震速報")
            return

        for alert in alerts:
            if alert.alert_id in LAST_PWS_ALERT_IDS:
                continue

            LAST_PWS_ALERT_IDS.add(alert.alert_id)
            if len(LAST_PWS_ALERT_IDS) > 100:
                LAST_PWS_ALERT_IDS = set(list(LAST_PWS_ALERT_IDS)[-50:])

            from app.utils.line_utils import push_line_message_to_users

            logger.info(f"🚨 PWS 地震速報推播: {alert.alert_id}，推送給 {len(subscribers)} 位用戶")
            push_line_message_to_users(create_pws_alert_message(alert), subscribers)

    except Exception as e:
        logger.error(f"PWS 地震速報監控發生錯誤: {e}", exc_info=True)


def setup_pws_alert_job(scheduler, interval: int = 10):
    if not (config.NCDR_API_KEY or config.NCDR_DATASTORE_URL):
        logger.warning("NCDR_API_KEY 或 NCDR_DATASTORE_URL 未設定，PWS 地震速報監控未啟動")
        return

    logger.info("✅ 註冊 PWS 地震速報監控排程作業")
    logger.info(f"⏱️ PWS 檢查間隔: {interval} 秒")
    logger.info(f"⏳ PWS 最大延遲: {config.PWS_ALERT_MAX_LATENCY} 秒")

    scheduler.add_job(
        check_pws_alert_job,
        "interval",
        seconds=interval,
        id="pws_alert_checker",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
