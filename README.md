# CineMatch

A self-hosted movie and series discovery app powered by the full IMDB public dataset. No subscriptions, no API keys required — everything runs locally on your machine.

## What it does

CineMatch lets you browse, filter, and discover movies and TV series from a local database of 2.6 million+ titles. You can:

- Filter by **genre**, **decade**, **runtime**, and **minimum rating**
- Search for a **person** (actor, director, writer) and see all their works
- Switch between **Movies**, **Series**, or both
- Sort by **Popularity**, **Rating**, **Newest**, or **Oldest**
- Save titles to a **Watchlist** (stored in your browser)
- Get a **Surprise Me** random pick based on your current filters
- Optionally add a **TMDB API key** (free) to load movie posters and plot summaries

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React + Vite, served by nginx |
| Backend | FastAPI (Python) |
| Database | PostgreSQL 16 |
| Data source | [IMDB public datasets](https://datasets.imdbws.com/) |
| Poster images | TMDB API (optional, free) |

## Getting started

### Option A: Docker (recommended)

#### 1. Configure environment variables

```bash
cp .env.example .env
```

The defaults in `.env.example` work out of the box for Docker. If you have a TMDB API key, add it now — or you can enter it later in the app settings.

#### 2. Import the IMDB data (first time only)

The database needs to be populated before starting the app. This downloads ~1 GB of compressed data from IMDB and takes 15–30 minutes.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python import_imdb.py
```

> **Note:** `import_imdb.py` reads `DATABASE_URL` from your `.env` file. Make sure PostgreSQL is running before this step — you can start just the database with `docker compose up db -d`.

#### 3. Start everything

```bash
docker compose up --build
```

Open `http://localhost` in your browser. Services start in order (db → backend → frontend) and restart automatically on failure.

To stop:

```bash
docker compose down
```

---

### Option B: Manual setup

You'll need a PostgreSQL instance running locally. Update `DATABASE_URL` in your `.env` to point to it.

#### 1. Import the IMDB data (first time only)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python import_imdb.py
```

#### 2. Start the backend

```bash
cd backend
.venv/bin/uvicorn main:app --reload
```

The API runs at `http://localhost:8000`.

#### 3. Start the frontend

In a separate terminal:

```bash
npm install   # first time only
npm run dev
```

Open `http://localhost:5173` in your browser.

## Optional: Movie posters

To enable poster images and plot summaries:

1. Create a free account at [themoviedb.org](https://www.themoviedb.org/)
2. Go to Settings → API and copy your API key
3. In CineMatch, click the ⚙ gear icon in the top right and paste your key

Posters are cached in the database so they're only fetched once per title.

## Project structure

```
movie-chooser/
├── docker-compose.yml        # Orchestrates PostgreSQL, backend, and frontend containers
├── Dockerfile.frontend       # Multi-stage: Node build → nginx image
├── nginx.conf                # Serves the SPA and proxies /api to the backend
├── .env.example              # Environment variable template
├── backend/
│   ├── Dockerfile.backend    # Python 3.12 image running uvicorn
│   ├── main.py               # FastAPI app and all API endpoints
│   ├── import_imdb.py        # One-time IMDB dataset importer
│   ├── schema.sql            # PostgreSQL schema
│   ├── requirements.txt      # Python dependencies
│   └── imdb_data/            # Downloaded IMDB TSV files (generated)
├── src/
│   ├── App.jsx               # Main React app
│   └── App.css               # Styles
└── vite.config.js
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `TMDB_API_KEY` | No | TMDB key for posters and plot summaries |
| `VITE_API_URL` | No | Frontend API base URL (default: `/api`) |

See `.env.example` for details.

## Data included

The database includes the following IMDB datasets:

- **Titles** — primary title, type, year, runtime, genres
- **Ratings** — average rating and vote count
- **People** — actors, directors, writers, and other crew
- **Principals** — cast and crew per title
- **Crew** — directors and writers per title
- **Episodes** — season/episode data for TV series
- **Alternative titles** — international and regional titles

Adult titles are excluded at import time.
