# Container images

The [Docker build workflow](workflows/docker-build.yml) builds images for
`linux/amd64` and `linux/arm64`. This page describes the repository workflow;
it does not confirm which tags are currently published.

## Build triggers and tags

| Event | Workflow behavior |
| --- | --- |
| Push to `2.1`, `beta`, `main`, or `master` | Build and push a branch tag and a `sha-` tag. |
| Push a tag matching `v*.*.*` | Build and push semantic version tags and a `sha-` tag. |
| Pull request targeting `beta`, `main`, or `master` | Build both platforms without pushing an image. |
| Manual workflow dispatch | Build and push for the selected ref. |

The metadata configuration explicitly adds `latest` for the default branch.
Semantic version metadata can also add `latest` through the metadata action's
automatic behavior. A branch tag follows that branch; it is not a fixed release.

For a Git tag such as `v1.2.3`, the version patterns produce `1.2.3`, `1.2`, and
`1` image tags. Use a tag that exists in the registry when pinning an image.

## Run an image

Use [the README setup](../README.md#quick-start-with-docker-compose) or the
[Unraid guide](../UNRAID_SETUP.md). Both use
`ghcr.io/warheadtaylor/animesonarrproxy:latest`.

To select a branch build, change the Compose image entry, for example:

```yaml
image: ghcr.io/warheadtaylor/animesonarrproxy:2.1
```

Pull and recreate the service after changing its tag:

```bash
docker compose pull
docker compose up -d
```

## Build the current checkout

From the repository root:

```bash
docker build -t animesonarrproxy:local .
docker run -d \
  --name animesonarrproxy \
  -p 8000:8000 \
  -v "$(pwd)/data:/app/data" \
  --env-file .env \
  animesonarrproxy:local
```

Create `.env` from [the example](../.env.example), set your own `API_KEY`, and
keep `DATA_DIR=/app/data` for this command. See the README for manager setup.

## Publication and troubleshooting

The workflow uses `GITHUB_TOKEN` with `contents: read` and `packages: write`.
It skips registry login and image publication for pull requests.

If an image cannot be pulled, check the requested tag, package visibility, and
registry access. The workflow does not set package visibility.
Inspect the repository's Docker build workflow run for build or publication errors.
