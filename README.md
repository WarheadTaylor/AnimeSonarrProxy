# AnimeSonarrProxy

AnimeSonarrProxy is a FastAPI Torznab proxy for anime automation. It accepts
Sonarr and Radarr Torznab requests, resolves the requested media to anime-friendly
titles, searches Nyaa RSS directly, parses Nyaa release titles, filters uncertain
matches, and returns manager-friendly release titles.

## Core Flow

```text
Sonarr/Radarr -> /api Torznab request
              -> metadata resolver
              -> direct Nyaa RSS search
              -> anime release parser
              -> confident match filter
              -> normalized Torznab RSS
```

The returned RSS title is intentionally not always the original Nyaa title. The
proxy preserves the original Nyaa title internally and returns a normalized title
that Sonarr or Radarr can parse more reliably.

Examples:

```text
[SubsPlease] One Piece - S23E01 - 1156 (1080p)
Suzume (2022) [1080p][BDRip] -Group
```

## Supported API

All endpoints are served from `GET /api`.

| Query | Purpose |
| --- | --- |
| `t=caps` | Torznab capabilities. |
| `t=tvsearch&tvdbid=&season=&ep=` | Sonarr episode search. |
| `t=movie&tmdbid=` | Radarr movie search by TMDB ID. |
| `t=movie&imdbid=` | Radarr movie search by IMDb ID. |
| `t=movie&q=&year=` | Radarr/manual movie title fallback. |
| `t=search&q=` | Guarded generic/manual search and indexer tests. |

Searches other than `caps` require `apikey`.

## Metadata Sources

- `anime-offline-database` provides TVDB/TMDB/IMDb title mappings.
- TheXEM provides TVDB season/episode to anime absolute episode conversion.
- Optional Sonarr API integration confirms series title, season/episode, absolute
  episode number, and specials.
- Optional Radarr API integration confirms movie title, alternate titles, IDs, and
  year.

Manual mapping overrides and the old WebUI are not part of v1 of the rewrite.

## Nyaa Defaults

The proxy searches Nyaa directly. Default settings are conservative:

```env
NYAA_URL=https://nyaa.si
NYAA_CATEGORY=1_2
NYAA_NO_REMAKES=true
NYAA_TRUSTED_ONLY=false
```

`NYAA_CATEGORY=1_2` searches Anime English-translated releases. If
`NYAA_TRUSTED_ONLY=true`, the trusted-only Nyaa filter is used instead of
no-remakes.

## Configuration

Required:

| Variable | Description |
| --- | --- |
| `API_KEY` | Torznab API key configured in Sonarr/Radarr. |

Optional:

| Variable | Default |
| --- | --- |
| `HOST` | `0.0.0.0` |
| `PORT` | `8000` |
| `SONARR_URL` / `SONARR_API_KEY` | unset |
| `RADARR_URL` / `RADARR_API_KEY` | unset |
| `DATA_DIR` | `/app/data` |
| `ANIME_DB_UPDATE_INTERVAL` | `86400` |
| `CACHE_TTL` | `3600` |
| `MAX_RESULTS_PER_QUERY` | `100` |
| `TORZNAB_DEFAULT_LANGUAGE` | `English` |
| `LOG_LEVEL` | `INFO` |

## Sonarr Setup

Add a custom Torznab indexer:

- URL: `http://your-server-ip:8000`
- API path: `/api`
- API key: `API_KEY`
- Categories: `5070`

For best episode matching, configure `SONARR_URL` and `SONARR_API_KEY`.

## Radarr Setup

Add a custom Torznab indexer:

- URL: `http://your-server-ip:8000`
- API path: `/api`
- API key: `API_KEY`
- Categories: `2000,2060`

For best movie title/year matching, configure `RADARR_URL` and `RADARR_API_KEY`.

## Development

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Run tests:

```bash
python -m pytest
```

Build Docker image:

```bash
docker build -t animesonarrproxy .
docker-compose up -d --build
```
