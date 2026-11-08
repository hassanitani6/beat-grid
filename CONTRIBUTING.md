# Contributing

Thanks for helping! Small, focused pull requests are easiest to review.

## Set up

```bash
uv sync
uv run pytest
uv run ruff check .
```

## Ground rules

- Bug fixes come with a test that fails before the fix and passes after it.
- Test audio is generated in the tests (`tests/conftest.py`); never commit recorded music.
- Changes to the click sound must update the golden check in `tests/test_click.py` with an explanation.
- No network access or telemetry, and no new required dependencies without an issue first.

## Where things are

`grid.py` measures beats and computes shot lengths; `click.py` makes the click track; `cli.py` checks inputs and
writes files; `demo.py` the synthetic demo loop; `doctor.py` the environment report.
