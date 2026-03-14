"""
Movie Chooser API
Self-hosted movie/series database powered by IMDB public datasets.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, List
import math
import sqlite3
import time

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB_PATH = Path(__file__).parent / "movies.db"

TITLE_TYPES = {
    "movie":  ["movie", "tvMovie", "video"],
    "series": ["tvSeries", "tvMiniSeries", "tvSpecial"],
    "short":  ["short", "tvShort"],
    "all":    ["movie", "tvMovie", "video", "tvSeries", "tvMiniSeries", "tvSpecial", "short", "tvShort"],
}

SORT_OPTIONS = {
    "rating":     "r.average_rating DESC",
    "votes":      "r.num_votes DESC",
    "year_desc":  "t.start_year DESC",
    "year_asc":   "t.start_year ASC",
    "title":      "t.primary_title ASC",
    "popularity": "r.num_votes DESC",
}

TMDB_BASE = "https://api.themoviedb.org/3"


def get_db():
    """Read-only connection."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA query_only=ON")
    return conn


def get_write_db():
    """Read-write connection (for poster cache writes)."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def has_fts(conn) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='titles_fts'"
    ).fetchone()
    return row is not None


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DB_PATH.exists():
        print(f"WARNING: Database not found at {DB_PATH}")
        print("Run: python import_imdb.py")
    else:
        # Apply missing tables one by one (safe — CREATE IF NOT EXISTS)
        conn = get_write_db()
        try:
            # Core tables (always safe)
            for stmt in [
                """CREATE TABLE IF NOT EXISTS posters (
                    tconst TEXT PRIMARY KEY, poster_path TEXT, overview TEXT,
                    tmdb_id INTEGER, fetched_at INTEGER NOT NULL,
                    FOREIGN KEY (tconst) REFERENCES titles(tconst))""",
            ]:
                conn.execute(stmt)
            conn.commit()
            # FTS5 is optional — skip gracefully if not compiled in
            try:
                conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS titles_fts USING fts5(
                    tconst UNINDEXED, primary_title, original_title,
                    content='titles', content_rowid='rowid')""")
                conn.commit()
            except Exception as e:
                print(f"FTS5 not available ({e}) — search will use LIKE fallback")
        except Exception as e:
            print(f"Schema migration warning: {e}")
        finally:
            conn.close()

        # Print DB status
        try:
            r = get_db()
            count = r.execute("SELECT COUNT(*) FROM titles").fetchone()[0]
            print(f"Database: {DB_PATH} ({count:,} titles)")
            if count == 0:
                print("WARNING: Database is empty — run: python import_imdb.py")
        except Exception:
            print("WARNING: Could not read titles table — run: python import_imdb.py")
    yield


app = FastAPI(
    title="Movie Chooser API",
    description="Self-hosted movie database powered by IMDB public datasets",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


def build_type_filter(media_type: str):
    types = TITLE_TYPES.get(media_type, TITLE_TYPES["all"])
    placeholders = ",".join("?" * len(types))
    return f"t.title_type IN ({placeholders})", types


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "Movie Chooser API v2", "docs": "/docs"}


@app.get("/stats")
def stats():
    db = get_db()
    result = {}
    for table in ["titles", "ratings", "people", "principals", "crew", "episodes", "akas", "posters"]:
        try:
            result[table] = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:
            result[table] = 0

    types = db.execute(
        "SELECT title_type, COUNT(*) as n FROM titles GROUP BY title_type ORDER BY n DESC"
    ).fetchall()
    result["by_type"] = {r["title_type"]: r["n"] for r in types}
    result["has_fts"] = has_fts(db)

    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    result["db_size_mb"] = round(db_size / 1024 / 1024, 1)
    return result


