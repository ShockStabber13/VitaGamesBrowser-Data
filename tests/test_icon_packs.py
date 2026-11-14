import importlib.util
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("make_icon_packs", ROOT/"tools/make_icon_packs.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class PackTests(unittest.TestCase):
    def test_valid_pack_and_genres(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            covers = root/"covers"
            covers.mkdir()
            (covers/"PCSE00001.jpg").write_bytes(b"\xff\xd8\xff\xd9")
            (covers/"bad.jpg").write_bytes(b"\xff\xd8\xff\xd9")
            metadata = root/"genres.tsv"
            metadata.write_text("PCSE00001\tAction,RPG\n")
            packs = module.create_packs(covers, root/"out",
                "https://example.com/vita", metadata)
            self.assertEqual(len(packs), 1)
            with ZipFile(root/"out"/"vita-icons-01.zip") as z:
                self.assertEqual(set(z.namelist()), {"genres.tsv", "PCSE00001.jpg"})
            self.assertIn("https://example.com/vita/vita-icons-01.zip",
                          (root/"out"/"packs.tsv").read_text())
    def test_invalid_url_and_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            covers = root/"covers"
            covers.mkdir()
            (covers/"PCSE00001.jpg").write_bytes(b"not a jpeg")
            with self.assertRaises(ValueError):
                module.create_packs(covers, root/"out", "http://bad.example")
            with self.assertRaises(ValueError):
                module.create_packs(covers, root/"out", "https://good.example")

if __name__ == "__main__":
    unittest.main()
