# 内置资源来源

这些文件是单文件程序的长期运行依赖，不是临时测试副本。原文件按字节保留；Python、Tk、python-lz4、PyInstaller 及通用 ReShade 插件的许可证由构建流程另行收集。

## 游戏资源读取器

`tools/game_data/archive.py` 原样来自本机自有工具 `G:/Temp/Githud/hd2-lua_mods_test/tools/archive.py`，仅用于读取本机游戏资源。原工具没有声明独立许可证，不将此脚本标注为第三方 MIT 或 Filediver 授权。

- SHA-256：`3e2880692597b2904071bcf53e1612df0a2a4f43f5f8877c4a2ec942f96e2d51`
- 运行依赖：Python 标准库及 `lz4.block`；没有复制原工具的其他分析或写入脚本。

## 装备名称

`names/armor-names.json`、`names/helmet-names.json` 原样来自本机 `D:/TYHH10-git/Helldivers2ModManager/src/Helldivers2ModManager/Resources/Data/`。[管理器仓库](https://github.com/TYHH100/Helldivers2ModManager)的本地 Apache-2.0 许可证保存为 `licenses/Helldivers2ModManager.LICENSE.txt`。

两个 JSON 保留原有“数据来自”字段，指向[社区 Helldivers 2 Archive Labeling 表格](https://docs.google.com/spreadsheets/d/1oQys_OI5DWou4GeRE3mW56j7BIi4M7KftBIPAl1ULFw/edit?gid=1105619619#gid=1105619619)。本次未发现表格的独立许可证声明，不据管理器许可证推断表格另行授予 Apache-2.0 许可。

| 文件 | SHA-256 |
| --- | --- |
| armor-names.json | `bb044555edef1286cb77f8fafd3ce0c7427deb075ac2ddbcac93b6591723c2d7` |
| helmet-names.json | `b8d65d242c7d91183d2bd4844e66c7b5d14281957c10463bce3f19cbeb27cdb4` |

## LZ4 原生库

本机 python-lz4 4.4.5 包内含 LZ4 1.9.4。`licenses/LZ4.LICENSE.txt` 取自 [LZ4 v1.9.4 的 lib/LICENSE](https://github.com/lz4/lz4/blob/v1.9.4/lib/LICENSE)，为 BSD-2-Clause；SHA-256 为 `8b58c446121a109ccf32edc094bba3010a3d85e4ee3702950db55e4d3e87736c`。Python 绑定本身的 [BSD-3-Clause 许可证](https://github.com/python-lz4/python-lz4/blob/v4.4.5/LICENSE)由构建流程另行收集。
