# AGENTS.md - AI Coding Agent Guidelines for AnimeSonarrProxy

## Project overview

AnimeSonarrProxy is a Python FastAPI application with two search endpoints:
`/api` searches Nyaa RSS for Sonarr and Radarr; `/newznab` searches configured
Newznab providers and proxies NZB downloads. Metadata services resolve titles
and episode numbers. The application has no Prowlarr backend or WebUI.

## Setup and verification

Follow [README.md](README.md#development) for local setup and
[REQUIREMENTS.md](REQUIREMENTS.md) for dependency installation.

```bash
python -m pytest
python -m pytest tests/test_direct_nyaa_flow.py
python -m pytest tests/test_newznab_flow.py
```

Optional style tools are not in the development requirements:

```bash
python -m pip install mypy black isort
mypy app/
black app/
isort app/
```

## Code locations

- `app/main.py` configures FastAPI and service startup.
- `app/config.py` defines settings and provider validation.
- `app/models.py` defines request context and release data.
- `app/api/torznab.py` and `app/api/newznab.py` handle the endpoints.
- `app/services/core.py` and `app/services/newznab_core.py` coordinate searches.
- `app/services/metadata.py` resolves titles and episode metadata.
- Other `app/services/` modules contain provider clients, release parsing,
  matching, and RSS rendering.

When changing search terms, read [CONTEXT.md](CONTEXT.md). When changing the
Nyaa backend, read the [design decision](docs/adr/0001-direct-nyaa-core-flow.md).
When changing settings or deployment, update the configuration reference in
[README.md](README.md#configuration) and `.env.example` to match `app/config.py`.

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
from app.models import SearchResult
```

### Type Hints
Always use type hints for function parameters and return values:
```python
async def get_result(self, tvdb_id: int) -> Optional[SearchResult]:
    """Get a release result by TVDB ID."""
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

## Environment variables

Set a local `API_KEY`. Provider and manager integrations are optional. Use
[app/config.py](app/config.py) for accepted settings and defaults, and the
[configuration guide](README.md#configuration) for deployment behavior.
