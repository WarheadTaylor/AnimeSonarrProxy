# Unraid Setup

AnimeSonarrProxy now searches Nyaa directly. Prowlarr is not required for v1 of
the rewritten core flow.

## Docker Compose

Create `/mnt/user/appdata/animesonarrproxy/docker-compose.yml`:

```yaml
version: "3.8"

services:
  animesonarrproxy:
    image: ghcr.io/warheadtaylor/animesonarrproxy:latest
    container_name: animesonarrproxy
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - /mnt/user/appdata/animesonarrproxy/data:/app/data
    environment:
      - API_KEY=change-me
      - HOST=0.0.0.0
      - PORT=8000
      - NYAA_URL=https://nyaa.si
      - NYAA_NO_REMAKES=true
      - NYAA_TRUSTED_ONLY=false
      - SONARR_URL=http://sonarr:8989
      - SONARR_API_KEY=your_sonarr_api_key
      - RADARR_URL=http://radarr:7878
      - RADARR_API_KEY=your_radarr_api_key
      - DATA_DIR=/app/data
      - LOG_LEVEL=INFO
```

Start it:

```bash
cd /mnt/user/appdata/animesonarrproxy
docker-compose up -d
```

## Sonarr

Add a custom Torznab indexer:

- URL: `http://your-unraid-ip:8000`
- API path: `/api`
- API key: the `API_KEY` value above
- Categories: `5070`

Set `SONARR_URL` and `SONARR_API_KEY` when the proxy can reach Sonarr. This lets
the proxy confirm season/episode and absolute episode metadata.

The proxy searches Nyaa only for selected Torznab categories. Select Anime
(`5070`) to search Nyaa Anime English-translated (`1_2`), or
Live Action/English-translated (`100041`) to search Nyaa Live Action
English-translated (`4_1`).

## Radarr

Add a custom Torznab indexer:

- URL: `http://your-unraid-ip:8000`
- API path: `/api`
- API key: the `API_KEY` value above
- Categories: `2000,2060`

Set `RADARR_URL` and `RADARR_API_KEY` when the proxy can reach Radarr. This lets
the proxy confirm movie titles, alternate titles, IDs, and year.

## Data

Persist `/app/data`. It stores cached anime metadata and TheXEM data.

Back up:

- `/mnt/user/appdata/animesonarrproxy/data/anime-offline-database.json`
- `/mnt/user/appdata/animesonarrproxy/data/thexem_cache.json`
