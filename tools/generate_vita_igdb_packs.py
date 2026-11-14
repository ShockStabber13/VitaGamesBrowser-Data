#!/usr/bin/env python3
"""Build PS Vita-specific IGDB cover/genre ZIPs for the Vita Games Browser.

Only public game metadata (title IDs, genres, cover JPEGs) is published.
NPS package URLs, zRIFs, and other package entitlements are never exported.
"""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import difflib
import io
import json
import os
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

from make_icon_packs import create_packs
from build_vita_switch_packs import build_vita_switch_packs

VITA_PLATFORM = 46
BASE_GAME_TYPES = {0, 4, 8, 9, 10, 11, 12}
NPS_GAMES_URL = "https://nopaystation.com/tsv/PSV_GAMES.tsv"
IGDB_GAMES_URL = "https://api.igdb.com/v4/games"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
VITA_ID = re.compile(r"^[A-Z0-9]{9}$")
REGION_SUFFIX = re.compile(
    r"\s*[\[(](?:USA|US|EUR|EU|JPN|JP|ASIA|ASA|ENG|EN|"
    r"CHN|KOR|GER|FRA|ITA|ESP|RUS|UK|ENGLISH)[\])]\s*$",
    re.I,
)
GENRES = {
    "Action": "Action",
    "Adventure": "Adventure",
    "Role-playing (RPG)": "RPG",
    "Platform": "Platformer",
    "Puzzle": "Puzzle",
    "Racing": "Racing",
    "Sport": "Sports",
    "Fighting": "Fighting",
    "Strategy": "Strategy",
    "Tactical": "Strategy",
    "Simulator": "Simulation",
    "Simulation": "Simulation",
    "Visual Novel": "Visual Novel",
    "Shooter": "Shooter",
    "Music": "Music",
    "Indie": "Indie",
    "Arcade": "Arcade",
    "Point-and-click": "Adventure",
    "Hack and slash/Beat 'em up": "Action",
    "Quiz/Trivia": "Puzzle",
    "Pinball": "Arcade",
    "Card & Board Game": "Strategy",
}
MAX_NPS_BYTES = 32 * 1024 * 1024
MAX_COVER_BYTES = 5 * 1024 * 1024


def fetch_limited(url: str, max_bytes: int, headers: dict | None = None,
                  data: bytes | None = None) -> bytes:
    request = Request(url, data=data, headers={
        "User-Agent": "VitaGamesBrowser-IGDB/0.15",
        **(headers or {}),
    }, method="POST" if data is not None else "GET")
    with urlopen(request, timeout=90) as response:
        content = response.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(f"Response exceeds {max_bytes:,} bytes: {url}")
    return content


def parse_nps_games(raw: bytes) -> dict[str, str]:
    # Same TSV indices as blastrock/pkgj src/db.cpp ModeGames.
    result: dict[str, str] = {}
    for row in csv.reader(io.StringIO(raw.decode("utf-8-sig", "replace")),
                          delimiter="\t"):
        if len(row) < 6:
            continue
        content_id = row[5].strip()
        if len(content_id) < 16:
            continue
        title_id = content_id[7:16].upper()
        if not VITA_ID.fullmatch(title_id):
            continue
        title = row[2].strip()
        # Mirror the current PKGj list: skip unavailable game packages.
        if not title or not row[3].strip() or row[3] in {"MISSING", "CART ONLY"}:
            continue
        if row[4] == "MISSING":
            continue
        result.setdefault(title_id, title)
    return result


def get_igdb_token(client_id: str, client_secret: str) -> str:
    if not client_id or not client_secret:
        raise ValueError("IGDB_CLIENT_ID and IGDB_CLIENT_SECRET are required")
    body = urlencode({"client_id": client_id, "client_secret": client_secret,
                      "grant_type": "client_credentials"}).encode()
    response = json.loads(fetch_limited(TOKEN_URL, 64 * 1024,
                                        {"Content-Type": "application/x-www-form-urlencoded"},
                                        body))
    if not response.get("access_token"):
        raise ValueError("Twitch OAuth did not provide an IGDB token")
    return response["access_token"]


