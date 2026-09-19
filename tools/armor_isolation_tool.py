"""Build a complete, reviewable isolation package without deploying game files."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib
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
        manifest = source / "manifest.json"
        if manifest.is_file():
            return manifest
        matches = sorted(path for path in source.iterdir() if path.is_file() and PATCH_NAME.fullmatch(path.name))
        if len(matches) != 1:
            raise ValueError(f"目录须包含一个主 patch 文件，当前找到 {len(matches)} 个；请直接选择要处理的文件。")
        source = matches[0]
    if not source.is_file() or (source.name.lower() != "manifest.json" and not PATCH_NAME.fullmatch(source.name)):
        raise ValueError("请选择模组目录、manifest.json 或主 patch 文件，不是 .stream 或 .gpu_resources。")
    return source


def source_builder(source: Path):
    name = "build_modular_isolated" if source.name.lower() == "manifest.json" else "build_generic_isolated"
    return importlib.import_module(name)


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
    source = resolve_source(source)
    result = source_builder(source).analyze(SimpleNamespace(source=source, game=Path(game),
                                             reader_tools=Path(reader_tools), kits=Path(kits),
                                             target=[], coexist_manifest=[]))
    labels = load_names(names)
    for candidate in result["candidates"]:
        candidate["name"] = labels.get((candidate["type"], candidate["archive"]), candidate["id"])
    return result


def validate_output(output_root: Path, source: Path, game: Path):
    resolved = Path(output_root).expanduser().resolve()
    source = Path(source).resolve()
    source_root = source if source.is_dir() else source.parent
    for protected in (source_root, Path(game).resolve()):
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


def run_logged(command, log_path: Path, log):
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    environment = {**os.environ, "PYTHONUTF8": "1"}
    with log_path.open("w", encoding="utf-8") as recording:
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                   errors="replace", creationflags=flags, env=environment)
        try:
            for line in process.stdout:
                recording.write(line)
                log(line.rstrip())
            code = process.wait()
            if code:
                raise RuntimeError(f"运行时配置校验失败，退出码 {code}；详情见本次输出日志。")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()


def runtime_release(directory: Path | None = None):
    import build_cm14_isolated as archive

    directory = directory or ROOT / "dist/armor-isolation-runtime"
    metadata = directory / "runtime-release.json"
    if not metadata.is_file():
        raise ValueError("缺少预编译通用插件。请使用包含 dist/armor-isolation-runtime 的完整工具包。")
    release = json.loads(metadata.read_text(encoding="utf-8-sig"))
    if (release.get("schema") != "hd2-armor-runtime-release/1" or
            release.get("runtime_schema") != "hd2-armor-runtime/1" or
            release.get("expected_game_dll_sha256") != archive.DLL_SHA256 or
            release.get("sdk_api") != 17 or release.get("reshade_version") != "6.5.1"):
        raise ValueError("预编译通用插件版本不匹配。")
    required = {"ArmorIsolation.addon64", "ArmorIsolation.ini", "validate_runtime_profile.exe"}
    rows = release.get("files", [])
    if len(rows) != len(required) or {row.get("name") for row in rows} != required:
        raise ValueError("通用插件发布清单不完整。")
    for row in rows:
        path = directory / row["name"]
        if (not path.is_file() or path.stat().st_size != row["size"] or
                archive.sha256_file(path) != row["sha256"].lower()):
            raise ValueError(f"通用插件文件缺失或校验不符：{path}")
    return directory, release


def package_readme(manifest):
    package_id = manifest["package_id"]
    names = [f"`{target['kit']}` ({'体甲' if target['type'] == 0 else '头盔'})" for target in manifest["targets"]]
    modular = manifest.get("source_kind") == "modular"
    if modular:
        mod_directory = manifest["modular"]["mod_directory"]
        required_options = "、".join(f"`{item['name']}`" for item in manifest["modular"].get("required_options", []))
        prerequisites = f"启用基础选项 {required_options}" if required_options else "启用隔离报告列出的基础模型与材质选项"
        selection = "再选择配件和头部版本；材质分辨率仍按原清单单选。"
        if manifest["modular"].get("manifest_format") == "legacy":
            prerequisites = ("从原 Options 中选择一个方案" if manifest["modular"].get("option_count")
                             else "使用根目录补丁")
            selection = "原旧版清单保持不变。"
        resource_description = (f"`{mod_directory}/`：保留原模组目录、选项清单、预览图及其他附带文件；"
                                "补丁在原位置完成隔离，各配件仍通过原选项开关，外挂材质包保持共享。")
        installation = (f"在管理器中导入 `{mod_directory}/`，{prerequisites}，"
                        f"{selection}"
                        "不要把所有子目录补丁同时安装，也不要导入本包外层隔离报告。"
                        "原 manifest 的 Guid 保持不变，先停用原版本，再通过管理器替换或重新导入；"
                        "原版与隔离版不能作为两个相同身份的模组同时启用。")
        scope = ("本版支持单补丁及受支持的旧版/V1 模组目录。模块化输出保留完整选项树，"
                 "同一组件集合共用私有映射和一份运行时 JSON；改变配件选择后须完整退出并重启游戏。"
                 "基础模型和依赖材质包仍须启用，具体支持边界及组合检查结果见 manifest 的 modular 字段。"
                 "仅纹理/材质替换、缺少完整目标 Unit、披风及未知外部依赖尚未支持。")
    else:
        resource_description = "`patch/`：三个资源补丁，模型按 Kit 隔离，模组内相同材质和纹理共用一组私有 ID。"
        installation = "通过模组管理器安装 `patch/` 中的三个文件，保持同一补丁编号。不要按文件名直接覆盖游戏中已有 patch_0。"
        scope = ("本版支持单个补丁三件套、体甲和头盔，且输入覆盖所选目标全部非披风 Unit。"
                 "仅纹理/材质替换、部分 Unit 替换、披风及未知外部依赖尚未支持。")
    header_description = ("" if modular else
                          "- `generated/generic_resource_map.hpp`：资源映射的离线导出，通用插件不读取或编译此头文件。\n")
    return f"""# 护甲资源隔离包 {package_id}

