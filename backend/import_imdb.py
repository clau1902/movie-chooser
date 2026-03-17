#!/usr/bin/env python3
"""
IMDB Dataset Importer
Downloads and imports all IMDB public datasets into PostgreSQL.

Datasets used (all free, updated daily by IMDB):
  https://datasets.imdbws.com/
"""

import gzip
import io
import os
import sys
import time
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
import requests
from tqdm import tqdm

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://cinematch:cinematch@localhost:5432/cinematch")
SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DATA_DIR = Path(__file__).parent / "imdb_data"

DATASETS = {
    "title.basics":     "https://datasets.imdbws.com/title.basics.tsv.gz",
    "title.ratings":    "https://datasets.imdbws.com/title.ratings.tsv.gz",
    "name.basics":      "https://datasets.imdbws.com/name.basics.tsv.gz",
    "title.principals": "https://datasets.imdbws.com/title.principals.tsv.gz",
    "title.crew":       "https://datasets.imdbws.com/title.crew.tsv.gz",
    "title.episode":    "https://datasets.imdbws.com/title.episode.tsv.gz",
    "title.akas":       "https://datasets.imdbws.com/title.akas.tsv.gz",
}

DEFAULT_TYPES = {
    "movie", "tvMovie", "tvSeries", "tvMiniSeries",
    "tvSpecial", "video", "short", "tvShort",
}

NULL = "\\N"


def null(v):
    return None if v == NULL or v == "" else v


def null_int(v):
    x = null(v)
    return int(x) if x is not None else None


def null_float(v):
    x = null(v)
    return float(x) if x is not None else None


def download(name, url, force=False):
    DATA_DIR.mkdir(exist_ok=True)
    dest = DATA_DIR / f"{name}.tsv.gz"
    if dest.exists() and not force:
        print(f"  [skip] {name} already downloaded ({dest.stat().st_size // 1024 // 1024} MB)")
        return dest

    print(f"  Downloading {name}...")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with open(dest, "wb") as f, tqdm(total=total, unit="B", unit_scale=True, desc=name) as bar:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                f.write(chunk)
                bar.update(len(chunk))
    return dest