def get_vita_igdb_games(client_id: str, client_secret: str) -> list[dict]:
    token = get_igdb_token(client_id, client_secret)
    headers = {"Client-ID": client_id,
               "Authorization": "Bearer " + token,
               "Content-Type": "text/plain"}
    items: list[dict] = []
    last = 0
    while True:
        query = (
            "fields id,name,game_type,cover.image_id,artworks.image_id,"
            "screenshots.image_id,genres.name,alternative_names.name,"
            "rating,rating_count,first_release_date,summary;"
            f"where id > {last} & platforms = ({VITA_PLATFORM});"
            "sort id asc; limit 500;"
        ).encode()
        for attempt in range(6):
            try:
                batch = json.loads(fetch_limited(IGDB_GAMES_URL, 6 * 1024 * 1024,
                                                 headers, query))
                break
            except Exception:
                if attempt == 5:
                    raise
                time.sleep(min(30, 2 ** (attempt + 1)))
        if not isinstance(batch, list):
            raise ValueError(f"Unexpected IGDB response: {str(batch)[:200]}")
        if not batch:
            break
        for game in batch:
            gid = int(game["id"])
            if gid <= last:
                continue
            last = gid
            if int(game.get("game_type") or 0) in BASE_GAME_TYPES and game.get("name"):
                items.append(game)
        if len(batch) < 500:
            break
        time.sleep(0.38)
    if len(items) < 100:
        raise ValueError("IGDB returned unexpectedly few PSVita entries")
    return items


def normalize(name: str) -> str:
    name = name.replace("™", "").replace("®", "")
    name = unicodedata.normalize("NFKD", name).casefold()
    name = "".join(c for c in name if not unicodedata.combining(c))
    while REGION_SUFFIX.search(name):
        name = REGION_SUFFIX.sub("", name)
    name = name.replace("&", " and ")
    name = name.replace("™", "").replace("®", "")
    name = re.sub(r"[^a-z0-9]+", " ", name)
    name = " ".join(name.split())
    return name[4:] if name.startswith("the ") else name


def aliases(game: dict) -> set[str]:
    vals = [game.get("name") or ""]
    vals.extend(a.get("name") or "" for a in game.get("alternative_names") or []
                if isinstance(a, dict))
    return {s for x in vals if (s := normalize(str(x)))}


def make_lookup(games: list[dict]) -> tuple[dict[str, list[dict]], dict[str, list[tuple[str, dict]]]]:
    exact: dict[str, list[dict]] = {}
    buckets: dict[str, list[tuple[str, dict]]] = {}
    for game in games:
        for alias in aliases(game):
            exact.setdefault(alias, []).append(game)
            buckets.setdefault(alias.split()[0], []).append((alias, game))
    return exact, buckets


def match_game(title: str, lookup) -> tuple[dict | None, str]:
    exact, buckets = lookup
    name = normalize(title)
    if not name:
        return None, "empty"
    matches = {int(x["id"]): x for x in exact.get(name, [])}
    if len(matches) == 1:
        return next(iter(matches.values())), "exact"
    if len(matches) > 1:
        return None, "ambiguous"
    # Fuzzy matching requires a very high threshold and a clear winner.
    # Matching against only the first title word reduces false positives.
    scored: dict[int, float] = {}
    first_word = name.split()[0]
    for alias, game in buckets.get(first_word, []):
        if abs(len(alias) - len(name)) > max(3, int(len(name) * .12)):
            continue
        score = difflib.SequenceMatcher(None, name, alias).ratio()
        gid = int(game["id"])
        scored[gid] = max(score, scored.get(gid, 0))
    top = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)
    if top and top[0][1] >= .96 and (len(top) == 1 or top[0][1] - top[1][1] >= .05):
        gid = top[0][0]
        for matches in exact.values():
            for game in matches:
                if int(game["id"]) == gid:
                    return game, "fuzzy"
    return None, "unmatched"


