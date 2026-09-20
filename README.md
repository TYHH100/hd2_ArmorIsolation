# ArmorIsolation · Helldivers 2 护甲资源隔离工具

为 Helldivers 2 体甲与头盔外观模组生成独立资源包，减少共享模型、材质和纹理导致的非目标装备外观变化。

工具提供图形界面：选择源模组、分析候选装备、明确指定替换目标，再生成配套补丁与运行时配置。游戏端通过统一的 ReShade 插件 `ArmorIsolation.addon64` 加载配置。

## 主要功能

- **显式选择目标**：体甲与头盔分别选择，避免将共享资源的所有装备一并替换。
- **资源隔离**：为模型及其依赖分配私有资源 ID，同一模组内部复用材质与纹理。
- **保留模组选项**：支持符合检查条件的旧版/V1 模组，保留目录结构、配件开关与单选分辨率。
- **多包检查**：检测目标装备及资源 ID 冲突，多个包共用一份运行时插件。
- **独立输出**：不修改源模组，不自动部署到游戏目录，不覆盖已有生成结果。

## 兼容范围

当前实现绑定特定游戏版本，**不保证兼容后续游戏更新或所有外观模组**。

| 项目 | 要求或范围 |
| --- | --- |
| 游戏 | 本机已安装 Helldivers 2；支持的 `game.dll` 版本为 `1.0.0.18930`，同时校验 SHA-256 |
| 游戏端运行环境 | 支持 Add-on 的 ReShade 6.5.1；工具附带护甲插件，不包含 ReShade 主程序 |
| 输入 | 单个主补丁及其配套数据，或符合依赖检查的旧版/V1 模组目录 |
| 替换范围 | 所选体甲或头盔的完整非披风模型替换 |

暂不支持部分模型替换、纯材质/纹理模组、披风隔离、无清单的多主补丁及需要额外克隆外部材质的输入。具体判断以工具检查结果和[适用边界](docs/generic-isolation-tool.md)为准。

不同隔离包仍不能同时控制同一件装备。生成及校验成功后，仍需在游戏内检查两种体型、混搭和非目标装备的实际外观。

## 快速开始

### 单文件版

取得已打包的 `ArmorIsolation.exe` 后，无需安装 Python 或编译工具。

1. 将 EXE 放在可写文件夹并启动，确认自动识别或手动选择的游戏目录。
2. 选择源模组目录、`manifest.json` 或主补丁文件，点击“分析候选”。
3. 根据模组实际用途勾选目标体甲和头盔，点击“生成隔离包”。候选命中不代表该装备就是预期目标。
4. 在输出目录查看结果；默认位置为 EXE 旁的 `ArmorIsolation-output`。
5. 完整退出游戏，按生成包内的 README 安装补丁、通用插件与配置，再启动游戏验证外观。

安装隔离版本时，应停用对应的原始替换模组，避免原资源覆盖继续影响其他装备。更换配置、停用或卸载也需完整退出游戏；插件不支持热更新或热恢复。

单文件版的构建产物位于 `dist/portable/ArmorIsolation.exe`，源码仓库不等同于已打包程序。详见[单文件版使用与构建说明](docs/portable-exe.md)。

### 从源码运行

需要 Python 3.11+（含 tkinter）和 `lz4`。在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install lz4
.\Start-ArmorIsolation.cmd
```

生成隔离包还需要 `dist/armor-isolation-runtime/` 中完整且通过哈希校验的运行时文件。开发者可使用 `tools/build_universal_addon.ps1` 构建；该步骤需要 MSVC、CMake 与 Ninja，参见[运行时构建说明](docs/universal-reshade-runtime.md)。仅启动图形界面不代表生成依赖已齐备。

## 工作流程

项目由 Python 生成工具和 C++ 游戏端插件组成：

```text
源模组 + 显式选择的目标装备
  → Python 解析资源与选项依赖
  → 分配私有资源 ID、重打包补丁
  → 校验并输出补丁、运行时 JSON 和配套插件
  → 用户退出游戏后安装
  → ReShade 插件读取配置、校验目标并等待资源
  → 将目标装备关联到私有资源
