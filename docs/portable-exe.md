# 单文件护甲隔离工具

分发 `ArmorIsolation.exe` 一个文件即可。适用于 Windows 10/11 x64，内置 Python、Tk、LZ4、游戏数据读取器、装备名称、Kit 快照和通用 ReShade 插件，无需安装 Python 或编译工具。

## 使用

1. 把 EXE 放在可写文件夹，双击启动；游戏目录自动从 Steam 库识别，也可手动选择。
2. 选择模组目录、manifest.json 或主 patch 文件，点击“分析候选”。
3. 明确勾选实际替换的体甲与头盔，再点击“生成隔离包”。旧版多选一与 V1 配件/子选项会保留。
4. 默认结果在 EXE 旁的 `ArmorIsolation-output`，也可自选输出目录。按生成包内 README 安装模组和通用插件；工具不自动部署。

仍需本机安装游戏。当前绑定游戏 DLL `1.0.0.18930` 及其已验证 SHA-256，其他版本会拒绝处理。游戏端需支持 Add-on 的 ReShade 6.5.1；内置的是护甲 Add-on，不是 ReShade 主程序。

单文件启动会把内置组件解压到系统临时目录，退出后自动清理；生成结果不会保存在这个临时目录。启动错误日志在 `%LOCALAPPDATA%/ArmorIsolation/logs/tool.log`；分析和生成错误显示在窗口日志中。组件来源及许可证可在“使用说明”中查看。

## 开发者重建

在项目根目录用 Windows x64 Python 3.11+（需 Tk）执行：

```powershell
python -m venv build/exe-venv
./build/exe-venv/Scripts/python.exe -m pip install -r requirements-exe.txt
./build/exe-venv/Scripts/python.exe -X utf8 -B tools/build_portable_exe.py
```

预编译 Add-on 必须先位于 `dist/armor-isolation-runtime`，生成方式见 `tools/build_universal_addon.ps1`。打包脚本验证其哈希，再内置同一份 DLL；默认产物为 `dist/portable/ArmorIsolation.exe`。已有 EXE 不覆盖，重建时用 `--output` 指定新目录。构建中间目录自动清理，保留 EXE、构建日志和 `release.json`。

验证入口：`ArmorIsolation.exe --log-file <日志绝对路径> --smoke-test`；诊断命令使用 `--cli analyze` 或 `--cli build`，参数与 Python 后端一致。验证单文件移动运行时使用 `tools/validate_portable_exe.py`，记录离线验证，不能代替游戏外观测试。

打包依据：[PyInstaller 单文件模式](https://pyinstaller.org/en/stable/operating-mode.html)、[运行时资源路径](https://pyinstaller.org/en/stable/runtime-information.html)。
