#!/usr/bin/env python3
"""Compose the 1600x900 announcement graphic (Discord, Twitter, repo social
preview) from the README panel screenshots. ImageMagick only.

    tools/demo/social.py [docs/images/announcement.png]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGES = ROOT / "docs" / "images"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else IMAGES / "announcement.png"
MONO = "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf"
BOLD = "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Bold.ttf"

W, H = 1600, 900
FG, DIM, FAINT, ACCENT = "#e7e9f0", "#9aa3b5", "#6b7487", "#5b8cff"
INSTALL = "omarchy plugin add https://github.com/salemsayed/omawarden.git --enable"
HIGHLIGHTS = [
    "Instant, ranked search of your logins",
    "Passwords, usernames and one-time codes on a",
    "self-clearing clipboard, never in history",
    "Vault secrets never touch the shell",
]


def main() -> None:
    argv = ["magick", "-size", f"{W}x{H}", "gradient:#14182a-#0b0d16", "-gravity", "northwest"]
    argv += ["-fill", FG, "-font", BOLD, "-pointsize", "76", "-annotate", "+96+96", "OmaWarden"]
    argv += ["-fill", DIM, "-font", MONO, "-pointsize", "30", "-annotate", "+98+196", "Bitwarden in the Omarchy bar"]
    y = 296
    bullets = [(0, HIGHLIGHTS[0]), (0, HIGHLIGHTS[1]), (1, HIGHLIGHTS[2]), (0, HIGHLIGHTS[3])]
    for cont, line in bullets:
        if not cont:
            argv += ["-fill", ACCENT, "-font", BOLD, "-pointsize", "22", "-annotate", f"+98+{y}", "▸"]
        argv += ["-fill", "#c9cdd6", "-font", MONO, "-pointsize", "22", "-annotate", f"+128+{y}", line]
        y += 34 if cont or bullets.index((cont, line)) == 1 else 44
    # Install command in a chip.
    chip_w, chip_h, cx, cy = 720, 56, 96, 776
    argv += ["-fill", "#1b2033", "-stroke", "#2c3450", "-strokewidth", "1",
             "-draw", f"roundrectangle {cx},{cy} {cx + chip_w},{cy + chip_h} 10,10", "-stroke", "none"]
    argv += ["-fill", FAINT, "-font", MONO, "-pointsize", "15", "-annotate", f"+{cx + 18}+{cy + 19}", "$ " + INSTALL]
    # Panels: vault behind, search in front with a soft shadow.
    argv += ["(", str(IMAGES / "panel-vault.png"), "-resize", "560x", ")", "-geometry", "+960+96", "-composite"]
    argv += ["(", str(IMAGES / "panel-search.png"), "-resize", "560x",
             "(", "+clone", "-background", "black", "-shadow", "60x18+0+14", ")", "+swap",
             "-background", "none", "-layers", "merge", "+repage", ")", "-geometry", "+790+470", "-composite"]
    argv += [str(OUT)]
    subprocess.run(argv, check=True)
    print(OUT)


if __name__ == "__main__":
    main()
