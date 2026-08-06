#!/usr/bin/env python3
"""Local browser UI for Mac-authoritative Windows synchronization.

The server binds only to 127.0.0.1.  It never deletes Windows-only files and
requires a successful dry-run Plan before Sync.  When a Windows target differs,
the PowerShell/rclone engine preserves the old target before replacing it.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import secrets
import subprocess
import threading
import unicodedata
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from cross_device_sync_gui import DiffRow, SyncBackend


WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}


def validate_windows_paths(paths: list[str]) -> None:
    """Fail before Plan when two Mac paths cannot coexist safely on Windows."""
    seen: dict[str, str] = {}
    invalid: list[str] = []
    collisions: list[tuple[str, str]] = []
    for path in paths:
        key = unicodedata.normalize("NFC", path).casefold()
        if key in seen and seen[key] != path:
            collisions.append((seen[key], path))
        else:
            seen[key] = path
        for component in path.split("/"):
            stem = component.split(".", 1)[0].upper()
            if (
                any(ord(char) < 32 for char in component)
                or re.search(r'[<>:"\\|?*]', component)
                or component.endswith((" ", "."))
                or stem in WINDOWS_RESERVED
            ):
                invalid.append(path)
                break
    if collisions or invalid:
        details = [f"대소문자/정규화 충돌: {len(collisions)}개", f"Windows 금지 경로: {len(invalid)}개"]
        examples = [f"{left} <> {right}" for left, right in collisions[:5]] + invalid[:5]
        raise RuntimeError("Windows에 안전하게 배치할 수 없는 경로가 있습니다. " + ", ".join(details + examples))


def open_local_url(url: str) -> None:
    """Open the local UI without falling back to Safari on macOS."""
    if platform.system() == "Darwin":
        for app in ("NAVER Whale", "Google Chrome"):
            result = subprocess.run(
                ["open", "-a", app, url],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if result.returncode == 0:
                return
        raise RuntimeError("NAVER Whale 또는 Google Chrome을 열 수 없습니다.")
    if not webbrowser.open(url):
        raise RuntimeError("기본 브라우저를 열 수 없습니다.")


HTML = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mac 기준 Windows 맞추기</title>
<style>
:root{color-scheme:light;--ink:#18212f;--muted:#64748b;--line:#dbe3ee;--blue:#2563eb;--pale:#eff6ff;--green:#047857;--warn:#9a3412}
*{box-sizing:border-box}body{margin:0;background:#f5f7fb;color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1180px;margin:30px auto;padding:0 22px}.hero,.card{background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:0 8px 28px rgba(30,50,80,.06)}
.hero{padding:28px 30px}.eyebrow{color:var(--blue);font-weight:700}.hero h1{font-size:30px;margin:5px 0 8px}.hero p{margin:4px 0;color:var(--muted)}
.rule{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:22px}.rule div{background:#f8fafc;border:1px solid var(--line);padding:15px;border-radius:12px}.rule strong{display:block;margin-bottom:3px}
.card{padding:22px 24px;margin-top:18px}h2{font-size:20px;margin:0 0 12px}.status{padding:13px 15px;background:var(--pale);border-radius:10px;font-weight:650}.counts{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}.count{border:1px solid var(--line);border-radius:10px;padding:12px}.count b{display:block;font-size:22px}.count span{color:var(--muted);font-size:13px}
.buttons{display:flex;gap:10px;flex-wrap:wrap}.btn{border:0;border-radius:10px;padding:11px 16px;font-weight:700;cursor:pointer}.primary{background:var(--blue);color:#fff}.safe{background:var(--green);color:#fff}.secondary{background:#e8eef7;color:var(--ink)}.danger{background:#fff1f2;color:#9f1239}.btn:disabled{opacity:.45;cursor:not-allowed}
.help{color:var(--muted);margin:10px 0 0}.warning{color:var(--warn);font-weight:650}.result{white-space:pre-wrap;max-height:320px;overflow:auto;background:#0f172a;color:#dbeafe;border-radius:10px;padding:14px;font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}
.toolbar{display:flex;gap:10px;margin-bottom:10px}.toolbar input{flex:1;border:1px solid var(--line);border-radius:9px;padding:10px}.table-wrap{max-height:430px;overflow:auto;border:1px solid var(--line);border-radius:10px}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px 11px;border-bottom:1px solid #edf1f6}th{position:sticky;top:0;background:#f8fafc}td.path{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}.tag{font-weight:700;color:var(--blue)}
@media(max-width:800px){.rule,.counts{grid-template-columns:1fr 1fr}}
</style>
</head>
<body><main>
<section class="hero">
  <div class="eyebrow">누락 없는 전체 복제 · 기본 방향: Mac → Windows</div>
  <h1>Mac 루트 전체를 같은 위치로 Windows에 맞추기</h1>
  <p>숨김 파일, <code>.git</code>, 의존성, 가상환경, 캐시, DB를 포함한 모든 상대경로를 Windows의 <code>dev/projects/00-career</code> 아래에 반영합니다.</p>
  <div class="rule">
    <div><strong>Mac에만 있는 파일</strong>Windows의 같은 상대경로에 생성</div>
    <div><strong>양쪽 내용이 다른 파일</strong>Windows 원본을 보관한 뒤 Mac판 반영</div>
    <div><strong>Windows에만 있는 파일</strong>삭제하거나 Mac으로 가져오지 않음</div>
  </div>
</section>

<section class="card">
  <h2>1. 현재 상태 확인</h2>
  <div id="status" class="status">준비 중…</div>
  <div class="counts">
    <div class="count"><b id="macOnly">—</b><span>Mac에만 있음</span></div>
    <div class="count"><b id="different">—</b><span>양쪽 재확인/차이 후보</span></div>
    <div class="count"><b id="winOnly">—</b><span>Windows에만 있음 · 그대로 둠</span></div>
    <div class="count"><b id="totalMac">—</b><span>Plan에서 검사할 Mac 전체 파일</span></div>
  </div>
  <div class="buttons"><button id="scan" class="btn secondary">양쪽 다시 검사</button></div>
</section>

<section class="card">
  <h2>2. 변경 예정 확인</h2>
  <p>Plan은 읽기 전용입니다. 실제 파일은 바꾸지 않고, Mac 루트 전체에서 Windows에 무엇이 생성·교체될지만 검사합니다.</p>
  <div class="buttons"><button id="plan" class="btn primary" disabled>안전 Plan 실행</button></div>
  <p class="help">이름·확장자·숨김 여부·Git 관리 여부로 제외하지 않습니다. Windows에만 있는 파일은 삭제하지 않습니다.</p>
</section>

<section class="card">
  <h2>3. Windows에 실제 반영</h2>
  <p class="warning">성공한 Plan 이후에만 실행할 수 있습니다. 다른 Windows 파일은 삭제하지 않습니다.</p>
  <div class="buttons"><button id="sync" class="btn safe" disabled>검토한 Plan대로 Windows 맞추기</button></div>
</section>

<section class="card">
  <h2>Mac 기준 후보 파일</h2>
  <div class="toolbar"><input id="search" placeholder="상대경로 검색"><span id="shown"></span></div>
  <div class="table-wrap"><table><thead><tr><th>판단</th><th>상대경로</th><th>Mac 크기</th><th>Windows 크기</th></tr></thead><tbody id="rows"></tbody></table></div>
</section>

<section class="card">
  <h2>실행 기록</h2><div id="result" class="result">아직 실행 기록이 없습니다.</div>
  <div class="buttons" style="margin-top:12px"><button id="stop" class="btn danger">이 도구 종료</button></div>
</section>
</main>
<script>
const TOKEN=__TOKEN__;
const $=id=>document.getElementById(id);
let lastRows=[];
async function api(action){
 const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-Sync-Token':TOKEN},body:JSON.stringify({action})});
 const d=await r.json(); if(!r.ok) throw new Error(d.error||'요청 실패'); return d;
}
function renderRows(){
 const q=$('search').value.trim().toLowerCase(); const rows=lastRows.filter(x=>x.path.toLowerCase().includes(q)).slice(0,1000);
 $('rows').innerHTML=rows.map(x=>`<tr><td class="tag">${x.label}</td><td class="path">${escapeHtml(x.path)}</td><td>${fmt(x.mac_size)}</td><td>${fmt(x.windows_size)}</td></tr>`).join('');
 $('shown').textContent=`${rows.length.toLocaleString()}개 표시`;
}
function escapeHtml(s){return s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function fmt(v){return v===null?'—':Number(v).toLocaleString()+' B'}
async function poll(){
 try{const r=await fetch('/api/status',{headers:{'X-Sync-Token':TOKEN}});const d=await r.json();
  $('status').textContent=d.message;$('macOnly').textContent=num(d.counts.mac_only);$('different').textContent=num(d.counts.different);$('winOnly').textContent=num(d.counts.windows_only);$('totalMac').textContent=num(d.counts.total_mac);
  $('scan').disabled=d.busy;$('plan').disabled=d.busy||!d.scan_ready;$('sync').disabled=d.busy||!d.plan_ready;
  if(d.rows){lastRows=d.rows;renderRows()} if(d.result)$('result').textContent=d.result;
 }catch(e){$('status').textContent='상태 읽기 실패: '+e.message} setTimeout(poll,1200);
}
function num(v){return v==null?'—':Number(v).toLocaleString()}
$('search').addEventListener('input',renderRows);
$('scan').onclick=()=>api('scan').catch(e=>alert(e.message));
$('plan').onclick=()=>api('plan').catch(e=>alert(e.message));
$('sync').onclick=()=>{if(confirm('Mac을 기준으로 Windows의 같은 상대경로에 실제 반영할까요?\n\nWindows에만 있는 파일은 삭제하지 않고, 교체되는 Windows 원본은 충돌 보관 폴더에 저장합니다.'))api('sync').catch(e=>alert(e.message))};
$('stop').onclick=()=>api('stop').then(()=>window.close()).catch(e=>alert(e.message));
poll();
</script></body></html>"""


