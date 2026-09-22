"""Exercise only a copied portable EXE, then remove its generated test package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
PATCH_LANE = re.compile(r"[0-9a-fA-F]{16}\.patch_[0-9]+(?:\.stream|\.gpu_resources)?")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def tree(root):
    files, directories = {}, set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_file():
            files[relative] = path
        elif path.is_dir():
            directories.add(relative)
    return files, directories


def clean_environment():
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() not in {"PYTHONHOME", "PYTHONPATH"}
                   and not key.upper().startswith(("PYINSTALLER", "_PYI_"))}
    system_root = environment.get("SystemRoot") or environment.get("SYSTEMROOT")
    require(system_root, "缺少 SystemRoot，无法建立独立的 Windows 验证环境")
    for key in list(environment):
        if key.upper() == "PATH":
            del environment[key]
    environment["PATH"] = os.pathsep.join((str(Path(system_root) / "System32"), system_root))
    return environment


def run_stage(executable, arguments, log_file, cwd, environment, stages):
    started = time.monotonic()
    result = subprocess.run([str(executable), "--log-file", str(log_file), *arguments],
                            cwd=cwd, env=environment, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW)
    recorded = log_file.read_text(encoding="utf-8-sig") if log_file.is_file() else ""
    output = recorded or result.stdout
    stages.append({"action": arguments[1] if arguments[0] == "--cli" else "gui_smoke",
                   "exit_code": result.returncode,
                   "seconds": round(time.monotonic() - started, 3)})
    require(result.returncode == 0,
            f"EXE 阶段失败，退出码 {result.returncode}：\n{output[-6000:]}")
    return output


def analysis_document(output):
    # The CLI normally writes just JSON; tolerate a launcher log prefix.
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", output):
        try:
            document, _ = decoder.raw_decode(output[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(document, dict) and isinstance(document.get("candidates"), list):
            return document
    raise ValueError("分析日志中没有找到候选 JSON")


def validate(args):
    require(os.name == "nt", "便携 EXE 验证需要 Windows")
    executable = args.exe.resolve(strict=True)
    source = args.source.resolve(strict=True)
    if source.is_file():
        require(source.name.lower() == "manifest.json", "完整目录验收需选择模组目录或 manifest.json")
        source = source.parent
    require((source / "manifest.json").is_file(), "完整目录验收需包含原模组 manifest.json")
    game = args.game.resolve(strict=True)
    require(executable.is_file() and game.is_dir(), "EXE 或游戏路径不正确")
    targets = [value.lower() for value in args.target]
    require(all(re.fullmatch(r"[0-9a-f]{8}", value) for value in targets), "目标须为 8 位 Kit ID")
    require(len(set(targets)) == len(targets), "目标 Kit 不能重复")
    report_path = args.report.resolve()
    require(not report_path.is_relative_to(source) and not report_path.is_relative_to(game),
            "验证报告不能写入源模组或游戏目录")
    files, directories = tree(source)
    baseline = {relative: sha256(path) for relative, path in files.items()}
    attachments = {relative: digest for relative, digest in baseline.items()
                   if not PATCH_LANE.fullmatch(Path(relative).name)}
    report = {"schema": "hd2-portable-exe-validation/1", "status": "failed",
              "exe": str(executable), "exe_sha256": sha256(executable),
              "source": str(source), "game": str(game), "targets": targets,
              "game_runtime_verified": False, "temporary_files_removed": False, "stages": []}
    build_root = ROOT / "build"
    build_root.mkdir(exist_ok=True)
    temporary_root = None
    try:
        with tempfile.TemporaryDirectory(prefix="portable-validation-", dir=build_root) as temporary:
            temporary_root = Path(temporary).resolve()
            require(temporary_root.parent == build_root.resolve(), "临时目录不在工作区 build 内")
            require(not report_path.is_relative_to(temporary_root), "报告不能位于临时测试目录")
            app = temporary_root / "中文 程序目录"
            cwd = temporary_root / "独立 空工作目录"
            logs = temporary_root / "验证 日志"
            output = temporary_root / "隔离 输出"
            for directory in (app, cwd, logs):
                directory.mkdir()
            copied_exe = app / executable.name
            shutil.copy2(executable, copied_exe)
            require(sha256(copied_exe) == report["exe_sha256"], "复制后的 EXE 哈希不一致")
            environment = clean_environment()
            smoke = run_stage(copied_exe, ["--smoke-test"], logs / "gui.log", cwd,
                              environment, report["stages"])
            require("GUI_SMOKE_OK" in smoke, "EXE 图形界面启动检查未返回 GUI_SMOKE_OK")
            analysis = run_stage(copied_exe, ["--cli", "analyze", "--source", str(source),
                                             "--game", str(game)], logs / "analyze.log", cwd,
                                 environment, report["stages"])
            document = analysis_document(analysis)
            (logs / "candidates.json").write_text(json.dumps(document, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
            candidates = {row["id"].lower(): row for row in document["candidates"]}
            for target in targets:
                require(target in candidates and candidates[target].get("supported") is True,
                        f"明确选择的目标不可处理：{target}；{candidates.get(target)}")
            arguments = ["--cli", "build", "--source", str(source), "--game", str(game),
                         "--output", str(output)]
            for target in targets:
                arguments.extend(("--target", target))
            run_stage(copied_exe, arguments, logs / "build.log", cwd, environment, report["stages"])
            packages = list(output.glob("armor-*"))
            require(len(packages) == 1 and packages[0].is_dir(), "未生成唯一完整隔离包")
            package = packages[0]
            manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
            require({row["kit"] for row in manifest["targets"]} == set(targets), "生成包目标不一致")
            require(manifest.get("game_runtime_verified") is False, "离线验证不能宣称游戏实测")
            require(manifest.get("package_status") == "built_and_runtime_configuration_validated",
                    "生成包尚未完成运行时配置验证")
            require(manifest["addon"].get("profile_storage") == "hd2-armor-patch-footer/1",
                    "EXE 仍在生成旧独立配置")
            require(not (package / "runtime/ArmorIsolation").exists(), "不应再输出待安装的独立 JSON")
            main_patches = {row["path"] for row in manifest["output"]
                            if re.fullmatch(r"[0-9a-fA-F]{16}\.patch_[0-9]+", Path(row["path"]).name)}
            require(main_patches == {row["path"] for row in manifest["addon"]["embedded_profiles"]},
                    "部分主补丁缺少内嵌配置")
            for row in manifest["output"]:
                require(sha256(package / row["path"]) == row["sha256"], "追加配置后补丁哈希未更新")
            preserved = (package / manifest["modular"]["mod_directory"]).resolve()
            require(preserved == (package / "mod" / source.name).resolve(), "保留模组目录位置不正确")
            output_files, output_directories = tree(preserved)
            require(set(files) == set(output_files) and directories == output_directories,
                    "生成包未完整保留原文件和目录路径")
            for relative, digest in attachments.items():
                require(sha256(output_files[relative]) == digest, f"原清单或附件被改动：{relative}")
            addon_hash = sha256(package / "runtime/ArmorIsolation.addon64")
            release = json.loads((package / "runtime-release.json").read_text(encoding="utf-8"))
            addon_rows = [row for row in release["files"] if row["name"] == "ArmorIsolation.addon64"]
            require(len(addon_rows) == 1 and addon_rows[0]["sha256"] == addon_hash
                    and manifest["addon"]["sha256"] == addon_hash, "通用插件哈希与发布记录不符")
            runtime_log = (package / "runtime-check.log").read_text(encoding="utf-8")
            profile_lines = [line for line in runtime_log.splitlines() if line.startswith("PROFILE_OK ")]
            require(len(profile_lines) == 1, "配置校验未返回唯一 PROFILE_OK")
            require(list(app.iterdir()) == [copied_exe], "EXE 旁出现了额外依赖或未清理文件")
            require(not any(cwd.iterdir()), "独立工作目录中出现了输出文件")
            after_files, after_directories = tree(source)
            require(set(files) == set(after_files) and directories == after_directories
                    and all(sha256(after_files[relative]) == digest for relative, digest in baseline.items()),
                    "验证过程中源模组发生变化")
            report.update({"status": "passed", "gui_smoke_ok": True,
                           "only_exe_copied": True, "python_environment_removed": True,
                           "path_system_directories_only": True, "independent_empty_cwd": True,
                           "candidates": [{key: row.get(key) for key in ("id", "name", "type", "supported")}
                                          for row in document["candidates"]],
                           "package_id": manifest["package_id"], "resource_count": len(manifest["mapping"]),
                           "profile_storage": manifest["addon"]["profile_storage"],
                           "embedded_patch_count": len(main_patches), "no_sidecar_json": True,
                           "source_file_count": len(files), "source_directory_count": len(directories),
                           "all_relative_paths_preserved": True, "all_non_patch_bytes_preserved": True,
                           "original_manifest_bytes_preserved": True, "source_unchanged": True,
                           "addon_sha256": addon_hash, "runtime_configuration_result": profile_lines[0]})
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        report["temporary_files_removed"] = temporary_root is not None and not temporary_root.exists()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    require(report["temporary_files_removed"], "临时 EXE 或隔离包未清理")
    print("PORTABLE_EXE_OK", report_path)
    return report


def main():
    parser = argparse.ArgumentParser(description="验证单文件 EXE 独立运行，完成后清理临时大文件")
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--target", action="append", required=True)
    parser.add_argument("--report", type=Path, required=True)
    validate(parser.parse_args())


if __name__ == "__main__":
    main()
