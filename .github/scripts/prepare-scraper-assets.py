#!/usr/bin/env python3
"""Optimize Batocera scraper media in a staged release package."""
from pathlib import Path
import sys

from PIL import Image


def prepare(asset_dir: Path) -> None:
    for stem in ("screenshot", "box2d", "fanart"):
        source = asset_dir / f"{stem}.png"
        target = asset_dir / f"{stem}.jpg"
        if not source.is_file():
            # Source archives ship the same optimized JPEGs as release packages.
            with Image.open(target) as image:
                if image.format != "JPEG":
                    raise ValueError(f"not a JPEG: {target}")
            continue
        with Image.open(source) as image:
            image.convert("RGB").save(
                target, "JPEG", quality=88, optimize=True, progressive=True
            )
        source.unlink()

    logo = asset_dir / "logo.png"
    if not logo.is_file():
        raise FileNotFoundError(logo)
    with Image.open(logo) as image:
        image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        image.save(logo, "PNG", optimize=True, compress_level=9)

    with Image.open(logo) as image:
        if image.width > 1200:
            raise ValueError(f"logo is still {image.width}px wide")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: prepare-scraper-assets.py ASSET_DIRECTORY")
    prepare(Path(sys.argv[1]))
