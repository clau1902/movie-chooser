import { useState, useEffect, useCallback, useRef } from 'react'
import './App.css'

const API = 'http://localhost:8000'
const TMDB_IMG = 'https://image.tmdb.org/t/p/w342'
const TMDB_IMG_LG = 'https://image.tmdb.org/t/p/w500'

const GENRE_COLORS = {
  Action: '#e63946', Adventure: '#f4a261', Animation: '#2ec4b6',
  Comedy: '#f7b731', Crime: '#8b5cf6', Documentary: '#64748b',
  Drama: '#3b82f6', Fantasy: '#ec4899', 'Film-Noir': '#1e293b',
  History: '#b45309', Horror: '#dc2626', Music: '#10b981',
  Musical: '#a855f7', Mystery: '#6366f1', News: '#0ea5e9',
  Romance: '#f43f5e', 'Sci-Fi': '#06b6d4', Sport: '#84cc16',
  Thriller: '#7c3aed', War: '#6b7280', Western: '#d97706',
  'Talk-Show': '#14b8a6', 'Reality-TV': '#f59e0b', default: '#e63946',
}

const RUNTIME_BUCKETS = {
  short: { label: '< 90m', min: null, max: 89 },
  mid:   { label: '90–150m', min: 90, max: 150 },
  long:  { label: '> 150m', min: 151, max: null },
}

const DECADES = [null, 1920, 1930, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020]

function genreColor(g) { return GENRE_COLORS[g] || GENRE_COLORS.default }

// ─── Persistent state hook ────────────────────────────────────────────────────
function usePersistedState(key, defaultVal) {
  const [val, setVal] = useState(() => {
    try {
      const s = localStorage.getItem(key)
      return s !== null ? JSON.parse(s) : defaultVal
    } catch { return defaultVal }
  })
  const set = useCallback((next) => {
    setVal(prev => {
      const resolved = typeof next === 'function' ? next(prev) : next
      localStorage.setItem(key, JSON.stringify(resolved))
      return resolved
    })
  }, [key])
  return [val, set]
}

// ─── Watchlist hook ───────────────────────────────────────────────────────────
function useWatchlist() {
  const [watchlist, setWatchlist] = useState(() => {
    try { return JSON.parse(localStorage.getItem('watchlist') || '{}') }
    catch { return {} }
  })
  const toggle = useCallback((item) => {
    setWatchlist(prev => {
      const next = { ...prev }
      if (next[item.tconst]) {
        delete next[item.tconst]
      } else {
        next[item.tconst] = {
          tconst: item.tconst, primary_title: item.primary_title,
          start_year: item.start_year, genres: item.genres,
          average_rating: item.average_rating, title_type: item.title_type,
          runtime_minutes: item.runtime_minutes, num_votes: item.num_votes,
          added_at: Date.now(),
        }
      }
      localStorage.setItem('watchlist', JSON.stringify(next))
      return next
    })
  }, [])
  return { watchlist, toggle, has: (id) => !!watchlist[id] }
}

// ─── Poster batch hook ────────────────────────────────────────────────────────
function usePosterBatch(items) {
  const [posters, setPosters] = useState({})

  useEffect(() => {
    if (!items.length) return
    const tmdbKey = localStorage.getItem('tmdb_key') || ''
    const tconsts = items.map(i => i.tconst)
    fetch(`${API}/posters`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tconsts, tmdb_key: tmdbKey }),
    })
      .then(r => r.json())
      .then(d => setPosters(prev => ({ ...prev, ...(d.posters || {}) })))
      .catch(() => {})
  }, [items])

  return posters
}

// ─── Components ───────────────────────────────────────────────────────────────

function GenreBadge({ genre, small }) {
  return (
    <span className={`genre-badge ${small ? 'small' : ''}`} style={{ '--gc': genreColor(genre) }}>
      {genre}
    </span>
  )
}

