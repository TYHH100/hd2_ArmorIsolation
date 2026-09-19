"""Local desktop entry point for explicitly selected armor isolation targets."""

from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import queue
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any


def kit_id(value: str | int) -> str:
    if isinstance(value, int):
        return f"{value:08x}"
    return str(value).lower().removeprefix("0x").zfill(8)


def target_kind(value: Any) -> str:
    return {0: "体甲", 1: "头盔", "0": "体甲", "1": "头盔",
            "armor": "体甲", "helmet": "头盔"}.get(value, str(value))


def candidate_reason(candidate: dict[str, Any]) -> str:
    reasons = candidate.get("reasons", [])
    return "；".join(str(item) for item in reasons) if isinstance(reasons, list) else str(reasons)


class ArmorIsolationApp:
    def __init__(self, root: tk.Tk, backend: Any, source: str = "") -> None:
        self.root = root
        self.backend = backend
        self.busy = False
        self.candidates: dict[str, dict[str, Any]] = {}
        self.selected: set[str] = set()
        self.coexist: list[Path] = []
        self.package: Path | None = None
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.controls: list[ttk.Widget] = []
        self.defaults = backend.discover_defaults()
        self.values = {key: tk.StringVar(value=source if key == "source" else self.defaults.get(key, ""))
                       for key in ("source", "game", "reader_tools", "output", "kits", "names")}
        self.search = tk.StringVar()
        self.status = tk.StringVar(value="待分析")
        self.selection_summary = tk.StringVar(value="已选 0 项")
        self.candidate_summary = tk.StringVar(value="候选 0 项")
        self.detail = tk.StringVar(value="")
        self.show_advanced = False
        self.root.title("护甲资源隔离工具")
        width = min(1260, max(980, root.winfo_screenwidth() - 100))
        height = min(900, max(700, root.winfo_screenheight() - 110))
        root.geometry(f"{width}x{height}")
        root.minsize(980, 700)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self._build_ui()
        for value in self.values.values():
            value.trace_add("write", self._parameters_changed)
        self.search.trace_add("write", lambda *_: self._render_candidates())
        self.root.after(75, self._drain_events)

    def _button(self, parent: ttk.Frame, text: str, command: Any, **kwargs: Any) -> ttk.Button:
        button = ttk.Button(parent, text=text, command=command, **kwargs)
        self.controls.append(button)
        return button

    def _path_row(self, parent: ttk.Frame, row: int, key: str, label: str,
                  *, file: bool = False, source: bool = False) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
        entry = ttk.Entry(parent, textvariable=self.values[key])
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        self.controls.append(entry)
        self._button(parent, "选择文件" if file or source else "选择目录",
                     lambda: self._browse_path(key, file=file or source)).grid(
                         row=row, column=2, padx=(8, 0), pady=4)
        if source:
            self._button(parent, "选择目录", lambda: self._browse_path(key)).grid(
                row=row, column=3, padx=(8, 0), pady=4)

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=29)
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 15, "bold"))
        outer = ttk.Frame(self.root, padding=16)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(5, weight=1)
        ttk.Label(outer, text="护甲资源隔离", style="Title.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))
        paths = ttk.Frame(outer)
        paths.grid(row=1, column=0, sticky="ew")
        paths.columnconfigure(1, weight=1)
        self._path_row(paths, 0, "source", "模组补丁", source=True)
        self._path_row(paths, 1, "game", "游戏目录")
        self._path_row(paths, 2, "output", "输出目录")
        self.advanced_button = self._button(paths, "展开附加设置", self._toggle_advanced)
        self.advanced_button.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.advanced_view = ttk.Frame(outer)
        self.advanced_view.columnconfigure(0, weight=1)
        self.advanced_canvas = tk.Canvas(self.advanced_view, height=190, highlightthickness=0,
                                        background=style.lookup("TFrame", "background") or "#f0f0f0")
        self.advanced_canvas.grid(row=0, column=0, sticky="ew")
        advanced_scroll = ttk.Scrollbar(self.advanced_view, orient="vertical", command=self.advanced_canvas.yview)
        advanced_scroll.grid(row=0, column=1, sticky="ns")
        self.advanced_canvas.configure(yscrollcommand=advanced_scroll.set)
        self.advanced = ttk.Frame(self.advanced_canvas)
        advanced_window = self.advanced_canvas.create_window((0, 0), window=self.advanced, anchor="nw")
        self.advanced_canvas.bind("<Configure>", lambda event: self.advanced_canvas.itemconfigure(
            advanced_window, width=event.width))
        self.advanced.bind("<Configure>", lambda _event: self.advanced_canvas.configure(
            scrollregion=self.advanced_canvas.bbox("all")))
        self.advanced.columnconfigure(1, weight=1)
        self._path_row(self.advanced, 0, "reader_tools", "资源读取工具")
        self._path_row(self.advanced, 1, "kits", "Kit 数据", file=True)
        self._path_row(self.advanced, 2, "names", "名称目录（可选）")
        ttk.Label(self.advanced, text="共存清单（可选）").grid(row=3, column=0, sticky="nw", padx=(0, 12), pady=4)
        coexist_frame = ttk.Frame(self.advanced)
        coexist_frame.grid(row=3, column=1, sticky="ew", pady=4)
        coexist_frame.columnconfigure(0, weight=1)
        self.coexist_list = tk.Listbox(coexist_frame, height=2, exportselection=False, activestyle="dotbox")
        self.coexist_list.grid(row=0, column=0, sticky="ew")
        co_scroll = ttk.Scrollbar(coexist_frame, orient="horizontal", command=self.coexist_list.xview)
        co_scroll.grid(row=1, column=0, sticky="ew")
        self.coexist_list.configure(xscrollcommand=co_scroll.set)
        coexist_actions = ttk.Frame(self.advanced)
        coexist_actions.grid(row=3, column=2, sticky="n", padx=(8, 0), pady=4)
        self._button(coexist_actions, "添加清单", self._add_coexist).pack(fill="x")
        self._button(coexist_actions, "移除所选", self._remove_coexist).pack(fill="x", pady=(4, 0))

        actions = ttk.Frame(outer)
        actions.grid(row=3, column=0, sticky="ew", pady=(12, 10))
        actions.columnconfigure(2, weight=1)
        self.analyze_button = self._button(actions, "分析候选", self.analyze)
        self.analyze_button.grid(row=0, column=0)
        ttk.Label(actions, textvariable=self.candidate_summary).grid(row=0, column=1, sticky="w", padx=12)
        ttk.Label(actions, text="搜索").grid(row=0, column=3, padx=(12, 6))
        search = ttk.Entry(actions, textvariable=self.search, width=30)
        search.grid(row=0, column=4, sticky="e")
        self.controls.append(search)
        ttk.Separator(outer).grid(row=4, column=0, sticky="ew", pady=(0, 7))

        table_frame = ttk.Frame(outer)
        table_frame.grid(row=5, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        columns = ("checked", "name", "id", "kind", "coverage", "supported", "archive")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse", height=9)
        definitions = (("checked", "选择", 50, False), ("name", "名称", 280, True),
                       ("id", "Kit ID", 100, False), ("kind", "部位", 60, False),
                       ("coverage", "Unit 覆盖", 100, False), ("supported", "状态", 90, False),
                       ("archive", "Archive", 160, False))
        for key, title, width, stretch in definitions:
            self.table.heading(key, text=title)
            self.table.column(key, width=width, minwidth=width if not stretch else 180,
                              stretch=stretch, anchor="w" if key in {"name", "archive"} else "center")
        self.table.tag_configure("unsupported", foreground="#777777")
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.bind("<Button-1>", self._click_candidate)
        self.table.bind("<Double-1>", self._double_candidate)
        self.table.bind("<space>", self._space_candidate)
        self.table.bind("<<TreeviewSelect>>", self._show_detail)

        detail_label = ttk.Label(outer, textvariable=self.detail, wraplength=1000, anchor="w")
        detail_label.grid(row=6, column=0, sticky="ew", pady=(7, 0))
        def fit_layout(event: tk.Event) -> None:
            detail_label.configure(wraplength=max(200, event.width - 32))
            self.advanced_canvas.configure(height=max(80, min(190, event.height - 620)))

        outer.bind("<Configure>", fit_layout)
        selection = ttk.Frame(outer)
        selection.grid(row=7, column=0, sticky="ew", pady=10)
        selection.columnconfigure(0, weight=1)
        ttk.Label(selection, textvariable=self.selection_summary).grid(row=0, column=0, sticky="w")
        self.clear_button = self._button(selection, "清空选择", self._clear_selection)
        self.clear_button.grid(row=0, column=1, padx=(8, 0))
        self.generate_button = self._button(selection, "生成隔离包", self.generate)
        self.generate_button.grid(row=0, column=2, padx=(8, 0))
        self.generate_button.state(["disabled"])
        self.open_button = self._button(selection, "打开输出文件夹", self._open_output)
        self.open_button.grid(row=0, column=3, padx=(8, 0))
        self.open_button.state(["disabled"])

        ttk.Label(outer, textvariable=self.status).grid(row=8, column=0, sticky="w")
        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.grid(row=9, column=0, sticky="ew", pady=(5, 7))
        log_frame = ttk.Frame(outer)
        log_frame.grid(row=10, column=0, sticky="ew")
        log_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(log_frame, height=5, wrap="word", state="disabled", font=("Consolas", 10))
        self.log.grid(row=0, column=0, sticky="ew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=log_scroll.set)

    def _browse_path(self, key: str, *, file: bool = False) -> None:
        if self.busy:
            return
        current = Path(self.values[key].get()).expanduser()
        initial = current if current.is_dir() else current.parent
        options = {"parent": self.root, "initialdir": str(initial), "title": "选择文件" if file else "选择目录"}
        if file:
            options["filetypes"] = [("JSON 文件", "*.json"), ("所有文件", "*.*")] if key == "kits" else [
                ("模组补丁", "*.patch_*"), ("所有文件", "*.*")]
        result = filedialog.askopenfilename(**options) if file else filedialog.askdirectory(**options)
        if result:
            self.values[key].set(result)

    def _toggle_advanced(self) -> None:
        if self.busy:
            return
        self.show_advanced = not self.show_advanced
        if self.show_advanced:
            self.advanced_view.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        else:
            self.advanced_view.grid_remove()
        self.advanced_button.configure(text="收起附加设置" if self.show_advanced else "展开附加设置")

    def _add_coexist(self) -> None:
        if self.busy:
            return
        paths = filedialog.askopenfilenames(parent=self.root, title="选择已生成隔离包的 manifest.json",
                                           filetypes=[("JSON 文件", "*.json")])
        for name in paths:
            path = Path(name).resolve()
            if path not in self.coexist:
                self.coexist.append(path)
                self.coexist_list.insert("end", str(path))
        if paths:
            self._parameters_changed()

    def _remove_coexist(self) -> None:
        if self.busy:
            return
        for index in reversed(self.coexist_list.curselection()):
            del self.coexist[index]
            self.coexist_list.delete(index)
        self._parameters_changed()

    def _parameters_changed(self, *_: Any) -> None:
        self.candidates.clear()
        self.selected.clear()
        self.package = None
        self.detail.set("")
        self.status.set("参数已变更，待分析")
        self.open_button.state(["disabled"])
        self._render_candidates()

    def _render_candidates(self) -> None:
        query = self.search.get().strip().casefold()
        self.table.delete(*self.table.get_children())
        for identity, candidate in self.candidates.items():
            name = str(candidate.get("name") or identity)
            if query and query not in f"{name} {identity}".casefold():
                continue
            supported = bool(candidate.get("supported"))
            self.table.insert("", "end", iid=identity, values=(
                "☑" if identity in self.selected else ("☐" if supported else "—"), name, identity,
                target_kind(candidate.get("type")),
                f"{candidate.get('unit_matched', 0)} / {candidate.get('unit_total', 0)}",
                "可选择" if supported else "不支持", candidate.get("archive", "")),
                tags=() if supported else ("unsupported",))
        supported_count = sum(bool(c.get("supported")) for c in self.candidates.values())
        self.candidate_summary.set(f"候选 {len(self.candidates)} 项 · 可选择 {supported_count} 项")
        self._update_selection()

    def _update_selection(self) -> None:
        armor = sum(target_kind(self.candidates[i].get("type")) == "体甲" for i in self.selected)
        helmet = sum(target_kind(self.candidates[i].get("type")) == "头盔" for i in self.selected)
        self.selection_summary.set(f"已选 {len(self.selected)} 项：体甲 {armor} · 头盔 {helmet}")
        self.generate_button.state(["!disabled"] if self.selected and not self.busy else ["disabled"])
        self.clear_button.state(["!disabled"] if self.selected and not self.busy else ["disabled"])

    def _toggle_candidate(self, identity: str) -> None:
        if self.busy or identity not in self.candidates or not self.candidates[identity].get("supported"):
            return
        if identity in self.selected:
            self.selected.remove(identity)
        else:
            self.selected.add(identity)
        self.table.set(identity, "checked", "☑" if identity in self.selected else "☐")
        self._update_selection()

    def _click_candidate(self, event: tk.Event) -> str | None:
        if self.busy:
            return "break"
        identity = self.table.identify_row(event.y)
        if identity and self.table.identify_column(event.x) == "#1":
            self.table.selection_set(identity)
            self.table.focus(identity)
            self._toggle_candidate(identity)
            return "break"
        return None

    def _double_candidate(self, event: tk.Event) -> str:
        if self.table.identify_column(event.x) != "#1":
            self._toggle_candidate(self.table.identify_row(event.y))
        return "break"

    def _space_candidate(self, _event: tk.Event) -> str:
        self._toggle_candidate(self.table.focus())
        return "break"

    def _show_detail(self, *_: Any) -> None:
        selection = self.table.selection()
        if not selection:
            return
        candidate = self.candidates[selection[0]]
        reason = candidate_reason(candidate)
        self.detail.set(f"{selection[0]} · {candidate.get('name') or target_kind(candidate.get('type'))}"
                        + (f" · {reason}" if reason else ""))

    def _clear_selection(self) -> None:
        if not self.busy:
            self.selected.clear()
            self._render_candidates()

    def _capture_paths(self) -> dict[str, Path | None]:
        for key, label in (("source", "模组补丁"), ("game", "游戏目录"), ("reader_tools", "资源读取工具"),
                           ("kits", "Kit 数据"), ("output", "输出目录")):
            if not self.values[key].get().strip():
                raise ValueError(f"{label}不能为空")
        return {key: Path(value.get().strip()).expanduser() if value.get().strip() else None
                for key, value in self.values.items()}

    def _set_busy(self, busy: bool, status: str) -> None:
        self.busy = busy
        self.status.set(status)
        for widget in self.controls:
            widget.state(["disabled"] if busy else ["!disabled"])
        self.coexist_list.configure(state="disabled" if busy else "normal")
        self.table.state(["disabled"] if busy else ["!disabled"])
        self.open_button.state(["!disabled"] if self.package and not busy else ["disabled"])
        self._update_selection()
        if busy:
            self.progress.start(14)
        else:
            self.progress.stop()

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def analyze(self) -> None:
        if self.busy:
            return
        try:
            paths = self._capture_paths()
        except ValueError as error:
            messagebox.showerror("参数错误", str(error), parent=self.root)
            return
        self._parameters_changed()
        self._set_busy(True, "正在分析资源与候选套装…")
        self._append_log(f"分析：{paths['source']}")

        def work() -> None:
            try:
                result = self.backend.analyze_source(paths["source"], paths["game"], paths["reader_tools"],
                                                     paths["kits"], paths["names"])
                self.events.put(("analyzed", result))
            except Exception as error:
                self.events.put(("error", ("分析失败", str(error), traceback.format_exc())))

        threading.Thread(target=work, name="armor-analysis", daemon=False).start()

    def generate(self) -> None:
        if self.busy or not self.selected:
            return
        try:
            paths = self._capture_paths()
        except ValueError as error:
            messagebox.showerror("参数错误", str(error), parent=self.root)
            return
        targets = sorted(self.selected)
        coexist = list(self.coexist)
        self.package = None
        self._set_busy(True, "正在生成隔离包…")
        self._append_log("生成目标：" + ", ".join(targets))

        def work() -> None:
            try:
                package = self.backend.generate_package(
                    paths["source"], paths["game"], paths["reader_tools"], paths["kits"], targets,
                    paths["output"], coexist, lambda line: self.events.put(("log", str(line))))
                self.events.put(("generated", Path(package)))
            except Exception as error:
                self.events.put(("error", ("生成失败", str(error), traceback.format_exc())))

        threading.Thread(target=work, name="armor-generation", daemon=False).start()

    def _drain_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self._append_log(value)
                elif kind == "analyzed":
                    self.candidates = {kit_id(item["id"]): item for item in value.get("candidates", [])}
                    self.selected.clear()
                    self._set_busy(False, "分析完成" if self.candidates else "未找到候选套装")
                    self._render_candidates()
                    self._append_log(self.candidate_summary.get())
                elif kind == "generated":
                    self.package = value
                    self._set_busy(False, "隔离包已生成")
                    self._append_log(f"输出：{value}")
                elif kind == "error":
                    title, message, details = value
                    self._set_busy(False, title)
                    self._append_log(details)
                    messagebox.showerror(title, message, parent=self.root)
        except queue.Empty:
            pass
        self.root.after(75, self._drain_events)

    def _open_output(self) -> None:
        if not self.busy and self.package:
            try:
                os.startfile(str(self.package))
            except OSError as error:
                messagebox.showerror("无法打开文件夹", str(error), parent=self.root)

    def close(self) -> None:
        if self.busy:
            messagebox.showinfo("处理进行中", "当前任务尚未结束，请等待完成后关闭。", parent=self.root)
        else:
            self.root.destroy()


def main() -> int:
    parser = argparse.ArgumentParser(description="护甲资源隔离桌面工具")
    parser.add_argument("--source", default="", help="补丁文件或只含一个主补丁的目录")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    backend = importlib.import_module("armor_isolation_tool")
    root = tk.Tk()
    ArmorIsolationApp(root, backend, args.source)
    if args.smoke_test:
        root.update()
        print(f"GUI_SMOKE_OK {root.winfo_width()}x{root.winfo_height()}")
        root.destroy()
    else:
        root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
