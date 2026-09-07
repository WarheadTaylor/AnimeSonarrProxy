# AnimeSonarrProxy

AnimeSonarrProxy is a FastAPI proxy for anime automation. It accepts Sonarr and
Radarr Torznab requests, resolves the requested media to anime-friendly titles,
searches Nyaa RSS directly, parses release titles, filters uncertain matches,
and returns manager-friendly release titles. A separate Newznab endpoint supports Sonarr and Radarr through configurable
upstream Usenet providers. The Torznab endpoint also supports live-action TV
searches in the English-translated Nyaa category.

## Quick start with Docker Compose

You need Docker with the Compose plugin and network access to the search and
metadata providers. Run these commands from the repository root:

```bash
cp .env.example .env
```

Set `API_KEY` in `.env` to your own key. Then start the service:

```bash
docker compose up -d
curl --fail 'http://localhost:8000/api?t=caps'
```

The request returns XML capabilities. It confirms that the API responds, but does
not test a search or provider credentials. Configure an indexer below and use its
Test button to check the connection.

The supplied Compose file pulls a registry image. To build the checked-out code,
replace its `image:` entry with `build: .`, then run `docker compose up -d --build`.
See [Unraid setup](UNRAID_SETUP.md) for Unraid paths and
[container images](.github/CONTAINER_REGISTRY.md) for build triggers and tags.

## Request flow

- `/api` resolves metadata, searches Nyaa RSS, parses releases, filters matches,
  and returns normalized Torznab RSS.
- `/newznab` searches upstream Newznab providers. Resolved TV episode requests
  use anime title and episode mapping. Other supported requests can pass search
  constraints to providers without local metadata.
- `/newznab?t=get` retrieves the NZB from the configured provider.

The returned RSS title is intentionally not always the original Nyaa title. The
proxy preserves the original Nyaa title internally and returns a normalized title
that Sonarr or Radarr can parse more reliably.

Examples:

```text
[SubsPlease] One Piece - S23E01 - 1156 (1080p)
Suzume (2022) [1080p][BDRip] -Group
```

## API reference

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
| `t=search&q=` | Generic upstream search and indexer tests; omit `q` for RSS. |
| `t=movie&tmdbid=` | Movie search by TMDB ID. Also accepts `imdbid`, `q`, and `year`. |
| `t=get&provider=&id=` | Proxied NZB download from the selected upstream provider. |

Newznab searches and downloads require the local `apikey`. Upstream provider API
keys are configured server-side and are not returned to Sonarr in RSS links.

## Metadata sources

- `anime-offline-database` provides TVDB/TMDB/IMDb title mappings.
- TheXEM provides TVDB season/episode to anime absolute episode conversion.
- Optional Sonarr API integration confirms series title, season/episode, absolute
  episode number, and specials.
- Optional Radarr API integration confirms movie title, alternate titles, IDs, and
  year.

Live-action TV metadata can also use TMDB and TVmaze. TMDB requires
`TMDB_API_KEY`. See the configuration table for source settings.

The application has no WebUI or manual mapping overrides. Prowlarr is not required.

## Nyaa categories and filters

The proxy searches Nyaa directly when the Torznab request includes a supported
category:

| Torznab category | Nyaa category |
| --- | --- |
| `5070` Anime | `1_2` Anime English-translated |
| `2060` Movies/Anime | `1_2` Anime English-translated |
| `100041` Live Action/English-translated | `4_1` Live Action English-translated |

If no supported category is selected, the proxy does not search Nyaa.

Default Nyaa filters:

```env
NYAA_URL=https://nyaa.si
NYAA_NO_REMAKES=true
NYAA_TRUSTED_ONLY=false
```

If `NYAA_TRUSTED_ONLY=true`, the trusted-only Nyaa filter is used instead of
no-remakes. Otherwise `NYAA_NO_REMAKES=true` uses Nyaa's no-remakes filter for
selected categories.

## Configuration

Settings load from environment variables and `.env`. Names are case-sensitive.
Use [`.env.example`](.env.example) as a template. The optional integrations in the
template are commented out until you supply real addresses and keys.

Set your own API key before deployment. The application accepts a placeholder
by default; it does not enforce a required value.

