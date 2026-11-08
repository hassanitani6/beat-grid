# Changelog

Versions follow [Semantic Versioning](https://semver.org/).

## 0.1.0 — unreleased

First public release: `demo` (a synthetic drum loop to try it on), `analyze` (tempo, beats and bar starts to JSON), `click` (click-track WAV from a beat grid),
`cuts` (frame-accurate shot lengths from beat counts), `energy` (loudness and busyness per block of bars) and
`doctor`. Inputs are checked before anything is written; existing files are never replaced without `--overwrite`.
`cuts` defaults to 30 fps (phone video); use `--fps 25` for PAL video.
