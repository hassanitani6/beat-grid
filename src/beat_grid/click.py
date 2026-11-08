"""Click tracks: a short tone at every measured beat, louder and higher on downbeats."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .grid import BeatGrid

CLICK_SECONDS = 0.010
FADE_SECONDS = 0.002
BEAT_HZ, BEAT_DBFS = 1000.0, -18.0
ACCENT_HZ, ACCENT_DBFS = 1600.0, -12.0
SAMPLE_RATES = (44100, 48000)


def _burst(freq: float, dbfs: float, sr: int) -> np.ndarray:
    n = round(CLICK_SECONDS * sr)
    fade = round(FADE_SECONDS * sr)
    env = np.ones(n)
    env[:fade] = np.linspace(0.0, 1.0, fade)
    env[-fade:] = np.linspace(1.0, 0.0, fade)
    return env * np.sin(2 * np.pi * freq * np.arange(n) / sr) * 10 ** (dbfs / 20)


def click_samples(grid: BeatGrid, sr: int = 48000) -> np.ndarray:
    """Mono click at every measured beat (track time 0 = sample 0), downbeats louder; length = grid.duration.

    Clicks follow the measured beat times rather than a constant tempo, so they stay in step with real drummers."""
    if sr not in SAMPLE_RATES:
        raise ValueError(f"sample rate must be one of {', '.join(map(str, SAMPLE_RATES))}")
    audio = np.zeros(round(grid.duration * sr))
    beat, accent = _burst(BEAT_HZ, BEAT_DBFS, sr), _burst(ACCENT_HZ, ACCENT_DBFS, sr)
    accents = {round(a * sr) for a in grid.downbeats}
    for t in grid.beats:
        start = round(t * sr)
        click = accent if start in accents else beat
        end = min(start + len(click), len(audio))
        if start < end:
            audio[start:end] += click[:end - start]
    return audio


def write_wav(audio: np.ndarray, out_wav: Path, sr: int = 48000) -> Path:
    import soundfile as sf

    sf.write(str(out_wav), audio, sr, subtype="PCM_16", format="WAV")
    return Path(out_wav)


def accent_count(grid: BeatGrid, sr: int = 48000) -> int:
    """How many downbeats actually get the accented click: only those that fall on one of the beats."""
    beat_starts = {round(t * sr) for t in grid.beats}
    return len({round(a * sr) for a in grid.downbeats} & beat_starts)