@app.get("/genres")
def genres(media_type: str = Query("all")):
    db = get_db()
    type_filter, type_args = build_type_filter(media_type)
    rows = db.execute(
        f"""
        SELECT t.genres FROM titles t
        WHERE {type_filter}
          AND t.genres IS NOT NULL AND t.genres != ''
        """,
        type_args,
    ).fetchall()

    counts: dict[str, int] = {}
    for row in rows:
        for g in row["genres"].split(","):
            g = g.strip()
            if g and g != "\\N":
                counts[g] = counts.get(g, 0) + 1

    return {"genres": sorted(
        [{"name": k, "count": v} for k, v in counts.items()],
        key=lambda x: -x["count"],
    )}


@app.get("/discover")
def discover(
    media_type: str = Query("all"),
    genres: Optional[str] = Query(None),
    person_id: Optional[str] = Query(None),
    year_from: Optional[int] = Query(None),
    year_to: Optional[int] = Query(None),
    decade: Optional[int] = Query(None, description="e.g. 1990 → 1990–1999"),
    runtime_min: Optional[int] = Query(None, ge=0),
    runtime_max: Optional[int] = Query(None, ge=0),
    min_rating: float = Query(0.0, ge=0, le=10),
    min_votes: int = Query(100, ge=0),
    sort_by: str = Query("votes"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
):
    db = get_db()
    type_filter, type_args = build_type_filter(media_type)
    order = SORT_OPTIONS.get(sort_by, SORT_OPTIONS["votes"])

    conditions = [type_filter, "r.tconst IS NOT NULL"]
    args = type_args[:]

    if genres:
        for g in [g.strip() for g in genres.split(",") if g.strip()]:
            conditions.append("t.genres LIKE ?")
            args.append(f"%{g}%")

    if person_id:
        conditions.append("p.nconst = ?")
        args.append(person_id)

    if decade:
        conditions.append("t.start_year >= ? AND t.start_year < ?")
        args += [decade, decade + 10]
    else:
        if year_from:
            conditions.append("t.start_year >= ?")
            args.append(year_from)
        if year_to:
            conditions.append("t.start_year <= ?")
            args.append(year_to)

    if runtime_min is not None:
        conditions.append("t.runtime_minutes >= ?")
        args.append(runtime_min)
    if runtime_max is not None:
        conditions.append("t.runtime_minutes <= ?")
        args.append(runtime_max)

    if min_rating > 0:
        conditions.append("r.average_rating >= ?")
        args.append(min_rating)

    conditions.append("r.num_votes >= ?")
    args.append(min_votes)

    where = " AND ".join(conditions)
    join_person = "JOIN principals p ON p.tconst = t.tconst" if person_id else ""

    total = db.execute(
        f"SELECT COUNT(DISTINCT t.tconst) FROM titles t LEFT JOIN ratings r ON r.tconst = t.tconst {join_person} WHERE {where}",
        args,
    ).fetchone()[0]

    offset = (page - 1) * page_size
    rows = db.execute(
        f"""
        SELECT DISTINCT t.tconst, t.primary_title, t.original_title,
            t.title_type, t.start_year, t.end_year, t.runtime_minutes, t.genres,
            r.average_rating, r.num_votes
        FROM titles t
        LEFT JOIN ratings r ON r.tconst = t.tconst
        {join_person}
        WHERE {where}
        ORDER BY {order}
        LIMIT ? OFFSET ?
        """,
        args + [page_size, offset],
    ).fetchall()

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": math.ceil(total / page_size) if total else 1,
        "results": rows_to_dicts(rows),
    }


