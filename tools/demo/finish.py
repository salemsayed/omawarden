#!/usr/bin/env python3
"""Post-process OmaWarden captures: trim panel shots to their border, build the
timed demo GIF from raw frames, compose the bar-state strip and the
marketplace preview card. ImageMagick + ffmpeg only (no PIL on this box)."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "out"
DEST = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "final"
BORDER = (30, 102, 245)  # the panel's accent border at 1x
CANVAS_BG = "#0f1117"


def run(*argv: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([str(a) for a in argv], check=True, text=True, capture_output=True, **kw)


def column(path: Path, x: int) -> list[tuple[int, int, int]]:
    txt = run("magick", path, "-crop", f"1x+{x}+0", "+repage", "-depth", "8", "txt:-").stdout
    rows: list[tuple[int, int, int]] = []
    for line in txt.splitlines()[1:]:
        m = re.match(r"\d+,\d+: \((\d+),(\d+),(\d+)", line)
        if m:
            rows.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    return rows


def is_border(c: tuple[int, int, int]) -> bool:
    return sum(abs(a - b) for a, b in zip(c, BORDER)) < 60


def panel_bottom(path: Path) -> int | None:
    """Last row of the panel's left border (x=1), or None when no panel shows."""
    rows = column(path, 1)
    hits = [y for y, c in enumerate(rows) if is_border(c)]
    if len(hits) < 40 or hits[0] > 6:
        return None
    return hits[-1]


def trim_shot(src: Path, dst: Path) -> None:
    bottom = panel_bottom(src)
    if bottom is None:
        raise SystemExit(f"no panel border found in {src}")
    run("magick", src, "-crop", f"520x{bottom + 1}+0+0", "+repage", dst)
    print(f"{dst.name}: 520x{bottom + 1}")


def build_gif(frames_dir: Path, dst: Path, canvas_h: int = 700) -> None:
    times = [line.split() for line in (frames_dir / "times.txt").read_text().splitlines() if line.strip()]
    frames = [(frames_dir / name, int(ns)) for name, ns in times if (frames_dir / name).exists()]
    if len(frames) < 2:
        raise SystemExit("not enough frames")
    clean = frames_dir / "clean"
    clean.mkdir(exist_ok=True)
    cleaned: list[tuple[Path, int]] = []
    last_bottom: int | None = None
    for path, ns in frames:
        bottom = panel_bottom(path)
        out = clean / path.name
        if bottom is None:
            # Opening/closing animation or nothing on screen: blank frame.
            run("magick", "-size", f"520x{canvas_h}", f"xc:{CANVAS_BG}", out)
        else:
            run("magick", path, "-crop", f"520x{bottom + 1}+0+0", "+repage",
                "-background", CANVAS_BG, "-gravity", "north", "-extent", f"520x{canvas_h}", out)
        last_bottom = bottom
        cleaned.append((out, ns))
    # Drop exact-duplicate consecutive frames (same pixels) to keep the GIF small
    # while preserving timing through the concat durations.
    concat = frames_dir / "concat.txt"
    lines = []
    prev_sig = None
    kept: list[tuple[Path, int]] = []
    for out, ns in cleaned:
        sig = run("magick", out, "-format", "%#", "info:").stdout.strip()
        if sig == prev_sig:
            continue
        prev_sig = sig
        kept.append((out, ns))
    # ImageMagick encodes the GIF: per-frame delays in centiseconds straight
    # from the capture timestamps, frame-differenced, 128 colours.
    # Cap at 10 fps: a frame that lands within 100 ms of the previous kept
    # frame is folded into it (its time is added to the previous delay).
    paced: list[tuple[Path, int]] = []
    for out, ns in kept:
        if paced and ns - paced[-1][1] < 100_000_000:
            continue
        paced.append((out, ns))
    kept = paced
    argv: list[str] = ["magick"]
    for index, (out, ns) in enumerate(kept):
        next_ns = kept[index + 1][1] if index + 1 < len(kept) else ns + 1_500_000_000
        delay = max(10, round((next_ns - ns) / 1e7))  # centiseconds, ≥ 100 ms
        lines.append(f"file '{out}'\nduration {delay / 100:.3f}")
        argv += ["-delay", str(delay), str(out)]
    concat.write_text("\n".join(lines) + "\n")
    argv += ["-loop", "0", "-coalesce", "-colors", "96", "-fuzz", "3%", "-layers", "OptimizeFrame", str(dst)]
    run(*argv)
    print(f"{dst.name}: {len(kept)} frames kept of {len(frames)}, {dst.stat().st_size // 1024} KiB")


def bar_strip(dst: Path) -> None:
    tiles = []
    for name, label in (("bar-locked", "locked"), ("bar-unlocked", "unlocked"), ("bar-signin", "needs you")):
        src = OUT / f"{name}.png"
        if not src.exists():
            continue
        tile = OUT / f"{name}-tile.png"
        run("magick", src, "-filter", "point", "-resize", "400%",
            "-gravity", "south", "-background", CANVAS_BG, "-fill", "#c9cdd6",
            "-font", "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf", "-pointsize", "16", "-splice", "0x30", "-annotate", "+0+6", label, tile)
        tiles.append(tile)
    if not tiles:
        return
    run("magick", *tiles, "+append", "-background", CANVAS_BG, "-gravity", "center", "-extent", "110%x100%", dst)
    print(f"{dst.name}")


def onboarding_strip(dst: Path) -> None:
    """Setup → sign-in → locked, side by side on the card background."""
    parts = [DEST / f"{name}.png" for name in ("panel-setup", "panel-signin", "panel-locked")]
    if not all(part.exists() for part in parts):
        return
    run("magick", *parts, "-background", CANVAS_BG,
        "-gravity", "west", "-splice", "24x0", "-gravity", "north", "-splice", "0x24", "+append",
        "-gravity", "south", "-splice", "0x24", "-gravity", "east", "-splice", "24x0", "+repage", dst)
    print(f"{dst.name}")


def preview_card(dst: Path, front: Path, back: Path) -> None:
    """1200x750 marketplace card in the same spirit as the sibling plugins."""
    run("magick", "-size", "1200x750", "gradient:#14182a-#0b0d16", "-gravity", "northwest",
        "-fill", "#e7e9f0", "-font", "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Bold.ttf", "-pointsize", "46", "-annotate", "+116+34", "OmaWarden",
        "-fill", "#9aa3b5", "-font", "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf", "-pointsize", "19",
        "-annotate", "+117+92", "Bitwarden in the Omarchy bar — instant search, safe copies, one-key lock",
        "(", back, "-resize", "560x", ")", "-geometry", "+600+150", "-composite",
        "(", front, "-resize", "560x",
        "(", "+clone", "-background", "black", "-shadow", "60x18+0+14", ")", "+swap", "-background", "none",
        "-layers", "merge", "+repage", ")", "-geometry", "+100+300", "-composite",
        dst)
    print(f"{dst.name}")


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    for name in ("panel-locked", "panel-vault", "panel-search", "panel-settings", "panel-signin", "panel-setup"):
        src = OUT / f"{name}.png"
        if src.exists():
            trim_shot(src, DEST / f"{name}.png")
    if (OUT / "frames" / "times.txt").exists():
        build_gif(OUT / "frames", DEST / "demo.gif")
    bar_strip(DEST / "bar-states.png")
    onboarding_strip(DEST / "onboarding.png")
    if (DEST / "panel-vault.png").exists() and (DEST / "panel-search.png").exists():
        preview_card(DEST / "preview.png", DEST / "panel-search.png", DEST / "panel-vault.png")


if __name__ == "__main__":
    main()
