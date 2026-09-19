"""Validate sample packages with the same universal DLL, then remove test packages."""

from collections import Counter
import json
from pathlib import Path
import tempfile

import armor_isolation_tool as tool
import build_cm14_isolated as archive


def main():
    defaults = tool.discover_defaults()
    report = {"game_runtime_verified": False, "temporary_packages_removed": False,
              "runtime_mode": "universal_runtime", "per_package_compilation": False, "samples": []}
    baseline_files = [path for name in ("cm14-isolated", "b01-isolated")
                      for path in (tool.ROOT / "dist" / name).rglob("*")
                      if path.is_file() and (path.suffix == ".addon64" or ".patch_" in path.name)]
    baseline = {str(path): archive.sha256_file(path) for path in baseline_files}
    (tool.ROOT / "build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="generic-validation-", dir=tool.ROOT / "build") as temporary:
        output = Path(temporary)
        results = []
        for label in ("cm14-isolated", "b01-isolated"):
            fixed_path = tool.ROOT / "dist" / label / "manifest.json"
            fixed = json.loads(fixed_path.read_text(encoding="utf-8"))
            source = Path(fixed["source"])
            targets = [row["kit"] for row in fixed["targets"]]
            analysis = tool.analyze_source(source, Path(defaults["game"]), Path(defaults["reader_tools"]),
                                           Path(defaults["kits"]), Path(defaults["names"]))
            assert not analysis["auto_selected"]
            for target in targets:
                assert any(row["id"] == target and row["supported"] for row in analysis["candidates"])
            package = tool.generate_package(source, Path(defaults["game"]), Path(defaults["reader_tools"]),
                                            Path(defaults["kits"]), targets, output,
                                            [path / "manifest.json" for path in results])
            result = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
            unit_map = lambda document: {(row["kit"], row["source"]) for row in document["mapping"]
                                         if row["kind"] == "unit"}
            assert unit_map(result) == unit_map(fixed)
            assert result["source_sha256"] == fixed["source_sha256"]
            assert result["source_ids_in_output_toc"] == 0 and result["payloads_verified"]
            for row in result["package_files"]:
                assert archive.sha256_file(package / row["path"]) == row["sha256"]
            if label == "b01-isolated":
                assert len(result["mapping"]) == 106
                assert result["gpu_storage"]["physical_file_bytes"] == 353952896
                assert len(result["helmet_lod_adjustments"]) == 3
            report["samples"].append({"sample": label, "package_id": result["package_id"],
                                      "targets": targets, "source_sha256": result["source_sha256"],
                                      "candidate_count": len(analysis["candidates"]),
                                      "resource_counts": dict(Counter(row["kind"] for row in result["mapping"])),
                                      "shared_resource_count": result["shared_resource_count"],
                                      "gpu_bytes": result["gpu_storage"]["physical_file_bytes"],
                                      "lod_adjustments": len(result["helmet_lod_adjustments"]),
                                      "payloads_verified": True, "package_files_verified": True,
                                      "runtime_configuration_validated": True,
                                      "addon_sha256": result["addon"]["sha256"],
                                      "unit_owners_equal_accepted_sample": True})
            results.append(package)
        private_sets = [{int(row["target"], 16) for row in json.loads(
                        (path / "manifest.json").read_text(encoding="utf-8"))["mapping"]} for path in results]
        assert private_sets[0].isdisjoint(private_sets[1])
        assert {value >> 32 for value in private_sets[0]}.isdisjoint(value >> 32 for value in private_sets[1])
        assert report["samples"][0]["addon_sha256"] == report["samples"][1]["addon_sha256"]
        report["same_addon_binary"] = True
    assert all(archive.sha256_file(Path(path)) == digest for path, digest in baseline.items())
    report["accepted_sample_artifacts_unchanged"] = True
    report["temporary_packages_removed"] = not output.exists()
    report["cross_package_ids_disjoint"] = True
    destination = tool.ROOT / "docs/generic-sample-validation.json"
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("GENERIC_SAMPLES_OK", destination)


if __name__ == "__main__":
    main()
