# Anime Sonarr Proxy (ASP)

A Torznab-compatible proxy that sits between Sonarr and Prowlarr to improve anime search results. It translates Sonarr's TVDB-based queries into anime-friendly searches using title mappings and absolute episode numbering.

## Features

- **Title Mapping**: Translates TVDB IDs to AniList/MAL with multiple title variants (English, Romaji, Native, Synonyms)
- **Absolute Episode Numbering**: Converts Sonarr's S01E01 format to absolute episode numbers
- **Query Optimization**: Generates Nyaa-friendly search queries
- **Torznab Compatible**: Drop-in replacement that Sonarr can talk to directly
- **Caching**: Reduces API calls with configurable caching

## Architecture

```
Sonarr → Anime Sonarr Proxy → Prowlarr → Nyaa.si
              ↓
        AniList API + anime-offline-database
        (title mapping & episode calculation)
```

## Quick Start

### Docker Compose (Recommended for Unraid)

```yaml
version: "3.8"
services:
  anime-sonarr-proxy:
    build: .
    container_name: anime-sonarr-proxy
    ports:
      - "9696:9696"
    environment:
      - PROWLARR_URL=http://prowlarr:9696
      - PROWLARR_API_KEY=your_prowlarr_api_key
      - PROWLARR_INDEXER_ID=1  # Your Nyaa indexer ID in Prowlarr
    volumes:
      - ./data:/app/data  # For caching
    restart: unless-stopped
```

### Manual Setup

```bash
# Clone and install
cd anime-sonarr-proxy
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your settings

# Run
uvicorn app.main:app --host 0.0.0.0 --port 9696
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `PROWLARR_URL` | Prowlarr base URL | `http://localhost:9696` |
| `PROWLARR_API_KEY` | Prowlarr API key | Required |
| `PROWLARR_INDEXER_ID` | Nyaa indexer ID in Prowlarr | Required |
| `CACHE_TTL_HOURS` | How long to cache mappings | `24` |
| `PREFERRED_SUBGROUPS` | Comma-separated preferred release groups | `SubsPlease,Erai-raws,EMBER` |
| `LOG_LEVEL` | Logging level | `INFO` |

## Sonarr Setup

1. Go to **Settings → Indexers → Add**
2. Choose **Torznab**
3. Configure:
   - **Name**: `Anime Proxy`
   - **URL**: `http://your-server:9696`
   - **API Key**: `sonarr` (or whatever you set)
   - **Categories**: `5070` (Anime)
4. Test and Save

## How It Works

### 1. Incoming Request
Sonarr sends a Torznab search:
```
GET /api?t=tvsearch&tvdbid=388593&season=1&ep=5
```

### 2. Title Mapping
The proxy:
1. Looks up TVDB ID `388593` in anime-offline-database
2. Finds AniList/MAL IDs
3. Fetches all title variants from AniList API:
   - English: "Frieren: Beyond Journey's End"
   - Romaji: "Sousou no Frieren"
   - Synonyms: ["Frieren"]

### 3. Episode Translation
- Checks if anime has multiple seasons on TVDB but is single-season on AniList
- Calculates absolute episode number (S01E05 → Episode 5, S02E01 → Episode 29, etc.)

### 4. Search Query Generation
Builds optimized queries for Nyaa:
```
"Frieren" 05 | "Sousou no Frieren" 05
```

### 5. Forward to Prowlarr
Sends the rewritten query to Prowlarr, gets results, and returns them to Sonarr in Torznab format.

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api?t=caps` | Torznab capabilities |
| `GET /api?t=tvsearch` | TV/Anime search |
| `GET /health` | Health check |
| `GET /mapping/{tvdb_id}` | Debug: view mapping for a TVDB ID |

## Troubleshooting

### No results found
1. Check the mapping endpoint: `GET /mapping/{tvdb_id}`
2. Verify Prowlarr indexer ID is correct
3. Check logs for query being sent

### Wrong episode numbers
- Some anime have different season splits between TVDB and AniList
- You can add manual overrides in `data/overrides.json`

### Rate limiting
- AniList has rate limits; the proxy caches aggressively to avoid hitting them
- If you see 429 errors, increase `CACHE_TTL_HOURS`

## Manual Overrides

Create `data/overrides.json` for problematic mappings:

```json
{
  "388593": {
    "anilist_id": 154587,
    "titles": ["Frieren", "Sousou no Frieren"],
    "episode_offset": 0,
    "absolute_numbering": true
  }
}
}
```

## Development

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests
pytest

# Run with auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 9696
```

## License

MIT
