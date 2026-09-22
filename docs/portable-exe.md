# 单文件护甲隔离工具

分发 `ArmorIsolation.exe` 一个文件即可。适用于 Windows 10/11 x64，内置 Python、Tk、LZ4、游戏数据读取器、装备名称、Kit 快照和通用 ReShade 插件，无需安装 Python 或编译工具。

2026-09-22 自动兼容改进版：`dist/portable-compatible/ArmorIsolation.exe`。通过两种已审定的完整装配模板识别，允许已核实的外部对象字段位置和数组步长成组变化；六个函数、Piece 字段及内部指令守卫全部保留。已有旧插件时先正常退出游戏，更新 `dist/armor-isolation-runtime/ArmorIsolation.addon64` 到游戏 `bin`，重启后由新插件导出本次版本数据。详见 [本次验证](native-19099-validation.md)。

2026-09-21 内嵌配置版位于 `dist/portable-embedded/ArmorIsolation.exe`，旧 `dist/portable/` 保留。新版生成包的配置随主补丁安装和卸载，不再要求逐模组复制 JSON；需一次性更新通用插件，详见[补丁内嵌配置](embedded-patch-profile.md)。

性能与本机诊断版位于 `dist/portable-local/ArmorIsolation.exe`：包含每次启动重置日志的新版插件。点击“读取本机游戏数据”，在游戏已进入主菜单时自动定位所选安装目录的进程，只读提取并比较装备数据。输出目录的 `local-game-analysis.json` 每次成功检查覆盖更新，临时数据自动清理；无需网络、无需填写 PID。该操作不启用新版本写入，也不覆盖内置可信快照。

CLI：`ArmorIsolation.exe --cli inspect-local --game <游戏目录> --output <诊断目录>`。成功提取的记录可能包含其他已加载插件的修改，不能仅凭读取成功宣布已适配游戏更新。

## 使用

1. 把 EXE 放在可写文件夹，双击启动；游戏目录自动从 Steam 库识别，也可手动选择。
2. 选择模组目录、manifest.json 或主 patch 文件，点击“分析候选”。
3. 明确勾选实际替换的体甲与头盔，再点击“生成隔离包”。旧版多选一与 V1 配件/子选项会保留。
4. 默认结果在 EXE 旁的 `ArmorIsolation-output`，也可自选输出目录。按生成包内 README 安装模组和通用插件；工具不自动部署。

仍需本机安装游戏。已验证基准为 DLL `1.0.0.18930`；新版支持关键原生代码与数据布局仍匹配的新版本自动适配，布局改变时会停止。游戏端需支持 Add-on 的 ReShade 6.5.1；内置的是护甲 Add-on，不是 ReShade 主程序。

## 本机适配文件

本机适配版位于 `dist/portable-adaptive/ArmorIsolation.exe`，无需联网。游戏更新后，安装新版通用插件的游戏会在装备表就绪且自身尚未发布隔离配置时，自动提取 Kit 与原生布局证据，写入 **游戏根目录/ArmorIsolation.local-game.json**（与 `bin`、`data` 文件夹同级）。固定文件成功后覆盖，失败保留上次完整文件；旧文件版本不匹配时不会使用。启动阶段最多每 10 秒重试一次，共 6 次，不在正常运行时持续扫描。

EXE 在“分析候选”和“生成隔离包”时自动查找该文件，校验当前 `game.dll`、`helldivers2.exe` 的 SHA-256。因此导出成功后可退出游戏再生成，无需手选适配数据。文件缺失、损坏或版本过期时，会尝试从已运行的游戏重新读取并导出；未启动游戏则提示先启动。也可点击“读取本机游戏数据”手动刷新，窗口日志会显示导出路径和失败原因。游戏目录需要写入权限。

检查会一次报告全部六个函数的匹配情况，并分别显示原生布局、当前快照来源和适配文件可用性。布局通过但快照来自已加载隔离插件的进程时，仍不能将其导出为原始数据；若已有与当前 DLL/EXE 匹配且完整校验通过的原始适配文件，则复用该文件，诊断报告继续保留本次实际读取结果。

已知版本继续使用内置、已核实的原始 Kit 数据；手动导出会将它与本机读取的布局证据组合，并注明来源。未知版本不接收已加载隔离插件后外部读取的 Kit，以免把私有资源当作原始数据；应使用新插件发布前自动导出的文件。已加载旧插件时，退出游戏后更新插件，再重新启动。普通诊断报告仍写到所选输出目录。

新版本生成包绑定本次 DLL、EXE 和 Kit 快照；游戏端仍自行发现原生布局并检查目标源字段及资源是否就绪，不直接信任文件内地址。旧包在新版本中只有布局与全部目标源字段仍相符时才可继续使用；字段变化要用同一 EXE 重新生成包。不同游戏版本的适配包不能混用。配置和资源不做热更新，安装、更新、移除均需先正常退出游戏。

这不是对任意未来版本的保证：关键函数实现、Kit/Body/Piece 或资源表结构变化，歧义匹配及原生证据缺失都会拒绝处理，可能仍需更新工具。自动测试和本机只读检查不等于未知版本的游戏实测。参考：[Windows PE 格式](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)、[ReadProcessMemory](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-readprocessmemory)。

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
