# Notes for coding agents

- Install: `uv sync`. Test: `uv run pytest` (a few seconds). Lint: `uv run ruff check .`.
- Package code is in `src/beat_grid/`. All file writing goes through `cli.check_outputs` and `cli._atomic`.
- Every change needs a test; test audio is synthetic and generated in `tests/conftest.py`.
- Do not add network calls or telemetry, and do not commit audio files.