@app.get("/search/titles")
def search_titles(
    q: str = Query(..., min_length=1),
    media_type: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
):
    db = get_db()
    type_filter, type_args = build_type_filter(media_type)
    offset = (page - 1) * page_size

    # Use FTS5 if available for fast, ranked search
    if has_fts(db):
        safe_q = q.replace('"', '""')
        match_term = f'"{safe_q}"'
        try:
            rows = db.execute(
                f"""
                SELECT t.tconst, t.primary_title, t.original_title,
                    t.title_type, t.start_year, t.end_year,
                    t.runtime_minutes, t.genres,
                    r.average_rating, r.num_votes
                FROM titles_fts fts
                JOIN titles t ON t.tconst = fts.tconst
                LEFT JOIN ratings r ON r.tconst = t.tconst
                WHERE titles_fts MATCH ? AND {type_filter}
                ORDER BY rank, r.num_votes DESC NULLS LAST
                LIMIT ? OFFSET ?
                """,
                [match_term] + type_args + [page_size, offset],
            ).fetchall()
            total = db.execute(
                f"""
                SELECT COUNT(*) FROM titles_fts fts
                JOIN titles t ON t.tconst = fts.tconst
                WHERE titles_fts MATCH ? AND {type_filter}
                """,
                [match_term] + type_args,
            ).fetchone()[0]
            return {
                "page": page, "page_size": page_size, "total": total,
                "total_pages": math.ceil(total / page_size) if total else 1,
                "results": rows_to_dicts(rows),
            }
        except Exception:
            pass  # fall through to LIKE

    # Fallback: LIKE search
    pattern = f"%{q}%"
    rows = db.execute(
        f"""
        SELECT DISTINCT t.tconst, t.primary_title, t.original_title,
            t.title_type, t.start_year, t.end_year, t.runtime_minutes, t.genres,
            r.average_rating, r.num_votes
        FROM titles t
        LEFT JOIN ratings r ON r.tconst = t.tconst
        WHERE {type_filter} AND (t.primary_title LIKE ? OR t.original_title LIKE ?)
        ORDER BY r.num_votes DESC NULLS LAST
        LIMIT ? OFFSET ?
        """,
        type_args + [pattern, pattern, page_size, offset],
    ).fetchall()
    total = db.execute(
        f"SELECT COUNT(*) FROM titles t WHERE {type_filter} AND (t.primary_title LIKE ? OR t.original_title LIKE ?)",
        type_args + [pattern, pattern],
    ).fetchone()[0]

    return {
        "page": page, "page_size": page_size, "total": total,
        "total_pages": math.ceil(total / page_size) if total else 1,
        "results": rows_to_dicts(rows),
    }


@app.get("/search/people")
def search_people(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50)):
    db = get_db()
    rows = db.execute(
        """
        SELECT p.nconst, p.primary_name, p.birth_year, p.death_year,
               p.primary_profession, p.known_for_titles
        FROM people p
        WHERE p.primary_name LIKE ?
        ORDER BY (SELECT COUNT(*) FROM principals pr WHERE pr.nconst = p.nconst) DESC
        LIMIT ?
        """,
        [f"%{q}%", limit],
    ).fetchall()
    return {"results": rows_to_dicts(rows)}


