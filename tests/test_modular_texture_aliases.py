from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_cm14_isolated as archive
from modular_texture_aliases import discover_texture_aliases


def material(textures, slots=None, marker=0):
    slots = slots or list(range(1, len(textures) + 1))
    payload = bytearray(0x88 + len(textures) * 12)
    struct.pack_into("<I", payload, 0x40, len(textures))
    struct.pack_into("<I", payload, 0x44, marker)
    for index, (slot, value) in enumerate(zip(slots, textures)):
        struct.pack_into("<I", payload, 0x88 + index * 4, slot)
        struct.pack_into("<Q", payload, 0x88 + len(textures) * 4 + index * 8, value)
    return bytes(payload)


def source(resources):
    data, entries = bytearray(), {}
    for (kind, value), payload in resources.items():
        entries[kind, value] = archive.Entry((value, kind, len(data), 0, 0, 0, 0, len(payload), 0, 0, 1, 1, 0))
        data.extend(payload)
    return SimpleNamespace(entries=entries, data=bytes(data))


class TextureAliasTests(unittest.TestCase):
    def fixture(self, first=(10, 20), second=(30, 40), first_payload=None, second_payload=None,
                first_resources=None, second_resources=None):
        paths = (Path("textures/low/a.patch_0"), Path("textures/high/a.patch_0"))
        catalog = SimpleNamespace(root=Path("source"), patch_paths=paths, manifest={"Version": 1, "Options": [
            {"Name": "arbitrary alternatives", "Include": ["textures"], "SubOptions": [
                {"Name": "alpha", "Include": ["textures\\low"]},
                {"Name": "beta", "Include": ["textures/high"]}]}]})
        first_resources = first_resources if first_resources is not None else first
        second_resources = second_resources if second_resources is not None else second
        sources = {paths[0]: source({(archive.MATERIAL, 100): first_payload or material(first),
                                   **{(archive.TEXTURE, value): b"low" for value in first_resources}}),
                   paths[1]: source({(archive.MATERIAL, 100): second_payload or material(second),
                                    **{(archive.TEXTURE, value): b"high" for value in second_resources}})}
        return catalog, sources

    def test_aliases_follow_slots_without_names_and_keep_external_references(self):
        catalog, sources = self.fixture(first=(30, 20, 99), second=(10, 40, 99),
                                        first_resources=(30, 20), second_resources=(10, 40))
        before = [value.data for value in sources.values()]
        aliases, evidence = discover_texture_aliases(catalog, sources)
        self.assertEqual(aliases, {(archive.TEXTURE, 30): (archive.TEXTURE, 10),
                                   (archive.TEXTURE, 40): (archive.TEXTURE, 20)})
        self.assertEqual(evidence[0]["status"], "aliased")
        self.assertEqual(evidence[0]["materials"][0]["slots"][0]["slot"], "00000001")
        self.assertFalse(evidence[0]["materials"][0]["slots"][2]["local"])
        self.assertEqual(before, [value.data for value in sources.values()])

    def test_material_nonreference_changes_reject_entire_group(self):
        catalog, sources = self.fixture(second_payload=material((30, 40), marker=1))
        aliases, evidence = discover_texture_aliases(catalog, sources)
        self.assertEqual(aliases, {})
        self.assertIn("outside Texture64", evidence[0]["reason"])

    def test_duplicate_slot_hashes_do_not_form_aliases(self):
        catalog, sources = self.fixture(first_payload=material((10, 20), slots=(1, 1)))
        aliases, evidence = discover_texture_aliases(catalog, sources)
        self.assertEqual(aliases, {})
        self.assertIn("duplicate", evidence[0]["reason"])

    def test_union_collision_with_two_textures_in_one_branch_is_rejected(self):
        catalog, sources = self.fixture(second=(30, 30))
        aliases, evidence = discover_texture_aliases(catalog, sources)
        self.assertEqual(aliases, {})
        self.assertIn("collide", evidence[0]["reason"])

    def test_missing_external_texture_is_never_aliased(self):
        catalog, sources = self.fixture(second_resources=(30,))
        aliases, evidence = discover_texture_aliases(catalog, sources)
        self.assertEqual(aliases, {})
        self.assertIn("external", evidence[0]["reason"])

    def test_material_key_sets_must_match(self):
        catalog, sources = self.fixture()
        sources[catalog.patch_paths[1]] = source({(archive.MATERIAL, 101): material((30, 40)),
                                                (archive.TEXTURE, 30): b"a", (archive.TEXTURE, 40): b"b"})
        aliases, evidence = discover_texture_aliases(catalog, sources)
        self.assertEqual(aliases, {})
        self.assertIn("Material key sets", evidence[0]["reason"])

    def test_model_choice_and_missing_default_branch_are_skipped(self):
        for model in (False, True):
            with self.subTest(model=model):
                catalog, sources = self.fixture()
                if model:
                    sources[catalog.patch_paths[0]] = source({(archive.UNIT, 1): b"unit"})
                else:
                    catalog.manifest["Options"][0]["SubOptions"][1]["Include"] = ["missing/default"]
                aliases, evidence = discover_texture_aliases(catalog, sources)
                self.assertEqual(aliases, {})
                self.assertEqual(evidence[0]["status"], "skipped")

    def test_other_component_cannot_define_alias_texture_or_reference_it(self):
        for references in (False, True):
            with self.subTest(references=references):
                catalog, sources = self.fixture()
                other = Path("other/a.patch_0")
                catalog.patch_paths += (other,)
                sources[other] = source({(archive.MATERIAL, 200): material((30,))} if references else
                                        {(archive.TEXTURE, 30): b"elsewhere"})
                with self.assertRaisesRegex(ValueError, "outside"):
                    discover_texture_aliases(catalog, sources)

    def test_direct_kit_texture_reference_rejects_alias_but_cape_is_ignored(self):
        catalog, sources = self.fixture()
        kit = {"id": "12345678", "bodies": [{"pieces": [
            {"slot": 0, "resources": {"unit": "0000000000000001", "texture": "000000000000000a"}}]}]}
        with self.assertRaisesRegex(ValueError, "directly references"):
            discover_texture_aliases(catalog, sources, [kit])
        kit["bodies"][0]["pieces"][0]["slot"] = 1
        self.assertTrue(discover_texture_aliases(catalog, sources, [kit])[0])

    def test_incomplete_catalog_source_set_is_rejected(self):
        catalog, sources = self.fixture()
        sources.pop(catalog.patch_paths[0])
        with self.assertRaisesRegex(ValueError, "complete catalog"):
            discover_texture_aliases(catalog, sources)

    def test_null_options_and_suboptions_are_accepted(self):
        catalog, sources = self.fixture()
        catalog.manifest["Options"][0]["SubOptions"] = None
        self.assertEqual(discover_texture_aliases(catalog, sources), ({}, []))
        catalog.manifest["Options"] = None
        self.assertEqual(discover_texture_aliases(catalog, sources), ({}, []))


if __name__ == "__main__":
    unittest.main()