def mapped_genres(game: dict) -> list[str]:
    result = set()
    for field in game.get("genres") or []:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name", ""))
        result.add(GENRES.get(name, "Other"))
    return sorted(result)


def cover_candidates(game: dict) -> list[str]:
    """Same IGDB order and size fallback as SwitchGamesBrowser.

    First cover_big_2x -> cover_big; then artworks; then screenshots.
    A missing cover or failed image no longer becomes permanent NO ART.
    """
    sources: list[tuple[str, str]] = []
    cover = game.get("cover") or {}
    if isinstance(cover, dict) and cover.get("image_id"):
        sources.append(("t_cover_big_2x", str(cover["image_id"])))
        sources.append(("t_cover_big", str(cover["image_id"])))
    for key, size in (("artworks", "t_720p"),
                      ("screenshots", "t_screenshot_big")):
        for entry in game.get(key) or []:
            if isinstance(entry, dict) and entry.get("image_id"):
                sources.append((size, str(entry["image_id"])))
    urls: list[str] = []
    for size, image_id in sources:
        if re.fullmatch(r"[a-zA-Z0-9_]+", image_id):
            url = ("https://images.igdb.com/igdb/image/upload/"
                   + size + "/" + image_id + ".jpg")
            if url not in urls:
                urls.append(url)
    return urls


def cover_url(game: dict) -> str:
    """Return the best IGDB candidate, retained for existing callers."""
    options = cover_candidates(game)
    return options[0] if options else ""


COVER_WIDTH = 360
COVER_HEIGHT = 508
COVER_MAX_BYTES = 80 * 1024