| Variable | Description |
| --- | --- |
| `API_KEY` | Local API key for both endpoints, including NZB downloads. Use this key in Sonarr and Radarr. |

Optional:

| Variable | Default |
| --- | --- |
| `HOST` | `0.0.0.0` |
| `PORT` | `8000` |
| `NEWZNAB_URL` / `NEWZNAB_API_KEY` | unset |
| `NEWZNAB_API_PATH` | unset; use `NEWZNAB_URL` as the complete endpoint |
| `NEWZNAB_ID` | `newznab` |
| `NEWZNAB_NAME` | `Newznab` |
| `NEWZNAB_CATEGORIES` | `5070` |
| `NEWZNAB_PROVIDERS` | unset |
| `NEWZNAB_MAX_QUERY_VARIANTS` | `12` |
| `NEWZNAB_DEFAULT_CATEGORIES` | `5070` |
| `PUBLIC_BASE_URL` | unset |
| `SONARR_URL` / `SONARR_API_KEY` | unset |
| `RADARR_URL` / `RADARR_API_KEY` | unset |
| `TMDB_API_KEY` | unset |
| `DRAMA_METADATA_ENABLED` | `true` |
| `DRAMA_METADATA_SOURCE_ORDER` | `["sonarr","tmdb","tvmaze"]` |
| `NYAA_URL` | `https://nyaa.si` |
| `NYAA_NO_REMAKES` | `true` |
| `NYAA_TRUSTED_ONLY` | `false` |
| `DATA_DIR` | `/app/data` |
| `ANIME_DB_URL` | Latest release URL in [app/config.py](app/config.py) |
| `ANIME_DB_UPDATE_INTERVAL` | `86400` |
| `CACHE_TTL` | `3600` |
| `MAX_RESULTS_PER_QUERY` | `100` |
| `TORZNAB_DEFAULT_LANGUAGE` | `English` |
| `LOG_LEVEL` | `INFO` |

Time values are in seconds. `ANIME_DB_UPDATE_INTERVAL` controls the database age
check at startup; there is no scheduled refresh task. `CACHE_TTL` controls TMDB
and TVmaze caches. Nyaa has a separate 60-second cache, and TheXEM caches supported
responses for seven days.

Set `DATA_DIR=./data` for local development. Persist `/app/data` in Docker.
`HOST` and `PORT` apply when you run `python -m app.main`. The Docker image and
explicit Uvicorn commands use their command-line host and port. To change the
external Docker port, change the port mapping, for example `8080:8000`.

The supplied Compose file forwards only its listed environment variables and fixes
some values. To use settings such as `TMDB_API_KEY`, `DRAMA_METADATA_ENABLED`,
`DRAMA_METADATA_SOURCE_ORDER`, or `ANIME_DB_URL`, add them to its `environment`
section. A value in `.env` alone does not pass an unlisted variable to the container.

Use a JSON array for `DRAMA_METADATA_SOURCE_ORDER`. Newznab category settings
accept a JSON array or comma-separated IDs.

## Sonarr Torznab setup

Add a custom Torznab indexer:

- URL: `http://your-server-ip:8000`
- API path: `/api`
- API key: `API_KEY`
- Categories: `5070`

For best episode matching, configure `SONARR_URL` and `SONARR_API_KEY`.

## Sonarr Newznab setup

Add a custom Newznab indexer:

- URL: `http://your-server-ip:8000`
- API path: `/newznab`
- API key: `API_KEY`
- Anime categories: `5070`

Keep `/newznab` in the API path field, not in both the URL and API path.
The API key here is the proxy's key, not an upstream provider's key.

Configure one upstream Newznab provider with simple env vars:

```env
NEWZNAB_URL=https://api.nzbgeek.info
NEWZNAB_API_KEY=your_nzbgeek_api_key
NEWZNAB_ID=nzbgeek
NEWZNAB_NAME=NZBGeek
NEWZNAB_CATEGORIES=5070
```

For multiple providers, set `NEWZNAB_PROVIDERS` to a JSON array. A nonempty array
replaces the simple provider settings:

