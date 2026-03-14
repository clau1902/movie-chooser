PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-64000;
PRAGMA temp_store=MEMORY;

CREATE TABLE IF NOT EXISTS titles (
    tconst          TEXT PRIMARY KEY,
    title_type      TEXT NOT NULL,
    primary_title   TEXT NOT NULL,
    original_title  TEXT,
    start_year      INTEGER,
    end_year        INTEGER,
    runtime_minutes INTEGER,
    genres          TEXT
);

CREATE TABLE IF NOT EXISTS ratings (
    tconst          TEXT PRIMARY KEY,
    average_rating  REAL NOT NULL,
    num_votes       INTEGER NOT NULL,
    FOREIGN KEY (tconst) REFERENCES titles(tconst)
);

CREATE TABLE IF NOT EXISTS people (
    nconst              TEXT PRIMARY KEY,
    primary_name        TEXT NOT NULL,
    birth_year          INTEGER,
    death_year          INTEGER,
    primary_profession  TEXT,
    known_for_titles    TEXT
);

CREATE TABLE IF NOT EXISTS principals (
    tconst      TEXT NOT NULL,
    ordering    INTEGER NOT NULL,
    nconst      TEXT NOT NULL,
    category    TEXT,
    job         TEXT,
    characters  TEXT,
    PRIMARY KEY (tconst, ordering),
    FOREIGN KEY (tconst) REFERENCES titles(tconst),
    FOREIGN KEY (nconst) REFERENCES people(nconst)
);

CREATE TABLE IF NOT EXISTS crew (
    tconst      TEXT PRIMARY KEY,
    directors   TEXT,
    writers     TEXT,
    FOREIGN KEY (tconst) REFERENCES titles(tconst)
);

CREATE TABLE IF NOT EXISTS episodes (
    tconst          TEXT PRIMARY KEY,
    parent_tconst   TEXT NOT NULL,
    season_number   INTEGER,
    episode_number  INTEGER,
    FOREIGN KEY (tconst) REFERENCES titles(tconst),
    FOREIGN KEY (parent_tconst) REFERENCES titles(tconst)
);

CREATE TABLE IF NOT EXISTS akas (
    tconst      TEXT NOT NULL,
    ordering    INTEGER NOT NULL,
    title       TEXT,
    region      TEXT,
    language    TEXT,
    types       TEXT,
    attributes  TEXT,
    is_original INTEGER DEFAULT 0,
    PRIMARY KEY (tconst, ordering),
    FOREIGN KEY (tconst) REFERENCES titles(tconst)
);

CREATE TABLE IF NOT EXISTS posters (
    tconst        TEXT PRIMARY KEY,
    poster_path   TEXT,
    overview      TEXT,
    tmdb_id       INTEGER,
    fetched_at    INTEGER NOT NULL,
    FOREIGN KEY (tconst) REFERENCES titles(tconst)
);

CREATE VIRTUAL TABLE IF NOT EXISTS titles_fts USING fts5(
    tconst        UNINDEXED,
    primary_title,
    original_title,
    content='titles',
    content_rowid='rowid'
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_titles_type       ON titles(title_type);
CREATE INDEX IF NOT EXISTS idx_titles_year       ON titles(start_year);
CREATE INDEX IF NOT EXISTS idx_titles_genres     ON titles(genres);
CREATE INDEX IF NOT EXISTS idx_ratings_avg       ON ratings(average_rating DESC);
CREATE INDEX IF NOT EXISTS idx_ratings_votes     ON ratings(num_votes DESC);
CREATE INDEX IF NOT EXISTS idx_principals_nconst ON principals(nconst);
CREATE INDEX IF NOT EXISTS idx_principals_tconst ON principals(tconst);
CREATE INDEX IF NOT EXISTS idx_people_name       ON people(primary_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_episodes_parent   ON episodes(parent_tconst);
CREATE INDEX IF NOT EXISTS idx_akas_region       ON akas(region);
