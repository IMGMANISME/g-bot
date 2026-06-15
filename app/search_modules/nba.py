#app/search_modules/nba.py
import requests
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0"}

TEAM_NAME_MAP = {
    "勇士": "Golden State Warriors",
    "湖人": "Los Angeles Lakers",
    "快艇": "LA Clippers",
    "國王": "Sacramento Kings",
    "太陽": "Phoenix Suns",
    "獨行俠": "Dallas Mavericks",
    "火箭": "Houston Rockets",
    "馬刺": "San Antonio Spurs",
    "灰熊": "Memphis Grizzlies",
    "鵜鶘": "New Orleans Pelicans",
    "金塊": "Denver Nuggets",
    "雷霆": "Oklahoma City Thunder",
    "灰狼": "Minnesota Timberwolves",
    "拓荒者": "Portland Trail Blazers",
    "爵士": "Utah Jazz",
    "籃網": "Brooklyn Nets",
    "尼克": "New York Knicks",
    "76人": "Philadelphia 76ers",
    "暴龍": "Toronto Raptors",
    "塞爾提克": "Boston Celtics",
    "公牛": "Chicago Bulls",
    "騎士": "Cleveland Cavaliers",
    "活塞": "Detroit Pistons",
    "溜馬": "Indiana Pacers",
    "公鹿": "Milwaukee Bucks",
    "老鷹": "Atlanta Hawks",
    "黃蜂": "Charlotte Hornets",
    "熱火": "Miami Heat",
    "魔術": "Orlando Magic",
    "巫師": "Washington Wizards"
}


STATUS_MAP = {
    "Scheduled": "尚未開打",
    "In Progress": "比賽進行中",
    "Final": "比賽已結束",
    "Postponed": "已延期"
}


def normalize_team_name(name: str) -> str:
    """將使用者輸入轉換為 API 可識別的正式隊名"""
    name = name.strip()
    return TEAM_NAME_MAP.get(name, name)


def get_team_standings(team_name: str) -> str:
    try:
        team_name = normalize_team_name(team_name)

        url = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()

        for conference in data.get("children", []):
            entries = conference.get("standings", {}).get("entries", [])
            for team in entries:
                info = team.get("team", {})
                if team_name.lower() in info.get("displayName", "").lower():
                    stats = {s["name"]: s["displayValue"] for s in team.get("stats", [])}

                    wins = stats.get("wins", "N/A")
                    losses = stats.get("losses", "N/A")
                    win_pct = stats.get("winPercent", "N/A")
                    seed = stats.get("playoffSeed", "N/A")
                    games_behind = stats.get("gamesBehind", "N/A")

                    return (
                        f"🏀 {info['displayName']} 戰績：\n"
                        f"📊 勝敗：{wins} 勝 {losses} 負\n"
                        f"📈 勝率：{win_pct}\n"
                        f"🏅 排名：第 {seed} 名\n"
                        f"📉 落後第一名場次：{games_behind}"
                    )

        return f"⚠️ 找不到「{team_name}」的戰績資訊。"

    except Exception as e:
        logger.error(f"戰績查詢失敗：{e}")
        return f"⚠️ 無法取得「{team_name}」戰績，請稍後再試"
    
