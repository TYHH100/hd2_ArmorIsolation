"""Per-operation native compatibility context; never changes bundled version constants."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import os
import re

import build_cm14_isolated as archive

CURRENT = ContextVar("armor_game_compatibility", default=None)
BASE_KITS_SHA256 = "e68b82eb7dacde3219f7d049b692dfb418f7f2a35516d98c3dab7515eb0409c1"
EXPORT_NAME = "ArmorIsolation.local-game.json"


def kits_digest(kits):
    return hashlib.sha256(json.dumps(kits, ensure_ascii=True, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def identity():
    current = CURRENT.get()
    return ({key: current[key] for key in ("expected_game_version", "expected_game_dll_sha256",
                                         "source_kits_sha256", "runtime_compatibility")} if current else
            {"expected_game_version": "1.0.0.18930", "expected_game_dll_sha256": archive.DLL_SHA256,
             "source_kits_sha256": BASE_KITS_SHA256})


def validate_current(game, kits):
    current = CURRENT.get()
    if current is None:
        return None
    game, kits = Path(game).resolve(), Path(kits).resolve()
    if (game != current["game"] or kits != current["kits"] or
            archive.sha256_file(game / "data/game/game.dll") != current["expected_game_dll_sha256"] or
            archive.sha256_file(game / "bin/helldivers2.exe") != current["runtime_compatibility"]["exe_sha256"] or
            archive.sha256_file(kits) != current["source_kits_sha256"]):
        raise ValueError("游戏文件或本轮适配快照已变化，拒绝生成；请重新分析。")
    return json.loads(kits.read_text(encoding="utf-8"))


def validate_capture(report, dll_hash, exe_hash):
    if (report.get("schema") != "hd2-local-game-observation/1" or
            report.get("status") != "observed_layout_candidate" or
            report.get("write_authorized") is not False or report.get("game_dll_sha256") != dll_hash):
        raise ValueError("自动适配缺少稳定且与当前 DLL 匹配的本机快照。")
    native = report.get("native_compatibility", {})
    required = {"armor_assembly", "material_texture", "resource_lookup", "resource_redirect", "resource_online", "type_find"}
    if (native.get("mode") != "signature-validated-v1" or native.get("exe_sha256") != exe_hash or
            set(native.get("functions", {})) != required):
        raise ValueError("自动适配未通过原生布局检查：" + report.get("native_compatibility_error", "关键函数证据不完整"))
    if report.get("snapshot_stage") not in {"before_isolation", "without_isolation", "verified_baseline"}:
        raise ValueError("当前数据可能已经被隔离插件修改；请更新通用插件后重启游戏，使用它在发布前自动导出的文件。")
    if report.get("snapshot_stage") == "verified_baseline" and dll_hash != archive.DLL_SHA256:
        raise ValueError("内置原始快照不能用于其他 DLL 版本。")
    kits = report.get("kits")
    if not isinstance(kits, list) or not 1 <= len(kits) <= 4096:
        raise ValueError("自动适配的 Kit 数量超出支持范围。")
    if any(not isinstance(row, dict) or not re.fullmatch(r"[0-9a-f]{8}", str(row.get("id", ""))) for row in kits):
        raise ValueError("自动适配的 Kit ID 无效。")
    if len({row["id"] for row in kits}) != len(kits):
        raise ValueError("自动适配的 Kit ID 重复。")
    if report.get("kits_sha256") != kits_digest(kits):
        raise ValueError("本机适配文件的数据校验失败，请重新导出。")
    return kits


def save_export(game, report):
    game = Path(game).resolve()
    validate_capture(report, archive.sha256_file(game / "data/game/game.dll"),
                     archive.sha256_file(game / "bin/helldivers2.exe"))
    destination = game / EXPORT_NAME
    # One atomically replaced file, including both snapshot and native evidence.
    with tempfile.TemporaryDirectory(prefix=".armor-export-", dir=game) as temporary:
        staging = Path(temporary) / EXPORT_NAME
        staging.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        os.replace(staging, destination)
    return destination


def load_export(game, dll_hash, exe_hash):
    path = Path(game) / EXPORT_NAME
    if not path.is_file():
        return None
    try:
        if path.stat().st_size > 32 * 1024 * 1024:
            return None
        report = json.loads(path.read_text(encoding="utf-8"))
        validate_capture(report, dll_hash, exe_hash)
        return report
    except (ValueError, TypeError, KeyError):
        return None


@contextmanager
def game_context(game, kits, runtime_provider):
    game, kits = Path(game).resolve(), Path(kits).resolve()
    dll = game / "data/game/game.dll"
    if not dll.is_file():
        yield kits
        return
    dll_hash = archive.sha256_file(dll)
    exe_hash = archive.sha256_file(game / "bin/helldivers2.exe")
    report = load_export(game, dll_hash, exe_hash)
    if dll_hash == archive.DLL_SHA256:
        # The bundled known-version snapshot remains the source of truth.
        yield kits
        return
    with tempfile.TemporaryDirectory(prefix="armor-adaptation-") as temporary:
        folder = Path(temporary)
        if report is None:
            runtime, _ = runtime_provider()
            report_path = folder / "observation.json"
            result = subprocess.run([str(runtime / "validate_runtime_profile.exe"), "--capture-game", str(game), str(report_path)],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if result.returncode or not report_path.is_file():
                raise ValueError("游戏目录没有匹配的适配文件；请先启动游戏并进入主菜单：" + (result.stderr or result.stdout).strip())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            save_export(game, report)
        snapshot = validate_capture(report, dll_hash, exe_hash)
        local_kits = folder / "kits.json"
        local_kits.write_text(json.dumps(snapshot, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        kits_hash = archive.sha256_file(local_kits)
        current = {"game": game, "kits": local_kits, "expected_game_version": "local-" + dll_hash[:16],
                   "expected_game_dll_sha256": dll_hash, "source_kits_sha256": kits_hash,
                   "runtime_compatibility": {"mode": "signature-validated-v1", "exe_sha256": exe_hash, "kits_sha256": kits_hash}}
        token = CURRENT.set(current)
        try:
            validate_current(game, local_kits)
            yield local_kits
        finally:
            CURRENT.reset(token)
