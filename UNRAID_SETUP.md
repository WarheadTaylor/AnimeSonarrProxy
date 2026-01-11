# Unraid Setup Guide for AnimeSonarrProxy

This guide will walk you through setting up AnimeSonarrProxy on Unraid using Docker.

## Method 1: Using Docker Compose Manager (Recommended)

### Prerequisites
- Unraid 6.9.0 or later
- Docker Compose Manager plugin installed

### Steps

1. **Install Docker Compose Manager Plugin**
   - Go to Unraid Web UI → Plugins → Install Plugin
   - Enter: `https://raw.githubusercontent.com/dcflachs/composeman/master/composeman.plg`
   - Click Install

2. **Create Docker Compose Directory**
   ```bash
   mkdir -p /mnt/user/appdata/animesonarrproxy
   cd /mnt/user/appdata/animesonarrproxy
   ```

3. **Create docker-compose.yml**
   Create a file `/mnt/user/appdata/animesonarrproxy/docker-compose.yml` with this content:

   ```yaml
   version: '3.8'

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
         - API_KEY=your-secret-api-key-here
         - HOST=0.0.0.0
         - PORT=8000
         - PROWLARR_URL=http://prowlarr:9696  # or http://192.168.x.x:9696
         - PROWLARR_API_KEY=your_prowlarr_api_key
         - LOG_LEVEL=INFO
       networks:
         - arr-network

   networks:
     arr-network:
       external: true  # Use existing network with Sonarr/Prowlarr
   ```

4. **Create Data Directory**
   ```bash
   mkdir -p /mnt/user/appdata/animesonarrproxy/data
   ```

5. **Start the Container**
   - Go to Docker Compose Manager in Unraid
   - Click "Add New Stack"
   - Name: `animesonarrproxy`
   - Path: `/mnt/user/appdata/animesonarrproxy/docker-compose.yml`
   - Click "Compose Up"

## Method 2: Using Unraid Docker Interface

### Steps

1. **Add Container**
   - Go to Docker tab → Add Container

2. **Configure Container**
   - **Name:** `animesonarrproxy`
   - **Repository:** `ghcr.io/warheadtaylor/animesonarrproxy:latest`
   - **Network Type:** `Bridge`

3. **Add Ports**
   - **Container Port:** `8000`
   - **Host Port:** `8000`
   - **Connection Type:** `TCP`

4. **Add Paths**
   - **Container Path:** `/app/data`
   - **Host Path:** `/mnt/user/appdata/animesonarrproxy/data`
   - **Access Mode:** `Read/Write`

5. **Add Environment Variables**
   Click "Add another Path, Port, Variable, Label or Device" for each:

   | Name | Key | Value |
   |------|-----|-------|
   | API Key | `API_KEY` | `your-secret-api-key-here` |
   | Host | `HOST` | `0.0.0.0` |
   | Port | `PORT` | `8000` |
   | Prowlarr URL | `PROWLARR_URL` | `http://192.168.x.x:9696` |
   | Prowlarr API Key | `PROWLARR_API_KEY` | `your_prowlarr_api_key` |
   | Log Level | `LOG_LEVEL` | `INFO` |

6. **Apply and Start**

## Method 3: Manual Build on Unraid

If you want to build from source:

1. **Install User Scripts Plugin**
   - Go to Plugins → Install Plugin
   - Search for "User Scripts"

2. **Clone Repository**
   ```bash
   cd /mnt/user/appdata
   git clone https://github.com/yourusername/AnimeSonarrProxy.git animesonarrproxy
   cd animesonarrproxy
   ```

3. **Build Docker Image**
   ```bash
   docker build -t animesonarrproxy:local .
   ```

4. **Run Container**
   ```bash
   docker run -d \
     --name animesonarrproxy \
     --restart unless-stopped \
     -p 8000:8000 \
     -v /mnt/user/appdata/animesonarrproxy/data:/app/data \
     -e API_KEY=your-secret-api-key-here \
     -e PROWLARR_URL=http://192.168.x.x:9696 \
     -e PROWLARR_API_KEY=your_prowlarr_api_key \
     animesonarrproxy:local
   ```

## Post-Installation Setup

### 1. Access WebUI
Navigate to `http://your-unraid-ip:8000` to access the mapping management interface.

### 2. Configure Sonarr

1. In Sonarr, go to **Settings → Indexers**
2. Click the **+** button → **Custom → Torznab**
3. Configure:
   - **Name:** `AnimeSonarrProxy`
   - **URL:** `http://your-unraid-ip:8000`
   - **API Path:** `/api`
   - **API Key:** The API key you set in environment variables
   - **Categories:** `5070` (TV/Anime)
4. Test and Save

### 3. Configure Prowlarr

Make sure you have Nyaa or other anime indexers configured in Prowlarr.

## Networking

### Option A: Host Network (Simplest)
If your containers use host networking, use `http://localhost:9696` for Prowlarr URL.

### Option B: Custom Docker Network (Recommended)
Create a custom network for all *arr apps:

```bash
docker network create arr-network

# Connect existing containers
docker network connect arr-network sonarr
docker network connect arr-network prowlarr
docker network connect arr-network animesonarrproxy
```

Then use container names in URLs:
- Prowlarr URL: `http://prowlarr:9696`
- AnimeSonarrProxy URL in Sonarr: `http://animesonarrproxy:8000`

### Option C: Bridge Network (Default)
Use container IP addresses or host IP with port mappings.

## Troubleshooting

### Check Logs
```bash
docker logs animesonarrproxy
```

### Verify Container is Running
```bash
docker ps | grep animesonarrproxy
```

### Test API Endpoint
```bash
curl "http://localhost:8000/api?t=caps&apikey=your-api-key"
```

### Verify Data Directory Permissions
```bash
ls -la /mnt/user/appdata/animesonarrproxy/data
```

### Common Issues

1. **Container won't start**
   - Check logs: `docker logs animesonarrproxy`
   - Verify port 8000 is not in use: `netstat -tulpn | grep 8000`

2. **Can't connect to Prowlarr**
   - Verify Prowlarr URL and API key
   - Check network connectivity: `docker exec animesonarrproxy curl http://prowlarr:9696`

3. **Sonarr can't connect to proxy**
   - Verify firewall rules
   - Check API key matches
   - Test from Sonarr container: `docker exec sonarr curl http://animesonarrproxy:8000/api?t=caps`

## Updating

### Docker Compose Method
```bash
cd /mnt/user/appdata/animesonarrproxy
docker-compose pull
docker-compose up -d
```

### Unraid Docker Tab
1. Go to Docker tab
2. Click "Check for Updates"
3. Update if available

### Manual Build
```bash
cd /mnt/user/appdata/animesonarrproxy
git pull
docker build -t animesonarrproxy:local .
docker stop animesonarrproxy
docker rm animesonarrproxy
# Re-run docker run command from installation
```

## Backup

Important files to backup:
- `/mnt/user/appdata/animesonarrproxy/data/mappings.json` - Cached mappings
- `/mnt/user/appdata/animesonarrproxy/data/overrides.json` - User overrides

Use Unraid's built-in backup tools or:
```bash
cp -r /mnt/user/appdata/animesonarrproxy/data /mnt/user/backups/animesonarrproxy-$(date +%Y%m%d)
```

## Support

For issues, check:
1. Container logs
2. GitHub Issues
3. Unraid forums