class State:
    def __init__(self, backend: SyncBackend) -> None:
        self.backend = backend
        self.lock = threading.Lock()
        self.busy = False
        self.phase = "starting"
        self.message = "SSH 연결 확인 완료 · 양쪽 파일을 검사합니다."
        self.rows: list[DiffRow] = []
        self.plan_paths: list[str] = []
        self.plan_ready = False
        self.result = "아직 실행 기록이 없습니다."
        self.error = ""

    def start(self, phase: str, message: str, job: Callable[[], None]) -> None:
        with self.lock:
            if self.busy:
                raise RuntimeError("이미 다른 작업이 진행 중입니다.")
            self.busy = True
            self.phase = phase
            self.message = message
            self.error = ""

        def worker() -> None:
            try:
                job()
            except Exception as exc:  # noqa: BLE001 - shown in local UI
                with self.lock:
                    self.error = f"{type(exc).__name__}: {exc}"
                    self.message = f"오류: {self.error}"
                    self.plan_ready = False
            finally:
                with self.lock:
                    self.busy = False

        threading.Thread(target=worker, daemon=True).start()

    def scan(self) -> None:
        def job() -> None:
            rows = self.backend.compare()
            with self.lock:
                self.rows = rows
                self.plan_paths = []
                self.plan_ready = False
                self.phase = "scanned"
                self.message = "검사 완료 · 아래에서 안전 Plan을 실행하세요."
                self.result = "검사 완료. 아직 실제 파일은 변경하지 않았습니다."
        self.start("scanning", "Mac과 Windows의 모든 파일을 읽는 중…", job)

    def plan(self) -> None:
        with self.lock:
            if not self.rows:
                raise RuntimeError("먼저 양쪽 파일 검사를 완료하세요.")
            paths = [row.path for row in self.rows if row.mac is not None]
        validate_windows_paths(paths)

        def job() -> None:
            result = self.backend.invoke("MacToWindows", None, "Plan", True)
            text = (result.stdout + "\n" + result.stderr).strip()
            with self.lock:
                self.result = (text[-20000:] if text else f"Plan exit={result.returncode}")
                self.plan_paths = paths if result.returncode == 0 else []
                self.plan_ready = result.returncode == 0
                self.phase = "planned" if result.returncode == 0 else "plan_failed"
                self.message = (
                    f"Plan 성공 · Mac 파일 {len(paths):,}개의 체크섬 검사가 끝났습니다."
                    if result.returncode == 0 else f"Plan 실패 · 실행 기록을 확인하세요. (exit={result.returncode})"
                )
        self.start("planning", "읽기 전용 Plan 실행 중 · 파일 수에 따라 시간이 걸릴 수 있습니다…", job)

    def sync(self) -> None:
        with self.lock:
            if not self.plan_ready or not self.plan_paths:
                raise RuntimeError("현재 검사 결과와 일치하는 성공한 Plan이 필요합니다.")
            paths = list(self.plan_paths)

        def job() -> None:
            result = self.backend.invoke("MacToWindows", None, "Sync", True)
            text = (result.stdout + "\n" + result.stderr).strip()
            verification_error = ""
            if result.returncode == 0:
                post_rows = self.backend.compare()
                missing = [row.path for row in post_rows if row.mac is not None and row.windows is None]
                size_mismatch = [
                    row.path for row in post_rows
                    if row.mac is not None and row.windows is not None and row.mac.size != row.windows.size
                ]
                if missing or size_mismatch:
                    verification_error = (
                        f"사후 inventory 실패: 누락 {len(missing):,}개, 크기 불일치 {len(size_mismatch):,}개"
                    )
            with self.lock:
                if verification_error:
                    text = (text + "\n" + verification_error).strip()
                self.result = (text[-20000:] if text else f"Sync exit={result.returncode}")
                self.plan_ready = False
                success = result.returncode == 0 and not verification_error
                self.phase = "synced" if success else "sync_failed"
                self.message = (
                    "Windows 반영 및 원본 경로 사후 검증 완료 · Windows에만 있던 파일은 그대로 유지했습니다."
                    if success else f"동기화 또는 완전성 검증 실패 · 실행 기록을 확인하세요. (exit={result.returncode})"
                )
        self.start("syncing", "Mac 기준으로 Windows에 반영 중…", job)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            counts = {
                "mac_only": sum(row.status == "mac_only" for row in self.rows),
                "windows_only": sum(row.status == "windows_only" for row in self.rows),
                "different": sum(row.status in {"same_size_time_diff", "conflict"} for row in self.rows),
                "total_mac": sum(row.mac is not None for row in self.rows),
            }
            candidates = []
            for row in self.rows:
                if row.status not in {"mac_only", "same_size_time_diff", "conflict"}:
                    continue
                candidates.append({
                    "path": row.path,
                    "label": {
                        "mac_only": "Windows에 생성",
                        "same_size_time_diff": "체크섬 재확인",
                        "conflict": "Windows 백업 후 Mac 반영",
                    }[row.status],
                    "mac_size": row.mac.size if row.mac else None,
                    "windows_size": row.windows.size if row.windows else None,
                })
                if len(candidates) >= 5000:
                    break
            return {
                "busy": self.busy,
                "phase": self.phase,
                "message": self.message,
                "scan_ready": bool(self.rows),
                "plan_ready": self.plan_ready,
                "counts": counts,
                "rows": candidates,
                "result": self.result,
                "error": self.error,
            }


