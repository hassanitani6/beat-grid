"""beat-grid: measure a song's beats and cut video to them.

    beat-grid demo             [-o DIR]          a synthetic drum loop, demo.wav, to try it on
    beat-grid analyze SONG...  [-o DIR]          beats, bar starts and tempo -> SONG.beats.json
    beat-grid click GRID.json  [-o DIR]          click track WAV at every measured beat
    beat-grid cuts GRID.json --beats 4,2,2,1,1   shot lengths that land on the beat, in whole frames
    beat-grid energy SONG [--grid GRID.json]     loudness and busyness per block of bars (find the drop)
    beat-grid doctor                             environment report for bug reports
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path

from . import __version__

AUDIO_TYPES = {".wav", ".flac", ".ogg", ".mp3", ".aiff", ".aif", ".m4a"}
# Names Windows reserves for devices, with or without an extension ("con.beats.json" is reserved too).
RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])$", re.IGNORECASE)


def reserved_on_windows(name: str) -> bool:
    """Windows ignores trailing dots and spaces and everything after the first dot when matching device names."""
    return bool(RESERVED.match(name.rstrip(" .").split(".")[0].rstrip(" ")))
MAX_SHOTS = 1000


class CliError(Exception):
    """A problem with the user's input; printed as one clean error line."""


def _stem(path: Path) -> str:
    name = path.name
    for suffix in (".beats.json", ".grid.json", ".json"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def _atomic(dest: Path, write) -> None:
    """Write to a new, uniquely named temporary file beside dest, then rename it over dest, so an interrupted run
    never leaves a half-written file and never touches a file it didn't create."""
    fd, name = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".part")
    os.close(fd)
    tmp = Path(name)
    try:
        write(tmp)
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve() or (a.exists() and b.exists() and os.path.samefile(a, b))
    except OSError:
        return False


def check_outputs(pairs: list[tuple[Path, Path]], out_dir: Path, overwrite: bool) -> None:
    """Refuse, before any work, outputs that would replace an input, clash with each other, already exist (without
    --overwrite), or that Windows can't create. `pairs` is (input, output)."""
    if out_dir.exists() and not out_dir.is_dir():
        raise CliError(f"{out_dir} is not a folder (a file has that name); choose another -o")
    problems, owners = [], {}
    inputs = [src for src, _ in pairs]
    for src, out in pairs:
        if reserved_on_windows(out.name):
            problems.append(f"{out.name} is a reserved device name on Windows; rename {src.name} first")
        if any(_same_file(out, i) for i in inputs):
            problems.append(f"{out} would replace an input file")
        key = str(out.resolve()).casefold()  # macOS and Windows treat names that differ only in case as one file
        if key in owners and owners[key] != src:
            problems.append(f"{owners[key].name} and {src.name} would both write {out.name}")
        owners.setdefault(key, src)
    if problems:
        raise CliError("nothing was written:\n  " + "\n  ".join(problems))
    existing = [out for _, out in pairs if out.exists()]
    if existing and not overwrite:
        shown = "\n  ".join(str(p) for p in existing[:10]) + ("\n  ..." if len(existing) > 10 else "")
        raise CliError(f"{len(existing)} output file(s) already exist, so nothing was written:\n  {shown}\n"
                       "Use --overwrite to replace them, or choose another -o.")


def _audio_inputs(paths: list[Path]) -> list[Path]:
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise CliError("not found: " + ", ".join(missing))
    odd = [p.name for p in paths if p.suffix.lower() not in AUDIO_TYPES]
    if odd:
        raise CliError(f"not an audio file: {', '.join(odd)} (looked for {', '.join(sorted(AUDIO_TYPES))})")
    return paths


def _parse_counts(text: str) -> list[int]:
    try:
        counts = [int(x) for x in text.split(",") if x.strip()]
    except ValueError:
        raise CliError(f"--beats must be whole numbers separated by commas, like 4,2,2,1,1 (got {text!r})") from None
    if not counts or any(n < 1 for n in counts):
        raise CliError("--beats needs at least one shot, and every shot must last 1 beat or more")
    if len(counts) > MAX_SHOTS:
        raise CliError(f"--beats lists {len(counts)} shots (at most {MAX_SHOTS})")
    return counts


def _say(args, text: str) -> None:
    if not args.quiet:
        print(text)