@app.get("/title/{tconst}")
def get_title(tconst: str):
    db = get_db()

    title = db.execute(
        """
        SELECT t.*, r.average_rating, r.num_votes,
               p.poster_path, p.overview, p.tmdb_id
        FROM titles t
        LEFT JOIN ratings r ON r.tconst = t.tconst
        LEFT JOIN posters p ON p.tconst = t.tconst
        WHERE t.tconst = ?
        """,
        [tconst],
    ).fetchone()

    if not title:
        raise HTTPException(404, "Title not found")

    result = dict(title)

    cast = db.execute(
        """
        SELECT p.nconst, p.primary_name, p.birth_year,
               pr.category, pr.characters, pr.ordering
        FROM principals pr
        JOIN people p ON p.nconst = pr.nconst
        WHERE pr.tconst = ?
        ORDER BY pr.ordering
        LIMIT 30
        """,
        [tconst],
    ).fetchall()
    result["cast"] = rows_to_dicts(cast)

    crew = db.execute("SELECT * FROM crew WHERE tconst = ?", [tconst]).fetchone()
    if crew:
        crew_dict = dict(crew)
        if crew_dict.get("directors"):
            dir_ids = crew_dict["directors"].split(",")[:5]
            crew_dict["director_details"] = rows_to_dicts(db.execute(
                f"SELECT nconst, primary_name FROM people WHERE nconst IN ({','.join('?'*len(dir_ids))})",
                dir_ids,
            ).fetchall())
        if crew_dict.get("writers"):
            wri_ids = crew_dict["writers"].split(",")[:5]
            crew_dict["writer_details"] = rows_to_dicts(db.execute(
                f"SELECT nconst, primary_name FROM people WHERE nconst IN ({','.join('?'*len(wri_ids))})",
                wri_ids,
            ).fetchall())
        result["crew"] = crew_dict

    if result.get("title_type") in ("tvSeries", "tvMiniSeries"):
        result["seasons"] = rows_to_dicts(db.execute(
            """
            SELECT season_number, COUNT(*) as episode_count
            FROM episodes WHERE parent_tconst = ?
            GROUP BY season_number ORDER BY season_number
            """,
            [tconst],
        ).fetchall())

    result["akas"] = rows_to_dicts(db.execute(
        "SELECT title, region, language, types FROM akas WHERE tconst = ? AND region IS NOT NULL ORDER BY is_original DESC LIMIT 20",
        [tconst],
    ).fetchall())

    if result.get("genres"):
        first_genre = result["genres"].split(",")[0].strip()
        result["similar"] = rows_to_dicts(db.execute(
            """
            SELECT t.tconst, t.primary_title, t.start_year, t.genres,
                   r.average_rating, r.num_votes, p.poster_path
            FROM titles t
            LEFT JOIN ratings r ON r.tconst = t.tconst
            LEFT JOIN posters p ON p.tconst = t.tconst
            WHERE t.tconst != ? AND t.title_type = ? AND t.genres LIKE ? AND r.num_votes >= 1000
            ORDER BY r.average_rating DESC
            LIMIT 8
            """,
            [tconst, result["title_type"], f"%{first_genre}%"],
        ).fetchall())

    return result


@app.get("/person/{nconst}")
def get_person(nconst: str, limit: int = Query(20, ge=1, le=100)):
    db = get_db()
    person = db.execute("SELECT * FROM people WHERE nconst = ?", [nconst]).fetchone()
    if not person:
        raise HTTPException(404, "Person not found")

    result = dict(person)
    result["titles"] = rows_to_dicts(db.execute(
        """
        SELECT t.tconst, t.primary_title, t.title_type, t.start_year,
               t.genres, r.average_rating, r.num_votes,
               pr.category, pr.characters, p.poster_path
        FROM principals pr
        JOIN titles t ON t.tconst = pr.tconst
        LEFT JOIN ratings r ON r.tconst = t.tconst
        LEFT JOIN posters p ON p.tconst = t.tconst
        WHERE pr.nconst = ?
        ORDER BY r.num_votes DESC NULLS LAST
        LIMIT ?
        """,
        [nconst, limit],
    ).fetchall())
    return result


class PostersRequest(BaseModel):
    tconsts: List[str]
    tmdb_key: Optional[str] = None