```

生成包的 `manifest.json` 记录资源映射、输出文件与哈希等信息；`runtime/ArmorIsolation/*.json` 则是游戏端插件直接读取的配置。两者用途不同。

## 项目结构

### 目录概览

| 目录 | 内容 |
| --- | --- |
| [tools/](tools/) | Python 界面、生成后端、打包脚本、验证工具及历史实验脚本 |
| [src/](src/) | C++ ReShade 插件实现 |
| [include/](include/) | 运行时配置、资源探测和固定实验映射的 C++ 头文件 |
| [assets/](assets/) | 装备名称、内置资源来源和许可证 |
| [docs/](docs/) | 使用文档、设计分析、验证报告及绑定版本的装备快照 |
| [tests/](tests/) | Python 与 C++ 自动化回归测试 |
| [third_party/](third_party/) | 固定版本的 ReShade SDK 和 nlohmann/json |

### 根目录文件

| 文件 | 用途 |
| --- | --- |
| `README.md` | 项目介绍、使用入口和结构说明 |
| `AGENTS.md` | 开发约定与已知易错点，不参与程序运行 |
| `LICENSE` | 项目自身的 MIT 许可证 |
| `.gitignore` | 排除本地环境、构建产物、缓存和测试模组 |
| `Start-ArmorIsolation.cmd` | 可双击的源码版启动入口，调用 PowerShell 启动器 |
| `Start-ArmorIsolation.ps1` | 查找 Python、检查 tkinter/lz4 并启动界面，也支持启动检查 |
| `CMakeLists.txt` | 定义插件、原生校验器与测试的构建目标，支持通用版和历史实验模式 |
| `requirements-exe.txt` | 单文件 EXE 的打包依赖及版本 |

### 生成工具与界面

以下文件位于 `tools/`，构成当前主要生成流程。

| 文件 | 用途 |
| --- | --- |
| `armor_isolation_app.py` | 单文件 EXE 入口，处理窗口模式日志，并提供命令行和发布验证入口 |
| `armor_isolation_gui.py` | 图形界面：选择目录、展示候选、勾选目标、启动生成和显示日志 |
| `armor_isolation_tool.py` | 协调分析、生成、运行时校验和最终输出 |
| `build_generic_isolated.py` | 通用单补丁生成：版本检查、目标匹配、依赖分析、私有 ID 分配和重打包 |
| `build_modular_isolated.py` | 模块化模组生成：保留目录与选项，处理跨补丁依赖和共享映射 |
| `modular_source.py` | 解析旧版/V1 清单、本体、Options、SubOptions 和补丁来源 |
| `modular_texture_aliases.py` | 识别符合条件的互斥分辨率分支，处理纹理 ID 对应关系 |
| `runtime_profile.py` | 从生成包 manifest 导出通用插件配置，也用于旧包迁移 |
| `isolation_paths.py` | 管理源码/EXE 资源与输出路径，并查找 Steam 游戏目录 |
| `game_data/archive.py` | 读取本机游戏资源，供依赖分析等流程使用 |

### 游戏端插件

| 文件 | 用途 |
| --- | --- |
| `src/cm14_isolation_addon.cpp` | 插件主体：接入 ReShade、检查游戏结构、等待资源、克隆装备配置并发布引用 |
| `include/armor_runtime_profile.hpp` | 通用配置结构、JSON 解析、目标与依赖校验及多包冲突检查 |
| `include/cm14_resource_probe.hpp` | 检查游戏资源就绪、缺失、不可读或不兼容等状态 |
| `include/cm14_resource_map.hpp` | CM-14 固定实验的装备和资源映射 |
| `include/b01_resource_map.hpp` | B-01 固定实验的装备和资源映射 |

插件主体沿用早期命名，但同时用于当前通用插件。构建开关决定读取 JSON 配置还是使用固定映射，不能根据 `cm14` 文件名前缀判断代码已经弃用。

### 构建与打包

以下脚本位于 `tools/`。

| 文件 | 用途 |
| --- | --- |
| `build_universal_addon.ps1` | 构建当前通用插件、原生校验器和测试，生成运行时发布哈希清单 |
| `build_portable_exe.py` | 将界面、Python 依赖、数据和预编译插件打包为单文件 EXE |
| `build_generic_addon.ps1` | 历史的逐包编译插件入口，当前普通生成流程不使用 |
| `build_cm14_addon.ps1`、`build_b01_addon.ps1` | 构建对应固定实验插件 |

### 历史实验与分析工具

以下文件同样位于 `tools/`，用于复现固定实验或调查资源问题。

| 文件 | 用途 |
| --- | --- |
| `build_cm14_isolated.py` | CM-14 固定包生成器，同时提供仍被通用流程复用的资源解析和重打包代码 |
| `build_b01_isolated.py` | B-01 固定包生成器，部分逻辑仍被通用生成器复用 |
| `analyze_b01_source.py` | 分析 B-01 源模组覆盖范围和依赖，输出报告 |
| `analyze_b01_helmets.py` | 对比头盔网格与 LOD 引用，辅助定位模型缺失 |
| `inspect_appearance.py` | 只读检查外观相关数据，可读取运行中游戏模块 |
| `plan_armor_isolation.py` | 读取装备记录并规划私有资源映射，不应用修改 |
| `probe_cm14_resources.cpp` | 原生资源状态探测程序，也被其他构建模式复用 |
| `manage_cm14_test.ps1`、`manage_b01_test.ps1` | 固定实验包的状态检查、安装与卸载；安装/卸载入口会操作游戏文件 |

固定实验代码与通用代码目前存在复用关系，整理目录时需要同步调整导入和构建引用，不能直接删除整组历史命名文件。

### 数据与第三方组件

| 文件或目录 | 用途 |
| --- | --- |
| `assets/names/armor-names.json` | 体甲显示名称 |
| `assets/names/helmet-names.json` | 头盔显示名称 |
| `assets/THIRD_PARTY.md` | 内置资源来源、哈希与许可说明 |
| `assets/licenses/` | 对应来源项目及 LZ4 的许可证副本 |
| `third_party/reshade-v6.5.1/` | ReShade SDK 头文件及来源、许可证；不包含 ReShade 主程序 |
| `third_party/nlohmann-json-3.12.0/` | C++ JSON 解析库及其说明、许可证 |

装备名称用于界面显示，实际匹配依赖 Kit ID 和资源 ID。ReShade SDK 中的 `reshade.hpp` 提供接入入口，`reshade_api*.hpp` 定义设备、资源、格式和管线接口，`reshade_events.hpp` 定义事件，`reshade_overlay.hpp` 提供覆盖层相关接口。

### 文档与分析数据

`docs/` 按内容可分为以下几组：

| 文件或分组 | 用途 |
| --- | --- |
| `generic-isolation-tool.md` | 完整使用流程、支持范围和生成步骤 |
| `portable-exe.md` | 单文件版使用、构建与验证 |
| `modular-isolation-tool.md` | 模组选项、配件、分辨率和跨补丁依赖规则 |
| `universal-reshade-runtime.md` | 通用插件配置、运行流程、迁移和构建 |
| `modular-tg122-reference.md` | TG-122 模块化样本的结构与依赖参考 |
| `cm14-*`、`b01-*` | 固定实验分析、修复过程、安装前探测与相关证据 |
| `appearance-*.txt` | 外观入口、装配、材质、资源加载、UI 和场景路径的分析记录 |
| `appearance-*.json`、`armor-isolation-*.json` | 外观/装备快照、依赖样本、ID 规划或分析结果 |
| `armor-analysis.md`、`armor-appearance-execution.md` | 护甲分析与外观执行流程说明 |
| `armor-resource-isolation.md`、`armor-isolation-dependencies.md`、`armor-isolation-resource-lookup.txt` | 资源隔离、依赖关系与资源查找记录 |
| `*-validation.json` | 样本或打包验证报告，记录对应一次验证的结果 |

**`docs/armor-isolation-live-kits.json` 是实际运行依赖。** 通用生成器、运行时配置导出和 EXE 打包均使用这份绑定版本的装备快照；不能将 `docs/` 整体视为可删除的说明材料。

### 自动化测试与样本验证

`tests/` 中的文件按模块对应：

| 测试文件 | 检查范围 |
| --- | --- |
| `test_generic_builder.py`、`test_modular_builder.py` | 单补丁与模块化隔离生成 |
| `test_modular_source.py` | 清单解析、组件与选项语义 |
| `test_modular_texture_aliases.py` | 分辨率分支的纹理归一条件 |
| `test_isolation_tool.py`、`test_generic_ui.py` | 工具流程与界面相关逻辑 |
| `test_isolation_paths.py` | 路径处理与游戏安装发现 |
| `test_runtime_profile_export.py` | Python 运行时配置导出 |
| `test_cm14_builder.py`、`test_b01_builder.py` | 固定样本生成回归 |
| `test_runtime_profile.cpp`、`test_universal_addon.cpp` | 原生配置校验与通用插件事务逻辑 |
| `test_generic_addon.cpp`、`test_cm14_addon.cpp`、`test_b01_addon.cpp` | 历史插件构建模式的回归 |

`tools/` 还提供更接近完整生成流程的验证入口：

| 文件 | 用途 |
| --- | --- |
| `validate_generic_samples.py` | 对真实样本执行通用生成，检查资源、隔离结果和插件一致性 |
| `validate_modular_sample.py` | 检查模块化样本的选项、依赖和生成结果 |
| `validate_portable_exe.py` | 在独立目录中验证单个 EXE 的实际分析与生成能力，结束后清理临时副本和测试产物 |
| `validate_runtime_profile.cpp` | 使用与插件相同的配置加载器，离线校验单个或整组运行时 JSON |

部分样本验证需要本机游戏数据和指定源模组。自动化通过不替代游戏内的体型、混搭及场景外观检查。

## 文档

- [完整使用流程与支持范围](docs/generic-isolation-tool.md)
- [单文件版使用与构建](docs/portable-exe.md)
- [模块化模组、配件与分辨率选项](docs/modular-isolation-tool.md)
- [通用 ReShade 插件、配置与旧包迁移](docs/universal-reshade-runtime.md)

## 依赖与参考

- [ReShade SDK 6.5.1](https://github.com/crosire/reshade/tree/v6.5.1/include)：游戏端 Add-on 接口。
- [Filediver](https://github.com/xypwn/filediver)：游戏资源格式参考。
- [nlohmann/json](https://github.com/nlohmann/json)：运行时 JSON 配置解析。
- [python-lz4](https://github.com/python-lz4/python-lz4)：LZ4 数据处理。
- [PyInstaller](https://github.com/pyinstaller/pyinstaller)：单文件程序打包。

## AI
本项目的所有代码和相关分析，所用的AI模型是GPT 6 Astra

## 许可证

本项目采用 [MIT License](LICENSE)。第三方组件遵循各自许可证；源模组及其素材的权利归原作者所有。
