# Project Voice - TME AI Agent

A FastAPI-based voice + search assistant with morning news refresh, vector database update, and optional Kafka worker flow.

## Features

- Voice to text (STT) via HTTP and WebSocket
- Search/chat endpoint with session context
- News scraping and embedding update to vector store
- Daily morning refresh workflow (Airflow DAG)
- Cache management endpoints
- Metrics endpoint for Prometheus
- Docker and production deploy configs

## Tech Stack

- Python 3.10
- FastAPI + Uvicorn
- ChromaDB
- Kafka (optional in local, used in worker flow)
- Airflow (for DAG scheduling)
- Faster-Whisper (STT)

## Project Structure

- API/: application code (voice routes, search brain, services)
- dags/: Airflow DAGs
- data/: local DB/vector data
- deploy/: production compose + nginx assets
- font_end/: static web UI
- temp_audio/: temporary audio files

## Main Services

- API app entry: API.voice.main:app
- Morning DAG: dags/tme_morning_refresh.py
- Python scheduler (non-Airflow): scheduler.py
- Manual/standalone refresh script: run_news_refresh.py
- Kafka worker: kafka_worker.py

## Environment Variables

Create a .env file in project root:

```env
GROQ_API_KEY=your_groq_api_key
TAVILY_API_KEY=your_tavily_api_key
OPENAI_API_KEY=your_openai_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id

KAFKA_BOOTSTRAP_SERVERS=localhost:9092
USE_CELERY=false
REDIS_BROKER=redis://localhost:6379/0
REDIS_BACKEND=redis://localhost:6379/1
```

## Run With Docker (Recommended)

```bash
docker compose up --build
```

Default ports:

- API: 8000
- Chroma (if enabled): 8001
- Kafka: 9092
- Prometheus: 9090

## Run Local (Python)

1) Install dependencies

```bash
pip install -r requirements.txt
```

2) Start API server

```bash
uvicorn API.voice.main:app --host 127.0.0.1 --port 8000 --reload
```

3) Open web UI

- http://127.0.0.1:8000/static/index.html

## Morning News Update

### Primary (Airflow DAG)

- File: dags/tme_morning_refresh.py
- DAG ID: tme_daily_news_refresh
- Schedule: 0 6 * * * (every day at 06:00)

### Non-Airflow Option

Run manual refresh once:

```bash
python run_news_refresh.py
```

Run scheduled mode from script:

```bash
python run_news_refresh.py --schedule
```

Alternative scheduler with configurable hour:

```bash
python scheduler.py
```

## API Endpoints

Base URL (local): http://127.0.0.1:8000

- GET / -> health check
- POST /v1/stt -> upload audio file (wav/mp3/m4a)
- WS /v1/stt -> realtime STT stream
- POST /v1/search -> ask with optional session_id
- GET /v1/search?q=...&session_id=...
- DELETE /v1/search/session/{session_id}
- GET /v1/search/session/{session_id}
- DELETE /v1/cache
- DELETE /v1/cache/expired
- POST /v1/news/refresh
- GET /v1/metrics

## Production Deploy

Use deploy config:

```bash
cd deploy
docker compose -f docker-compose.prod.yml up -d --build
```

## Notes

- Ensure ffmpeg is available (required by audio processing).
- temp_audio is used for temporary files during STT.
- data keeps local DB/vector data; backup before destructive operations.
- If Kafka is unavailable, some flows fallback to direct refresh behavior.

## Troubleshooting

- API does not start: check .env keys and installed dependencies.
- STT fails on upload: verify audio format and ffmpeg availability.
- Morning update not running: verify scheduler mode or Airflow DAG activation.
- Docker service fails: inspect docker compose logs for the failing service.

## License

Internal/Private project unless specified otherwise.