@app.post("/posters")
async def get_posters(body: PostersRequest):
    """Batch fetch poster images + overviews from TMDB. Caches results in DB."""
    tconsts = body.tconsts[:50]
    if not tconsts:
        return {"posters": {}}

    db = get_db()
    cached = {
        r["tconst"]: dict(r)
        for r in db.execute(
            f"SELECT tconst, poster_path, overview, tmdb_id FROM posters WHERE tconst IN ({','.join('?'*len(tconsts))})",
            tconsts,
        ).fetchall()
    }

    missing = [t for t in tconsts if t not in cached]

    if missing and body.tmdb_key:
        db_w = get_write_db()
        async with httpx.AsyncClient(timeout=5) as client:
            for tconst in missing:
                try:
                    resp = await client.get(
                        f"{TMDB_BASE}/find/{tconst}",
                        params={"api_key": body.tmdb_key, "external_source": "imdb_id"},
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    hit = (data.get("movie_results") or data.get("tv_results") or [None])[0]
                    if not hit:
                        continue
                    poster_path = hit.get("poster_path")
                    overview = hit.get("overview") or ""
                    tmdb_id = hit.get("id")
                    db_w.execute(
                        "INSERT OR REPLACE INTO posters VALUES (?,?,?,?,?)",
                        [tconst, poster_path, overview, tmdb_id, int(time.time())],
                    )
                    db_w.commit()
                    cached[tconst] = {
                        "tconst": tconst, "poster_path": poster_path,
                        "overview": overview, "tmdb_id": tmdb_id,
                    }
                except Exception:
                    continue

    return {"posters": cached}


@app.get("/random")
def random_pick(
    media_type: str = Query("all"),
    genres: Optional[str] = Query(None),
    decade: Optional[int] = Query(None),
    runtime_max: Optional[int] = Query(None),
    min_rating: float = Query(7.0),
    min_votes: int = Query(1000),
):
    db = get_db()
    type_filter, type_args = build_type_filter(media_type)

    conditions = [type_filter, "r.tconst IS NOT NULL", "r.average_rating >= ?", "r.num_votes >= ?"]
    args = type_args + [min_rating, min_votes]

    if genres:
        for g in genres.split(","):
            g = g.strip()
            if g:
                conditions.append("t.genres LIKE ?")
                args.append(f"%{g}%")

    if decade:
        conditions.append("t.start_year >= ? AND t.start_year < ?")
        args += [decade, decade + 10]

    if runtime_max:
        conditions.append("t.runtime_minutes <= ?")
        args.append(runtime_max)

    where = " AND ".join(conditions)
    row = db.execute(
        f"""
        SELECT t.tconst, t.primary_title, t.original_title,
               t.title_type, t.start_year, t.end_year,
               t.runtime_minutes, t.genres,
               r.average_rating, r.num_votes
        FROM titles t
        LEFT JOIN ratings r ON r.tconst = t.tconst
        WHERE {where}
        ORDER BY RANDOM()
        LIMIT 1
        """,
        args,
    ).fetchone()

    if not row:
        raise HTTPException(404, "No matching title found. Try relaxing filters.")
    return dict(row)


@app.get("/top-rated")
def top_rated(
    media_type: str = Query("all"),
    genre: Optional[str] = Query(None),
    min_votes: int = Query(10000),
    limit: int = Query(50, ge=1, le=250),
):
    db = get_db()
    type_filter, type_args = build_type_filter(media_type)

    conditions = [type_filter, "r.tconst IS NOT NULL", "r.num_votes >= ?"]
    args = type_args + [min_votes]

    if genre:
        conditions.append("t.genres LIKE ?")
        args.append(f"%{genre}%")

    where = " AND ".join(conditions)
    rows = db.execute(
        f"""
        SELECT t.tconst, t.primary_title, t.original_title,
               t.title_type, t.start_year, t.genres,
               r.average_rating, r.num_votes
        FROM titles t
        LEFT JOIN ratings r ON r.tconst = t.tconst
        WHERE {where}
        ORDER BY r.average_rating DESC, r.num_votes DESC
        LIMIT ?
        """,
        args + [limit],
    ).fetchall()
    return {"results": rows_to_dicts(rows)}


@app.get("/trending")
def trending(
    media_type: str = Query("all"),
    year: Optional[int] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    db = get_db()
    type_filter, type_args = build_type_filter(media_type)

    conditions = [type_filter, "r.tconst IS NOT NULL", "r.average_rating >= 5"]
    args = type_args[:]

    if year:
        conditions.append("t.start_year = ?")
        args.append(year)

    where = " AND ".join(conditions)
    rows = db.execute(
        f"""
        SELECT t.tconst, t.primary_title, t.title_type, t.start_year,
               t.genres, r.average_rating, r.num_votes
        FROM titles t
        LEFT JOIN ratings r ON r.tconst = t.tconst
        WHERE {where}
        ORDER BY r.num_votes DESC
        LIMIT ?
        """,
        args + [limit],
    ).fetchall()
    return {"results": rows_to_dicts(rows)}
