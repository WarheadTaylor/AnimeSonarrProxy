# AnimeSonarrProxy

[![Docker Build](https://github.com/WarheadTaylor/AnimeSonarrProxy/actions/workflows/docker-build.yml/badge.svg)](https://github.com/WarheadTaylor/AnimeSonarrProxy/actions/workflows/docker-build.yml)
[![GitHub release](https://img.shields.io/github/v/release/WarheadTaylor/AnimeSonarrProxy)](https://github.com/WarheadTaylor/AnimeSonarrProxy/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Torznab-compatible proxy that sits between Sonarr and Prowlarr to improve anime search results. It translates Sonarr's TVDB-based queries into anime-friendly searches using title mappings and absolute episode numbering.

## Features

- **🎯 Smart Title Mapping**: Translates TVDB IDs to AniDB/AniList/MAL with multiple title variants (English, Romaji, Native, Synonyms)
- **📊 TheXEM Integration**: Uses TheXEM.info for accurate TVDB → AniDB episode number mappings
- **🔗 Sonarr API Integration**: Optional direct Sonarr integration for accurate episode metadata lookup (distinguishes regular episodes from specials)
- **🌐 Romaji-First Searches**: Prioritizes romaji titles for better search accuracy on anime indexers
- **🔍 Multi-Query Search**: Sends separate queries for each title variant to maximize search results
- **🎨 Web Management Interface**: Easy-to-use WebUI for managing mappings and overrides
- **💾 Multiple Data Sources**: Uses TheXEM + anime-offline-database (offline) with AniList API fallback
- **🔄 Smart Caching**: Reduces API calls with JSON-based caching system
- **🐳 Docker Ready**: Includes Docker and Unraid deployment options
- **📦 Result Deduplication**: Intelligently merges and deduplicates results from multiple queries

## Architecture

```
Sonarr → AnimeSonarrProxy (Torznab API) → Prowlarr → Nyaa
   ↑           ↓
   └───────────┤ (optional episode metadata lookup)
               ↓
    TheXEM.info (episode mapping)
    anime-offline-database (titles + IDs)
    AniList API (fallback enrichment)
               ↓
          WebUI (mapping management)
```

## Quick Start

### Docker with Pre-built Image (Recommended)

```bash
# Create a directory for the project
mkdir animesonarrproxy && cd animesonarrproxy

# Download docker-compose.yml
curl -O https://raw.githubusercontent.com/WarheadTaylor/AnimeSonarrProxy/main/docker-compose.yml

# Create .env file
curl -O https://raw.githubusercontent.com/WarheadTaylor/AnimeSonarrProxy/main/.env.example
mv .env.example .env
# Edit .env with your Prowlarr settings

# Start with Docker Compose
docker-compose up -d

# Access WebUI
http://localhost:8000
```

### Docker from Source

```bash
# Clone repository
git clone https://github.com/WarheadTaylor/AnimeSonarrProxy.git
cd AnimeSonarrProxy

# Create .env file
cp .env.example .env
# Edit .env with your Prowlarr settings

# Build and start
docker-compose up -d --build

# Access WebUI
http://localhost:8000
```

### Manual Setup

```bash
# Clone and install
git clone https://github.com/yourusername/AnimeSonarrProxy.git
cd AnimeSonarrProxy
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your settings

# Create data directory
mkdir -p data

# Run
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Unraid

See [UNRAID_SETUP.md](UNRAID_SETUP.md) for detailed Unraid installation instructions.

## Configuration

Edit `.env` file or set environment variables:

### Required Settings

| Variable | Description | Example |
|----------|-------------|---------|
| `API_KEY` | API key for Sonarr to authenticate | `your-secret-api-key-here` |
| `PROWLARR_URL` | Prowlarr base URL | `http://localhost:9696` |
| `PROWLARR_API_KEY` | Prowlarr API key | `abc123...` |

### Optional Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `HOST` | Host to bind to | `0.0.0.0` |
| `PORT` | Port to listen on | `8000` |
| `SONARR_URL` | Sonarr URL for episode metadata lookup | *(not set)* |
| `SONARR_API_KEY` | Sonarr API key | *(not set)* |
| `DATA_DIR` | Directory for data storage | `/app/data` |
| `ANIME_DB_UPDATE_INTERVAL` | Seconds between database updates | `86400` (24h) |
| `CACHE_TTL` | Cache TTL in seconds | `3600` (1h) |
| `MAPPING_CACHE_TTL` | Mapping cache TTL in seconds | `604800` (7d) |
| `MAX_RESULTS_PER_QUERY` | Max results per query | `100` |
| `ENABLE_DEDUPLICATION` | Enable result deduplication | `true` |
| `LOG_LEVEL` | Logging level | `INFO` |

### Sonarr Integration (Recommended)

When `SONARR_URL` and `SONARR_API_KEY` are configured, the proxy can query Sonarr directly to determine accurate episode metadata. This helps distinguish between:
- **Regular episodes**: Searched as "Title 39" (absolute episode number)
- **Specials/OVAs**: Searched with "Title OVA", "Title Special", etc.

Without this integration, the proxy defaults to treating numeric queries as absolute episode numbers (which works for most anime).

## Sonarr Setup

1. Go to **Settings → Indexers**
2. Click **Add Indexer → Torznab → Custom**
3. Configure:
   - **Name**: `AnimeSonarrProxy`
   - **Enable RSS**: ✅
   - **Enable Automatic Search**: ✅
   - **Enable Interactive Search**: ✅
   - **URL**: `http://your-server-ip:8000`
   - **API Path**: `/api`
   - **API Key**: The API key from your `.env` file
   - **Categories**: `5070` (TV/Anime)
4. Click **Test** then **Save**

## Prowlarr Setup

Make sure you have anime indexers configured in Prowlarr:

1. Go to **Indexers** in Prowlarr
2. Add **Nyaa** or other anime indexers
3. Configure categories to include **TV/Anime (5070)**
4. Get your Prowlarr API key from **Settings → General**

## Web Management Interface

Access the WebUI at `http://your-server-ip:8000`

### Features

- **View Cached Mappings**: See all TVDB → AniList/MAL mappings
- **Create Overrides**: Manually map TVDB IDs when auto-mapping fails
- **Search Titles**: Filter mappings by TVDB ID or title
- **Statistics Dashboard**: View total mappings, overrides, and database status
- **Delete Overrides**: Remove incorrect manual mappings

### Creating an Override

When an anime isn't automatically mapped or is mapped incorrectly:

1. Open the WebUI
2. Scroll to "Add New Override"
3. Enter:
   - **TVDB ID**: The TVDB ID from Sonarr (find in series URL)
   - **AniList ID**: (Optional) AniList ID from anilist.co/anime/ID
   - **MyAnimeList ID**: (Optional) MAL ID
   - **Custom Titles**: One title per line (Romaji, English, etc.)
   - **Notes**: Optional notes about the mapping
4. Click **Save Override**

Example:
```
TVDB ID: 388593
AniList ID: 154587
Custom Titles:
  Frieren
  Sousou no Frieren
  Frieren: Beyond Journey's End
  葬送のフリーレン
```

## How It Works

### 1. Sonarr Request
```
GET /api?t=tvsearch&tvdbid=388593&season=2&ep=1&apikey=xxx
```

### 2. Title Mapping
- Checks user overrides
- Looks up TVDB ID in anime-offline-database
- Falls back to AniList API if needed
- Extracts all title variants

### 3. Episode Translation (via TheXEM)
- Queries TheXEM.info for TVDB → AniDB episode mapping
- Converts S02E01 to AniDB absolute episode number
- Falls back to season_info metadata or estimation if TheXEM unavailable
- Handles season offsets and special episodes accurately

### 4. Multi-Query Search
Generates and executes multiple queries:
```
"Frieren" 29
"Sousou no Frieren" 29
"Frieren: Beyond Journey's End" 29
```

### 5. Deduplication
- Merges results from all queries
- Removes duplicates by GUID
- Fuzzy matching for similar titles
- Sorts by seeders and date

### 6. Return to Sonarr
Converts results to Torznab XML format with proper metadata.

## API Endpoints

### Torznab API (for Sonarr)

| Endpoint | Description |
|----------|-------------|
| `GET /api?t=caps` | Capabilities |
| `GET /api?t=tvsearch&tvdbid=X&season=Y&ep=Z` | TV search |
| `GET /api?t=search&q=query` | Generic search |

### WebUI API

| Endpoint | Description |
|----------|-------------|
| `GET /` | WebUI home page |
| `GET /api/mappings` | Get all cached mappings |
| `GET /api/mappings/{tvdb_id}` | Get specific mapping |
| `POST /api/mappings/override` | Create/update override |
| `DELETE /api/mappings/override/{tvdb_id}` | Delete override |
| `GET /api/stats` | Get statistics |

## Data Files

All data is stored in the `DATA_DIR` (default: `/app/data`):

```
data/
├── anime-offline-database.json   # Downloaded anime database
├── mappings.json                 # Cached TVDB → AniDB/AniList mappings
├── thexem_cache.json            # TheXEM episode mapping cache
└── overrides.json               # User-defined overrides
```

### Backup
These files should be backed up to preserve your mappings:
- `mappings.json`
- `thexem_cache.json`
- `overrides.json`

## Troubleshooting

### No results found

1. **Check the mapping**:
   ```bash
   curl "http://localhost:8000/api/mappings/388593"
   ```

2. **Verify Prowlarr connectivity**:
   - Check `PROWLARR_URL` and `PROWLARR_API_KEY` in `.env`
   - Test Prowlarr directly

3. **Check logs**:
   ```bash
   docker logs animesonarrproxy
   # or
   tail -f /var/log/animesonarrproxy.log
   ```

### Wrong episode numbers

Some anime have different season structures on TVDB vs AniList:
- Create a manual override in the WebUI
- Add custom episode number mappings if needed

### Sonarr can't connect

1. **Check API key**: Must match between Sonarr and `.env`
2. **Check firewall**: Ensure port 8000 is accessible
3. **Test endpoint**:
   ```bash
   curl "http://localhost:8000/api?t=caps&apikey=your-api-key"
   ```

### Database not updating

- Check logs for download errors
- Manually trigger update by restarting the container
- Verify internet connectivity

### Rate limiting (AniList API)

- Proxy respects AniList's 90 requests/minute limit
- Cached mappings reduce API calls
- If you see rate limit warnings, they're handled automatically

## Development

### Prerequisites
- Python 3.11+
- pip

### Setup

```bash
# Clone
git clone https://github.com/yourusername/AnimeSonarrProxy.git
cd AnimeSonarrProxy

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run in development mode
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Project Structure

```
AnimeSonarrProxy/
├── app/
│   ├── api/
│   │   ├── torznab.py          # Torznab API endpoints
│   │   └── webui.py            # WebUI API endpoints
│   ├── services/
│   │   ├── thexem.py           # TheXEM.info API client
│   │   ├── anime_db.py         # anime-offline-database handler
│   │   ├── anilist.py          # AniList API client
│   │   ├── sonarr.py           # Sonarr API client (episode metadata)
│   │   ├── mapping.py          # Mapping service
│   │   ├── episode.py          # Episode translation
│   │   ├── prowlarr.py         # Prowlarr client
│   │   └── query.py            # Query builder & deduplication
│   ├── static/                 # WebUI assets
│   ├── config.py               # Configuration
│   ├── models.py               # Pydantic models
│   └── main.py                 # FastAPI application
├── data/                       # Data directory
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

### Running Tests

```bash
# Install dev dependencies
pip install pytest pytest-asyncio httpx

# Run tests
pytest
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) file for details

## Credits

- [TheXEM.info](https://thexem.info) for accurate episode number mappings between TVDB and AniDB
- [anime-offline-database](https://github.com/manami-project/anime-offline-database) for TVDB → AniDB/AniList mappings
- [AniList](https://anilist.co) for their excellent API
- [Prowlarr](https://prowlarr.com) for indexer management
- [Sonarr](https://sonarr.tv) for TV series management

## Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/AnimeSonarrProxy/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/AnimeSonarrProxy/discussions)
- **Discord**: [Link to Discord server]

## Roadmap

- [ ] Season/episode override management in WebUI
- [ ] Batch release detection and filtering
- [ ] Preferred subgroup configuration
- [ ] Release quality filtering
- [ ] Enhanced fuzzy title matching
- [ ] Webhook support for new releases
- [ ] Prometheus metrics
- [ ] Multi-language support