def _decode_failure(e: BaseException) -> str | None:
    """Why a song couldn't be used, or None for an unexpected error (a bug, which should not be hidden)."""
    from .grid import decode_errors
    if isinstance(e, ValueError):
        return str(e)
    if isinstance(e, MemoryError):
        return "not enough memory to analyse it"
    if isinstance(e, decode_errors()):
        return f"couldn't decode it ({type(e).__name__}); for M4A/AAC and similar formats install ffmpeg"
    return None


def _analyze(args) -> int:
    from .grid import analyze_track, decode_errors, grid_json
    tracks = _audio_inputs(args.songs)
    pairs = [(t, args.out_dir / f"{_stem(t)}.beats.json") for t in tracks]
    check_outputs(pairs, args.out_dir, args.overwrite)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    failed = 0
    for i, (track, out) in enumerate(pairs, 1):
        try:
            g = analyze_track(track)
        except (ValueError, MemoryError, *decode_errors()) as e:
            failed += 1
            why = _decode_failure(e)
            print(f"[{i}/{len(pairs)}] {track.name}: skipped ({why})", file=sys.stderr)
            continue
        text = grid_json(g)
        _atomic(out, lambda p, text=text: p.write_text(text, encoding="utf-8", newline="\n"))
        _say(args, f"[{i}/{len(pairs)}] {track.name}: {g.bpm:g} BPM, {len(g.beats)} beats, "
                   f"{len(g.downbeats)} bars -> {out}")
    if failed:
        print(f"{failed} of {len(pairs)} song(s) were not analysed.", file=sys.stderr)
    return 1 if failed else 0


def _click(args) -> int:
    from .click import accent_count, click_samples, write_wav
    from .grid import load_grid
    if not args.grid.is_file():
        raise CliError(f"not found: {args.grid}")
    grid = load_grid(args.grid)
    out = args.out_dir / f"{_stem(args.grid)}.click.wav"
    check_outputs([(args.grid, out)], args.out_dir, args.overwrite)
    audio = click_samples(grid, args.sample_rate)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    _atomic(out, lambda p: write_wav(audio, p, args.sample_rate))
    accented = accent_count(grid, args.sample_rate)
    _say(args, f"{len(grid.beats)} clicks ({accented} accented) -> {out}")
    if accented < len(grid.downbeats):
        print(f"warning: {len(grid.downbeats) - accented} downbeat(s) don't fall on any beat in the grid, so they "
              "have no click", file=sys.stderr)
    return 0


def _cuts(args) -> int:
    from .grid import load_grid, shot_durations
    if not args.grid.is_file():
        raise CliError(f"not found: {args.grid}")
    if not 1 <= args.fps <= 240:
        raise CliError("--fps must be between 1 and 240")
    if not 0 <= args.lead <= 10:
        raise CliError("--lead must be between 0 and 10 frames")
    grid = load_grid(args.grid)
    counts = _parse_counts(args.beats)
    offset = args.offset
    if offset is not None and not (math.isfinite(offset) and offset >= 0):
        raise CliError("--offset must be a number of seconds, 0 or more")
    if offset is None:
        offset = grid.downbeats[0] if grid.downbeats else grid.beats[0]
    try:
        durations = shot_durations(grid, offset, counts, args.lead, args.fps)
    except ValueError as e:
        raise CliError(str(e)) from None
    empty = [i for i, d in enumerate(durations, 1) if round(d * args.fps) < 1]
    if empty:
        raise CliError(f"shot(s) {', '.join(map(str, empty))} would be 0 frames long; use a smaller --lead, a higher "
                       "--fps, or more beats per shot")
    if args.json:
        shots = [{"beats": n, "seconds": d, "frames": round(d * args.fps)}
                 for n, d in zip(counts, durations, strict=True)]
        print(json.dumps({"offset": offset, "fps": args.fps, "shots": shots}, indent=1))
        return 0
    _say(args, f"music starts at {offset:g} s, {args.fps} fps, cuts {args.lead} frame(s) early")
    for n, d in zip(counts, durations, strict=True):
        print(f"{n} beat{'s' if n != 1 else ' '} -> {d:.2f} s ({round(d * args.fps)} frames)")
    print(f"total {sum(durations):.2f} s")
    return 0


