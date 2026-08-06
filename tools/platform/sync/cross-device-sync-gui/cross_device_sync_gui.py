#!/usr/bin/env python3
"""Human-in-the-loop Windows-Mac file comparison and sync GUI.

The GUI never chooses a winner from mtime alone.  It builds a metadata plan,
lets the user inspect and select each direction, then delegates copying to the
fail-closed PowerShell/rclone engine.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import queue
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, BooleanVar, StringVar, Tk, Toplevel, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any, Callable


TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".json", ".jsonl", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".csv", ".tsv", ".py", ".ps1",
    ".sh", ".command", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".html",
    ".css", ".xml", ".sql", ".java", ".c", ".h", ".cpp", ".hpp",
}


@dataclass
class FileInfo:
    path: str
    size: int
    mod_time: str


@dataclass
class DiffRow:
    path: str
    status: str
    mac: FileInfo | None
    windows: FileInfo | None
    decision: str = "skip"
    mac_hash: str = ""
    windows_hash: str = ""

    @property
    def recommendation(self) -> str:
        return {
            "mac_only": "Mac에만 있음 · Windows 복사 검토",
            "windows_only": "Windows에만 있음 · Mac 복사 검토",
            "likely_same": "크기·수정시각 동일 · 전송 불필요",
            "same_size_time_diff": "크기 동일·수정시각 다름 · 해시 비교 권장",
            "conflict": "양쪽 내용 후보가 다름 · 미리보기/해시 후 선택",
            "verified_same": "SHA-256 동일 · 전송 불필요",
            "verified_conflict": "SHA-256 다름 · 보존 후 교체 방향 선택",
        }[self.status]


def run(args: list[str], timeout: int = 900, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=check,
    )


def windows_sftp_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    if len(normalized) < 3 or normalized[1:3] != ":/":
        raise ValueError(f"Windows 절대경로가 아닙니다: {value}")
    return f"/{normalized[0].upper()}:{normalized[2:]}"


class SyncBackend:
    def __init__(self, aicc_root: Path, profile_name: str) -> None:
        self.aicc_root = aicc_root
        self.state_root = Path(os.environ.get("AICC_STATE_ROOT", Path.home() / ".ai-control-center"))
        self.config_path = self.state_root / "cross-device" / "sync.json"
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        if profile_name not in self.config["profiles"]:
            raise KeyError(f"설정에 없는 프로필: {profile_name}")
        self.profile_name = profile_name
        self.profile = self.config["profiles"][profile_name]
        self.is_windows = platform.system().lower() == "windows"
        self.remote_host = (
            self.config["devices"]["mac"]["ssh_host"]
            if self.is_windows
            else self.config["devices"]["windows"]["ssh_host"]
        )
        self.rclone = shutil.which("rclone")
        if not self.rclone and os.name == "nt":
            package_root = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
            matches = sorted(package_root.glob("Rclone.Rclone_*/rclone-*/rclone.exe"), reverse=True)
            if matches:
                self.rclone = str(matches[0])
        self.ssh = shutil.which("ssh")
        self.pwsh = shutil.which("pwsh")
        if not self.rclone or not self.ssh or not self.pwsh:
            raise RuntimeError("rclone, ssh, pwsh 7이 모두 PATH에 있어야 합니다.")
        if os.name == "nt":
            self.rclone = str(Path(self.rclone).resolve(strict=True))
        self.engine = aicc_root / "tools" / "platform" / "sync" / "Sync-CrossDeviceFilesOverSsh.ps1"
        if not self.engine.is_file():
            raise FileNotFoundError(self.engine)
        self.sftp_args = self._resolve_sftp_args()

    @property
    def mac_path(self) -> str:
        return self.profile["mac_path"]

    @property
    def windows_path(self) -> str:
        return self.profile["windows_path"]

    def _resolve_sftp_args(self) -> list[str]:
        result = run([self.ssh, "-G", self.remote_host], timeout=30)
        values: dict[str, list[str]] = {}
        for raw in result.stdout.splitlines():
            if " " not in raw:
                continue
            key, value = raw.split(" ", 1)
            values.setdefault(key.lower(), []).append(value.strip())
        required = {
            "host": (values.get("hostname") or [""])[0],
            "user": (values.get("user") or [""])[0],
            "port": (values.get("port") or ["22"])[0],
        }
        if not all(required.values()):
            raise RuntimeError(f"SSH 설정이 불완전합니다: {self.remote_host}")
        identity = ""
        for candidate in values.get("identityfile", []):
            expanded = os.path.expanduser(candidate)
            if not Path(expanded).is_file():
                continue
            probe = subprocess.run(
                [
                    self.ssh, "-q", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                    "-o", "ConnectTimeout=15", "-i", expanded,
                    self.remote_host, "exit 0",
                ],
                timeout=30,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if probe.returncode == 0:
                identity = expanded
                break
        if not identity:
            raise RuntimeError(f"실제 SSH 인증에 성공하는 개인키가 없습니다: {self.remote_host}")
        args = [
            "--sftp-host", required["host"], "--sftp-user", required["user"],
            "--sftp-port", required["port"], "--sftp-key-file", identity,
            "--sftp-shell-type", "unix" if self.is_windows else "powershell",
        ]
        known_hosts = Path.home() / ".ssh" / "known_hosts"
        if known_hosts.is_file():
            args += ["--sftp-known-hosts-file", str(known_hosts), "--sftp-host-key-algorithms", "ssh-ed25519"]
        return args

    def _filters(self) -> list[str]:
        args: list[str] = []
        dirs = list(self.profile.get("exclude_dirs", []))
        for name in dirs:
            for pattern in (f"/{name}/**", f"**/{name}/**"):
                args += ["--exclude", pattern]
        for name in self.profile.get("exclude_names", []):
            args += ["--exclude", f"**/{name}"]
        for suffix in self.profile.get("exclude_suffixes", []):
            args += ["--exclude", f"**/*{suffix}"]
        for prefix in self.profile.get("git_managed_prefixes", []):
            args += ["--exclude", f"/{prefix.rstrip('/')}/**"]
        for pattern in self.profile.get("exclude_path_patterns", []):
            args += ["--exclude", pattern]
        return args

    def _location(self, device: str) -> tuple[str, list[str]]:
        if device == "mac":
            if self.is_windows:
                return f":sftp:{self.mac_path}", self.sftp_args
            return self.mac_path, []
        if self.is_windows:
            return self.windows_path, []
        return f":sftp:{windows_sftp_path(self.windows_path)}", self.sftp_args

    def inventory(self, device: str) -> dict[str, FileInfo]:
        location, connection = self._location(device)
        min_age = int(self.config.get("safety", {}).get("min_age_minutes", 5))
        command = [
            self.rclone, "lsjson", location, "--recursive", "--files-only", "--no-mimetype",
            "--copy-links", "--metadata", *self._filters(), *connection,
        ]
        if min_age > 0:
            command[6:6] = ["--min-age", f"{min_age}m"]
        result = run(command, timeout=1800)
        rows = json.loads(result.stdout or "[]")
        return {
            item["Path"].replace("\\", "/"): FileInfo(
                path=item["Path"].replace("\\", "/"),
                size=int(item.get("Size", 0)),
                mod_time=str(item.get("ModTime", "")),
            )
            for item in rows
            if not item.get("IsDir")
        }

    def compare(self) -> list[DiffRow]:
        mac = self.inventory("mac")
        windows = self.inventory("windows")
        rows: list[DiffRow] = []
        for path in sorted(set(mac) | set(windows), key=str.casefold):
            m = mac.get(path)
            w = windows.get(path)
            if m is None:
                status = "windows_only"
            elif w is None:
                status = "mac_only"
            elif m.size == w.size:
                status = "likely_same" if m.mod_time == w.mod_time else "same_size_time_diff"
            else:
                status = "conflict"
            rows.append(DiffRow(path=path, status=status, mac=m, windows=w))
        return rows

    def _single_location(self, device: str, relative: str) -> tuple[str, list[str]]:
        root, connection = self._location(device)
        return f"{root.rstrip('/')}/{relative}", connection

    def hash_file(self, device: str, relative: str) -> str:
        location, connection = self._single_location(device, relative)
        process = subprocess.Popen(
            [self.rclone, "cat", location, *connection],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        digest = hashlib.sha256()
        assert process.stdout is not None
        for chunk in iter(lambda: process.stdout.read(1024 * 1024), b""):
            digest.update(chunk)
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        code = process.wait(timeout=900)
        if code != 0:
            raise RuntimeError(f"원격 파일 해시 읽기 실패: {relative}\n{stderr[-1000:]}")
        return digest.hexdigest()

    def preview(self, device: str, relative: str, limit: int = 65536) -> str:
        if Path(relative).suffix.lower() not in TEXT_SUFFIXES:
            return "[텍스트 미리보기를 지원하지 않는 형식입니다. 장치에서 열기를 사용하세요.]"
        location, connection = self._single_location(device, relative)
        result = run([self.rclone, "cat", location, "--head", str(limit), *connection], timeout=120, check=False)
        if result.returncode != 0:
            return f"[읽기 실패]\n{result.stderr[-1000:]}"
        return result.stdout

    def open_on_device(self, device: str, relative: str) -> None:
        if device == "mac":
            path = str(Path(self.mac_path) / PurePosixPath(relative))
            if self.is_windows:
                run([self.ssh, self.remote_host, "open", "-R", path], timeout=30, check=False)
            else:
                subprocess.Popen(["open", "-R", path])
        else:
            path = str(PurePosixPath(self.windows_path.replace("\\", "/")) / PurePosixPath(relative))
            ps = f"Start-Process explorer.exe -ArgumentList '/select,\"{path}\"'"
            if self.is_windows:
                subprocess.Popen([self.pwsh, "-NoProfile", "-Command", ps])
            else:
                run([self.ssh, self.remote_host, ps], timeout=30, check=False)

    def invoke(self, direction: str, files: list[str] | None, action: str, replace: bool) -> subprocess.CompletedProcess[str]:
        plan_root = self.state_root / "cross-device" / "gui-plans"
        plan_root.mkdir(parents=True, exist_ok=True)
        command = [
            self.pwsh, "-NoProfile", "-File", str(self.engine),
            "-Action", action, "-Direction", direction,
            "-WindowsPath", self.windows_path, "-MacPath", self.mac_path,
            "-ConflictMode", "PreserveAndReplace" if replace else "Stop",
            "-ConfigPath", str(self.config_path),
        ]
        if files is not None:
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            manifest = plan_root / f"{stamp}-{direction}.txt"
            manifest.write_text("".join(f"{path}\n" for path in sorted(set(files))), encoding="utf-8")
            command += ["-FilesFrom", str(manifest)]
        return run(command, timeout=21600, check=False)


class SyncGui:
    STATUS_LABELS = {
        "mac_only": "Mac만",
        "windows_only": "Windows만",
        "likely_same": "동일 후보",
        "same_size_time_diff": "같은 크기·시간 다름",
        "conflict": "충돌 후보",
        "verified_same": "해시 동일",
        "verified_conflict": "해시 충돌",
    }
    DECISION_LABELS = {"skip": "건너뜀", "MacToWindows": "Mac → Windows", "WindowsToMac": "Windows → Mac"}

    def __init__(self, root: Tk, backend: SyncBackend) -> None:
        self.root = root
        self.backend = backend
        self.rows: list[DiffRow] = []
        self.by_iid: dict[str, DiffRow] = {}
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.last_plan: dict[str, list[str]] | None = None
        self.search_var = StringVar()
        self.status_var = StringVar(value="all")
        self.show_same = BooleanVar(value=False)
        self.summary_var = StringVar(value="SSH 연결 확인 완료 · 비교를 시작하세요.")
        self._build()
        self.root.after(150, self._poll)

    def _build(self) -> None:
        self.root.title(f"Windows ↔ Mac 선택 동기화 · {self.backend.profile_name}")
        self.root.geometry("1500x850")
        header = ttk.Frame(self.root, padding=10)
        header.pack(fill="x")
        ttk.Label(header, text="Windows ↔ Mac 선택 동기화", font=("Arial", 18, "bold")).pack(side=LEFT)
        ttk.Label(header, textvariable=self.summary_var).pack(side=LEFT, padx=20)
        ttk.Button(header, text="양쪽 다시 비교", command=self.scan).pack(side=RIGHT)

        filters = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        filters.pack(fill="x")
        ttk.Label(filters, text="경로 검색").pack(side=LEFT)
        search = ttk.Entry(filters, textvariable=self.search_var, width=45)
        search.pack(side=LEFT, padx=6)
        search.bind("<KeyRelease>", lambda _event: self.refresh())
        ttk.Label(filters, text="상태").pack(side=LEFT, padx=(15, 4))
        status = ttk.Combobox(
            filters, textvariable=self.status_var, state="readonly", width=15,
            values=("all", "mac_only", "windows_only", "same_size_time_diff", "conflict", "verified_conflict", "verified_same"),
        )
        status.pack(side=LEFT)
        status.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        ttk.Checkbutton(filters, text="동일 후보도 표시", variable=self.show_same, command=self.refresh).pack(side=LEFT, padx=12)

        table_frame = ttk.Frame(self.root, padding=(10, 0))
        table_frame.pack(fill=BOTH, expand=True)
        columns = ("status", "path", "mac", "windows", "recommendation", "decision")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        widths = {"status": 100, "path": 520, "mac": 150, "windows": 150, "recommendation": 310, "decision": 130}
        labels = {"status": "상태", "path": "상대경로", "mac": "Mac 크기 / 수정", "windows": "Windows 크기 / 수정", "recommendation": "추천", "decision": "사용자 선택"}
        for name in columns:
            self.tree.heading(name, text=labels[name])
            self.tree.column(name, width=widths[name], anchor="w")
        scroll = ttk.Scrollbar(table_frame, orient=VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        scroll.pack(side=RIGHT, fill="y")
        self.tree.bind("<Double-1>", lambda _event: self.preview_selected())

        actions = ttk.Frame(self.root, padding=10)
        actions.pack(fill="x")
        ttk.Button(actions, text="미리보기 / 해시 비교", command=self.preview_selected).pack(side=LEFT)
        ttk.Button(actions, text="Mac → Windows 선택", command=lambda: self.set_decision("MacToWindows")).pack(side=LEFT, padx=5)
        ttk.Button(actions, text="Windows → Mac 선택", command=lambda: self.set_decision("WindowsToMac")).pack(side=LEFT, padx=5)
        ttk.Button(actions, text="건너뛰기", command=lambda: self.set_decision("skip")).pack(side=LEFT, padx=5)
        ttk.Button(actions, text="선택 Plan", command=self.plan).pack(side=RIGHT, padx=5)
        ttk.Button(actions, text="검토한 Plan 실행", command=self.sync).pack(side=RIGHT, padx=5)

        note = (
            "수정시각이 더 최신이라는 이유만으로 승자를 정하지 않습니다. 충돌 교체를 선택하면 대상 원본을 "
            ".cross-device-conflicts/<시각>/ 아래에 먼저 보존합니다. 삭제 동기화는 제공하지 않습니다."
        )
        ttk.Label(self.root, text=note, padding=(10, 0, 10, 10), foreground="#555").pack(fill="x")

    @staticmethod
    def _compact(info: FileInfo | None) -> str:
        if not info:
            return "—"
        stamp = info.mod_time.replace("T", " ")[:16]
        return f"{info.size:,} B · {stamp}"

    def _busy(self, label: str, job: Callable[[], Any], event_name: str) -> None:
        self.summary_var.set(label)
        def worker() -> None:
            try:
                self.events.put((event_name, job()))
            except Exception as exc:  # noqa: BLE001 - surfaced in GUI
                self.events.put(("error", f"{type(exc).__name__}: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "scan_done":
                    self.rows = payload
                    self.last_plan = None
                    self.refresh()
                    counts: dict[str, int] = {}
                    for row in self.rows:
                        counts[row.status] = counts.get(row.status, 0) + 1
                    self.summary_var.set(
                        f"총 {len(self.rows):,} · Mac만 {counts.get('mac_only',0):,} · "
                        f"Windows만 {counts.get('windows_only',0):,} · 같은 크기/시간 다름 {counts.get('same_size_time_diff',0):,} · "
                        f"크기 충돌 {counts.get('conflict',0):,}"
                    )
                elif event == "hash_done":
                    row, mac_hash, windows_hash = payload
                    row.mac_hash, row.windows_hash = mac_hash, windows_hash
                    row.status = "verified_same" if mac_hash and mac_hash == windows_hash else "verified_conflict"
                    self.refresh()
                    self._show_preview(row)
                elif event == "plan_done":
                    results, selected = payload
                    self.last_plan = selected if all(result.returncode == 0 for result in results) else None
                    self._show_results("Plan 결과", results)
                elif event == "sync_done":
                    results = payload
                    self.last_plan = None
                    self._show_results("동기화 결과", results)
                    if all(result.returncode == 0 for result in results):
                        messagebox.showinfo("완료", "선택 파일 동기화가 완료됐습니다. 양쪽을 다시 비교합니다.")
                        self.scan()
                elif event == "error":
                    self.summary_var.set("오류 발생")
                    messagebox.showerror("오류", payload)
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def scan(self) -> None:
        self._busy("양쪽 안정 파일 목록을 읽는 중…", self.backend.compare, "scan_done")

    def refresh(self) -> None:
        selected_paths = {self.by_iid[iid].path for iid in self.tree.selection() if iid in self.by_iid}
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.by_iid.clear()
        query = self.search_var.get().strip().casefold()
        status_filter = self.status_var.get()
        visible = 0
        for index, row in enumerate(self.rows):
            if query and query not in row.path.casefold():
                continue
            if not self.show_same.get() and row.status in {"likely_same", "verified_same"}:
                continue
            if status_filter != "all" and row.status != status_filter:
                continue
            iid = f"r{index}"
            self.tree.insert("", END, iid=iid, values=(
                self.STATUS_LABELS[row.status], row.path, self._compact(row.mac), self._compact(row.windows),
                row.recommendation, self.DECISION_LABELS[row.decision],
            ))
            self.by_iid[iid] = row
            if row.path in selected_paths:
                self.tree.selection_add(iid)
            visible += 1
            if visible >= 5000:
                break

    def selected_rows(self) -> list[DiffRow]:
        return [self.by_iid[iid] for iid in self.tree.selection() if iid in self.by_iid]

    def set_decision(self, decision: str) -> None:
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo("선택 필요", "먼저 파일 행을 선택하세요.")
            return
        for row in rows:
            row.decision = decision
        self.last_plan = None
        self.refresh()

    def preview_selected(self) -> None:
        rows = self.selected_rows()
        if len(rows) != 1:
            messagebox.showinfo("한 파일 선택", "미리보기는 한 파일씩 선택하세요.")
            return
        row = rows[0]
        if row.mac and row.windows:
            self._busy(
                "선택 파일 SHA-256을 양쪽에서 계산 중…",
                lambda: (row, self.backend.hash_file("mac", row.path), self.backend.hash_file("windows", row.path)),
                "hash_done",
            )
        else:
            self._show_preview(row)

    def _show_preview(self, row: DiffRow) -> None:
        window = Toplevel(self.root)
        window.title(f"비교 · {row.path}")
        window.geometry("1350x760")
        header = ttk.Frame(window, padding=8)
        header.pack(fill="x")
        ttk.Label(header, text=row.path, font=("Arial", 12, "bold")).pack(side=LEFT)
        ttk.Label(header, text=f"  {row.recommendation}").pack(side=LEFT)
        ttk.Button(header, text="Mac에서 열기", command=lambda: self.backend.open_on_device("mac", row.path)).pack(side=RIGHT)
        ttk.Button(header, text="Windows에서 열기", command=lambda: self.backend.open_on_device("windows", row.path)).pack(side=RIGHT, padx=5)
        panes = ttk.Panedwindow(window, orient="horizontal")
        panes.pack(fill=BOTH, expand=True, padx=8, pady=8)
        left = ScrolledText(panes, wrap="none")
        right = ScrolledText(panes, wrap="none")
        panes.add(left, weight=1)
        panes.add(right, weight=1)
        left.insert(END, f"[Mac]\nSHA-256: {row.mac_hash or '미계산/없음'}\n\n")
        right.insert(END, f"[Windows]\nSHA-256: {row.windows_hash or '미계산/없음'}\n\n")
        left.insert(END, self.backend.preview("mac", row.path) if row.mac else "[Mac에 없음]")
        right.insert(END, self.backend.preview("windows", row.path) if row.windows else "[Windows에 없음]")
        left.configure(state="disabled")
        right.configure(state="disabled")

    def _decision_groups(self) -> dict[str, list[str]]:
        return {
            direction: [row.path for row in self.rows if row.decision == direction]
            for direction in ("MacToWindows", "WindowsToMac")
        }

    def plan(self) -> None:
        groups = self._decision_groups()
        if not any(groups.values()):
            messagebox.showinfo("선택 필요", "파일을 선택하고 방향을 지정하세요.")
            return
        def job() -> tuple[list[subprocess.CompletedProcess[str]], dict[str, list[str]]]:
            results = []
            for direction, files in groups.items():
                if not files:
                    continue
                replace = any(row.path in files and row.status in {"same_size_time_diff", "conflict", "verified_conflict"} for row in self.rows)
                results.append(self.backend.invoke(direction, files, "Plan", replace))
            return results, groups
        self._busy("선택 방향별 dry-run Plan 실행 중…", job, "plan_done")

    def sync(self) -> None:
        groups = self._decision_groups()
        if self.last_plan != groups:
            messagebox.showwarning("Plan 필요", "현재 선택과 일치하는 성공한 Plan을 먼저 실행하세요.")
            return
        count = sum(len(files) for files in groups.values())
        conflicts = sum(
            1 for row in self.rows
            if row.decision != "skip" and row.status in {"same_size_time_diff", "conflict", "verified_conflict"}
        )
        question = (
            f"검토한 {count:,}개 파일을 동기화할까요?\n\n"
            f"충돌 교체 {conflicts:,}개는 대상 원본을 .cross-device-conflicts에 보존합니다.\n"
            "다른 파일 삭제는 하지 않습니다."
        )
        if not messagebox.askyesno("최종 실행 확인", question):
            return
        def job() -> list[subprocess.CompletedProcess[str]]:
            results = []
            for direction, files in groups.items():
                if not files:
                    continue
                replace = any(row.path in files and row.status in {"same_size_time_diff", "conflict", "verified_conflict"} for row in self.rows)
                results.append(self.backend.invoke(direction, files, "Sync", replace))
            return results
        self._busy("선택 파일 동기화 중…", job, "sync_done")

    def _show_results(self, title: str, results: list[subprocess.CompletedProcess[str]]) -> None:
        window = Toplevel(self.root)
        window.title(title)
        window.geometry("1100x650")
        text = ScrolledText(window, wrap="word")
        text.pack(fill=BOTH, expand=True)
        for result in results:
            text.insert(END, f"exit={result.returncode}\n{result.stdout}\n{result.stderr}\n{'='*80}\n")
        text.configure(state="disabled")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="00-career")
    parser.add_argument("--aicc-root")
    parser.add_argument("--scan-now", action="store_true")
    args = parser.parse_args()
    aicc_root = Path(args.aicc_root or os.environ.get("AICC_ROOT") or (Path.home() / "dev" / "projects" / "tools" / "AICC")).resolve()
    backend = SyncBackend(aicc_root, args.profile)
    root = Tk()
    gui = SyncGui(root, backend)
    if args.scan_now:
        root.after(250, gui.scan)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
