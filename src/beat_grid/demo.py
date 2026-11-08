"""A synthetic drum loop to try beat-grid on: sine-wave kicks and noise hi-hats, so it is free of any copyright."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def drum_loop(path: Path, bpm: float = 120, seconds: float = 20, sr: int = 44100) -> Path:
    """120 BPM, a kick on the first beat of every bar, hi-hats on the others; the second half is louder (a "drop")."""
    import soundfile as sf

    rng = np.random.default_rng(0)
    y = np.zeros(int(seconds * sr))
    period, n = 60 / bpm, int(0.08 * sr)
    t = np.arange(n) / sr
    kick = np.sin(2 * np.pi * (60 + 60 * np.exp(-t * 30)) * t) * np.exp(-t * 25)
    hat = rng.standard_normal(n) * np.exp(-t * 120) * 0.3
    for k in range(int(seconds / period)):
        i = int(k * period * sr)
        seg = y[i:i + n]
        loud = 1.0 if k < 16 else 2.0
        seg += 0.3 * loud * (kick if k % 4 == 0 else hat)[:len(seg)]
    sf.write(str(path), y, sr, subtype="PCM_16", format="WAV")
    return Path(path)
