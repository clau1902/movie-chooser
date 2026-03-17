"""
Movie Chooser API
Self-hosted movie/series database powered by IMDB public datasets.
"""

from contextlib import asynccontextmanager
from typing import Optional, List
import math
import os
import time

import httpx
import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://cinematch:cinematch@db:5432/cinematch")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")

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


class _Conn:
    """Thin wrapper giving psycopg2 a sqlite3-compatible execute() interface."""
    def __init__(self, conn):
        self._conn = conn
        self._cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    def execute(self, sql, args=()):
        self._cur.execute(sql, args)
        return self._cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        try:
            self._cur.close()
            self._conn.close()
        except Exception:
            pass


def get_db():
    return _Conn(psycopg2.connect(DATABASE_URL))


def get_write_db():
    return _Conn(psycopg2.connect(DATABASE_URL))


def has_fts(conn) -> bool:
    return conn.execute(
        "SELECT EXISTS(SELECT 1 FROM titles WHERE search_vector IS NOT NULL)"
    ).fetchone()[0]


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        conn = get_write_db()
        count = conn.execute("SELECT COUNT(*) FROM titles").fetchone()[0]
        print(f"Database: {count:,} titles")
        if count == 0:
            print("WARNING: Database is empty — run: python import_imdb.py")
        else:
            print(f"FTS search: {'enabled' if has_fts(conn) else 'disabled (ILIKE fallback)'}")
        conn.close()
    except Exception as e:
        print(f"WARNING: Could not connect to database: {e}")
        print("Make sure PostgreSQL is running and DATABASE_URL is correct.")
        print("Then run: python import_imdb.py")
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
    placeholders = ",".join(["%s"] * len(types))
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
            db.rollback()
            result[table] = 0

    types = db.execute(
        "SELECT title_type, COUNT(*) as n FROM titles GROUP BY title_type ORDER BY n DESC"
    ).fetchall()
    result["by_type"] = {r["title_type"]: r["n"] for r in types}
    result["has_fts"] = has_fts(db)

    try:
        db_size = db.execute("SELECT pg_database_size(current_database())").fetchone()[0]
        result["db_size_mb"] = round(db_size / 1024 / 1024, 1)
    except Exception:
        result["db_size_mb"] = 0

    db.close()
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

    db.close()
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
            conditions.append("t.genres ILIKE %s")
            args.append(f"%{g}%")

    if person_id:
        conditions.append("p.nconst = %s")
        args.append(person_id)

    if decade:
        conditions.append("t.start_year >= %s AND t.start_year < %s")
        args += [decade, decade + 10]
    else:
        if year_from:
            conditions.append("t.start_year >= %s")
            args.append(year_from)
        if year_to:
            conditions.append("t.start_year <= %s")
            args.append(year_to)

    if runtime_min is not None:
        conditions.append("t.runtime_minutes >= %s")
        args.append(runtime_min)
    if runtime_max is not None:
        conditions.append("t.runtime_minutes <= %s")
        args.append(runtime_max)

    if min_rating > 0:
        conditions.append("r.average_rating >= %s")
        args.append(min_rating)

    conditions.append("r.num_votes >= %s")
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
        LIMIT %s OFFSET %s
        """,
        args + [page_size, offset],
    ).fetchall()

    db.close()
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

    if has_fts(db):
        try:
            rows = db.execute(
                f"""
                SELECT DISTINCT t.tconst, t.primary_title, t.original_title,
                    t.title_type, t.start_year, t.end_year,
                    t.runtime_minutes, t.genres,
                    r.average_rating, r.num_votes
                FROM titles t
                LEFT JOIN ratings r ON r.tconst = t.tconst
                WHERE t.search_vector @@ plainto_tsquery('english', %s) AND {type_filter}
                ORDER BY ts_rank(t.search_vector, plainto_tsquery('english', %s)) DESC,
                         r.num_votes DESC NULLS LAST
                LIMIT %s OFFSET %s
                """,
                [q] + type_args + [q, page_size, offset],
            ).fetchall()
            total = db.execute(
                f"""
                SELECT COUNT(DISTINCT t.tconst) FROM titles t
                WHERE t.search_vector @@ plainto_tsquery('english', %s) AND {type_filter}
                """,
                [q] + type_args,
            ).fetchone()[0]
            db.close()
            return {
                "page": page, "page_size": page_size, "total": total,
                "total_pages": math.ceil(total / page_size) if total else 1,
                "results": rows_to_dicts(rows),
            }
        except Exception:
            pass  # fall through to ILIKE

    pattern = f"%{q}%"
    rows = db.execute(
        f"""
        SELECT DISTINCT t.tconst, t.primary_title, t.original_title,
            t.title_type, t.start_year, t.end_year, t.runtime_minutes, t.genres,
            r.average_rating, r.num_votes
        FROM titles t
        LEFT JOIN ratings r ON r.tconst = t.tconst
        WHERE {type_filter} AND (t.primary_title ILIKE %s OR t.original_title ILIKE %s)
        ORDER BY r.num_votes DESC NULLS LAST
        LIMIT %s OFFSET %s
        """,
        type_args + [pattern, pattern, page_size, offset],
    ).fetchall()
    total = db.execute(
        f"SELECT COUNT(*) FROM titles t WHERE {type_filter} AND (t.primary_title ILIKE %s OR t.original_title ILIKE %s)",
        type_args + [pattern, pattern],
    ).fetchone()[0]

    db.close()
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
        WHERE p.primary_name ILIKE %s
        ORDER BY (SELECT COUNT(*) FROM principals pr WHERE pr.nconst = p.nconst) DESC
        LIMIT %s
        """,
        [f"%{q}%", limit],
    ).fetchall()
    db.close()
    return {"results": rows_to_dicts(rows)}