def _energy(args) -> int:
    from .grid import analyze_track, decode_errors, load_grid, track_energy, track_seconds
    (track,) = _audio_inputs([args.song])
    if not 1 <= args.bars <= 64:
        raise CliError("--bars must be between 1 and 64")
    grid = load_grid(args.grid) if args.grid else None
    try:
        if grid is not None:
            seconds = track_seconds(track)
            if abs(seconds - grid.duration) > 0.5:
                print(f"warning: {args.grid.name} is for a {grid.duration:g} s song but {track.name} is "
                      f"{seconds:.3f} s; is it the right grid?", file=sys.stderr)
        grid = grid or analyze_track(track)
        rows = track_energy(track, grid, args.bars, args.fps)
    except (MemoryError, *decode_errors()) as e:
        raise CliError(f"{track.name}: {_decode_failure(e)}") from None
    if args.json:
        print(json.dumps(rows, indent=1))
        return 0
    print(f"{track.name}: {grid.bpm:g} BPM, {args.bars}-bar blocks")
    print(f"{'start':>8} {'end':>8} {'rms_db':>8} {'onset/s':>8}")
    for r in rows:
        print(f"{r['start']:8.2f} {r['end']:8.2f} {r['rms_db']:8.1f} {r['onset_density']:8.2f}")
    return 0


def _parser() -> argparse.ArgumentParser:
    from .grid import DEFAULT_FPS
    p = argparse.ArgumentParser(prog="beat-grid", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"beat-grid {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def outputs(s):
        s.add_argument("-o", "--out-dir", type=Path, default=Path("."), help="output folder (default: current)")
        s.add_argument("--overwrite", action="store_true", help="replace existing output files")

    s = sub.add_parser("demo", help="write a synthetic drum loop (demo.wav) to try the other commands on")
    outputs(s)
    s = sub.add_parser("analyze", help="measure beats, bar starts and tempo")
    s.add_argument("songs", nargs="+", type=Path, help="audio files (wav, flac, mp3, ...)")
    outputs(s)
    s = sub.add_parser("click", help="click track WAV from a beat grid")
    s.add_argument("grid", type=Path, help="a .beats.json file from 'analyze', or your own")
    s.add_argument("--sample-rate", type=int, choices=(44100, 48000), default=48000)
    outputs(s)
    s = sub.add_parser("cuts", help="shot lengths, in whole frames, that cut on the beat")
    s.add_argument("grid", type=Path)
    s.add_argument("--beats", required=True, help="beats per shot, e.g. 4,2,2,1,1")
    s.add_argument("--offset", type=float, help="where the edit starts in the song, seconds (default: first bar)")
    s.add_argument("--fps", type=int, default=DEFAULT_FPS, help=f"video frame rate (default: {DEFAULT_FPS})")
    s.add_argument("--lead", type=int, default=1, help="cut this many frames before the beat (default: 1)")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("energy", help="loudness and onset density per block of bars")
    s.add_argument("song", type=Path)
    s.add_argument("--grid", type=Path, help="use this beat grid instead of measuring the song again")
    s.add_argument("--bars", type=int, default=4, help="bars per block (default: 4)")
    s.add_argument("--fps", type=int, default=DEFAULT_FPS, help=argparse.SUPPRESS)
    s.add_argument("--json", action="store_true")
    for s in sub.choices.values():
        s.add_argument("-q", "--quiet", action="store_true")
    d = sub.add_parser("doctor", help="environment report to paste into bug reports")
    d.add_argument("--json", action="store_true")
    return p


def _demo(args) -> int:
    from .demo import drum_loop
    out = args.out_dir / "demo.wav"
    check_outputs([(Path("<generated>"), out)], args.out_dir, args.overwrite)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    _atomic(out, drum_loop)
    _say(args, f"wrote a synthetic 20-second drum loop -> {out}")
    return 0


COMMANDS = {"demo": _demo, "analyze": _analyze, "click": _click, "cuts": _cuts, "energy": _energy}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    args = _parser().parse_args(argv)
    if args.command == "doctor":
        from .doctor import run
        return run(as_json=args.json)
    try:
        return COMMANDS[args.command](args)
    except (CliError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"error: {e.strerror or e}: {e.filename or ''}".rstrip(": "), file=sys.stderr)
        return 1
