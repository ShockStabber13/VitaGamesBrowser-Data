"""Offline tests for title-ID mapping to IGDB PlayStation Vita metadata."""
import importlib.util
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from generate_vita_igdb_packs import (
    VITA_PLATFORM, BASE_GAME_TYPES, parse_nps_games, normalize, make_lookup,
    match_game, mapped_genres, cover_url, cover_candidates, make_cover,
    igdb_cover_key, igdb_library,
)
from PIL import Image

class VitaIGDBTests(unittest.TestCase):
    def test_platform_and_game_types(self):
        self.assertEqual(VITA_PLATFORM, 46)
        self.assertIn(0, BASE_GAME_TYPES)
        self.assertNotIn(1, BASE_GAME_TYPES)
        self.assertNotIn(2, BASE_GAME_TYPES)

    def test_pkgj_tsv_positions_never_leak_package_metadata(self):
        raw = (
            "titleid\tregion\tname\turl\tzrif\tcontentid\tmodified\n"
            "PCSE00001\tUS\tExample Game\thttps://example.com/a.pkg\tkey\t"
            "UP0001-PCSE00001_00-EXAMPLE0000000001\t2020\n"
            "PCSE00002\tUS\tMissing Game\tMISSING\tMISSING\t"
            "UP0001-PCSE00002_00-EXAMPLE0000000002\t2020\n"
        ).encode()
        names = parse_nps_games(raw)
        self.assertEqual(names, {"PCSE00001": "Example Game"})
        self.assertNotIn("pkg", str(names))

    def test_name_matching_is_conservative(self):
        games = [
            {"id": 9, "name": "Example Game",
             "alternative_names": [{"name": "Game Example"}]},
            {"id": 10, "name": "Example Game: Deluxe Edition"},
        ]
        lookup = make_lookup(games)
        game, reason = match_game("Example Game (USA)", lookup)
        self.assertEqual((game["id"], reason), (9, "exact"))
        game, reason = match_game("Game Example", lookup)
        self.assertEqual((game["id"], reason), (9, "exact"))
        game, reason = match_game("Something unrelated", lookup)
        self.assertIsNone(game)
        self.assertEqual(reason, "unmatched")
        self.assertEqual(normalize("The Game™ [EU]"), "game")

    def test_ambiguous_match_is_skipped(self):
        lookup = make_lookup([{"id": 1, "name": "Same Game"},
                              {"id": 2, "name": "Same Game"}])
        game, reason = match_game("Same Game", lookup)
        self.assertIsNone(game)
        self.assertEqual(reason, "ambiguous")

    def test_genres_map_to_vita_ui(self):
        g = {"genres": [{"name": "Role-playing (RPG)"},
                        {"name": "Platform"}, {"name": "Indie"}]}
        self.assertEqual(mapped_genres(g), ["Indie", "Platformer", "RPG"])
        self.assertTrue(cover_url({"cover":{"image_id":"co1234"}}).startswith("https://images.igdb.com/"))
        self.assertEqual(cover_url({"cover":{"image_id":"evil/name"}}), "")

    def test_switch_igdb_artwork_fallbacks(self):
        # Exact same priority as the Switch pipeline: cover (2x, normal),
        # artwork, screenshot; preserve a path for games without cover art.
        game = {"cover": {"image_id": "co123"},
                "artworks": [{"image_id": "ar456"}],
                "screenshots": [{"image_id": "sc789"}]}
        urls = cover_candidates(game)
        self.assertEqual([u.rsplit("/", 2)[-2] for u in urls],
                         ["t_cover_big_2x", "t_cover_big",
                          "t_720p", "t_screenshot_big"])
        self.assertEqual(len(cover_candidates({
            "artworks": [{"image_id": "ar456"}]})), 1)
        self.assertEqual(cover_candidates({"cover": {"image_id": "../bad"}}), [])
        self.assertEqual(cover_url({"screenshots": [
            {"image_id": "sc789"}]}), urls[-1])

    def test_igdb_library_keeps_unmatched_games_and_aliases(self):
        games = [
            {"id": 123, "name": "Unmatched Vita Game",
             "genres": [{"name": "Adventure"}],
             "alternative_names": [{"name": "Alternate Name"}]},
            {"id": 7, "name": "Persona 4 Golden",
             "genres": [{"name": "Role-playing (RPG)"}]},
        ]
        result = igdb_library(games)
        self.assertEqual(len(result.strip().splitlines()), 2)
        self.assertIn("123\tUnmatched Vita Game\tAdventure\tAlternate Name\tIG0000123", result)
        self.assertIn("7\tPersona 4 Golden\tRPG\t\tIG0000007", result)
        self.assertEqual(igdb_cover_key(123), "IG0000123")
        with self.assertRaises(ValueError):
            igdb_cover_key(10_000_000)

    def test_rich_metadata_and_screenshot_list_is_published(self):
        games = [{
            "id": 173, "name": "Vita Story",
            "genres": [{"name": "Adventure"}],
            "first_release_date": 1420070400,
            "rating": 85.2, "rating_count": 19,
            "summary": "An IGDB synopsis.",
            "screenshots": [
                {"image_id": "screenshot_123"},
                {"image_id": "screenshot_123"},
                {"image_id": "../unsafe"},
                {"image_id": "screenshot_456"}],
        }]
        values=igdb_library(games).strip().split("\t")
        self.assertEqual(len(values),10)
        self.assertEqual(values[5],"85")
        self.assertEqual(values[6],"19")
        self.assertEqual(values[7],"2015-01-01")
        self.assertEqual(values[8],"An IGDB synopsis.")
        self.assertEqual(values[9],"screenshot_123|screenshot_456")

    def test_cover_is_valid_jpeg(self):
        image = Image.new("RGB", (720, 1016), "blue")
        raw = io.BytesIO()
        image.save(raw, "PNG")
        result = make_cover(raw.getvalue())
        self.assertTrue(result.startswith(b"\xff\xd8\xff"))
        self.assertLessEqual(len(result), 80*1024)
        with Image.open(io.BytesIO(result)) as cover:
            self.assertEqual(cover.size, (360, 508))

if __name__ == "__main__":
    unittest.main()