def make_handler(state: State, token: str, server_ref: list[ThreadingHTTPServer | None]):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *args: Any) -> None:
            return

        def _authorized(self) -> bool:
            return self.headers.get("X-Sync-Token") == token

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/":
                page = HTML.replace("__TOKEN__", json.dumps(token)).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(page)
                return
            if path == "/api/status" and self._authorized():
                self._json(HTTPStatus.OK, state.snapshot())
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/action" or not self._authorized():
                self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                action = body.get("action")
                if action == "scan":
                    state.scan()
                elif action == "plan":
                    state.plan()
                elif action == "sync":
                    state.sync()
                elif action == "stop":
                    self._json(HTTPStatus.OK, {"ok": True})
                    server = server_ref[0]
                    if server:
                        threading.Thread(target=server.shutdown, daemon=True).start()
                    return
                else:
                    raise ValueError("지원하지 않는 작업입니다.")
                self._json(HTTPStatus.ACCEPTED, {"ok": True})
            except Exception as exc:  # noqa: BLE001 - local UI response
                self._json(HTTPStatus.CONFLICT, {"error": str(exc)})

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="00-career")
    parser.add_argument("--aicc-root")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--no-scan", action="store_true")
    args = parser.parse_args()
    aicc_root = Path(args.aicc_root or (Path.home() / "dev" / "projects" / "tools" / "ai-control-center")).resolve()
    backend = SyncBackend(aicc_root, args.profile)
    state = State(backend)
    token = secrets.token_urlsafe(24)
    server_ref: list[ThreadingHTTPServer | None] = [None]
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(state, token, server_ref))
    server_ref[0] = server
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"SYNC_GUI_URL={url}", flush=True)
    if not args.no_scan:
        state.scan()
    if not args.no_open:
        threading.Timer(0.4, lambda: open_local_url(url)).start()
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
