# Container Registry Setup

This project uses GitHub Actions to automatically build and push Docker images to GitHub Container Registry (ghcr.io).

## Automatic Builds

The workflow (`.github/workflows/docker-build.yml`) automatically builds and pushes images when:

- **Push to main/master branch** → Tagged as `latest`
- **Push a tag like `v1.0.0`** → Tagged as `v1.0.0`, `1.0`, `1`, and `latest`
- **Pull Request** → Builds but doesn't push (testing only)

## Image Tags

Images are available at: `ghcr.io/warheadtaylor/animesonarrproxy`

Available tags:
- `latest` - Latest stable build from main branch
- `v1.0.0` - Specific version tags (semver)
- `1.0` - Major.minor version
- `1` - Major version only
- `main-abc1234` - Specific commit SHA on main branch

## Using the Pre-built Image

### Docker Compose (Recommended)

```yaml
services:
  animesonarrproxy:
    image: ghcr.io/warheadtaylor/animesonarrproxy:latest
    # ... rest of configuration
```

### Docker CLI

```bash
docker pull ghcr.io/warheadtaylor/animesonarrproxy:latest

docker run -d \
  --name animesonarrproxy \
  -p 8000:8000 \
  -v ./data:/app/data \
  -e PROWLARR_URL=http://prowlarr:9696 \
  -e PROWLARR_API_KEY=your_key \
  ghcr.io/warheadtaylor/animesonarrproxy:latest
```

## Platform Support

Images are built for multiple architectures:
- `linux/amd64` (x86_64)
- `linux/arm64` (ARM64/aarch64)

Docker will automatically pull the correct architecture for your system.

## Updating

To update to the latest version:

```bash
# Docker Compose
docker-compose pull
docker-compose up -d

# Docker CLI
docker pull ghcr.io/warheadtaylor/animesonarrproxy:latest
docker stop animesonarrproxy
docker rm animesonarrproxy
# Run docker run command again
```

## Building Locally

If you prefer to build from source:

```bash
git clone https://github.com/WarheadTaylor/AnimeSonarrProxy.git
cd AnimeSonarrProxy
docker build -t animesonarrproxy:local .
```

## Releases

To create a new release:

1. Update version in relevant files
2. Commit changes
3. Create and push a tag:
   ```bash
   git tag -a v1.0.0 -m "Release v1.0.0"
   git push origin v1.0.0
   ```
4. GitHub Actions will automatically build and push the tagged release

## Viewing Available Images

Visit the package page:
https://github.com/WarheadTaylor/AnimeSonarrProxy/pkgs/container/animesonarrproxy

## Permissions

The GitHub Actions workflow uses `GITHUB_TOKEN` which is automatically provided. No additional secrets are required.

Images are public by default. To make them public (if they're not already):

1. Go to https://github.com/WarheadTaylor/AnimeSonarrProxy/pkgs/container/animesonarrproxy
2. Click "Package settings"
3. Scroll to "Danger Zone"
4. Click "Change visibility" → "Public"

## Troubleshooting

### Image pull errors

If you get permission errors pulling the image:

```bash
# Login to GitHub Container Registry
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
```

### Build failures

Check the Actions tab: https://github.com/WarheadTaylor/AnimeSonarrProxy/actions

### Using specific versions

For production, it's recommended to pin to a specific version:

```yaml
image: ghcr.io/warheadtaylor/animesonarrproxy:v1.0.0
```

Instead of using `latest`, which can change unexpectedly.
