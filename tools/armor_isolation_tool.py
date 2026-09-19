"""Build a complete, reviewable isolation package without deploying game files."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
PATCH_NAME = re.compile(r"^[0-9a-fA-F]{16}\.patch_[0-9]+$")


def discover_defaults():
    def first_existing(candidates):
        return str(next((path for path in candidates if path.exists()), candidates[0]))

    return {
        "game": first_existing([Path("G:/AppData/SteamLibrary/steamapps/common/Helldivers 2")]),
        "reader_tools": first_existing([ROOT.parent / "hd2-lua_mods_test/tools"]),
        "output": str(ROOT / "dist/generated"),
        "kits": str(ROOT / "docs/armor-isolation-live-kits.json"),
        "names": first_existing([Path("D:/TYHH10-git/Helldivers2ModManager/src/Helldivers2ModManager/Resources/Data")]),
    }


def resolve_source(value: Path) -> Path:
    source = Path(value).expanduser().resolve(strict=True)
    if source.is_dir():
        matches = sorted(path for path in source.iterdir() if path.is_file() and PATCH_NAME.fullmatch(path.name))
        if len(matches) != 1:
            raise ValueError(f"目录须包含一个主 patch 文件，当前找到 {len(matches)} 个；请直接选择要处理的文件。")
        source = matches[0]
    if not source.is_file() or not PATCH_NAME.fullmatch(source.name):
        raise ValueError("请选择主 patch 文件，不是 .stream 或 .gpu_resources。")
    return source


def load_names(directory: Path | None):
    result = {}
    if directory and Path(directory).is_dir():
        for kind, filename in ((0, "armor-names.json"), (1, "helmet-names.json")):
            path = Path(directory) / filename
            if path.is_file():
                document = json.loads(path.read_text(encoding="utf-8-sig"))
                for archive, name in document.items():
                    if re.fullmatch(r"[0-9a-fA-F]{16}", archive) and isinstance(name, str):
                        result[kind, archive.lower()] = name
    return result


def analyze_source(source: Path, game: Path, reader_tools: Path, kits: Path,
                   names: Path | None = None):
    import build_generic_isolated as builder

    result = builder.analyze(SimpleNamespace(source=resolve_source(source), game=Path(game),
                                             reader_tools=Path(reader_tools), kits=Path(kits),
                                             target=[], coexist_manifest=[]))
    labels = load_names(names)
    for candidate in result["candidates"]:
        candidate["name"] = labels.get((candidate["type"], candidate["archive"]), candidate["id"])
    return result


def validate_output(output_root: Path, source: Path, game: Path):
    resolved = Path(output_root).expanduser().resolve()
    for protected in (source.parent.resolve(), Path(game).resolve()):
        if resolved == protected or resolved.is_relative_to(protected):
            raise ValueError("输出目录不能位于源模组或游戏目录内。")
    if resolved.exists() and not resolved.is_dir():
        raise ValueError("输出路径已存在且不是目录。")
    return resolved


@contextmanager
def staging_directory(output_root: Path):
    output_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".building-", dir=output_root)).resolve()
    try:
        yield staging
    finally:
        # Only remove the directory this invocation created under the chosen output root.
        if staging.parent != output_root.resolve() or not staging.name.startswith(".building-"):
            raise ValueError("Temporary output path escaped its owner directory")
        if staging.exists():
            shutil.rmtree(staging)


def run_build(command, log_path: Path, log):
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    environment = {**os.environ, "PYTHONUTF8": "1"}
    with log_path.open("w", encoding="utf-8") as recording:
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                   errors="replace", creationflags=flags, env=environment)
        try:
            for line in process.stdout:
                recording.write(line)
                if not line.startswith(("注意: 包含文件:", "Note: including file:")):
                    log(line.rstrip())
            code = process.wait()
            if code:
                raise RuntimeError(f"插件构建或测试失败，退出码 {code}；详情见本次输出日志。")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()


def package_readme(manifest):
    package_id = manifest["package_id"]
    names = [f"`{target['kit']}` ({'体甲' if target['type'] == 0 else '头盔'})" for target in manifest["targets"]]
    return f"""# 护甲资源隔离包 {package_id}

本包已完成离线生成、插件编译和本地测试，尚未单独通过游戏画面验收。工具没有写入游戏目录。

目标：{', '.join(names)}。

- `patch/`：三个资源补丁，模型按 Kit 隔离，模组内相同材质和纹理共用一组私有 ID。
- `addon/ArmorIsolation_{package_id}.addon64` 与同名 `.ini`：必须与本包补丁配套使用，配置节为 `ArmorIsolation`。
- `manifest.json`：来源哈希、目标、资源依赖、已应用的已知修正及输出哈希。
- `generated/generic_resource_map.hpp`：本包插件使用的映射与目标布局。
- `build.log`：本次构建及测试记录。
- `tools/probe_resources.exe`：本包专用只读资源探针，参数为游戏 PID。

## 安装与测试

1. 正常退出游戏。停用源模组及其他仍覆盖相同原资源的版本；不能让原版覆盖包与隔离包同时生效。
2. 通过模组管理器安装 `patch/` 中的三个文件，保持同一补丁编号。不要按文件名直接覆盖游戏中已有 patch_0。
3. 将 `addon/` 中的 `.addon64` 和 `.ini` 配套部署到游戏 `bin/`。需要已启用 add-on 的 ReShade 6.5.1 / API17。更换相同目标时移除确认归属的旧实验插件，不能同时运行两份目标重叠的隔离插件。
4. 启动后在军械库加载目标，查看同名 `.log` 中各 Kit 的 `APPLIED`，切换装备触发重建；检查体甲两种体型、头盔、混搭以及原本共用资源的其他装备。
5. 预览通过后再检查舰桥和任务场景。`APPLIED` 仅代表配置发布，不能替代外观验收。

