# Unraid setup

Run AnimeSonarrProxy with Docker Compose on Unraid. You need Compose support,
a free host port, and network access to the search and metadata providers.
Prowlarr is not required.

## Create the service

Create `/mnt/user/appdata/animesonarrproxy/docker-compose.yml`:

```yaml
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
      API_KEY: ${API_KEY}
      NYAA_URL: https://nyaa.si
      NYAA_NO_REMAKES: "true"
      NYAA_TRUSTED_ONLY: "false"
      DATA_DIR: /app/data
      LOG_LEVEL: INFO
```

Create `.env` in the same directory and set your own key:

```env
API_KEY=replace-with-your-own-key
```

Start the service and check its API:

```bash
cd /mnt/user/appdata/animesonarrproxy
docker compose up -d
curl --fail 'http://localhost:8000/api?t=caps'
```

The API returns XML capabilities. Check startup errors with
`docker compose logs --tail=100 animesonarrproxy`.

## Connect Sonarr or Radarr

Use `http://your-unraid-ip:8000` as the indexer URL and the key from `.env`.

| Manager and indexer type | API path | Categories |
| --- | --- | --- |
| Sonarr custom Torznab | `/api` | `5070` for anime; `100041` for English-translated live-action TV |
| Radarr custom Torznab | `/api` | `2000,2060`; `2060` selects Nyaa anime movies |
| Sonarr custom Newznab | `/newznab` | `5070` for anime |
| Radarr custom Newznab | `/newznab` | `2000` or provider movie subcategories |

Newznab requires an upstream provider. Add its settings under `environment`:

```yaml
      NEWZNAB_URL: ${NEWZNAB_URL}
      NEWZNAB_API_KEY: ${NEWZNAB_API_KEY}
```

Set both values in `.env`. Follow the [Newznab setup guide](README.md#sonarr-newznab-setup)
for API paths, multiple providers, and download addresses. The local Torznab
Movies/Anime category `2060` means Movies/3D on the Newznab endpoint.

For manager metadata lookups, add the applicable pair under `environment` and
set its values in `.env`:

```yaml
      SONARR_URL: ${SONARR_URL}
      SONARR_API_KEY: ${SONARR_API_KEY}
      RADARR_URL: ${RADARR_URL}
      RADARR_API_KEY: ${RADARR_API_KEY}
```

Use addresses reachable from the proxy container, such as
`http://your-unraid-ip:8989`. Container names such as `sonarr` work only when the
containers share a Docker network with name resolution. `localhost` refers to
the proxy container.

Run `docker compose up -d` after changing settings. Use the indexer's Test button
in each manager to check its connection.

## Data and updates

The mounted data directory stores `anime-offline-database.json` and
`thexem_cache.json`. Preserve this directory to retain cached metadata.
Keep your Compose file and `.env` when moving the service.

To update the selected image:

```bash
cd /mnt/user/appdata/animesonarrproxy
docker compose pull
docker compose up -d
```

See [container images](.github/CONTAINER_REGISTRY.md) for branch and release tags.
