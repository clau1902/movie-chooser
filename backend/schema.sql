CREATE TABLE IF NOT EXISTS titles (
    tconst          TEXT PRIMARY KEY,
    title_type      TEXT NOT NULL,
    primary_title   TEXT NOT NULL,
    original_title  TEXT,
    start_year      INTEGER,
    end_year        INTEGER,
    runtime_minutes INTEGER,
    genres          TEXT,
    search_vector   tsvector
);

CREATE TABLE IF NOT EXISTS ratings (
    tconst          TEXT PRIMARY KEY,
    average_rating  REAL NOT NULL,
    num_votes       INTEGER NOT NULL
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
    PRIMARY KEY (tconst, ordering)
);

CREATE TABLE IF NOT EXISTS crew (
    tconst      TEXT PRIMARY KEY,
    directors   TEXT,
    writers     TEXT
);

CREATE TABLE IF NOT EXISTS episodes (
    tconst          TEXT PRIMARY KEY,
    parent_tconst   TEXT NOT NULL,
    season_number   INTEGER,
    episode_number  INTEGER
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
    PRIMARY KEY (tconst, ordering)
);

CREATE TABLE IF NOT EXISTS posters (
    tconst        TEXT PRIMARY KEY,
    poster_path   TEXT,
    overview      TEXT,
    tmdb_id       INTEGER,
    fetched_at    INTEGER NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_titles_type       ON titles(title_type);
CREATE INDEX IF NOT EXISTS idx_titles_year       ON titles(start_year);
CREATE INDEX IF NOT EXISTS idx_titles_genres     ON titles(genres);
CREATE INDEX IF NOT EXISTS idx_ratings_avg       ON ratings(average_rating DESC);
CREATE INDEX IF NOT EXISTS idx_ratings_votes     ON ratings(num_votes DESC);
CREATE INDEX IF NOT EXISTS idx_principals_nconst ON principals(nconst);
CREATE INDEX IF NOT EXISTS idx_principals_tconst ON principals(tconst);
CREATE INDEX IF NOT EXISTS idx_people_name       ON people(lower(primary_name));
CREATE INDEX IF NOT EXISTS idx_episodes_parent   ON episodes(parent_tconst);
CREATE INDEX IF NOT EXISTS idx_akas_region       ON akas(region);
CREATE INDEX IF NOT EXISTS idx_titles_fts        ON titles USING GIN(search_vector);