@app.get("/title/{tconst}")
def get_title(tconst: str):
    db = get_db()

    title = db.execute(
        """
        SELECT t.tconst, t.title_type, t.primary_title, t.original_title,
               t.start_year, t.end_year, t.runtime_minutes, t.genres,
               r.average_rating, r.num_votes,
               p.poster_path, p.overview, p.tmdb_id
        FROM titles t
        LEFT JOIN ratings r ON r.tconst = t.tconst
        LEFT JOIN posters p ON p.tconst = t.tconst
        WHERE t.tconst = %s
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
        WHERE pr.tconst = %s
        ORDER BY pr.ordering
        LIMIT 30
        """,
        [tconst],
    ).fetchall()
    result["cast"] = rows_to_dicts(cast)

    crew = db.execute("SELECT * FROM crew WHERE tconst = %s", [tconst]).fetchone()
    if crew:
        crew_dict = dict(crew)
        if crew_dict.get("directors"):
            dir_ids = crew_dict["directors"].split(",")[:5]
            crew_dict["director_details"] = rows_to_dicts(db.execute(
                f"SELECT nconst, primary_name FROM people WHERE nconst IN ({','.join(['%s']*len(dir_ids))})",
                dir_ids,
            ).fetchall())
        if crew_dict.get("writers"):
            wri_ids = crew_dict["writers"].split(",")[:5]
            crew_dict["writer_details"] = rows_to_dicts(db.execute(
                f"SELECT nconst, primary_name FROM people WHERE nconst IN ({','.join(['%s']*len(wri_ids))})",
                wri_ids,
            ).fetchall())
        result["crew"] = crew_dict

    if result.get("title_type") in ("tvSeries", "tvMiniSeries"):
        result["seasons"] = rows_to_dicts(db.execute(
            """
            SELECT season_number, COUNT(*) as episode_count
            FROM episodes WHERE parent_tconst = %s
            GROUP BY season_number ORDER BY season_number
            """,
            [tconst],
        ).fetchall())

    result["akas"] = rows_to_dicts(db.execute(
        "SELECT title, region, language, types FROM akas WHERE tconst = %s AND region IS NOT NULL ORDER BY is_original DESC LIMIT 20",
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
            WHERE t.tconst != %s AND t.title_type = %s AND t.genres ILIKE %s AND r.num_votes >= 1000
            ORDER BY r.average_rating DESC
            LIMIT 8
            """,
            [tconst, result["title_type"], f"%{first_genre}%"],
        ).fetchall())

    db.close()
    return result


@app.get("/person/{nconst}")
def get_person(nconst: str, limit: int = Query(20, ge=1, le=100)):
    db = get_db()
    person = db.execute("SELECT * FROM people WHERE nconst = %s", [nconst]).fetchone()
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
        WHERE pr.nconst = %s
        ORDER BY r.num_votes DESC NULLS LAST
        LIMIT %s
        """,
        [nconst, limit],
    ).fetchall())
    db.close()
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
            f"SELECT tconst, poster_path, overview, tmdb_id FROM posters WHERE tconst IN ({','.join(['%s']*len(tconsts))})",
            tconsts,
        ).fetchall()
    }

    missing = [t for t in tconsts if t not in cached]

    key = body.tmdb_key or TMDB_API_KEY
    if missing and key:
        db_w = get_write_db()
        async with httpx.AsyncClient(timeout=5) as client:
            for tconst in missing:
                try:
                    resp = await client.get(
                        f"{TMDB_BASE}/find/{tconst}",
                        params={"api_key": key, "external_source": "imdb_id"},
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
                        """INSERT INTO posters (tconst, poster_path, overview, tmdb_id, fetched_at)
                           VALUES (%s, %s, %s, %s, %s)
                           ON CONFLICT (tconst) DO UPDATE SET
                           poster_path = EXCLUDED.poster_path,
                           overview    = EXCLUDED.overview,
                           tmdb_id     = EXCLUDED.tmdb_id,
                           fetched_at  = EXCLUDED.fetched_at""",
                        [tconst, poster_path, overview, tmdb_id, int(time.time())],
                    )
                    db_w.commit()
                    cached[tconst] = {
                        "tconst": tconst, "poster_path": poster_path,
                        "overview": overview, "tmdb_id": tmdb_id,
                    }
                except Exception:
                    continue
        db_w.close()

    db.close()
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

    conditions = [type_filter, "r.tconst IS NOT NULL", "r.average_rating >= %s", "r.num_votes >= %s"]
    args = type_args + [min_rating, min_votes]

    if genres:
        for g in genres.split(","):
            g = g.strip()
            if g:
                conditions.append("t.genres ILIKE %s")
                args.append(f"%{g}%")

    if decade:
        conditions.append("t.start_year >= %s AND t.start_year < %s")
        args += [decade, decade + 10]

    if runtime_max:
        conditions.append("t.runtime_minutes <= %s")
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

    db.close()
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

    conditions = [type_filter, "r.tconst IS NOT NULL", "r.num_votes >= %s"]
    args = type_args + [min_votes]

    if genre:
        conditions.append("t.genres ILIKE %s")
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
        LIMIT %s
        """,
        args + [limit],
    ).fetchall()
    db.close()
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
        conditions.append("t.start_year = %s")
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
        LIMIT %s
        """,
        args + [limit],
    ).fetchall()
    db.close()
    return {"results": rows_to_dicts(rows)}