def make_cover(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as img:
        if img.width > 5000 or img.height > 5000:
            raise ValueError("Unreasonably large cover image")
        img = ImageOps.contain(img.convert("RGB"), (COVER_WIDTH, COVER_HEIGHT),
                               method=Image.Resampling.LANCZOS)
        out_image = Image.new("RGB", (COVER_WIDTH, COVER_HEIGHT), (0, 0, 0))
        out_image.paste(img, ((COVER_WIDTH - img.width) // 2, (COVER_HEIGHT - img.height) // 2))
        for quality in (88, 82, 74, 66, 58, 48, 38):
            out = io.BytesIO()
            out_image.save(out, "JPEG", quality=quality, optimize=True)
            if len(out.getvalue()) <= COVER_MAX_BYTES:
                return out.getvalue()
    raise ValueError("Could not fit image within Vita pack limits")


def igdb_cover_key(igdb_id: int) -> str:
    """Use a fixed nine-character, non-NPS key accepted by Vita ZIP loader."""
    if not 0 < igdb_id < 10_000_000:
        raise ValueError(f"Unsupported IGDB numeric ID: {igdb_id}")
    return f"IG{igdb_id:07d}"


def igdb_library(games: list[dict]) -> str:
    """Complete standalone IGDB catalog; NO NPS/P KGj match is required.

    TSV: IGDB ID, name, genres, alternatives, cover key, rating, votes, date, summary, screenshot IDs.
    Fields are escaped by excluding tab/newline and the alias separator.
    """
    def clean(value: str) -> str:
        return str(value).replace("\t", " ").replace("\n", " ").replace("\r", " ").replace("|", " ").strip()

    lines = []
    seen = set()
    for game in sorted(games, key=lambda x: clean(x["name"]).casefold()):
        gid = int(game["id"])
        if gid in seen or not game.get("name"):
            continue
        seen.add(gid)
        aliases_ = [clean(row.get("name", "")) for row in
                    game.get("alternative_names") or [] if isinstance(row, dict)]
        genres = [clean(x) for x in mapped_genres(game)]
        try:
            rating = int(round(float(game.get("rating") or -1)))
            rating = max(-1, min(100, rating))
        except (TypeError, ValueError):
            rating = -1
        votes = max(0, int(game.get("rating_count") or 0))
        try:
            released = dt.datetime.fromtimestamp(
                int(game.get("first_release_date") or 0),
                dt.timezone.utc
            ).strftime("%Y-%m-%d") if game.get("first_release_date") else ""
        except (TypeError, ValueError, OverflowError):
            released = ""
        summary = clean(game.get("summary") or "")[:850]
        # Only actual IGDB screenshot image IDs. No videos or thumbnails
        # pretending to be screenshots. Poster is always gallery item 0.
        screenshots = []
        for item in game.get("screenshots") or []:
            if not isinstance(item, dict):
                continue
            image_id = str(item.get("image_id") or "")
            if (re.fullmatch(r"[A-Za-z0-9_]+", image_id) and
                    image_id not in screenshots):
                screenshots.append(image_id)
            if len(screenshots) == 6:
                break
        lines.append("\t".join([str(gid), clean(game["name"]),
                                 ",".join(genres),
                                 "|".join(x for x in aliases_ if x),
                                 igdb_cover_key(gid),
                                 str(rating), str(votes), released, summary,
                                 "|".join(screenshots)]))
    return "\n".join(lines) + "\n"


def add_igdb_posters(games: list[dict], cover_dir: Path,
                     mapped: list[dict]) -> tuple[int, int]:
    """Generate one IGDB poster per game, never dependent on PKGj names.

    First reuse the already downloaded matched NPS cover if possible;
    otherwise use the Switch-style URL fallback order.
    """
    by_id = {}
    for item in mapped:
        if item.get("hasCover"):
            by_id.setdefault(int(item["igdbId"]), item["titleId"])
    jobs: dict[tuple[str, ...], list[Path]] = {}
    written = 0
    for game in games:
        gid = int(game["id"])
        dest = cover_dir / (igdb_cover_key(gid) + ".jpg")
        if dest.exists():
            written += 1
            continue
        nps_titleid = by_id.get(gid)
        if nps_titleid and (cover_dir / (nps_titleid + ".jpg")).exists():
            dest.write_bytes((cover_dir / (nps_titleid + ".jpg")).read_bytes())
            written += 1
            continue
        choices = tuple(cover_candidates(game))
        if choices:
            jobs.setdefault(choices, []).append(dest)
    failures = 0

    def download_choices(urls):
        error = None
        for url in urls:
            try:
                return make_cover(fetch_limited(url, MAX_COVER_BYTES))
            except Exception as exc:
                error = exc
        raise RuntimeError(f"No IGDB artwork available: {error}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        tasks = {pool.submit(download_choices, urls): dests
                 for urls, dests in jobs.items()}
        for future in as_completed(tasks):
            dests = tasks[future]
            try:
                jpeg = future.result()
                for dest in dests:
                    dest.write_bytes(jpeg)
                    written += 1
            except Exception:
                failures += len(dests)
    return written, failures


def create_catalog(nps: dict[str, str], games: list[dict],
                   cover_dir: Path) -> tuple[dict, list[dict]]:
    cover_dir.mkdir(parents=True, exist_ok=True)
    lookup = make_lookup(games)
    output: list[dict] = []
    pending: dict[tuple[str, ...], list[str]] = {}
    matched = 0
    for title_id, nps_name in sorted(nps.items()):
        game, quality = match_game(nps_name, lookup)
        if game is None:
            continue
        matched += 1
        genres = mapped_genres(game)
        urls = tuple(cover_candidates(game))
        if urls and not (cover_dir / f"{title_id}.jpg").exists():
            pending.setdefault(urls, []).append(title_id)
        output.append({"titleId": title_id, "name": nps_name,
                       "igdbId": int(game["id"]), "genres": genres,
                       "match": quality, "hasCover": False})
    if matched < 100:
        raise ValueError("Fewer than 100 matching PSVita games; not publishing packs")

    # A single IGDB cover commonly serves several regional NPS title IDs.
    # Fetch each unique image only once and replicate its optimized JPEG.
    failures = 0
    def get_cover(urls: tuple[str, ...]) -> bytes:
        last_error: Exception | None = None
        for url in urls:
            try:
                return make_cover(fetch_limited(url, MAX_COVER_BYTES))
            except Exception as error:
                last_error = error
        raise RuntimeError(f"No usable IGDB image: {last_error}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        tasks = {pool.submit(get_cover, urls): (urls, ids)
                 for urls, ids in pending.items()}
        for index, future in enumerate(as_completed(tasks), 1):
            urls, ids = tasks[future]
            try:
                data = future.result()
                for title_id in ids:
                    (cover_dir / f"{title_id}.jpg").write_bytes(data)
            except Exception as e:
                failures += len(ids)
                if failures <= 8:
                    print(f"Could not download cover {urls[0]}: {e}", flush=True)
            if index % 100 == 0:
                print(f"IGDB images: {index}/{len(tasks)} sources", flush=True)

    icons = 0
    for game in output:
        game["hasCover"] = (cover_dir / f"{game['titleId']}.jpg").exists()
        if game["hasCover"]:
            icons += 1
    if icons < 50:
        raise ValueError(
            f"Only {icons} PS Vita covers generated; refusing empty/incomplete publication"
        )
    metadata = {
        "schemaVersion": 1, "platform": "PlayStation Vita",
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "npsGames": len(nps), "igdbGames": len(games),
        "matchedTitles": matched, "generatedCovers": icons,
        "unmatchedTitles": len(nps) - matched, "imageFailures": failures,
        "games": output,
    }
    return metadata, output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/vita"))
    parser.add_argument("--public-url", default=(
        "https://raw.githubusercontent.com/ShockStabber13/"
        "VitaGamesBrowser-Data/main/vita"))
    parser.add_argument("--nps-tsv", type=Path, help="Optional local PSV_GAMES.tsv for testing")
    args = parser.parse_args()
    if args.nps_tsv:
        nps_raw = args.nps_tsv.read_bytes()
    else:
        nps_raw = fetch_limited(NPS_GAMES_URL, MAX_NPS_BYTES)
    nps = parse_nps_games(nps_raw)
    if len(nps) < 100:
        raise ValueError(f"NPS PSV game list too small: {len(nps)} entries")
    games = get_vita_igdb_games(os.environ.get("IGDB_CLIENT_ID", ""),
                                 os.environ.get("IGDB_CLIENT_SECRET", ""))
    covers = args.output / "_covers"
    metadata, matches = create_catalog(nps, games, covers)
    library_text = igdb_library(games)
    standalone_posters, poster_failures = add_igdb_posters(games, covers, matches)
    # Exactly the Switch packed-cover binary layout: 16 raw JPEG shards
    # indexed by IGDB ID and byte offset. No Vita ZIP extraction required.
    switch_covers = build_vita_switch_packs(covers, args.output)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "igdb-library.tsv").write_text(library_text, encoding="utf-8")
    print(f"IGDB-first library: {len(games)} games, "
          f"{standalone_posters} posters, {poster_failures} failed images", flush=True)
    (args.output / "igdb-vita-games.json").write_text(
        json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")
    genres = "\n".join(f"{x['titleId']}\t{','.join(x['genres'])}"
                       for x in matches if x["genres"]) + "\n"
    genres_path = args.output / "genres.tsv"
    genres_path.write_text(genres, encoding="utf-8")
    packs = create_packs(covers, args.output, args.public_url, genres_path)
    if not packs:
        raise ValueError("No downloadable Vita icon packs generated")
    print(json.dumps({k: v for k, v in metadata.items() if k != "games"},
                     indent=2), flush=True)
    print(f"Wrote {len(packs)} icon ZIP packs to {args.output}", flush=True)


if __name__ == "__main__":
    main()
