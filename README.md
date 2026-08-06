English | [繁體中文](./README.zh-TW.md)
 
# G-Bot
 
> A LINE bot platform running in continuous production on cloud infrastructure. It combines LLM conversation, real-time information lookup, task scheduling, and proactive notifications behind a layered architecture, with health-check and metrics endpoints for operational monitoring.
 
**Stack:** Python 3.11 · FastAPI · PostgreSQL · SQLAlchemy · APScheduler · Docker · Google Gemini · LINE Messaging API
 
---
 
## Why I Built This
 
Most LINE bots are single-layer scripts: receive a message, return a reply. That works until you add the fifth feature, and then nothing is maintainable. G-Bot is my attempt to build one as an **extensible service platform** instead:
 
- **Modular lookups** — weather, news, restaurants, and earthquake data are independently replaceable modules. Adding a new lookup type requires no changes to core logic.
- **Swappable bot personas** — system prompts live in profile directories. Change one environment variable and the same codebase deploys as an entirely different bot.
- **Proactive, not just reactive** — APScheduler drives user-defined reminders and continuous earthquake monitoring.
- **Actually operable** — `/health` and `/metrics` endpoints expose service and database state, so the deployment can be monitored rather than guessed at.
---
 
## Architecture
 
```mermaid
flowchart TB
    LINE["LINE Platform"]
 
    subgraph APP["FastAPI Application"]
        direction TB
        MAIN["main.py<br/>lifecycle · routes"]
        HANDLERS["handlers/<br/>event & command parsing"]
        SERVICES["services/<br/>business workflows"]
        REPOS["repositories/<br/>data access layer"]
    end
 
    subgraph ENGINES["Processing Engines"]
        GEMINI["gemini_engine<br/>conversation & context"]
        SEARCH["realtime_search<br/>query routing"]
        SCHED["APScheduler<br/>reminders · earthquake watch"]
    end
 
    subgraph MODULES["search_modules/"]
        WEATHER["Weather CWA"]
        MAPS["Google Maps"]
        TAVILY["Tavily Search"]
        NBA["NBA"]
    end
 
    PROMPTS["prompts/profile/<br/>swappable system prompts"]
    DB[("PostgreSQL<br/>history · settings · schedules")]
    OPS["/health · /metrics"]
 
    LINE -->|"webhook /callback"| MAIN
    MAIN --> HANDLERS
    HANDLERS --> SERVICES
    SERVICES --> GEMINI
    SERVICES --> SEARCH
    SERVICES --> REPOS
    SEARCH --> MODULES
    PROMPTS -.injected config.-> GEMINI
    SCHED --> SERVICES
    REPOS --> DB
    SCHED -->|"proactive push"| LINE
    MAIN --> OPS
    GEMINI -->|"reply"| LINE
```
 
### Layer Responsibilities
 
| Layer | Responsibility | Why the boundary is here |
|---|---|---|
| `handlers/` | Parse LINE events and commands | Isolates the LINE SDK — swapping messaging platforms touches only this layer |
| `services/` | Orchestrate business workflows | Core logic stays independent of the framework and database implementation |
| `repositories/` | Data access | Centralizes database operations, making testing and storage swaps straightforward |
| `search_modules/` | External API wrappers | Each external service is isolated, so one outage doesn't cascade |
| `prompts/` | Bot behavior definitions | Prompts live in files rather than hardcoded strings, so they're version-controlled |
 
---
 
## Implementation Notes
 
**Group conversation memory**
In group chats, shared memory is keyed by group ID, and every message is stored as `username: message`. This lets the LLM attribute statements to the right speaker instead of blending several people's messages into one voice.
 
**Swappable prompt profiles**
The `SYSTEM_PROMPT_PROFILE` environment variable points to `app/prompts/<profile>/`, which holds `conversation.txt` (persona and constraints) and `realtime.txt` (rules for answering lookups). Adding a directory produces a completely different bot — no code changes required.
 
**Service observability**
`/health` verifies service and database connectivity. `/metrics` reports performance indicators and is protected by `METRICS_TOKEN`; when the token is unset, the endpoint returns 404 rather than leaking data.
 
---
 
## Features
 
- LINE text and location message handling
- Gemini AI conversation with persistent history
- Tavily real-time search and news lookup
- Weather, NBA, and time queries
- Google Maps restaurant recommendations
- Daily and one-time reminders
- Earthquake monitoring and push notifications
- Reply-mode control: quiet, active, mention-only, reply-to-all
- Speaker attribution in group chats
- `/health` health check and `/metrics` performance endpoint
## Tech Stack
 