def iter_tsv(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        header = f.readline().strip().split("\t")
        for line in f:
            values = line.rstrip("\n").split("\t")
            yield dict(zip(header, values))


def create_schema(conn):
    print("Creating schema...")
    cur = conn.cursor()
    with open(SCHEMA_PATH) as f:
        sql = f.read()
    for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
        cur.execute(stmt)
    conn.commit()
    cur.close()


def import_titles(conn, path, allowed_types):
    print("Importing titles...")
    cur = conn.cursor()
    batch = []
    count = 0
    skipped = 0

    for row in tqdm(iter_tsv(path), desc="titles"):
        t = row["titleType"]
        if t not in allowed_types:
            skipped += 1
            continue
        if row.get("isAdult") == "1":
            skipped += 1
            continue

        batch.append((
            row["tconst"], t,
            row["primaryTitle"],
            null(row.get("originalTitle")),
            null_int(row.get("startYear")),
            null_int(row.get("endYear")),
            null_int(row.get("runtimeMinutes")),
            null(row.get("genres")),
        ))
        count += 1

        if len(batch) >= 50_000:
            execute_values(cur,
                "INSERT INTO titles (tconst, title_type, primary_title, original_title, start_year, end_year, runtime_minutes, genres) VALUES %s ON CONFLICT DO NOTHING",
                batch)
            conn.commit()
            batch.clear()

    if batch:
        execute_values(cur,
            "INSERT INTO titles (tconst, title_type, primary_title, original_title, start_year, end_year, runtime_minutes, genres) VALUES %s ON CONFLICT DO NOTHING",
            batch)
        conn.commit()

    cur.close()
    print(f"  -> {count:,} titles imported, {skipped:,} skipped")


def import_ratings(conn, path):
    print("Importing ratings...")
    cur = conn.cursor()
    batch = []
    count = 0

    for row in tqdm(iter_tsv(path), desc="ratings"):
        batch.append((row["tconst"], null_float(row["averageRating"]), null_int(row["numVotes"])))
        count += 1

        if len(batch) >= 50_000:
            execute_values(cur,
                "INSERT INTO ratings (tconst, average_rating, num_votes) VALUES %s ON CONFLICT DO NOTHING",
                batch)
            conn.commit()
            batch.clear()

    if batch:
        execute_values(cur,
            "INSERT INTO ratings (tconst, average_rating, num_votes) VALUES %s ON CONFLICT DO NOTHING",
            batch)
        conn.commit()

    cur.close()
    print(f"  -> {count:,} ratings imported")


def import_people(conn, path):
    print("Importing people...")
    cur = conn.cursor()
    batch = []
    count = 0

    for row in tqdm(iter_tsv(path), desc="people"):
        batch.append((
            row["nconst"], row["primaryName"],
            null_int(row.get("birthYear")), null_int(row.get("deathYear")),
            null(row.get("primaryProfession")), null(row.get("knownForTitles")),
        ))
        count += 1

        if len(batch) >= 50_000:
            execute_values(cur,
                "INSERT INTO people (nconst, primary_name, birth_year, death_year, primary_profession, known_for_titles) VALUES %s ON CONFLICT DO NOTHING",
                batch)
            conn.commit()
            batch.clear()

    if batch:
        execute_values(cur,
            "INSERT INTO people (nconst, primary_name, birth_year, death_year, primary_profession, known_for_titles) VALUES %s ON CONFLICT DO NOTHING",
            batch)
        conn.commit()

    cur.close()
    print(f"  -> {count:,} people imported")


def import_principals(conn, path):
    print("Importing principals (cast/crew)...")
    cur = conn.cursor()
    KEEP_CATEGORIES = {
        "actor", "actress", "self", "director", "writer",
        "producer", "composer", "cinematographer",
    }
    batch = []
    count = 0
    skipped = 0

    for row in tqdm(iter_tsv(path), desc="principals"):
        cat = row.get("category", "")
        if cat not in KEEP_CATEGORIES:
            skipped += 1
            continue

        batch.append((
            row["tconst"], null_int(row["ordering"]), row["nconst"],
            null(cat), null(row.get("job")), null(row.get("characters")),
        ))
        count += 1

        if len(batch) >= 50_000:
            execute_values(cur,
                "INSERT INTO principals (tconst, ordering, nconst, category, job, characters) VALUES %s ON CONFLICT DO NOTHING",
                batch)
            conn.commit()
            batch.clear()

    if batch:
        execute_values(cur,
            "INSERT INTO principals (tconst, ordering, nconst, category, job, characters) VALUES %s ON CONFLICT DO NOTHING",
            batch)
        conn.commit()

    cur.close()
    print(f"  -> {count:,} principal entries imported, {skipped:,} skipped")


def import_crew(conn, path):
    print("Importing crew (directors/writers)...")
    cur = conn.cursor()
    batch = []
    count = 0

    for row in tqdm(iter_tsv(path), desc="crew"):
        batch.append((row["tconst"], null(row.get("directors")), null(row.get("writers"))))
        count += 1

        if len(batch) >= 50_000:
            execute_values(cur,
                "INSERT INTO crew (tconst, directors, writers) VALUES %s ON CONFLICT DO NOTHING",
                batch)
            conn.commit()
            batch.clear()

    if batch:
        execute_values(cur,
            "INSERT INTO crew (tconst, directors, writers) VALUES %s ON CONFLICT DO NOTHING",
            batch)
        conn.commit()

    cur.close()
    print(f"  -> {count:,} crew records imported")


def import_episodes(conn, path):
    print("Importing episode data...")
    cur = conn.cursor()
    batch = []
    count = 0

    for row in tqdm(iter_tsv(path), desc="episodes"):
        batch.append((
            row["tconst"], row["parentTconst"],
            null_int(row.get("seasonNumber")), null_int(row.get("episodeNumber")),
        ))
        count += 1

        if len(batch) >= 50_000:
            execute_values(cur,
                "INSERT INTO episodes (tconst, parent_tconst, season_number, episode_number) VALUES %s ON CONFLICT DO NOTHING",
                batch)
            conn.commit()
            batch.clear()

    if batch:
        execute_values(cur,
            "INSERT INTO episodes (tconst, parent_tconst, season_number, episode_number) VALUES %s ON CONFLICT DO NOTHING",
            batch)
        conn.commit()

    cur.close()
    print(f"  -> {count:,} episodes imported")


def import_akas(conn, path):
    print("Importing alternative titles (akas)...")
    cur = conn.cursor()
    batch = []
    count = 0

    for row in tqdm(iter_tsv(path), desc="akas"):
        batch.append((
            row["titleId"], null_int(row["ordering"]),
            null(row.get("title")), null(row.get("region")), null(row.get("language")),
            null(row.get("types")), null(row.get("attributes")),
            1 if row.get("isOriginalTitle") == "1" else 0,
        ))
        count += 1

        if len(batch) >= 50_000:
            execute_values(cur,
                "INSERT INTO akas (tconst, ordering, title, region, language, types, attributes, is_original) VALUES %s ON CONFLICT DO NOTHING",
                batch)
            conn.commit()
            batch.clear()

    if batch:
        execute_values(cur,
            "INSERT INTO akas (tconst, ordering, title, region, language, types, attributes, is_original) VALUES %s ON CONFLICT DO NOTHING",
            batch)
        conn.commit()

    cur.close()
    print(f"  -> {count:,} aka entries imported")


def build_fts_index(conn):
    print("Building full-text search index (this may take a few minutes)...")
    cur = conn.cursor()
    cur.execute("""
        UPDATE titles
        SET search_vector = to_tsvector('english',
            coalesce(primary_title, '') || ' ' || coalesce(original_title, ''))
    """)
    conn.commit()
    cur.close()
    print("  -> FTS index built")


def print_stats(conn):
    cur = conn.cursor()
    print("\n=== Database Statistics ===")
    for table in ["titles", "ratings", "people", "principals", "crew", "episodes", "akas"]:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"  {table:20s}: {cur.fetchone()[0]:>10,}")

    print("\n  Title types breakdown:")
    cur.execute("SELECT title_type, COUNT(*) as n FROM titles GROUP BY title_type ORDER BY n DESC")
    for row in cur.fetchall():
        print(f"    {row[0]:20s}: {row[1]:>8,}")

    cur.execute("SELECT pg_database_size(current_database())")
    db_size = cur.fetchone()[0]
    print(f"\n  DB size: {db_size / 1024 / 1024:.1f} MB")
    cur.close()


