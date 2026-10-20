# 启动对照开关验证

2026-10-20。新版插件：`dist/armor-isolation-runtime/ArmorIsolation.addon64`，SHA-256 `67e75672de9c310067d7aab76f5be2aeff7ab7f2bdf5c8ca4cb34e54f5de8429`。新版单文件工具：`dist/portable-startup-options/ArmorIsolation.exe`，SHA-256 `adadffe141c44f0722caf5db1f0bfe2940e089db97c6a768a76476615f678b74`。

- 全新临时构建目录执行 clean build，三项原生测试通过；构建目录已清理。新增测试覆盖 INI 独立开关及缺省值、非法值、会话内不热变更、双关闭不创建后台任务，以及新版本/适配包禁止旧偏移回退。模拟后台结果覆盖四种组合，快照单开不会采用布局。
- 生成器 20 项和 IAS 工具入口 6 项 Python 测试通过。
- 单 EXE 已移动至中文临时目录，清除 Python 搜索环境、PATH 只留系统目录，完成 GUI smoke、无 IAS 不写入、真实四目标模组分析与完整生成，并核对输出携带上述新版插件及运行组件哈希。测试复制品和隔离包已清理，详见[机器验收记录](startup-options-portable-validation.json)。
- 原构建 venv 指向已不存在的旧账户 Python；本次创建独立临时环境使用本机 Python 3.13.14，按项目锁定依赖构建。完成后的删除请求被自动审批以 `blocked by policy` 拒绝，`build/startup-options-venv` 暂留；未绕过拒绝。

未部署到游戏，未验证 EAC 或游戏内覆盖层实际交互。两项开关控制插件启动采集/适配，不代表插件零内存访问，也不控制 IAS 自身或桌面工具的手动读取/生成。每组对照须完整退出并重启游戏；已有快照保留。

配置与行为见[运行时说明](universal-reshade-runtime.md)。未引入新第三方库；沿用项目内的 [ReShade 许可证](../third_party/reshade-v6.5.1/LICENSE.md)、[ImGui 许可证](../third_party/imgui/LICENSE.txt) 及发布包的 `licenses`。INI 接口依据：[GetPrivateProfileIntW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getprivateprofileintw)、[WritePrivateProfileStringW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-writeprivateprofilestringw)。