- Python 3.11
- FastAPI + Uvicorn
- LINE Messaging API
- Google Gemini API
- PostgreSQL
- SQLAlchemy
- APScheduler
- Docker
## Documentation
 
- [Railway Deployment Guide](./Railyway.md)
## Project Structure
 
```
app/
├── main.py                    # FastAPI entry point, lifecycle, API routes
├── config.py                  # Environment variables and settings validation
├── database.py                # SQLAlchemy engine, session, table initialization
├── line_bot.py                # LINE webhook event registration
├── gemini_engine.py           # Gemini conversation and context handling
├── realtime_search.py         # Real-time query routing
├── earthquake.py              # Earthquake data lookup and notification
├── schedule_notification.py   # APScheduler reminders and background tasks
├── handlers/                  # LINE event and command handling
├── services/                  # Conversation, lookup, recommendation workflows
├── models/                    # SQLAlchemy models
├── repositories/              # Database access layer
├── prompts/                   # Swappable bot system prompt templates
├── search_modules/            # Weather, NBA, Tavily, Google Maps modules
├── utils/                     # Logger, cache, decorators, LINE helpers
└── views/                     # LINE quick reply / menu builders
```
 
## Bot Prompts
 
System prompts live in `app/prompts/<profile>/`. The default profile is `gbot`.
 
```
app/prompts/gbot/
├── conversation.txt   # General persona and constraints
└── realtime.txt       # Rules for answering real-time lookups
```
 
To build a different bot, add a directory such as `app/prompts/support_bot/` containing the same two files, then set:
 
```
SYSTEM_PROMPT_PROFILE=support_bot
```
 
---
 
## Local Development
 
### Requirements
 
- Python 3.11+
- PostgreSQL
- A LINE Developers Channel
- A Google AI Studio API key
### Install
 
```bash
pip install -r requirements.txt
```
 
### Configure Environment Variables
 
Create a `.env` file — copy `.env.example` and edit it.
 
```
LINE_CHANNEL_ACCESS_TOKEN=your_line_channel_access_token
LINE_CHANNEL_SECRET=your_line_channel_secret
GEMINI_API_KEY=your_gemini_api_key
DATABASE_URL=postgresql://username:password@localhost:5432/gbot_db
```
 
See the Environment Variables section below for the full list.
 