def main():
    force = "--force" in sys.argv
    skip_akas = "--skip-akas" in sys.argv
    all_types = "--all-types" in sys.argv
    allowed_types = None if all_types else DEFAULT_TYPES

    print("=" * 60)
    print("  IMDB Dataset Importer")
    print("=" * 60)
    print(f"  Database: {DATABASE_URL}")
    print(f"  Force re-download: {force}")
    print()

    print("Step 1: Downloading datasets...")
    files = {}
    for name, url in DATASETS.items():
        if skip_akas and name == "title.akas":
            continue
        files[name] = download(name, url, force=force)

    conn = psycopg2.connect(DATABASE_URL)

    print("\nStep 2: Creating schema...")
    create_schema(conn)

    print("\nStep 3: Importing data...")
    t0 = time.time()

    import_titles(conn, files["title.basics"], allowed_types or DEFAULT_TYPES)
    import_ratings(conn, files["title.ratings"])
    import_people(conn, files["name.basics"])
    import_principals(conn, files["title.principals"])
    import_crew(conn, files["title.crew"])
    import_episodes(conn, files["title.episode"])
    if "title.akas" in files:
        import_akas(conn, files["title.akas"])

    build_fts_index(conn)

    elapsed = time.time() - t0
    print(f"\nImport completed in {elapsed:.0f}s ({elapsed/60:.1f} min)")

    print_stats(conn)
    conn.close()
    print("\nDone! Start the app with: docker compose up")


if __name__ == "__main__":
    main()
