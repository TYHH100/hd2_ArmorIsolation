"""Compare read-only game observations without promoting them to write authority."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


NATIVE_FUNCTIONS = {"armor_assembly", "material_texture", "resource_lookup", "resource_redirect", "resource_online", "type_find"}


def _native_diagnostics(value):
    """Summarize read-only results; these never substitute for compatibility evidence."""
    if not isinstance(value, dict) or type(value.get("required")) is not int or value["required"] != len(NATIVE_FUNCTIONS):
        return None
    functions = value.get("functions")
    if not isinstance(functions, dict) or set(functions) != NATIVE_FUNCTIONS:
        return None
    matched, failed = 0, {}
    for name, row in functions.items():
        if not isinstance(row, dict):
            return None
        if row.get("status") == "matched" and type(row.get("rva")) is int and 0 < row["rva"] <= 0xFFFFFFFF:
            matched += 1
        elif row.get("status") == "failed" and isinstance(row.get("error"), str) and row["error"]:
            failed[name] = row["error"]
        else:
            return None
    if type(value.get("matched")) is not int or value["matched"] != matched:
        return None
    return {"required": len(NATIVE_FUNCTIONS), "matched": matched, "failed_functions": failed}


def compare_observation(observation, baseline, expected_dll, installed_dll):
    if (observation.get("schema") != "hd2-local-game-observation/1" or
            observation.get("write_authorized") is not False):
        raise ValueError("本机提取报告格式不受支持")
    result = {"schema": "hd2-local-game-comparison/1", "write_authorized": False,
              "game_runtime_verified": False, "status": observation.get("status"),
              "game_dll_sha256": observation.get("game_dll_sha256"),
              "current_file_matches": observation.get("game_dll_sha256") == installed_dll,
              "known_game_file": installed_dll == expected_dll,
              "native_layout_status": "unavailable",
              "snapshot_status": observation.get("snapshot_stage", "unknown"),
              "export_ready": False}
    diagnostics = _native_diagnostics(observation.get("native_diagnostics"))
    if diagnostics is not None:
        result["native_diagnostics"] = diagnostics
    if observation.get("status") != "observed_layout_candidate":
        result["reason"] = observation.get("error", "未提取到稳定的装备记录")
        return result

    def index(rows):
        if not isinstance(rows, list) or not 1 <= len(rows) <= 4096:
            raise ValueError("装备记录数量不合法")
        indexed = {}
        for row in rows:
            if (not isinstance(row, dict) or not isinstance(row.get("id"), str) or
                    not re.fullmatch(r"[0-9a-f]{8}", row["id"]) or row["id"] in indexed):
                raise ValueError("装备 ID 无效或重复")
            indexed[row["id"]] = row
        return indexed

    original, current = index(baseline), index(observation.get("kits"))
    added, removed = sorted(current.keys() - original.keys()), sorted(original.keys() - current.keys())
    changed = [{"id": key, "fields": sorted(name for name in original[key].keys() | current[key].keys()
                                               if original[key].get(name) != current[key].get(name))}
               for key in sorted(current.keys() & original.keys()) if current[key] != original[key]]
    result.update(count=len(current), added=added, removed=removed, changed=changed)
    native = observation.get("native_compatibility", {})
    complete_native = (isinstance(native, dict) and native.get("mode") == "signature-validated-v1" and
                       isinstance(native.get("functions"), dict) and set(native["functions"]) == NATIVE_FUNCTIONS)
    if complete_native:
        result["native_layout_status"] = "compatible"
    elif native or observation.get("native_compatibility_error"):
        result["native_layout_status"] = "incompatible"
    if not result["current_file_matches"]:
        result.update(status="stale_observation", native_layout_status="unavailable",
                      reason="提取报告与当前磁盘 DLL 不一致，请重新提取。")
    elif not result["known_game_file"]:
        if complete_native:
            if result["snapshot_status"] == "observed_only":
                result.update(status="new_version_snapshot_untrusted",
                              reason="新版本原生布局检查通过；当前读取发生在隔离插件加载后，不能作为原始快照。"
                                     "请更新通用插件并重启游戏，使用发布前自动导出的文件。")
            else:
                result.update(status="new_version_signature_compatible",
                              reason="新版本已匹配已知原生布局特征；运行时仍逐目标检查源字段，导出是否可用请查看导出结果。")
        else:
            result.update(status="new_version_candidate", reason="新版本未通过原生布局检查，停止自动适配：" +
                          observation.get("native_compatibility_error", "关键函数证据不完整"))
    elif added or removed or changed:
        result.update(status="live_data_differs", reason="运行中数据与原始快照不同，可能受插件或内容变化影响；不覆盖可信基准。")
    else:
        result.update(status="matches_verified_snapshot", reason="当前 DLL 与全部装备元数据符合已验证基准；场景外观仍需游戏验证。")
    return result


def inspect_game(game, output, runtime, kits, expected_dll):
    game, output = Path(game).resolve(), Path(output).resolve()
    if output == game or output.is_relative_to(game):
        raise ValueError("诊断输出不能位于游戏目录内")
    baseline = json.loads(Path(kits).read_text(encoding="utf-8-sig"))
    output.mkdir(parents=True, exist_ok=True)
    # A fresh report prevents a failed capture from consuming an earlier session.
    with tempfile.TemporaryDirectory(prefix=".local-inspection-", dir=output) as temporary:
        work = Path(temporary)
        observation_path = work / "observation.json"
        result = subprocess.run([str(Path(runtime) / "validate_runtime_profile.exe"), "--capture-game",
                                 str(game), str(observation_path)], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=90,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if not observation_path.is_file():
            raise ValueError("本机提取失败，请启动所选游戏并等待主菜单：" + (result.stderr or result.stdout).strip())
        if result.returncode not in (0, 1):
            raise ValueError("本机提取进程异常结束")
        observation = json.loads(observation_path.read_text(encoding="utf-8"))
        with (game / "data/game/game.dll").open("rb") as stream:
            installed_dll = hashlib.file_digest(stream, "sha256").hexdigest()
        comparison = compare_observation(observation, baseline, expected_dll, installed_dll)
        existing = None
        if comparison.get("current_file_matches"):
            from game_compatibility import EXPORT_NAME, load_export, save_export, kits_digest
            try:
                with (game / "bin/helldivers2.exe").open("rb") as stream:
                    installed_exe = hashlib.file_digest(stream, "sha256").hexdigest()
                existing = load_export(game, installed_dll, installed_exe)
            except OSError as error:
                comparison["export_error"] = str(error)
        if existing is not None:
            # Reuse validated original data; never replace it with the live observation.
            comparison.update(export_path=str(game / EXPORT_NAME), export_ready=True, export_source="existing")
            if comparison["status"] == "new_version_snapshot_untrusted":
                comparison["reason"] = ("新版本原生布局检查通过；本次插件加载后的快照仅用于诊断，"
                                        "生成将复用已校验且匹配当前游戏的适配文件。")
        elif comparison.get("current_file_matches") and comparison["native_layout_status"] == "compatible":
            exported = dict(observation)
            if installed_dll == expected_dll:
                # Existing add-ons may have changed live Kits; never persist those changes as original data.
                exported.update(kits=baseline, snapshot_stage="verified_baseline",
                                kits_sha256=kits_digest(baseline),
                                snapshot_source="bundled verified snapshot for this exact DLL; native evidence read locally")
            try:
                path = save_export(game, exported)
                comparison.update(export_path=str(path), export_ready=True, export_source=exported["snapshot_stage"])
                comparison.pop("export_error", None)
            except (ValueError, OSError) as error:
                comparison["export_error"] = str(error)
        report = {**comparison, "observation": observation}
        staging = work / "local-game-analysis.json"
        staging.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        destination = output / "local-game-analysis.json"
        os.replace(staging, destination)
    return destination, comparison
