"""在本机提供驾驶舱网页（web/ 目录），并用 cloudflared 快速隧道生成公开网址（无需账号）。

- 有 .gz 预压缩文件且浏览器支持时直接发压缩版，数据从约 2.5 MB 降到几百 KB
- 页面框架与 d3 允许浏览器缓存一天；data.json 每次都向服务器确认是否有更新
- 快速隧道每次启动网址都会变；public_url() 返回当前网址，隧道还没就绪时返回 None
"""
import atexit
import functools
import gzip
import json
import os
import re
import shutil
import socket
import subprocess
import urllib.request
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import lark_oapi as lark

WEB_DIR = Path(__file__).with_name("web")
PORT = 8765
_state = {"url": None}


class _Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # 不刷屏
        pass

    def send_head(self):
        path = Path(self.translate_path(self.path))
        if path.is_dir():
            path = path / "index.html"
        gz = path.with_name(path.name + ".gz")
        if path.is_file() and "gzip" in self.headers.get("Accept-Encoding", ""):
            if not gz.is_file() or gz.stat().st_mtime < path.stat().st_mtime:
                _write_gz(path)
            stat = gz.stat()
            etag = f'"{int(path.stat().st_mtime)}-{stat.st_size}"'
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.end_headers()
                return None
            self.send_response(200)
            self.send_header("Content-Type", self.guess_type(str(path)))
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(stat.st_size))
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache" if path.suffix in (".json", ".html") else "public, max-age=86400")
            self.end_headers()
            return open(gz, "rb")
        return super().send_head()


def _write_gz(path):
    tmp = path.with_name(path.name + ".gz.tmp")
    with open(path, "rb") as f, gzip.open(tmp, "wb", compresslevel=9) as g:
        shutil.copyfileobj(f, g)
    os.replace(tmp, path.with_name(path.name + ".gz"))


def write_data(data):
    """原子地写出 web/data.json 与压缩版，网页下次打开即为新数据。"""
    path = WEB_DIR / "data.json"
    tmp = path.with_name("data.json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)
    _write_gz(path)


def write_health(ok, **info):
    """web/health.json：最近一次刷新是否成功，供排查与页面判断数据是否过期。"""
    path = WEB_DIR / "health.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    data = {**old, "checked_at": now, "ok": ok, **info}
    if ok:
        data.update(last_ok=now, error=None)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _find_cloudflared():
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
    found = shutil.which("cloudflared") or next(iter(winget.glob("Cloudflare.cloudflared_*/cloudflared.exe")), None)
    return str(found) if found else None


def _run_tunnel(exe):
    """一直保持隧道：进程退出或被看门狗判定失效后，等一会儿重新开一条（网址会变，卡片按钮自动跟着变）。"""
    while True:
        proc = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        _state["proc"] = proc
        atexit.register(proc.terminate)  # 机器人退出时一并关掉隧道
        for line in proc.stdout:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if m and not _state["url"]:
                # 新网址要过一会儿才在公网生效；太早发给用户，飞书浏览器会缓存「找不到」。确认能打开后再启用
                threading.Thread(target=_publish_when_ready, args=(m.group(0),), daemon=True).start()
        _state["url"] = None
        lark.logger.error("cloudflared 隧道已退出，30 秒后重建")
        time.sleep(30)


def _publish_when_ready(url):
    for _ in range(24):  # 最多等 2 分钟
        try:
            if urllib.request.urlopen(f"{url}/health.json", timeout=10).status == 200:
                break
        except Exception:
            time.sleep(5)
    _state["url"] = url
    lark.logger.info(f"驾驶舱公开网址：{url}")


def _watch_tunnel():
    """看门狗：断网恢复后快速隧道的网址常常已失效但进程还在。每 5 分钟检查一次公开网址，
    连续 3 次打不开（且本机能上网）就关掉旧隧道，由 _run_tunnel 重建。"""
    fails = 0
    while True:
        time.sleep(300)
        url = _state["url"]
        if not url:
            continue
        try:
            ok = urllib.request.urlopen(f"{url}/health.json", timeout=20).status == 200
        except Exception:
            ok = False
        if ok:
            fails = 0
            continue
        try:  # 本机本身断网时不算隧道的问题，等网络恢复
            socket.getaddrinfo("open.feishu.cn", 443)
        except OSError:
            continue
        fails += 1
        lark.logger.warning(f"驾驶舱公开网址打不开（第 {fails} 次）：{url}")
        if fails >= 3 and _state.get("proc"):
            lark.logger.error("隧道已失效，正在重建")
            fails = 0
            _state["proc"].terminate()


def start(public=None):
    """public 为服务器的固定网址（如 http://1.2.3.4）时直接对外提供网页，不再开隧道。"""
    for p in [*WEB_DIR.glob("*.html"), *WEB_DIR.glob("*.js")]:  # 静态文件先压缩好，避免首个请求现压
        _write_gz(p)
    host, port = ("0.0.0.0", int(os.environ.get("WEB_PORT", 80))) if public else ("127.0.0.1", PORT)
    server = ThreadingHTTPServer((host, port), functools.partial(_Handler, directory=str(WEB_DIR)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if public:
        _state["url"] = public.rstrip("/")
        lark.logger.info(f"驾驶舱网址：{_state['url']}")
        return
    exe = _find_cloudflared()
    if not exe:
        lark.logger.error("找不到 cloudflared，驾驶舱只能在本机打开")
        return
    threading.Thread(target=_run_tunnel, args=(exe,), daemon=True).start()
    threading.Thread(target=_watch_tunnel, daemon=True).start()


def public_url():
    return _state["url"]