def get_conferences_standings(conference: str) -> str:
    try:
        # 中英對照表
        conference_map = {
            "東區": "Eastern Conference",
            "西區": "Western Conference",
            "east": "Eastern Conference",
            "west": "Western Conference"
        }

        # 標準化輸入
        conference_name = conference_map.get(conference.strip().lower())
        if not conference_name:
            return "⚠️ 僅支援查詢「東區」或「西區」的戰績資訊。"

        # 請求 ESPN API
        url = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()

        # 尋找指定會議資料
        conference_data = next((c for c in data.get("children", []) if c.get("name") == conference_name), None)
        if not conference_data:
            return f"⚠️ 找不到「{conference}」的戰績資訊。"

        entries = conference_data.get("standings", {}).get("entries", [])
        if not entries:
            return f"⚠️ 「{conference}」目前沒有球隊戰績資料。"

        # 整理球隊資料並排序（依照 seed）
        teams = []
        for team in entries:
            info = team.get("team", {})
            stats = {s["name"]: s["displayValue"] for s in team.get("stats", [])}
            raw_stats = {s["name"]: s.get("value", None) for s in team.get("stats", [])}

            teams.append({
                "displayName": info.get("displayName", "未知球隊"),
                "wins": stats.get("wins", "N/A"),
                "losses": stats.get("losses", "N/A"),
                "winPercent": stats.get("winPercent", "N/A"),
                "seed": raw_stats.get("playoffSeed", float("inf")),
                "gamesBehind": stats.get("gamesBehind", "N/A"),
                "streak": stats.get("streak", "N/A"),
                "differential": stats.get("differential", "N/A")
            })

        # 排序：依照 seed 排序
        teams.sort(key=lambda x: x["seed"])

        # 組裝輸出文字
        results = []
        for idx, team in enumerate(teams, start=1):
            results.append(
                f"🏀 {team['displayName']}（第 {idx} 名）\n"
                f"📊 勝敗：{team['wins']} 勝 {team['losses']} 負\n"
                f"📈 勝率：{team['winPercent']}｜📉 落後第一名：{team['gamesBehind']} 場\n"
                f"🔥 近期：{team['streak']}｜➕ 平均得分差：{team['differential']}"
            )

        return "\n\n---\n\n".join(results)

    except Exception as e:
        logger.error(f"會議查詢失敗：{e}")
        return "⚠️ 無法取得戰績資訊，請稍後再試。"

def get_team_today_game(team_name: str) -> str:
    try:
        team_name = normalize_team_name(team_name)

        url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()

        events = data.get("events", [])
        found_games = []

        for event in events:
            comp = event["competitions"][0]
            competitors = comp["competitors"]
            home = next(team for team in competitors if team["homeAway"] == "home")
            away = next(team for team in competitors if team["homeAway"] == "away")

            home_team = home["team"]["displayName"]
            away_team = away["team"]["displayName"]

            if team_name.lower() in (home_team.lower(), away_team.lower()):
                home_score = home.get("score", "N/A")
                away_score = away.get("score", "N/A")
                raw_status = comp["status"]["type"]["name"]
                status = STATUS_MAP.get(raw_status, comp["status"]["type"]["description"])

                found_games.append(
                    f"📌 {away_team} @ {home_team}\n"
                    f"📊 比數：{away_score} - {home_score}\n"
                    f"⏱️ 狀態：{status}"
                )

        if not found_games:
            return f"🏀 今日沒有「{team_name}」的比賽喔～"

        return "\n\n---\n\n".join(found_games)

    except Exception as e:
        logger.error(f"比賽查詢失敗：{e}")
        return f"⚠️ 無法取得「{team_name}」今日比賽資訊，請稍後再試"
    
def get_todays_game() -> str:
    try:
        url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()

        events = data.get("events", [])
        found_games = []

        for event in events:
            comp = event["competitions"][0]
            competitors = comp["competitors"]
            home = next(team for team in competitors if team["homeAway"] == "home")
            away = next(team for team in competitors if team["homeAway"] == "away")

            home_team = home["team"]["displayName"]
            away_team = away["team"]["displayName"]

            home_score = home.get("score", "N/A")
            away_score = away.get("score", "N/A")
            raw_status = comp["status"]["type"]["name"]
            status = STATUS_MAP.get(raw_status, comp["status"]["type"]["description"])

            found_games.append(
                f"📌 {away_team} @ {home_team}\n"
                f"📊 比數：{away_score} - {home_score}\n"
                f"⏱️ 狀態：{status}"
            )

        if not found_games:
            return "🏀 今日沒有比賽喔～"

        return "\n\n---\n\n".join(found_games)

    except Exception as e:
        logger.error(f"比賽查詢失敗：{e}")
        return "⚠️ 無法取得今日比賽資訊，請稍後再試"


def nba_info(query: str) -> str:
    if "戰績" in query:
        team_name = query.replace("戰績", "").strip()
        if team_name == "西區" or team_name == "東區":
            return get_conferences_standings(team_name)
        else:
            return get_team_standings(team_name)
    elif "比賽" in query:
        team_name = query.replace("比賽", "").strip()
        if team_name == "今日":
            return get_todays_game()
        else:
            return get_team_today_game(team_name)
    else:
        return "⚠️ 請明確輸入要查詢的球隊名稱以及「戰績」或「比賽」關鍵字～"
