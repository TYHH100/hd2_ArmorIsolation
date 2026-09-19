# 通用 ReShade 护甲隔离插件

## 一个插件加载多个包

`ArmorIsolation.addon64` 不再内置某个模组的资源 ID。固定 DLL 启动时读取同目录的 `ArmorIsolation/*.json`，通过校验后按目标 Kit 独立检查资源和发布配置。增加模组只增加补丁及 JSON，DLL 文件保持相同。

游戏目录布局：

```text
Helldivers 2/
  bin/
    ArmorIsolation.addon64
    ArmorIsolation.ini
    ArmorIsolation.log
    ArmorIsolation/
      <第一个包的24位ID>.json
      <第二个包的24位ID>.json
  data/
    <管理器分配编号的补丁三件套>
```

运行条件仍为当前验证的 `game.dll 1.0.0.18930` 与 ReShade 6.5.1 / API17。固定的是模组通用性，不是任意游戏版本兼容。

## 加载与发布流程

1. 首次 present 回调中读取配置目录，不在 DllMain 中访问配置文件。只加载目录顶层 `.json`，读取一次后保持不变。
2. 用 nlohmann/json 解析并严格验证 schema、重复键、数据类型、数量与大小。单文件上限 8 MiB、总计 32 MiB、最多 64 包和 402 目标。
3. 整组验证包 ID、Kit 归属、完整及高 32 位资源 ID 冲突、私有 ID 返回原资源的别名、允许的 Piece 偏移及实际依赖。重复 Kit 或任一损坏配置让整组停止，不先发布一部分。
4. 配置只声明资源和布局，不接受地址或函数调用。目标体甲/头盔、Body/Piece 及源 Unit 必须与实际游戏配置相符；计划修改的纹理字段也逐 Piece 核对原值。材质到纹理的传递依赖由离线生成器解析，插件核对显式依赖表，不能仅靠 JSON 再解析游戏资源。
5. 检查实际游戏 PE 时间戳、映像大小、代码前缀和 Kit 结构；每个目标只等待自身依赖。依赖按 Kit 建索引，多个模组不会因全局共享标记而互相等待无关纹理。
6. 沿用已验证的配置克隆和指针原子发布。Body/Piece 存储由独立分配持有，Profile 移动不会留下悬空指针。发布后的游戏引用不做热释放，移除需退出游戏。

INI 内容：

```ini
[ArmorIsolation]
Enabled=1
DiagnosticOnly=0
```

`DiagnosticOnly=1` 只检查、不发布新配置；`Enabled=0` 停止继续发布。若已经发布，两个选项都不能恢复旧配置，仍须重启。

日志 `CONFIG` 给出包、目标和资源总数；各目标的 `WAIT`、`READY`、`APPLIED`、`FAILED` 携带包 ID 和 Kit ID。配置组校验通过不代表资源已加载，`APPLIED` 也不代表场景外观已验收。

## 旧包迁移

通用插件检测到已加载 `CM14Isolation.addon64`、`B01Isolation.addon64` 或 `ArmorIsolation_<包ID>.addon64` 时会停止写入，并提示退出游戏迁移。不要让旧插件先发布后再热加载新插件。

已经准备的兼容配置位于 `dist/armor-isolation-runtime/compatibility/cm14-b01/ArmorIsolation/`：

| 配置 | 对应补丁 | 目标 | 资源 |
| --- | --- | --- | --- |
| `19d10a2d21b513a1e6cfcb3f.json` | 已验收 CM-14 专用版 | 2 | 51 |
| `5d0fe0c0c33fec377e654b73.json` | 已验收 B-01 revision 4 | 8 | 106 |

两份配置保留原专用补丁的私有 ID。完整退出游戏后，保留这些已验证补丁，停用确认属于旧实验的插件，安装固定 `ArmorIsolation.addon64` / INI，再将对应 JSON 放入 `bin/ArmorIsolation/`。只安装一个补丁时只放对应配置；未加载资源的目标会停留在 WAIT。

这两份配置不能用于重新生成、私有 ID 已不同的包。其他已生成的隔离包可以从自己的 manifest 导出：

```powershell
& 'G:\Temp\Githud\hd2-lua_mods_test\.venv\Scripts\python.exe' -X utf8 -B tools/runtime_profile.py --manifest '<包目录>\manifest.json' --output '<已存在的配置目录>'
& '.\dist\armor-isolation-runtime\validate_runtime_profile.exe' '<配置目录>'
```

导出只写 JSON，不复制或更改补丁。文件名必须与包 ID 一致，不覆盖已有文件。校验器与 DLL 使用同一加载器，只检查数据，不读写游戏进程。

回退时退出游戏，移除对应 JSON 和所属补丁；其他模组仍使用时保留通用 DLL/INI。若退回专用插件，还需停用通用版避免并存。文件归属和补丁编号由原部署方式管理，工具不自动删除游戏文件。

## 构建和证据

`tools/build_universal_addon.ps1` 只编译一次固定 DLL、原生校验器和测试，不依赖 `generic_resource_map.hpp`。生成 `runtime-release.json` 绑定三个发布文件的大小与 SHA；图形生成工具核对发布清单后复用同一组文件，无需每个模组安装 C++ 工具链。

配置解析覆盖多包、重复/损坏配置、归属和字段、容量限制、指针稳定等边界；事务测试覆盖声明式目标的源数据守卫、披风与标量保留、独立指针发布。游戏内验证另行进行，本轮不部署。

2026-09-19 验证结果：41 项 Python 测试通过；通用配置/事务两项原生测试，以及在全新目录重编的 CM-14/B-01 两项回归通过。旧补丁兼容组经校验器报告 `packages=2 targets=10 resources=157 fields=119 required=255`。重新生成的两包使用相同 DLL，SHA-256 均为 `65525e0d7af5f088d628a84275f2e29139542fb4235a24652348cbb4f7f4fcf7`，详见[样本验证记录](generic-sample-validation.json)；临时测试大包和构建目录已清理。

JSON 库使用官方 [nlohmann/json 3.12.0](https://github.com/nlohmann/json/releases/tag/v3.12.0)，单头文件 SHA-256 为 `aaf127c04cb31c406e5b04a63f1ae89369fccde6d8fa7cdda1ed4f32dfc5de63`，已按官方公布值核对，MIT 许可随源文件保留。ReShade 接口依据 [6.5.1 SDK](https://github.com/crosire/reshade/tree/v6.5.1/include)。