回退：完整退出游戏，通过原部署方式卸载本包补丁和对应插件/INI，再启用原模组。不要删除不确定归属的文件或造成补丁编号断层；关闭 INI 开关不能在运行中恢复已发布的配置。

## 当前适用范围

游戏 DLL 必须匹配 manifest 中的版本与 SHA-256。本版支持单个补丁三件套、体甲和头盔，且输入覆盖所选目标全部非披风 Unit。多补丁合并、仅纹理/材质替换、部分 Unit 替换、披风及未知外部依赖尚未支持。

不同模组可以使用相同原资源 ID，输出按内容与目标生成独立命名空间；同一 Kit 同时由多个隔离包控制仍属于冲突。生成时可提供并存包的 manifest 检查目标交集与资源 ID。未提供的外部包不在该检查范围内。

已知 LOD 修正仅在源资源内容精确匹配时使用，不把 B-01 的索引改动推广到其他模型。
"""


def generate_package(source: Path, game: Path, reader_tools: Path, kits: Path,
                     targets: list[str], output_root: Path,
                     coexist_manifests: list[Path] | None = None, log=print):
    import build_generic_isolated as builder

    source = resolve_source(source)
    game, reader_tools, kits = Path(game).resolve(), Path(reader_tools).resolve(), Path(kits).resolve()
    output_root = validate_output(output_root, source, game)
    if not targets:
        raise ValueError("请明确勾选要替换的体甲或头盔。")
    if not (reader_tools / "archive.py").is_file():
        raise ValueError("资源读取器目录缺少 archive.py。")
    try:
        import lz4.block  # noqa: F401
    except ImportError as error:
        raise ValueError("当前 Python 缺少 lz4，请使用已配置资源读取器的 Python 环境。") from error
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if not powershell:
        raise ValueError("未找到 PowerShell，无法构建配套插件。")
    log("正在分析依赖、分配私有 ID 并重打包资源……")
    with staging_directory(output_root) as staging:
        package = staging / "package"
        args = SimpleNamespace(source=source, game=game, reader_tools=reader_tools, kits=kits,
                               target=list(targets), output=package,
                               coexist_manifest=[Path(path) for path in (coexist_manifests or [])])
        manifest = builder.build(args)
        package_id = manifest["package_id"]
        if not re.fullmatch(r"[0-9a-f]{16,64}", package_id):
            raise ValueError("Invalid generated package ID")
        destination = output_root / f"armor-{package_id}"
        if destination.exists():
            raise FileExistsError(f"该输入与目标已有输出，未覆盖：{destination}。如需重建，请选择新的输出目录。")
        log(f"资源包已生成：{len(manifest['mapping'])} 个资源。正在编译和测试配套插件……")
        addon_dir = package / "addon"
        addon_dir.mkdir(exist_ok=True)
        run_build([powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   str(ROOT / "tools/build_generic_addon.ps1"),
                   "-HeaderDirectory", str(package / "generated"),
                   "-OutputDirectory", str(addon_dir),
                   "-BuildDirectory", str(staging / "build"), "-PackageId", package_id],
                  package / "build.log", log)
        addon = addon_dir / f"ArmorIsolation_{package_id}.addon64"
        if not addon.is_file() or not addon.stat().st_size:
            raise RuntimeError("编译没有产生预期插件，未发布输出包。")
        probe = staging / "build/probe_generic_resources.exe"
        if not probe.is_file():
            raise RuntimeError("编译没有产生本包资源探针，未发布输出包。")
        (package / "tools").mkdir()
        shutil.copy2(probe, package / "tools/probe_resources.exe")
        ini = addon.with_suffix(".ini")
        ini.write_text("[ArmorIsolation]\nEnabled=1\nDiagnosticOnly=0\n", encoding="ascii")
        manifest["package_status"] = "built_and_locally_tested"
        manifest["game_runtime_verified"] = False
        manifest["addon"] = {"name": addon.name, "config_section": "ArmorIsolation",
                             "reshade_version": "6.5.1", "sdk_api": 17}
        readme = package / "README.md"
        readme.write_text(package_readme(manifest), encoding="utf-8")
        records = []
        for path in sorted(package.rglob("*")):
            if path.is_file() and path.name != "manifest.json":
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                records.append({"path": path.relative_to(package).as_posix(),
                                "size": path.stat().st_size, "sha256": digest})
        manifest["package_files"] = records
        (package / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        package.rename(destination)
        log(f"生成完成：{destination}")
        return destination


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    defaults = discover_defaults()
    parser = argparse.ArgumentParser(description="护甲隔离包生成工具，不部署游戏文件")
    parser.add_argument("action", choices=("analyze", "build"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--game", type=Path, default=Path(defaults["game"]))
    parser.add_argument("--reader-tools", type=Path, default=Path(defaults["reader_tools"]))
    parser.add_argument("--kits", type=Path, default=Path(defaults["kits"]))
    parser.add_argument("--names", type=Path, default=Path(defaults["names"]))
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--output", type=Path, default=Path(defaults["output"]))
    parser.add_argument("--coexist-manifest", type=Path, action="append", default=[])
    args = parser.parse_args()
    try:
        if args.action == "analyze":
            print(json.dumps(analyze_source(args.source, args.game, args.reader_tools, args.kits, args.names),
                             ensure_ascii=False, indent=2))
        else:
            generate_package(args.source, args.game, args.reader_tools, args.kits, args.target,
                             args.output, args.coexist_manifest)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, f"处理失败：{error}\n")


if __name__ == "__main__":
    main()