本包已完成资源生成及通用插件配置校验，尚未单独通过游戏画面验收。工具没有写入游戏目录；生成本包不需要 C++ 编译环境。

目标：{', '.join(names)}。

- {resource_description}
- `runtime/ArmorIsolation.addon64`：所有模组共用的固定插件，只需安装一份。
- `runtime/ArmorIsolation/{package_id}.json`：本包的运行时配置，必须与本包补丁配套。
- `runtime/ArmorIsolation.ini`：通用插件开关，节名为 `ArmorIsolation`。已有配置可保留。
- `manifest.json`：来源哈希、目标、资源依赖、已应用的已知修正及输出哈希。
{header_description}- `runtime-check.log`：本次配置及并存检查记录。
- `tools/validate_runtime_profile.exe`：通用配置校验器，参数为配置文件或配置目录；不读取或修改游戏进程。

## 安装与测试

1. 正常退出游戏。停用源模组及其他仍覆盖相同原资源的版本；不能让原版覆盖包与隔离包同时生效。
2. {installation}
3. 将 `runtime/` 内容按目录结构部署到游戏 `bin/`。需要已启用 add-on 的 ReShade 6.5.1 / API17。通用 DLL 只装一份，每个模组新增自己的 JSON。迁移时停用确认属于旧实验版的 `CM14Isolation`、`B01Isolation` 或 `ArmorIsolation_<包ID>` 插件。
4. 启动后在军械库加载目标，查看 `bin/ArmorIsolation.log` 中包 ID 和各 Kit 的 `APPLIED`，切换装备触发重建；检查体甲两种体型、头盔、混搭以及原本共用资源的其他装备。
5. 预览通过后再检查舰桥和任务场景。`APPLIED` 仅代表配置发布，不能替代外观验收。

回退：完整退出游戏，通过原部署方式卸载本包补丁和本包 JSON，再启用原模组。其他隔离包仍在使用时保留通用 DLL/INI。不要删除不确定归属的文件或造成补丁编号断层；配置只在启动时读取，关闭 INI 开关不能在运行中恢复已发布的配置。