function PosterPlaceholder({ title, year, genres, rating }) {
  const g = genres ? genres.split(',')[0].trim() : ''
  const color = genreColor(g)
  const initials = title
    ? title.split(' ').filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase()
    : '?'
  return (
    <div className="poster-placeholder" style={{ '--pc': color }}>
      <div className="poster-top-bar" />
      <div className="poster-initials">{initials}</div>
      {year && <div className="poster-year">{year}</div>}
      {rating && <div className="poster-rating"><span className="gold">★</span> {rating.toFixed(1)}</div>}
    </div>
  )
}

function Poster({ item, posterData, large }) {
  const [imgFailed, setImgFailed] = useState(false)
  const src = posterData?.poster_path && !imgFailed
    ? `${large ? TMDB_IMG_LG : TMDB_IMG}${posterData.poster_path}`
    : null

  if (src) {
    return <img src={src} alt={item.primary_title} className="poster-img" loading="lazy"
      onError={() => setImgFailed(true)} />
  }
  return <PosterPlaceholder title={item.primary_title} year={item.start_year}
    genres={item.genres} rating={item.average_rating} />
}

function MovieCard({ item, onClick, onToggleWatchlist, isWatchlisted, posterData }) {
  const genres = item.genres ? item.genres.split(',').slice(0, 2) : []
  const isTV = item.title_type?.startsWith('tv')

  return (
    <article className="movie-card" onClick={() => onClick(item)} tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && onClick(item)}>
      <div className="card-poster">
        <Poster item={item} posterData={posterData} />
        <div className="card-overlay">
          <div className="card-overlay-content">
            {genres.map(g => <GenreBadge key={g} genre={g.trim()} small />)}
          </div>
          <div className="card-watch-btn">View Details →</div>
        </div>
        {isTV && <div className="card-type-badge">SERIES</div>}
        <button
          className={`heart-btn ${isWatchlisted ? 'active' : ''}`}
          onClick={e => { e.stopPropagation(); onToggleWatchlist(item) }}
          aria-label={isWatchlisted ? 'Remove from watchlist' : 'Add to watchlist'}
        >
          {isWatchlisted ? '♥' : '♡'}
        </button>
      </div>
      <div className="card-info">
        <h3 className="card-title">{item.primary_title}</h3>
        <div className="card-meta">
          <span className="card-year">{item.start_year || '—'}</span>
          {item.runtime_minutes && <span className="card-runtime">{item.runtime_minutes}m</span>}
          {item.average_rating && (
            <span className="card-rating">
              <span className="gold">★</span>{item.average_rating.toFixed(1)}
            </span>
          )}
        </div>
        {item.num_votes && <div className="card-votes">{item.num_votes.toLocaleString()} votes</div>}
      </div>
    </article>
  )
}

