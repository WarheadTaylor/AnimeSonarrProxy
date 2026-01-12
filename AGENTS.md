# AGENTS.md - AI Coding Agent Guidelines for AnimeSonarrProxy

## Project Overview

AnimeSonarrProxy is a Python FastAPI application that acts as a Torznab-compatible proxy
between Sonarr and Prowlarr, providing anime title mapping and episode number translation.

## Build and Run Commands

### Development Setup
```bash
python -m venv venv
source venv/bin/activate      # Linux/macOS  |  venv\Scripts\activate (Windows)
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Docker Commands
```bash
docker build -t animesonarrproxy .
docker run -p 8000:8000 -v ./data:/app/data animesonarrproxy
docker-compose up -d --build
```

### Testing Commands
```bash
pip install pytest pytest-asyncio httpx    # Install test dependencies
pytest                                      # Run all tests
pytest tests/test_mapping.py               # Run a single test file
pytest tests/test_mapping.py::test_func    # Run a single test function
pytest -v                                   # Verbose output
pytest -k "mapping"                         # Tests matching pattern
```

### Linting and Formatting
```bash
pip install mypy black isort
mypy app/        # Type checking
black app/       # Code formatting
isort app/       # Import sorting
```

## Project Structure

```
app/
├── main.py           # FastAPI entry point, lifespan events
├── config.py         # pydantic-settings configuration
├── models.py         # Pydantic models for data validation
├── api/
│   ├── torznab.py    # Torznab API endpoints (/api)
│   └── webui.py      # WebUI endpoints (/, /api/mappings)
└── services/
    ├── anime_db.py   # anime-offline-database handler
    ├── anilist.py    # AniList GraphQL API client
    ├── episode.py    # Episode number translation
    ├── mapping.py    # Title mapping service
    ├── prowlarr.py   # Prowlarr API client
    ├── query.py      # Query building and deduplication
    └── thexem.py     # TheXEM.info API client
```

## Code Style Guidelines

### Imports
Order in three groups separated by blank lines: stdlib, third-party, local
```python
import asyncio
import logging
from typing import Optional, List, Dict

import httpx
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.models import AnimeMapping
```

### Type Hints
Always use type hints for function parameters and return values:
```python
async def get_mapping(self, tvdb_id: int) -> Optional[AnimeMapping]:
    """Get anime mapping by TVDB ID."""
    ...
```
Use `Optional[T]` for nullable values. Use `List[T]` and `Dict[K, V]` for collections.

### Docstrings
- Every module needs a top-level docstring describing its purpose
- Every class needs a docstring describing its role
- Public methods need docstrings for params and return values
```python
"""AniList API client with rate limiting and caching."""

class AniListClient:
    """AniList GraphQL API client."""
    
    async def get_by_anilist_id(self, anilist_id: int) -> Optional[Dict]:
        """Get anime info by AniList ID."""
```

### Naming Conventions
- **Classes**: PascalCase (`MappingService`, `AnimeMapping`)
- **Functions/Methods**: snake_case (`get_mapping`, `_parse_json_item`)
- **Variables**: snake_case (`tvdb_id`, `rate_limit_tokens`)
- **Constants**: UPPER_SNAKE_CASE (`ANILIST_API_URL`, `MAX_RESULTS`)
- **Private methods**: prefix with underscore (`_load_cache`)

### Async/Await
Use async/await for all I/O operations (HTTP requests, file operations):
```python
async def search(self, query: str) -> List[SearchResult]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, params=params)
```

### Error Handling
Use try/except blocks, log errors appropriately, return sensible defaults or HTTPException:
```python
try:
    response = await client.get(url, params=params)
    response.raise_for_status()
except httpx.HTTPError as e:
    logger.error(f"API request failed: {e}")
    return []
```

### Logging
Use Python's logging module with appropriate levels:
```python
logger = logging.getLogger(__name__)
logger.debug(f"Cache hit for TVDB {tvdb_id}")
logger.info(f"Found {len(results)} results")
logger.warning(f"No mapping found for TVDB {tvdb_id}")
logger.error(f"Failed to parse response: {e}")
```

### Pydantic Models
Use Pydantic BaseModel for data validation. Use Field() for defaults with factories.

### Service Pattern
Services use singleton pattern with module-level instances initialized during app lifespan.

### FastAPI Routers
Organize endpoints using APIRouter, include with app.include_router().

### Configuration
Use pydantic-settings BaseSettings with env_file = ".env" and case_sensitive = True.

## Key Dependencies

- **FastAPI**: Web framework
- **Pydantic**: Data validation and settings
- **httpx**: Async HTTP client
- **uvicorn**: ASGI server

## Environment Variables

Required: `API_KEY`, `PROWLARR_URL`, `PROWLARR_API_KEY`

Optional: `HOST` (0.0.0.0), `PORT` (8000), `DATA_DIR` (/app/data), `LOG_LEVEL` (INFO),
`CACHE_TTL` (3600), `MAPPING_CACHE_TTL` (604800)