### Run
 
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8787 --reload
```
 
Health check:
 
```bash
curl http://localhost:8787/health
```
 
### LINE Developers Setup
 
1. Open the LINE Developers Console.
2. Go to your Messaging API Channel.
3. Set the Webhook URL to your deployed HTTPS domain followed by `/callback`.
4. Enable **Use webhook**.
5. Click **Verify** to confirm LINE can reach the service.
6. Send the bot a message to test.
---
 
## Group Conversation Memory
 
In one-on-one chats, G-Bot keys conversation memory by user ID.
 
In groups and rooms, it keys shared memory by group ID and records each user message as:
 
```
username: message
```
 
This lets Gemini distinguish between group members when reading history, so one person's statements are never attributed to another.
 
## Priority Users
 
If you don't know a user's LINE sender ID, you can designate priority users by display name with `PRIORITY_MENTION_NAMES`:
 
```
PRIORITY_MENTION_NAMES=Alice,Bob
```
 
G-Bot matches against LINE display names. On a match, the AI replies in a more polite and deferential tone while staying conversational.
 
Matching ignores case and whitespace, though names should still match the LINE display name as closely as possible.
 
---
 
## API Endpoints
 
| Method | Path | Description |
|---|---|---|
| GET | `/` | Basic service status |
| GET | `/health` | Health check, including database connectivity |
| GET | `/metrics` | Performance metrics |
| POST | `/callback` | LINE webhook |
 
## Environment Variables
 
### Required
 
| Variable | Description |
|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE bot access token |
| `LINE_CHANNEL_SECRET` | LINE bot channel secret |
| `GEMINI_API_KEY` | Google Gemini API key |
| `DATABASE_URL` | PostgreSQL connection string |
 
### Database
 
| Variable | Default | Description |
|---|---|---|
| `DB_POOL_SIZE` | 2 | PostgreSQL connection pool size |
| `DB_MAX_OVERFLOW` | 3 | Additional connections allowed beyond the pool |
| `DB_POOL_TIMEOUT` | 30 | Seconds to wait for a connection |
| `DB_POOL_RECYCLE` | 3600 | Connection recycle interval in seconds |
 
### AI
 
| Variable | Default | Description |
|---|---|---|
| `GEMINI_MODEL` | gemma-4-26b-a4b-it | Gemini model name |
| `GEMINI_TEMPERATURE` | 0.7 | Response temperature |
| `GEMINI_MAX_TOKENS` | 2048 | Maximum output tokens |
| `SYSTEM_PROMPT_PROFILE` | gbot | Prompt template directory under `app/prompts/` |
 
### LINE Bot
 
| Variable | Default | Description |
|---|---|---|
| `MENTION_KEYWORDS` | @G-bot | Comma-separated keywords that trigger mention mode |
| `ADMIN_USERS` | empty | Comma-separated admin LINE user IDs |
| `PRIORITY_MENTION_NAMES` | empty | Comma-separated LINE display names to treat as priority users |
| `ENABLE_LOADING_ANIMATION` | true | Whether to show the LINE loading animation |
| `LINE_LOADING_SECONDS` | 20 | Loading animation duration |
 
### External Services
 
| Variable | Description |
|---|---|
| `CWA_API_KEY` | Central Weather Administration key, used for weather and earthquakes |
| `GOOGLE_MAPS_API_KEY` | Google Maps key, used for restaurant recommendations |
| `WEATHER_API_KEY` | Weather API key |
| `TAVILY_API_KEY` | Tavily key, used for real-time search |
 
### Search and Caching
 
| Variable | Default | Description |
|---|---|---|
| `TAVILY_SEARCH_MAX_RESULTS` | 5 | Number of Tavily search results |
| `TAVILY_SEARCH_DEPTH` | basic | Tavily search depth |
| `TAVILY_SEARCH_TOPIC` | general | Tavily search topic |
| `TAVILY_INCLUDE_ANSWER` | true | Whether to include Tavily's summary answer |
| `TAVILY_CACHE_TTL` | 600 | Search cache lifetime in seconds |
 
### Restaurant Recommendations
 
| Variable | Default | Description |
|---|---|---|
| `DEFAULT_SEARCH_RADIUS` | 1500 | Default search radius in meters |
| `NEAR_RADIUS` | 500 | Radius for "nearby" searches |
| `FAR_RADIUS` | 2500 | Radius for "a bit farther" searches |
 
### Earthquake Notifications
 
| Variable | Default | Description |
|---|---|---|
| `EARTHQUAKE_CHECK_INTERVAL` | 20 | Check interval in seconds |
| `EARTHQUAKE_MIN_MAGNITUDE` | 4.0 | Default minimum magnitude for push notifications |
| `EARTHQUAKE_MAX_LATENCY` | 900 | Maximum acceptable data latency in seconds |
 
### System
 
| Variable | Default | Description |
|---|---|---|
| `PORT` | 8787 | Local or container service port |
| `LOG_LEVEL` | INFO | Logging level |
| `CORS_ALLOW_ORIGINS` | empty | Comma-separated allowed CORS origins |
| `METRICS_TOKEN` | empty | Access token for `/metrics`; unset means the endpoint returns 404 |
 
---
 
## Docker
 
Build the image:
 
```bash
docker build -t g-bot .
```
 
Run the container:
 
```bash
docker run -d \
  --name g-bot \
  -p 8787:8787 \
  --env-file .env \
  g-bot
```
 
---
 
## Commands
 
### Bot Control
 
| Command | Description |
|---|---|
| `#安靜` | Stop replying proactively |
| `#說話` | Resume replying |
| `#標記` | Reply only when mentioned |
| `#都回` | Reply to every message |
| `#狀態` | Show current status |
| `#功能` | List available features |
| `#清除` | Clear conversation history |
| `我的設定` | Show personal settings |
 
### Reminders
 
```
提醒我 開會 14:30          # Remind me about a meeting at 14:30
提醒我 喝水 09:00 每天      # Remind me to drink water at 09:00 daily
取消提醒 1                  # Cancel reminder #1
```
 
### Earthquake Notifications
 
```
地震通知開                  # Enable earthquake alerts
地震通知關                  # Disable earthquake alerts
地震門檻 4.5                # Set magnitude threshold to 4.5
```
 
### Real-Time Lookups
 
```
台北天氣                    # Taipei weather
NBA戰績                     # NBA standings
查一下 台灣最新新聞          # Search the latest news in Taiwan
附近餐廳                    # Nearby restaurants
```
 
---
 
## Maintenance Notes
 
- Never commit external API keys to Git.
- Redeploy after changing environment variables.
- Back up PostgreSQL before making significant schema changes.
- For multi-user deployments, adopt a proper migration tool such as Alembic.
## License
 
MIT