# 护甲资源隔离工具

面向 Helldivers 2 外观模组的本机处理工具。CM-14 与 B-01 专用实验已获用户游戏测试确认；此工具将隔离流程改成显式选择目标的通用生成入口。

普通使用直接双击 `dist/portable/ArmorIsolation.exe`，转发时只需这一个文件；使用步骤与重建方法见[单文件版说明](docs/portable-exe.md)。源码运行仍可双击 [Start-ArmorIsolation.cmd](Start-ArmorIsolation.cmd)。选择旧版/V1 模组根目录、其中的 `manifest.json` 或主补丁，分析后勾选目标体甲和头盔，点击“生成隔离包”。选项模组保留原目录、原清单、配件开关及单选分辨率；不自动部署到游戏。

所有模组共用固定的 `ArmorIsolation.addon64`，无需为每个包重新编译 DLL。单文件版内置 Python、Tk、LZ4、读取器、数据和插件；其他人只需准备游戏与源模组。源码运行需要 Python 3.11+、tkinter、lz4，MSVC/CMake/Ninja 仅供开发者重编通用插件使用。当前限定已验证游戏版本、完整模型替换，支持单补丁及满足依赖检查的旧版/V1 模组。

- [使用方法、处理过程和适用边界](docs/generic-isolation-tool.md)
- [通用 ReShade 插件与旧包迁移](docs/universal-reshade-runtime.md)
- [保留目录、配件开关与单选分辨率](docs/modular-isolation-tool.md)
- [TG-122 配件开关与外挂材质参考](docs/modular-tg122-reference.md)
- [B-01 实验及问题解决记录](docs/b01-isolation-walkthrough.md)
- [CM-14 头盔修复记录](docs/cm14-helmet-fix.md)

名称匹配仅用于显示；模组中共享资源可能命中许多装备，必须选择真正想替换的目标。通用工具新生成的包仍需要游戏内验收。

所用AI: gpt-6-astra进行代码编写与分析