```env
NEWZNAB_PROVIDERS=[{"id":"nzbgeek","name":"NZBGeek","url":"https://api.nzbgeek.info","api_key":"your_nzbgeek_api_key","enabled":true,"categories":[5070],"priority":100,"timeout":30.0}]
```

Each provider requires `id`, `name`, `url`, and `api_key`. Optional defaults are
`enabled=true`, `categories=[5070]`, `priority=100`, and `timeout=30.0` seconds.
Use a unique ID for each provider because download links select providers by ID.

`/api` remains Torznab/Nyaa only. `/newznab` is the upstream Newznab provider
proxy and uses `t=get` to proxy NZB downloads without exposing provider API keys.

`NEWZNAB_URL` must be the provider's complete API endpoint. For providers that
use `/api`, set `NEWZNAB_URL=https://indexer.example/api`, or use
`NEWZNAB_URL=https://indexer.example` with `NEWZNAB_API_PATH=/api`.
For multiple providers, the equivalent optional field is `"api_path":"/api"`.
Specify the path only once. Leave it unset for APIs served at the host root,
such as the NZBGeek example above. URLs must use HTTP(S); configure keys separately.

The Newznab proxy forwards anime ID/absolute-number searches, season searches,
title searches, daily air dates, and RSS requests with their search parameters.
Resolved TVDB season/episode searches retain anime title and episode mapping.
When local metadata is missing, the upstream provider can still resolve the ID.

### Radarr Newznab setup

Add a custom **Newznab** indexer with URL `http://your-server-ip:8000`, API path
`/newznab`, the proxy's `API_KEY`, and movie category `2000` or the desired movie
subcategories. The Newznab endpoint labels category `2060` as Movies/3D. The Torznab endpoint
uses that same ID for its local Movies/Anime mapping. Keep the endpoint category
settings separate.
Movie ID, title/year, and RSS requests are forwarded to the upstream providers.
The providers must support the requested Newznab search types and identifiers.
Radarr metadata integration is not required for these forwarded searches.

If downloads need a different reachable address, set `PUBLIC_BASE_URL` to the
proxy's base URL, without `/newznab`. Generated NZB links use that address.

## Radarr Torznab setup

Add a custom Torznab indexer:

- URL: `http://your-server-ip:8000`
- API path: `/api`
- API key: `API_KEY`
- Categories: `2000,2060`

For best movie title/year matching, configure `RADARR_URL` and `RADARR_API_KEY`.
The `/api` endpoint needs `2060` to select Nyaa anime movies; `2000` alone does
not select a Nyaa category.

## Development

Use Python 3.11, the version in the Docker image. From the repository root:

```bash
python -m venv venv
source venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

On Windows, activate with `venv\Scripts\activate` in Command Prompt or
`.\venv\Scripts\Activate.ps1` in PowerShell. Set your `API_KEY` and
`DATA_DIR=./data` in `.env`, then start the server:

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Run all tests or one endpoint suite:

```bash
python -m pytest
python -m pytest tests/test_direct_nyaa_flow.py
python -m pytest tests/test_newznab_flow.py
```

## Troubleshooting

| Symptom | Check |
| --- | --- |
| HTTP 403 | The manager must use the proxy's `API_KEY`. |
| `/newznab` search returns HTTP 503 | Configure at least one enabled provider with a URL and API key. |
| Nyaa returns no results | Include a supported `cat` value. Metadata or match filtering can also exclude results. Check service logs. |
| NZB download fails | Check provider credentials and the proxy address in the download link. Set `PUBLIC_BASE_URL` if needed. |
| Manager metadata lookup fails in Docker | Use an address reachable from the proxy container. `localhost` refers to that container. |
| `/` returns HTTP 404 | There is no WebUI. Use `/api?t=caps` or `/newznab?t=caps` to check the API. |

View container logs with `docker compose logs --tail=100 animesonarrproxy`.
An empty search response can also follow an upstream error; check the logs before
assuming that no releases exist.

## Maintainer references

- [Dependency installation](REQUIREMENTS.md)
- [Project glossary](CONTEXT.md)
- [Direct Nyaa design decision](docs/adr/0001-direct-nyaa-core-flow.md)
- [TheXEM client reference](docs/thexem_api.md)
- [Agent guidelines](AGENTS.md)
