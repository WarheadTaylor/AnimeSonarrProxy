# AnimeSonarrProxy

AnimeSonarrProxy is a FastAPI proxy for anime automation. It accepts Sonarr and
Radarr Torznab requests, resolves the requested media to anime-friendly titles,
searches Nyaa RSS directly, parses release titles, filters uncertain matches,
and returns manager-friendly release titles. It can also expose a separate
Newznab endpoint for Sonarr that searches configurable upstream Newznab providers
such as NZBGeek.

## Core Flow

```text
Sonarr/Radarr -> /api Torznab request
              -> metadata resolver
              -> direct Nyaa RSS search
              -> anime release parser
              -> confident match filter
              -> normalized Torznab RSS

Sonarr        -> /newznab Newznab request
              -> metadata resolver
              -> upstream Newznab provider search
              -> anime release parser
              -> confident match filter
              -> normalized Newznab RSS
              -> proxied upstream NZB download
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

Torznab endpoints are served from `GET /api`.

| Query | Purpose |
| --- | --- |
| `t=caps` | Torznab capabilities. |
| `t=tvsearch&tvdbid=&season=&ep=` | Sonarr episode search. |
| `t=movie&tmdbid=` | Radarr movie search by TMDB ID. |
| `t=movie&imdbid=` | Radarr movie search by IMDb ID. |
| `t=movie&q=&year=` | Radarr/manual movie title fallback. |
| `t=search&q=` | Guarded generic/manual search and indexer tests. |

Searches other than `caps` require `apikey`.

Newznab endpoints are served from `GET /newznab`.

| Query | Purpose |
| --- | --- |
| `t=caps` | Newznab capabilities. |
| `t=tvsearch&tvdbid=&season=&ep=` | Sonarr episode search through upstream Newznab providers. |
| `t=search&q=` | Generic/manual upstream Newznab search and indexer tests. |
| `t=get&provider=&id=` | Proxied NZB download from the selected upstream provider. |

Newznab searches and downloads require the local `apikey`. Upstream provider API
keys are configured server-side and are not returned to Sonarr in RSS links.

## Metadata Sources

- `anime-offline-database` provides TVDB/TMDB/IMDb title mappings.
- TheXEM provides TVDB season/episode to anime absolute episode conversion.
- Optional Sonarr API integration confirms series title, season/episode, absolute
  episode number, and specials.
- Optional Radarr API integration confirms movie title, alternate titles, IDs, and
  year.

Manual mapping overrides and the old WebUI are not part of v1 of the rewrite.

## Nyaa Defaults

The proxy searches Nyaa directly when the Torznab request includes a supported
category:

| Torznab category | Nyaa category |
| --- | --- |
| `5070` Anime | `1_2` Anime English-translated |
| `2060` Movies/Anime | `1_2` Anime English-translated |
| `100041` Live Action/English-translated | `4_1` Live Action English-translated |

If no supported category is selected, the proxy does not search Nyaa.

Default settings are conservative:

```env
NYAA_URL=https://nyaa.si
NYAA_NO_REMAKES=true
NYAA_TRUSTED_ONLY=false
```

If `NYAA_TRUSTED_ONLY=true`, the trusted-only Nyaa filter is used instead of
no-remakes. Otherwise `NYAA_NO_REMAKES=true` uses Nyaa's no-remakes filter for
selected categories.

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
| `NEWZNAB_URL` / `NEWZNAB_API_KEY` | unset |
| `NEWZNAB_ID` | `newznab` |
| `NEWZNAB_NAME` | `Newznab` |
| `NEWZNAB_CATEGORIES` | `5070` |
| `NEWZNAB_PROVIDERS` | unset |
| `NEWZNAB_MAX_QUERY_VARIANTS` | `8` |
| `NEWZNAB_DEFAULT_CATEGORIES` | `5070` |
| `PUBLIC_BASE_URL` | unset |
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

## Sonarr Newznab Setup

Add a custom Newznab indexer:

- URL: `http://your-server-ip:8000`
- API path: `/newznab`
- API key: `API_KEY`
- Categories: `5070`

Configure one upstream Newznab provider with simple env vars:

```env
NEWZNAB_URL=https://api.nzbgeek.info
NEWZNAB_API_KEY=your_nzbgeek_api_key
NEWZNAB_ID=nzbgeek
NEWZNAB_NAME=NZBGeek
NEWZNAB_CATEGORIES=5070
```

Or configure multiple providers with `NEWZNAB_PROVIDERS`:

```env
NEWZNAB_PROVIDERS=[{"id":"nzbgeek","name":"NZBGeek","url":"https://api.nzbgeek.info","api_key":"your_nzbgeek_api_key","enabled":true,"categories":[5070],"priority":100,"timeout":30.0}]
```

`/api` remains Torznab/Nyaa only. `/newznab` is the upstream Newznab provider
proxy and uses `t=get` to proxy NZB downloads without exposing provider API keys.

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
