# 护甲资源隔离工具

面向 Helldivers 2 外观模组的本机处理工具。CM-14 与 B-01 专用实验已获用户游戏测试确认；此工具将隔离流程改成显式选择目标的通用生成入口。

双击 [Start-ArmorIsolation.cmd](Start-ArmorIsolation.cmd)，选择模组主补丁，分析后勾选目标体甲和头盔，点击“生成隔离包”。生成资源补丁、配套 ReShade 插件、只读探针及处理清单；不自动部署到游戏。

目前支持已验证游戏版本、单补丁、完整模型替换。需要 Python 3.11+、tkinter、lz4、游戏数据读取器，以及 MSVC x64 / CMake / Ninja。本机启动器自动寻找现有环境，尚非免环境的独立 EXE。

- [使用方法、处理过程和适用边界](docs/generic-isolation-tool.md)
- [B-01 实验及问题解决记录](docs/b01-isolation-walkthrough.md)
- [CM-14 头盔修复记录](docs/cm14-helmet-fix.md)

名称匹配仅用于显示；模组中共享资源可能命中许多装备，必须选择真正想替换的目标。通用工具新生成的包仍需要游戏内验收。