function Modal({ item, onClose, onToggleWatchlist, isWatchlisted }) {
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [posterData, setPosterData] = useState(null)

  useEffect(() => {
    if (!item) return
    setLoading(true)
    setDetail(null)
    fetch(`${API}/title/${item.tconst}`)
      .then(r => r.json())
      .then(data => {
        setDetail(data)
        setLoading(false)
        // poster may already be in detail response (LEFT JOIN)
        if (data.poster_path) {
          setPosterData({ poster_path: data.poster_path, overview: data.overview })
        } else {
          // try to fetch
          const tmdbKey = localStorage.getItem('tmdb_key') || ''
          fetch(`${API}/posters`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tconsts: [item.tconst], tmdb_key: tmdbKey }),
          })
            .then(r => r.json())
            .then(d => setPosterData(d.posters?.[item.tconst] || null))
            .catch(() => {})
        }
      })
      .catch(() => setLoading(false))
  }, [item])

  useEffect(() => {
    const handler = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  if (!item) return null

  const genres = item.genres ? item.genres.split(',') : []
  const isTV = item.title_type?.startsWith('tv')
  const actors = detail?.cast?.filter(c =>
    c.category === 'actor' || c.category === 'actress' || c.category === 'self'
  ) || []
  const directors = detail?.crew?.director_details || []
  const overview = posterData?.overview || detail?.overview

  return (
    <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <button className="modal-close" onClick={onClose} aria-label="Close">✕</button>

        <div className="modal-hero">
          <div className="modal-poster">
            <Poster item={item} posterData={posterData} large />
          </div>
          <div className="modal-header-info">
            <div className="modal-type-row">
              <span className="modal-type">{isTV ? 'SERIES' : 'FILM'}</span>
            </div>
            <h2 className="modal-title">{item.primary_title}</h2>
            {item.original_title && item.original_title !== item.primary_title && (
              <p className="modal-original">{item.original_title}</p>
            )}
            <div className="modal-meta-row">
              {item.start_year && (
                <span>{item.start_year}{item.end_year && item.end_year !== item.start_year ? `–${item.end_year}` : ''}</span>
              )}
              {item.runtime_minutes && <span>{Math.floor(item.runtime_minutes / 60)}h {item.runtime_minutes % 60}m</span>}
              {item.average_rating && (
                <span className="modal-rating">
                  <span className="gold">★</span>{item.average_rating.toFixed(1)}
                  {item.num_votes && <small> ({item.num_votes.toLocaleString()} votes)</small>}
                </span>
              )}
            </div>
            <div className="modal-genres">
              {genres.map(g => <GenreBadge key={g} genre={g.trim()} />)}
            </div>
            {overview && <p className="modal-overview">{overview}</p>}
            <div className="modal-actions">
              <a className="imdb-link" href={`https://www.imdb.com/title/${item.tconst}`}
                target="_blank" rel="noreferrer">View on IMDB ↗</a>
              <button
                className={`watchlist-btn ${isWatchlisted ? 'active' : ''}`}
                onClick={() => onToggleWatchlist(item)}
              >
                {isWatchlisted ? '♥ Saved' : '♡ Watchlist'}
              </button>
            </div>
          </div>
        </div>

        {loading && <div className="modal-loading">Loading details…</div>}

        {!loading && detail && (
          <div className="modal-body">
            {directors.length > 0 && (
              <div className="modal-section">
                <h4 className="modal-section-title">Direction</h4>
                <div className="modal-people">
                  {directors.map(d => <span key={d.nconst} className="person-chip">{d.primary_name}</span>)}
                </div>
              </div>
            )}

            {actors.length > 0 && (
              <div className="modal-section">
                <h4 className="modal-section-title">Cast</h4>
                <div className="modal-people">
                  {actors.slice(0, 12).map(a => {
                    let charStr = ''
                    try { charStr = JSON.parse(a.characters || '[]').slice(0, 1).join(', ') } catch {}
                    return (
                      <div key={a.nconst} className="actor-chip">
                        <span className="actor-name">{a.primary_name}</span>
                        {charStr && <span className="actor-char">as {charStr}</span>}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {detail.seasons?.length > 0 && (
              <div className="modal-section">
                <h4 className="modal-section-title">Seasons</h4>
                <div className="seasons-grid">
                  {detail.seasons.map(s => (
                    <div key={s.season_number} className="season-chip">
                      <span>S{s.season_number ?? '?'}</span>
                      <span>{s.episode_count} eps</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {detail.akas?.length > 0 && (
              <div className="modal-section">
                <h4 className="modal-section-title">Also known as</h4>
                <div className="akas-list">
                  {detail.akas.slice(0, 10).map((a, i) => (
                    <span key={i} className="aka-item">
                      {a.title} {a.region && <em>({a.region})</em>}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {detail.similar?.length > 0 && (
              <div className="modal-section">
                <h4 className="modal-section-title">Similar Titles</h4>
                <div className="similar-grid">
                  {detail.similar.map(s => (
                    <div key={s.tconst} className="similar-item">
                      <span className="similar-title">{s.primary_title}</span>
                      <span className="similar-meta">
                        {s.start_year}{s.average_rating && ` · ★ ${s.average_rating}`}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function PersonSearch({ onSelect, selectedPerson, onClear }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [open, setOpen] = useState(false)
  const timerRef = useRef(null)

  const search = useCallback((q) => {
    if (!q.trim()) { setResults([]); setOpen(false); return }
    fetch(`${API}/search/people?q=${encodeURIComponent(q)}&limit=8`)
      .then(r => r.json())
      .then(d => { setResults(d.results || []); setOpen(true) })
      .catch(() => {})
  }, [])

  const handleInput = (e) => {
    const v = e.target.value
    setQuery(v)
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => search(v), 300)
  }

  const pick = (person) => {
    onSelect(person)
    setQuery(person.primary_name)
    setOpen(false)
    setResults([])
  }

  const clear = () => { setQuery(''); setResults([]); setOpen(false); onClear() }

  return (
    <div className="person-search">
      <div className="search-input-wrap">
        <span className="search-icon">⚑</span>
        <input type="text" placeholder="Search by actor or director…" value={query}
          onChange={handleInput} onFocus={() => results.length && setOpen(true)}
          className="search-input" autoComplete="off" />
        {(query || selectedPerson) && (
          <button className="search-clear" onClick={clear} aria-label="Clear">✕</button>
        )}
      </div>
      {selectedPerson && !open && (
        <div className="selected-person">
          <span>⚑ {selectedPerson.primary_name}</span>
          {selectedPerson.primary_profession && (
            <span className="person-prof">
              {selectedPerson.primary_profession.split(',').slice(0, 2).join(', ')}
            </span>
          )}
        </div>
      )}
      {open && results.length > 0 && (
        <ul className="search-dropdown">
          {results.map(p => (
            <li key={p.nconst} onClick={() => pick(p)} className="search-option">
              <span className="option-name">{p.primary_name}</span>
              {p.birth_year && <span className="option-year">b. {p.birth_year}</span>}
              {p.primary_profession && (
                <span className="option-prof">{p.primary_profession.split(',').slice(0, 2).join(', ')}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function SettingsModal({ onClose }) {
  const [key, setKey] = useState(localStorage.getItem('tmdb_key') || '')

  const save = () => {
    localStorage.setItem('tmdb_key', key.trim())
    onClose()
  }

  return (
    <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal settings-modal">
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="settings-body">
          <h2 className="settings-title">Settings</h2>

          <div className="settings-section">
            <label className="settings-label">TMDB API Key</label>
            <p className="settings-desc">
              Optional. Enables real movie posters and plot summaries.
              Get a free key at <a href="https://www.themoviedb.org/settings/api" target="_blank"
              rel="noreferrer" className="imdb-link">themoviedb.org ↗</a>
            </p>
            <div className="settings-input-row">
              <input
                type="password"
                className="settings-input"
                placeholder="Paste your TMDB API key…"
                value={key}
                onChange={e => setKey(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && save()}
              />
              <button className="settings-save-btn" onClick={save}>Save</button>
            </div>
            {localStorage.getItem('tmdb_key') && (
              <div className="settings-key-set">✓ API key is set — posters are enabled</div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Main App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [genres, setGenres] = useState([])
  const [selectedGenres, setSelectedGenres] = usePersistedState('filter_genres', [])
  const [mediaType, setMediaType] = usePersistedState('filter_mediaType', 'all')
  const [selectedPerson, setSelectedPerson] = useState(null)
  const [sortBy, setSortBy] = usePersistedState('filter_sortBy', 'votes')
  const [minRating, setMinRating] = usePersistedState('filter_minRating', 0)
  const [decade, setDecade] = usePersistedState('filter_decade', null)
  const [runtimeBucket, setRuntimeBucket] = usePersistedState('filter_runtime', null)
  const [view, setView] = usePersistedState('filter_view', 'discover')

  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(true)
  const [total, setTotal] = useState(0)

  const [selectedItem, setSelectedItem] = useState(null)
  const [surprise, setSurprise] = useState(null)
  const [surpriseLoading, setSurpriseLoading] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [apiError, setApiError] = useState(false)
  const [dbEmpty, setDbEmpty] = useState(false)

  const sentinelRef = useRef(null)
  const loadingRef = useRef(false)

  const { watchlist, toggle: toggleWatchlist, has: inWatchlist } = useWatchlist()
  const posters = usePosterBatch(results)

  // Load genres
  useEffect(() => {
    fetch(`${API}/genres?media_type=${mediaType}`)
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json() })
      .then(d => {
        const list = d.genres || []
        setGenres(list)
        setDbEmpty(list.length === 0)
      })
      .catch(() => setApiError(true))
  }, [mediaType])

  const buildParams = useCallback((pg) => {
    const params = new URLSearchParams({
      media_type: mediaType, sort_by: sortBy,
      page: pg, page_size: 24, min_rating: minRating, min_votes: 100,
    })
    if (selectedGenres.length) params.set('genres', selectedGenres.join(','))
    if (selectedPerson) params.set('person_id', selectedPerson.nconst)
    if (decade) params.set('decade', decade)
    if (runtimeBucket) {
      const b = RUNTIME_BUCKETS[runtimeBucket]
      if (b.min != null) params.set('runtime_min', b.min)
      if (b.max != null) params.set('runtime_max', b.max)
    }
    return params
  }, [mediaType, sortBy, minRating, selectedGenres, selectedPerson, decade, runtimeBucket])

  const fetchResults = useCallback(async (pg = 1, append = false) => {
    if (loadingRef.current) return
    loadingRef.current = true
    setLoading(true)
    try {
      const r = await fetch(`${API}/discover?${buildParams(pg)}`)
      if (!r.ok) throw new Error(r.status)
      const d = await r.json()
      const items = d.results || []
      setResults(prev => append ? [...prev, ...items] : items)
      setHasMore(pg < (d.total_pages || 1))
      setTotal(d.total || 0)
      setPage(pg)
    } catch { setApiError(true) }
    finally { setLoading(false); loadingRef.current = false }
  }, [buildParams])

  const fetchTopRated = useCallback(async () => {
    setLoading(true)
    const params = new URLSearchParams({ media_type: mediaType, min_votes: 10000, limit: 48 })
    if (selectedGenres.length) params.set('genre', selectedGenres[0])
    try {
      const r = await fetch(`${API}/top-rated?${params}`)
      const d = await r.json()
      setResults(d.results || [])
      setTotal(d.results?.length || 0)
      setHasMore(false)
    } catch { setApiError(true) }
    finally { setLoading(false) }
  }, [mediaType, selectedGenres])

  // Reset + fetch on filter changes
  useEffect(() => {
    setResults([])
    setPage(1)
    setHasMore(true)
    if (view === 'discover') fetchResults(1, false)
    else if (view === 'top-rated') fetchTopRated()
    // watchlist view: no fetch needed
  }, [mediaType, selectedGenres, selectedPerson, sortBy, minRating, decade, runtimeBucket, view])

  // Infinite scroll sentinel
  useEffect(() => {
    if (view !== 'discover' || !sentinelRef.current) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && hasMore && !loadingRef.current) {
          fetchResults(page + 1, true)
        }
      },
      { rootMargin: '300px' }
    )
    observer.observe(sentinelRef.current)
    return () => observer.disconnect()
  }, [view, hasMore, page, fetchResults])

  const handleSurprise = async () => {
    setSurpriseLoading(true)
    setSurprise(null)
    const params = new URLSearchParams({
      media_type: mediaType,
      min_rating: Math.max(minRating, 6.5),
      min_votes: 500,
    })
    if (selectedGenres.length) params.set('genres', selectedGenres.join(','))
    if (decade) params.set('decade', decade)
    if (runtimeBucket && RUNTIME_BUCKETS[runtimeBucket].max) {
      params.set('runtime_max', RUNTIME_BUCKETS[runtimeBucket].max)
    }
    try {
      const r = await fetch(`${API}/random?${params}`)
      const d = await r.json()
      setSurprise(d)
    } catch {}
    setSurpriseLoading(false)
  }

  const toggleGenre = (g) => setSelectedGenres(prev =>
    prev.includes(g) ? prev.filter(x => x !== g) : [...prev, g]
  )

  const displayResults = view === 'watchlist'
    ? Object.values(watchlist).sort((a, b) => b.added_at - a.added_at)
    : results

  if (apiError) {
    return (
      <div className="error-state">
        <div className="error-icon">⚡</div>
        <h1>API Offline</h1>
        <p>Start the backend to use CineMatch:</p>
        <pre>cd backend{'\n'}pip install -r requirements.txt{'\n'}python import_imdb.py   # first time only{'\n'}uvicorn main:app --reload</pre>
      </div>
    )
  }

  return (
    <>
      <header className="header">
        <div className="logo">
          <span className="logo-cine">CINE</span>
          <span className="logo-match">MATCH</span>
        </div>
        <p className="tagline">Your self-hosted movie & series oracle</p>
        <button className="settings-icon-btn" onClick={() => setShowSettings(true)} title="Settings">⚙</button>
      </header>

      <div className="controls">
        {/* Row 1: media type + view */}
        <div className="controls-row">
          <div className="media-toggle">
            {[['all', 'All'], ['movie', 'Movies'], ['series', 'Series']].map(([val, label]) => (
              <button key={val} className={`toggle-btn ${mediaType === val ? 'active' : ''}`}
                onClick={() => { setMediaType(val); setSelectedGenres([]) }}>
                {label}
              </button>
            ))}
          </div>
          <div className="view-toggle">
            {[['discover', 'Discover'], ['top-rated', 'Top Rated'], ['watchlist', `Watchlist (${Object.keys(watchlist).length})`]].map(([val, label]) => (
              <button key={val} className={`view-btn ${view === val ? 'active' : ''}`}
                onClick={() => setView(val)}>
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Person search */}
        <PersonSearch
          onSelect={p => { setSelectedPerson(p); setView('discover') }}
          selectedPerson={selectedPerson}
          onClear={() => setSelectedPerson(null)}
        />

        {/* Genres */}
        <div className="genres-section">
          <div className="genres-label">Genres</div>
          {dbEmpty ? (
            <div className="db-empty-notice">
              <span className="db-empty-icon">⚠</span>
              Backend not running — open a terminal and run:
              <code>cd backend && .venv/bin/uvicorn main:app --reload</code>
            </div>
          ) : (
            <div className="genre-pills">
              {genres.slice(0, 30).map(g => (
                <button key={g.name} className={`genre-pill ${selectedGenres.includes(g.name) ? 'active' : ''}`}
                  style={{ '--gc': genreColor(g.name) }} onClick={() => toggleGenre(g.name)}>
                  {g.name}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Sort + rating + decade + runtime */}
        {view !== 'watchlist' && (
          <div className="filter-rows">
            <div className="filter-row">
              <span className="sort-label">Sort</span>
              <div className="sort-options">
                {[['votes', 'Popular'], ['rating', 'Rating'], ['year_desc', 'Newest'], ['year_asc', 'Oldest']].map(([val, label]) => (
                  <button key={val} className={`sort-btn ${sortBy === val ? 'active' : ''}`}
                    onClick={() => setSortBy(val)}>{label}</button>
                ))}
              </div>
              <span className="sort-label">Rating</span>
              <div className="sort-options">
                {[0, 5, 6, 7, 7.5, 8].map(r => (
                  <button key={r} className={`sort-btn ${minRating === r ? 'active' : ''}`}
                    onClick={() => setMinRating(r)}>
                    {r === 0 ? 'Any' : `★ ${r}+`}
                  </button>
                ))}
              </div>
            </div>

            <div className="filter-row">
              <span className="sort-label">Decade</span>
              <div className="sort-options decade-options">
                {DECADES.map(d => (
                  <button key={d ?? 'all'} className={`sort-btn ${decade === d ? 'active' : ''}`}
                    onClick={() => setDecade(d)}>
                    {d ? `${d}s` : 'Any'}
                  </button>
                ))}
              </div>
              <span className="sort-label">Runtime</span>
              <div className="sort-options">
                <button className={`sort-btn ${runtimeBucket === null ? 'active' : ''}`}
                  onClick={() => setRuntimeBucket(null)}>Any</button>
                {Object.entries(RUNTIME_BUCKETS).map(([key, b]) => (
                  <button key={key} className={`sort-btn ${runtimeBucket === key ? 'active' : ''}`}
                    onClick={() => setRuntimeBucket(key)}>{b.label}</button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Surprise me */}
        <button className={`surprise-btn ${surpriseLoading ? 'loading' : ''}`}
          onClick={handleSurprise} disabled={surpriseLoading}>
          {surpriseLoading ? '⏳ Picking…' : '🎲 Surprise Me'}
        </button>
      </div>

      {surprise && (
        <div className="surprise-result">
          <div className="surprise-label">Your pick tonight</div>
          <button className="surprise-close" onClick={() => setSurprise(null)}>✕</button>
          <div className="surprise-card" onClick={() => { setSelectedItem(surprise); setSurprise(null) }}>
            <div className="surprise-title">{surprise.primary_title}</div>
            <div className="surprise-meta">
              {surprise.start_year} · {surprise.genres?.split(',').slice(0, 2).join(', ')}
              {surprise.average_rating && ` · ★ ${surprise.average_rating.toFixed(1)}`}
            </div>
            <span className="surprise-cta">View Details →</span>
          </div>
        </div>
      )}

      <main className="main">
        <div className="results-header">
          {view === 'watchlist'
            ? <span className="results-count">{Object.keys(watchlist).length} saved title{Object.keys(watchlist).length !== 1 ? 's' : ''}</span>
            : <span className="results-count">
                {loading && !results.length ? 'Loading…' : `${total.toLocaleString()} title${total !== 1 ? 's' : ''}`}
                {selectedGenres.length > 0 && ` · ${selectedGenres.join(', ')}`}
                {selectedPerson && ` · ${selectedPerson.primary_name}`}
                {decade && ` · ${decade}s`}
                {runtimeBucket && ` · ${RUNTIME_BUCKETS[runtimeBucket].label}`}
              </span>
          }
        </div>

        <div className="grid">
          {displayResults.map(item => (
            <MovieCard
              key={item.tconst}
              item={item}
              onClick={setSelectedItem}
              onToggleWatchlist={toggleWatchlist}
              isWatchlisted={inWatchlist(item.tconst)}
              posterData={posters[item.tconst]}
            />
          ))}
        </div>

        {!loading && displayResults.length === 0 && (
          <div className="empty-state">
            <div className="empty-icon">{view === 'watchlist' ? '🔖' : '🎬'}</div>
            <p>{view === 'watchlist' ? 'Your watchlist is empty. Heart some titles!' : 'No results found. Try different filters.'}</p>
          </div>
        )}

        {/* Infinite scroll sentinel */}
        {view === 'discover' && <div ref={sentinelRef} className="scroll-sentinel" />}
        {loading && results.length > 0 && <div className="loading-more">Loading more…</div>}
      </main>

      {selectedItem && (
        <Modal
          item={selectedItem}
          onClose={() => setSelectedItem(null)}
          onToggleWatchlist={toggleWatchlist}
          isWatchlisted={inWatchlist(selectedItem.tconst)}
        />
      )}

      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}
    </>
  )
}
