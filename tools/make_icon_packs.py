#!/usr/bin/env python3
"""Create PS Vita cover ZIP packs consumed by the Vita Games Browser.

Input JPEGs: covers/PCSE00000.jpg (nine-character uppercase Vita title IDs).
Optional genres.tsv: TITLEID<TAB>Action,RPG  (one title per line).
ZIPs must be hosted at publicly accessible HTTPS URLs, including for private
VitaGamesBrowser repositories. This script does not upload any artifacts.
"""
from __future__ import annotations
import argparse
import re
from pathlib import Path
from zipfile import ZipFile, ZIP_STORED

ID_PATTERN = re.compile(r"^[A-Z0-9]{9}\.jpg$")
MAX_JPEG = 256 * 1024
MAX_PACK = 12 * 1024 * 1024
MAX_FILES_PER_PACK = 1000  # Vita ZIP reader caps at 1200 entries including metadata

def create_packs(covers_dir: Path, output_dir: Path, base_url: str,
                 genre_file: Path | None = None) -> list[tuple[str, str]]:
    if not base_url.startswith("https://"):
        raise ValueError("A public HTTPS base URL is required")
    output_dir.mkdir(parents=True, exist_ok=True)
    genre = b""
    if genre_file:
        genre = genre_file.read_bytes()
        if len(genre) > 512 * 1024:
            raise ValueError("genres.tsv is too large")
        for line in genre.decode("utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t", 1)
            if len(fields) != 2 or not re.fullmatch(r"[A-Z0-9]{9}", fields[0]):
                raise ValueError(f"Invalid genre row: {line[:100]}")
    valid_files: list[Path] = []
    for path in sorted(covers_dir.glob("*.jpg")):
        if not ID_PATTERN.fullmatch(path.name):
            continue
        size = path.stat().st_size
        if size > MAX_JPEG or size < 4:
            raise ValueError(f"JPEG must be 4 bytes to 256 KiB: {path}")
        with path.open("rb") as f:
            if f.read(3) != b"\xff\xd8\xff":
                raise ValueError(f"Not a JPEG: {path}")
        valid_files.append(path)
    batches: list[list[Path]] = []
    current: list[Path] = []
    total = len(genre) + 8192
    for path in valid_files:
        size = path.stat().st_size + 256
        if current and (total + size > MAX_PACK or len(current) >= MAX_FILES_PER_PACK):
            batches.append(current)
            current = []
            total = len(genre) + 8192
        current.append(path)
        total += size
    if current:
        batches.append(current)
    if not batches and genre:
        batches.append([])
    packs: list[tuple[str, str]] = []
    for index, group in enumerate(batches, 1):
        filename = f"vita-icons-{index:02d}.zip"
        target = output_dir / filename
        with ZipFile(target, "w", compression=ZIP_STORED) as zipfile:
            if genre:
                zipfile.writestr("genres.tsv", genre)
            for jpg in group:
                zipfile.write(jpg, jpg.name)
        if target.stat().st_size > 16 * 1024 * 1024:
            raise ValueError(f"Pack exceeds Vita memory limit: {target}")
        packs.append((f"Vita icons {index}/{len(batches)}",
                      base_url.rstrip("/") + "/" + filename))
    (output_dir / "packs.tsv").write_text(
        "".join(f"{name}\t{url}\n" for name, url in packs),
        encoding="utf-8")
    return packs

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--covers", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--genres", type=Path)
    args = parser.parse_args()
    packs = create_packs(args.covers, args.output, args.base_url, args.genres)
    print(f"Built {len(packs)} packs and {args.output / 'packs.tsv'}")

if __name__ == "__main__":
    main()