## 当前适用范围

游戏 DLL 必须匹配 manifest 中的版本与 SHA-256。{scope}

不同模组可以使用相同原资源 ID，输出按内容与目标生成独立命名空间；同一 Kit 同时由多个隔离包控制仍属于冲突。生成时可提供并存包的 manifest 检查，游戏启动时通用插件再验证整个 JSON 目录；若存在冲突或损坏配置，则整组停止发布。

已知 LOD 修正仅在源资源内容精确匹配时使用，不把 B-01 的索引改动推广到其他模型。
"""


def generate_package(source: Path, game: Path, reader_tools: Path, kits: Path,
                     targets: list[str], output_root: Path,
                     coexist_manifests: list[Path] | None = None, log=print):
    import runtime_profile

    source = resolve_source(source)
    builder = source_builder(source)
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
    runtime_dir, release = runtime_release()
    log("正在分析依赖、分配私有 ID 并重打包资源……")
    with staging_directory(output_root) as staging:
        package = staging / "package"
        args = SimpleNamespace(source=source, game=game, reader_tools=reader_tools, kits=kits,
                               target=list(targets), output=package,
                               coexist_manifest=[Path(path) for path in (coexist_manifests or [])])
        manifest = builder.build(args)
        if manifest.get("source_kind") == "modular":
            log(f"原模组结构及选项已保留：{manifest['modular']['mod_directory']}；配件仍在管理器内选择。")
        package_id = manifest["package_id"]
        if not re.fullmatch(r"[0-9a-f]{24}", package_id):
            raise ValueError("Invalid generated package ID")
        destination = output_root / f"armor-{package_id}"
        if destination.exists():
            raise FileExistsError(f"该输入与目标已有输出，未覆盖：{destination}。如需重建，请选择新的输出目录。")
        log(f"资源包已生成：{len(manifest['mapping'])} 个资源。正在校验通用插件配置……")
        profile = runtime_profile.make_runtime_profile(manifest, kits)
        configs = package / "runtime/ArmorIsolation"
        configs.mkdir(parents=True)
        profile_path = configs / f"{package_id}.json"
        runtime_profile.write_profile(profile, profile_path)
        validation = staging / "validation-inputs"
        validation.mkdir()
        runtime_profile.write_profile(profile, validation / profile_path.name)
        for path in coexist_manifests or []:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
            existing = runtime_profile.make_runtime_profile(document, kits)
            runtime_profile.write_profile(existing, validation / f"{existing['package_id']}.json")
        run_logged([str(runtime_dir / "validate_runtime_profile.exe"), str(validation)],
                   package / "runtime-check.log", log)
        (package / "tools").mkdir()
        for row in release["files"]:
            subdirectory = "tools" if row["name"].endswith(".exe") else "runtime"
            shutil.copy2(runtime_dir / row["name"], package / subdirectory / row["name"])
        (package / "licenses").mkdir()
        for name in ("nlohmann-json.LICENSE.MIT", "ReShade.LICENSE.md"):
            shutil.copy2(runtime_dir / "licenses" / name, package / "licenses" / name)
        shutil.copy2(runtime_dir / "runtime-release.json", package / "runtime-release.json")
        addon = package / "runtime/ArmorIsolation.addon64"
        manifest["package_status"] = "built_and_runtime_configuration_validated"
        manifest["game_runtime_verified"] = False
        manifest["addon"] = {"name": addon.name, "config_section": "ArmorIsolation",
                             "reshade_version": "6.5.1", "sdk_api": 17, "mode": "universal_runtime",
                             "runtime_profile": profile_path.relative_to(package).as_posix(),
                             "sha256": next(row["sha256"] for row in release["files"] if row["name"] == addon.name)}
        readme = package / "README.md"
        readme.write_text(package_readme(manifest), encoding="utf-8")
        records = []
        for path in sorted(package.rglob("*")):
            if path.is_file() and path != package / "manifest.json":
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
    parser.add_argument("--source", type=Path, required=True,
                        help="模组目录、旧版/V1 manifest.json 或主 patch 文件")
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
