# Dependency installation

Use Python 3.11 to match the Docker image. Run installation commands inside a
virtual environment from the repository root.

## Runtime

[requirements.txt](requirements.txt) is the pinned runtime dependency list used
by the Docker build:

```bash
python -m pip install -r requirements.txt
```

## Development and tests

[requirements-dev.txt](requirements-dev.txt) includes runtime dependencies,
pytest, and pytest-asyncio:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

Keep dependency versions in these requirements files. See the
[development guide](README.md#development) for environment setup and server commands.
