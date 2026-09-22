import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import embedded_profile as embedded


class EmbeddedProfileTests(unittest.TestCase):
    def test_archive_bytes_preserved_and_configuration_follows_rename(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "0123456789abcdef.patch_0"
            original = struct.pack("<I", 0xF0000011) + bytes(508)
            path.write_bytes(original)
            profile = {"package_id": "1" * 24, "unicode": "配置"}
            row = embedded.append_profile(path, profile)
            self.assertEqual(path.read_bytes()[:row["archive_bytes"]], original)
            moved = path.rename(path.with_name("fedcba9876543210.patch_42"))
            self.assertEqual(json.loads(embedded.read_payload(moved)), profile)
            with self.assertRaisesRegex(ValueError, "already contains"):
                embedded.append_profile(moved, profile)

    def test_checksum_and_footer_bounds(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "0123456789abcdef.patch_0"
            path.write_bytes(struct.pack("<I", 0xF0000011) + bytes(252))
            embedded.append_profile(path, {"package_id": "a" * 24})
            valid = path.read_bytes()
            for index in (256, len(valid) - 64 + 16, len(valid) - 64 + 24,
                          len(valid) - 64 + 32, len(valid) - 1):
                damaged = bytearray(valid)
                damaged[index] ^= 1
                path.write_bytes(damaged)
                with self.subTest(index=index), self.assertRaises(ValueError):
                    embedded.read_payload(path)

    def test_ordinary_patch_ignored_and_nonarchive_not_modified(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "0123456789abcdef.patch_0"
            original = bytes(128)
            path.write_bytes(original)
            self.assertIsNone(embedded.read_payload(path))
            with self.assertRaisesRegex(ValueError, "Not an uncompressed"):
                embedded.append_profile(path, {})
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
