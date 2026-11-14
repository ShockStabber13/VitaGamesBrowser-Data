import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("build_vita_switch_packs",
    ROOT/"tools/build_vita_switch_packs.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SwitchCoverPackTests(unittest.TestCase):
    def test_sixteen_shards_and_every_poster_offset(self):
        with tempfile.TemporaryDirectory() as path:
            root=Path(path)
            covers=root/"covers"
            covers.mkdir()
            for id in range(1,130):
                image=Image.new("RGB",(360,508),(id,id//2,100))
                image.save(covers/f"IG{id:07d}.jpg",format="JPEG",quality=82)
            manifest=module.build_vita_switch_packs(covers,root/"output")
            self.assertEqual(manifest["schemaVersion"],2)
            self.assertEqual(manifest["imageCount"],129)
            self.assertEqual((manifest["width"], manifest["height"]), (360, 508))
            self.assertEqual(len(manifest["packs"]),16)
            self.assertEqual(len(list((root/"output").glob("covers-??.pack"))),16)
            text=(root/"output"/"covers-index.tsv").read_text()
            self.assertEqual(sum(x.startswith("PACK\t") for x in text.splitlines()),16)
            self.assertEqual(sum(x.startswith("IMAGE\t") for x in text.splitlines()),129)
            for key,entry in manifest["entries"].items():
                pack_name=f"covers-{entry['pack']:02x}.pack"
                data=(root/"output"/pack_name).read_bytes()
                start=entry["offset"]
                size=entry["size"]
                expected=(covers/f"IG{int(key[5:]):07d}.jpg").read_bytes()
                self.assertEqual(data[start:start+size],expected,key)
            for i,meta in manifest["packs"].items():
                pack=(root/"output"/meta["file"]).read_bytes()
                self.assertEqual(meta["bytes"],len(pack))
                self.assertEqual(meta["sha256"],hashlib.sha256(pack).hexdigest())
            self.assertEqual(manifest["entries"]["igdb-1"]["size"],
                             (covers/"IG0000001.jpg").stat().st_size)

    def test_invalid_jpeg_fails_fast(self):
        with tempfile.TemporaryDirectory() as path:
            root=Path(path)
            (root/"covers").mkdir()
            (root/"covers"/"IG0000001.jpg").write_bytes(b"not JPEG")
            with self.assertRaises(ValueError):
                module.build_vita_switch_packs(root/"covers",root/"out")


if __name__=="__main__":
    unittest.main()
