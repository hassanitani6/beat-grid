"""Beat grids: measure a track's beats and bar starts, and turn beat counts into frame-accurate shot lengths."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

DEFAULT_FPS = 30  # phone video; pass --fps 25 for PAL footage
ANALYSIS_SR = 22050
MAX_TRACK_SECONDS = 20 * 60  # whole tracks are decoded into memory; longer files are almost certainly mistakes
MAX_GRID_SECONDS = 60 * 60
MAX_BEATS = 50_000
MAX_GRID_BYTES = 5_000_000
# Decoding holds every sample in memory: 20 minutes of 48 kHz stereo is about 115 million samples (under 1 GB).
MAX_DECODED_SAMPLES = 120_000_000
MAX_UNKNOWN_FILE_BYTES = 200_000_000  # for formats libsndfile can't inspect, cap the compressed file size instead


def decode_errors() -> tuple[type[BaseException], ...]:
    """Exceptions that mean "this file can't be decoded" (as opposed to a bug or running out of memory)."""
    import soundfile as sf

    errors: list[type[BaseException]] = [sf.LibsndfileError, EOFError]
    try:
        from audioread.exceptions import DecodeError, NoBackendError
        errors += [DecodeError, NoBackendError]
    except ImportError:  # audioread is an optional fallback decoder of librosa
        pass
    return tuple(errors)


@dataclass
class BeatGrid:
    bpm: float
    beats: list[float]
    downbeats: list[float]
    duration: float


def _times(name: str, value, duration: float, problems: list[str]) -> list[float]:
    if not isinstance(value, list):
        problems.append(f"{name} must be a list of times in seconds")
        return []
    if len(value) > MAX_BEATS:
        problems.append(f"{name} has {len(value)} entries (at most {MAX_BEATS})")
        return []
    out = []
    for i, t in enumerate(value):
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t):
            problems.append(f"{name}[{i}] is not a finite number")
            return []
        out.append(float(t))
    if any(t < 0 for t in out):
        problems.append(f"{name} can't contain negative times")
    if any(b < a for a, b in zip(out, out[1:], strict=False)):
        problems.append(f"{name} must be in increasing order")
    if math.isfinite(duration) and duration > 0 and any(t > duration + 1e-6 for t in out):
        problems.append(f"{name} has times after the end of the track ({duration:g} s)")
    return out


def grid_from_dict(raw) -> BeatGrid:
    """A BeatGrid from parsed JSON, validated. Raises ValueError listing every problem.

    Accepts "accents" as another name for "downbeats", so hand-measured grids that mark accented beats work too.
    """
    if not isinstance(raw, dict):
        raise ValueError("a beat grid must be a JSON object with bpm, beats, downbeats and duration")
    problems: list[str] = []
    duration = raw.get("duration")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration):
        problems.append("duration must be a number of seconds")
        duration = float("nan")
    elif not 0 < duration <= MAX_GRID_SECONDS:
        problems.append(f"duration must be between 0 and {MAX_GRID_SECONDS} seconds (got {duration:g})")
    bpm = raw.get("bpm", 0.0)
    if isinstance(bpm, bool) or not isinstance(bpm, (int, float)) or not math.isfinite(bpm) or bpm < 0:
        problems.append("bpm must be a number, 0 or more")
        bpm = 0.0
    beats = _times("beats", raw.get("beats"), duration, problems)
    down_key = "downbeats" if "downbeats" in raw else "accents" if "accents" in raw else None
    downbeats = _times(down_key, raw[down_key], duration, problems) if down_key else []
    if not beats and not problems:
        problems.append("beats is empty")
    if problems:
        raise ValueError("; ".join(problems))
    return BeatGrid(bpm=float(bpm), beats=beats, downbeats=downbeats, duration=float(duration))


def load_grid(path) -> BeatGrid:
    path = Path(path)
    try:
        size = path.stat().st_size
        if size > MAX_GRID_BYTES:
            raise ValueError(f"the file is {size:,} bytes; beat grids up to {MAX_GRID_BYTES:,} bytes are supported")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except RecursionError:
        raise ValueError(f"couldn't read beat grid {path.name}: it is nested too deeply") from None
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise ValueError(f"couldn't read beat grid {path.name}: {e}") from None
    try:
        return grid_from_dict(raw)
    except ValueError as e:
        raise ValueError(f"{path.name}: {e}") from None


def grid_json(grid: BeatGrid) -> str:
    return json.dumps(asdict(grid), indent=1) + "\n"


def track_seconds(path) -> float:
    """Length in seconds, read from the header; refuses files too big to decode into memory."""
    import soundfile as sf

    name = Path(path).name
    try:
        info = sf.info(str(path))
    except sf.LibsndfileError:
        # Formats libsndfile can't read (e.g. M4A) go through librosa's fallback decoder, which needs ffmpeg.
        size = Path(path).stat().st_size
        if size > MAX_UNKNOWN_FILE_BYTES:
            raise ValueError(f"{name} is {size / 1e6:.0f} MB; files in this format up to "
                             f"{MAX_UNKNOWN_FILE_BYTES / 1e6:.0f} MB are supported") from None
        import librosa

        return float(librosa.get_duration(path=str(path)))
    if info.frames * info.channels > MAX_DECODED_SAMPLES:
        raise ValueError(f"{name} is too large to analyse ({info.channels} channels x {info.samplerate} Hz x "
                         f"{info.duration / 60:.0f} min); use a shorter, mono or lower-rate copy")
    return float(info.duration)


def _load_mono(path) -> tuple[np.ndarray, int]:
    import librosa

    seconds = track_seconds(path)
    if seconds > MAX_TRACK_SECONDS:
        raise ValueError(f"{Path(path).name} is {seconds / 60:.0f} minutes long; tracks up to "
                         f"{MAX_TRACK_SECONDS // 60} minutes are supported")
    y, sr = librosa.load(str(path), sr=ANALYSIS_SR, mono=True)
    if len(y) == 0:
        raise ValueError(f"{Path(path).name} has no audio")
    return y, sr


def analyze_track(path) -> BeatGrid:
    import librosa

    y, sr = _load_mono(path)
    onset = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, frames = librosa.beat.beat_track(onset_envelope=onset, sr=sr)
    times = librosa.frames_to_time(frames, sr=sr)
    if len(frames) == 0:
        raise ValueError(f"no beats found in {Path(path).name} (is it silent, or without a steady pulse?)")
    # Kick drums mark bar starts in most pop/electronic music, so the low band picks the downbeat phase.
    low = librosa.onset.onset_strength(y=y, sr=sr, fmax=200, n_mels=32)
    strength = low[np.minimum(frames, len(low) - 1)]
    phase = int(np.argmax([strength[k::4].mean() if len(strength[k::4]) else 0.0 for k in range(4)]))
    return finish_grid(float(np.atleast_1d(tempo)[0]), times, phase, len(y) / sr)


def finish_grid(tempo: float, times, phase: int, seconds: float) -> BeatGrid:
    """Round the measurements for the JSON file. Beats are clamped to the rounded duration, so a beat in the last
    fraction of a millisecond can never land "after the end" and make the file fail to load again."""
    duration = round(seconds, 3)
    beats = [min(round(float(t), 4), duration) for t in times]
    return BeatGrid(bpm=round(tempo, 2), beats=beats, downbeats=beats[phase::4], duration=duration)


def snap(t: float, fps: int = DEFAULT_FPS, lead_frames: int = 1) -> float:
    # Cuts read as "on the beat" when they land a frame early; perception lags the visual change.
    return max(0, round(t * fps) - lead_frames) / fps


def shot_durations(grid: BeatGrid, music_offset: float, beat_counts: list[int], lead_frames: int = 1,
                   fps: int = DEFAULT_FPS) -> list[float]:
    """Shot lengths (seconds, whole frames) for shots lasting `beat_counts` beats each, with the edit starting at
    `music_offset` seconds into the track."""
    first = next((i for i, b in enumerate(grid.beats) if b >= music_offset - 1e-6), None)
    if first is None:
        raise ValueError("track too short: no beat after music_offset")
    cuts, idx = [], first
    for n in beat_counts:
        idx += n
        if idx >= len(grid.beats):
            raise ValueError(f"track too short: needs beat #{idx}, track has {len(grid.beats)} beats")
        cuts.append(snap(grid.beats[idx] - music_offset, fps, lead_frames))
    starts = [0.0] + cuts[:-1]
    return [round(e - s, 4) for s, e in zip(starts, cuts, strict=True)]


def _blocks(grid: BeatGrid, bars: int, fps: int = DEFAULT_FPS) -> list[tuple[float, float]]:
    """`bars`-bar blocks from the downbeats; a pickup before the first downbeat is its own block."""
    starts = list(grid.downbeats[::bars]) or [0.0]
    if starts[0] > 1 / fps:
        starts.insert(0, 0.0)
    ends = starts[1:] + [grid.duration]
    return [(s, e) for s, e in zip(starts, ends, strict=True) if e - s > 1e-6]


def track_energy(path, grid: BeatGrid, bars: int = 4, fps: int = DEFAULT_FPS) -> list[dict]:
    """Loudness and onset density per block, for spotting a track's intro / build / drop / outro."""
    import librosa

    y, sr = _load_mono(path)
    onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time")
    rows = []
    for s, e in _blocks(grid, bars, fps):
        seg = y[int(s * sr):int(e * sr)]
        rms = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
        n = int(np.count_nonzero((onsets >= s) & (onsets < e)))
        rows.append({"start": round(s, 3), "end": round(e, 3), "rms_db": round(20 * np.log10(max(rms, 1e-10)), 2),
                     "onset_density": round(n / (e - s), 3)})
    return rows
