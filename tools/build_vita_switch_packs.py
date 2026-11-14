#!/usr/bin/env python3
"""Adapt the actual SwitchGamesBrowser 16-shard packed-cover format to Vita.

Switch reference: tools/build_cover_pack.py at feature/android-phone-relay.
Each pack is the concatenation of 360x508 JPEGs. The JSON manifest uses
identical pack/offset/size records; a compact TSV mirror avoids pulling a
large JSON parser into the Vita renderer.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from PIL import Image
COVER_WIDTH = 360
COVER_HEIGHT = 508

SHARDS = 16
MAX_POSTER_BYTES = 80 * 1024
PREFIX = "igdb-"


def build_vita_switch_packs(covers_dir: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    shards = [bytearray() for _ in range(SHARDS)]
    entries: dict[str, dict[str, int]] = {}
    for path in sorted(covers_dir.glob("IG???????.jpg")):
        numeric_id = int(path.stem[2:])
        if not numeric_id:
            continue
        key = f"{PREFIX}{numeric_id}"
        data = path.read_bytes()
        if not (4 <= len(data) <= MAX_POSTER_BYTES and
                data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9")):
            raise ValueError(f"Invalid JPEG for {key}")
        with Image.open(path) as poster:
            if poster.size != (COVER_WIDTH, COVER_HEIGHT) or poster.format != "JPEG":
                raise ValueError(f"Invalid image dimensions for {key}")
            poster.verify()
        shard = int(hashlib.sha1(key.encode("utf-8")).hexdigest()[0], 16)
        offset = len(shards[shard])
        shards[shard].extend(data)
        entries[key] = {"pack": shard, "offset": offset, "size": len(data)}

    if len(entries) < 100:
        raise ValueError("Too few Vita IGDB JPEGs for Switch-style packed covers")
    packs = {}
    for i, blob in enumerate(shards):
        name = f"covers-{i:02x}.pack"
        if len(blob) > 16 * 1024 * 1024:
            raise ValueError(f"Vita cover shard {i} exceeds 16 MiB")
        (output_dir / name).write_bytes(blob)
        packs[str(i)] = {
            "file": name, "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
        }

    manifest = {
        "schemaVersion": 2, "width": COVER_WIDTH, "height": COVER_HEIGHT,
        "format": "jpeg", "imageCount": len(entries),
        "packs": packs, "entries": entries,
    }
    (output_dir / "covers-manifest.json").write_text(
        json.dumps(manifest, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    lines = ["# VitaGamesBrowser packed covers 360x508 v2"]
    for i, info in packs.items():
        lines.append(f"PACK\t{i}\t{info['bytes']}\t{info['sha256']}")
    for key, entry in sorted(entries.items()):
        lines.append(f"IMAGE\t{key[5:]}\t{entry['pack']}\t"
                     f"{entry['offset']}\t{entry['size']}")
    (output_dir / "covers-index.tsv").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--covers", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_vita_switch_packs(args.covers, args.output)
    print(f"Switch packed covers: {result['imageCount']} posters / 16 packs")
