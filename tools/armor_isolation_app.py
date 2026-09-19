"""Windowed executable entry; also exposes the same backend for release validation."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import os
from pathlib import Path
import sys
import traceback


def main():
    args = sys.argv[1:]
    log_path = None
    if "--log-file" in args:
        index = args.index("--log-file")
        log_path = Path(args[index + 1]).resolve()
        del args[index:index + 2]
    if log_path is None and (sys.stdout is None or sys.stderr is None):
        log_path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArmorIsolation/logs/tool.log"
    with ExitStack() as stack:
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            recording = stack.enter_context(log_path.open("w", encoding="utf-8", buffering=1))
            stack.enter_context(redirect_stdout(recording))
            stack.enter_context(redirect_stderr(recording))
        sys.dont_write_bytecode = True
        cli = bool(args and args[0] == "--cli")
        sys.argv = [sys.argv[0], *(args[1:] if cli else args)]
        try:
            if cli:
                import armor_isolation_tool
                armor_isolation_tool.main()
            else:
                import armor_isolation_gui
                armor_isolation_gui.main()
            return 0
        except Exception:
            traceback.print_exc()
            if not cli and "--smoke-test" not in args:
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror("工具启动失败", f"请查看日志：{log_path}", parent=root)
                root.destroy()
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
