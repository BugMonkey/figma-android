#!/usr/bin/env python3
"""
figma_bridge_server.py — figma-android 插件桥 HTTP 服务器 (pull 模式)

skill 主动触发提取请求 → plugin 轮询到 pending → 提取数据 → POST 回 server → skill 读取。

用法:
  # 启动
  python3 figma_bridge_server.py [--port 7789]

  # 健康检查
  curl http://localhost:7789/health

端点:
  POST /api/request-extract  skill 请求 plugin 提取数据
  GET  /api/pending          plugin 轮询是否有待处理的提取请求
  GET  /api/plugin-status    skill 查询 plugin 是否在线
  POST /api/composition      plugin 发送节点树 + 截图（JSON）
  POST /api/assets           plugin 发送切图资源（JSON）
  GET  /health               健康检查
  GET  /api/status           查询最新数据就绪状态
"""

import json
import os
import sys
import time
import base64
import threading
import argparse
import shutil
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs



# Windows GBK 终端兼容：强制 stdout/stderr UTF-8
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ─── 全局状态 ───
CACHE_DIR = os.path.expanduser("~/.figma-android/cache")
_lock = threading.Lock()

# Pull 模型：pending_request 为 True 时 plugin 应执行提取
pending_request: bool = False

# extract-by-id 模式：指定 nodeId 提取，不依赖用户选中
pending_node_id: str = ""

# 调用方项目根目录（提取产物写入 {project_root}/.figma/）
pending_project_root: str = ""

# 遍历画板请求（复用 pending_request + __list_all__ nodeId）
artboard_list_data: dict = None  # 遍历结果缓存

# 请求过期机制：超过此时间(秒)未消费的 pending_request 自动清除
REQUEST_STALENESS = 30.0

# pending_request 专用过期阈值：必须容忍插件 iframe 被节流时的轮询间隔。
# 实测：iframe 不可见（Figma 窗口失焦 / 切到别的 tab）时，Chromium 会把插件的
# setInterval 节流到约 60s 一次。若沿用 30s，请求会在插件下一次轮询之前就被清除，
# 表现为「提取请求 Ns 未被插件消费」，而真实原因既非卡死也非版本过旧，
# 只是插件还没轮到下一次轮询。
PENDING_STALENESS = 150.0

# 请求创建时间（request-extract 时记录，composition/clear-pending 时归零）
request_created_at: float = 0.0

# 插件探活：记录最后一次 polling 时间
last_plugin_poll: float = 0.0
last_plugin_build: str = ""

# 上次提取失败的原因（plugin 提取失败时通过 /api/clear-pending 回填）
# 新提取请求发起时清空，composition 成功时清空
extract_last_error: str = ""

# 最新一次提取的数据信息
latest_data: dict = {
    "ready": False,
    "node_id": "",
    "file_key": "",
    "file_name": "",
    "page_name": "",
    "name": "",
    "timestamp": 0,
    "expected_images": 0,
    "received_images": 0,
}

# 当前在 Figma 中选中的节点（由 plugin UI 上报）
selected_node: dict = {
    "selected": False,
    "name": "",
    "id": "",
    "type": "",
    "pageName": "",
    "parentName": "",
    "parentId": "",
    "rootArtboardName": "",
    "rootArtboardId": "",
    "fileName": "",
    "isMarked": False,
    "updated_at": 0.0,
}


def reclaim_stale_pending_locked(now: float = None) -> bool:
    """回收「僵尸 pending」。返回 True 表示原 pending 已作废并被清掉。

    为什么需要：pending 的过期清除原先只写在 /api/pending 处理器里，而那个端点
    只有插件轮询时才会被调用。插件若长时间不在（面板被关、Figma 休眠），pending
    就永远不会被清，之后每一次 request-* 都拿到 409「已有请求在处理中」，且**无法
    自愈**——整条链路被一个永不消费的请求堵死，连「重试一次」都做不到。

    这里改用 request_created_at 的挂钟时间判断，不依赖插件轮询，让服务端能自行解锁。
    必须在持 _lock 时调用。
    """
    global pending_request, pending_node_id, request_created_at
    if not pending_request or request_created_at <= 0:
        return False
    age = (now if now is not None else time.time()) - request_created_at
    if age <= PENDING_STALENESS:
        return False
    pending_request = False
    pending_node_id = ""
    request_created_at = 0.0
    return True


def get_cache_dir(node_id: str) -> str:
    """返回缓存目录。
    优先使用 pending_project_root/.figma/（调用方项目目录），
    回退到 ~/.figma-android/cache/（独立中转缓存）。
    """
    safe_id = node_id.replace(":", "_")
    if pending_project_root:
        return os.path.join(pending_project_root, ".figma", f"figma_extract_plugin_{safe_id}")
    return os.path.join(CACHE_DIR, f"figma_extract_plugin_{safe_id}")


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def save_b64_image(b64_str: str, filepath: str):
    """保存 Base64 编码的 PNG 图片"""
    data = base64.b64decode(b64_str)
    with open(filepath, "wb") as f:
        f.write(data)


class BridgeHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器"""

    def log_message(self, format, *args):
        pass  # 静默日志

    def _cors_origin(self) -> str:
        origin = self.headers.get("Origin", "*") or "*"
        return origin

    def _send_cors_headers(self):
        origin = self._cors_origin()
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin")

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._send_cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: int = 200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self._send_cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        global pending_request, pending_node_id, request_created_at, latest_data, last_plugin_poll, last_plugin_build, selected_node, extract_last_error, artboard_list_data
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            self._send_text("ok")

        elif parsed.path == "/api/selected-node":
            # Agent 查询当前选中的节点信息
            with _lock:
                info = dict(selected_node)
                # 插件断连超过阈值 → 选中数据可能已过期
                now = time.time()
                last_seen = last_plugin_poll
                updated = info.get("updated_at", 0.0)
                if (now - last_seen > REQUEST_STALENESS
                        and last_seen > 0
                        and updated > 0
                        and now - updated > REQUEST_STALENESS):
                    info["stale"] = True
                else:
                    info["stale"] = False
            self._send_json(info)

        elif parsed.path == "/api/plugin-status":
            # Skill 查询插件是否在线
            with _lock:
                last_seen = last_plugin_poll
            now = time.time()
            connected = (now - last_seen) < 5.0  # 5 秒内有轮询 = 在线
            # plugin_iframe_visible: Figma 插件 iframe 不可见时 setInterval 暂停，
            # 因此 last_plugin_poll 在 4s 内更新 = iframe 可见且活跃轮询。
            # 阈值居中（2s 轮询间隔与 5s connected 之间），降低主线程繁忙时的假阴性；
            # 网页版 Figma 后台 tab 节流策略不同，该字段仅作辅助信号。
            iframe_visible = (now - last_seen) < 4.0 if last_seen > 0 else False
            with _lock:
                plugin_build = last_plugin_build
            self._send_json({
                "connected": connected,
                "last_seen": last_seen if last_seen > 0 else None,
                "plugin_iframe_visible": iframe_visible,
                "plugin_build": plugin_build,
            })

        elif parsed.path == "/api/pending":
            # Plugin 轮询是否有待处理的提取请求
            # 自动清除过期请求：插件断连超过阈值 → pending_request 僵尸 → 重置
            build = (parse_qs(parsed.query).get("build") or [""])[0]
            with _lock:
                now = time.time()
                last_plugin_poll = now  # 记录插件轮询时间
                if build:
                    last_plugin_build = build
                if pending_request and request_created_at > 0:
                    age = now - request_created_at
                    if age > PENDING_STALENESS:
                        pending_request = False
                        pending_node_id = ""
                        request_created_at = 0.0
                        # 过期清除回填超时错误。触发本块说明 plugin 仍在轮询 /api/pending。
                        # 注意：iframe 被节流时轮询间隔可达 60s+，因此「未被消费」的常见
                        # 原因既非提取卡死也非版本过旧，而是轮询间隔本身长于该阈值。
                        extract_last_error = (
                            f"提取请求 {age:.0f}s 未被插件消费。最可能原因："
                            f"Figma 插件 iframe 不可见，被浏览器节流至约 60s 轮询一次。"
                            f"请将 Figma 窗口置于前台并保持插件面板可见后重试。"
                            f"若插件面板已在前台仍反复失败，再考虑提取卡死或版本过旧。"
                        )
                is_pending = pending_request
                node_id = pending_node_id
                req_at = request_created_at
            result = {"pending": is_pending}
            if is_pending and node_id:
                result["nodeId"] = node_id
            if is_pending:
                result["requestCreatedAt"] = req_at
            self._send_json(result)

        elif parsed.path == "/api/status":
            # Skill 轮询最新数据就绪状态
            with _lock:
                info = dict(latest_data)
                info["extract_last_error"] = extract_last_error
            self._send_json(info)


        elif parsed.path == "/api/artboard-list":
            # Skill 读取遍历结果
            with _lock:
                result = dict(artboard_list_data) if artboard_list_data else {}
            self._send_json(result)

        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        global pending_request, pending_node_id, pending_project_root, request_created_at, latest_data, selected_node, extract_last_error, artboard_list_data
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON"}, 400)
            return

        if parsed.path == "/api/request-extract":
            project_root = data.get("project_root", "")
            with _lock:
                if pending_request and not reclaim_stale_pending_locked():
                    self._send_json({"status": "conflict", "message": "已有提取请求在处理中"}, 409)
                    return
                pending_request = True
                pending_node_id = ""
                pending_project_root = project_root
                request_created_at = time.time()
                latest_data["ready"] = False
                extract_last_error = ""
            self._send_json({"status": "ok", "pending": True})

        elif parsed.path == "/api/request-extract-by-id":
            node_id = data.get("node_id", "")
            if not node_id:
                self._send_json({"error": "missing node_id"}, 400)
                return
            project_root = data.get("project_root", "")
            with _lock:
                if pending_request and not reclaim_stale_pending_locked():
                    self._send_json({"status": "conflict", "message": "已有提取请求在处理中"}, 409)
                    return
                pending_request = True
                pending_node_id = node_id
                pending_project_root = project_root
                request_created_at = time.time()
                latest_data["ready"] = False
                extract_last_error = ""
            self._send_json({"status": "ok", "pending": True, "node_id": node_id})

        elif parsed.path == "/api/selected-node":
            # Plugin UI 上报当前选中节点
            with _lock:
                selected_node = {
                    "selected": data.get("selected", False),
                    "name": data.get("name", ""),
                    "id": data.get("id", ""),
                    "type": data.get("type", ""),
                    "pageName": data.get("pageName", ""),
                    "parentName": data.get("parentName", ""),
                    "parentId": data.get("parentId", ""),
                        "rootArtboardName": data.get("rootArtboardName", ""),
                        "rootArtboardId": data.get("rootArtboardId", ""),
                    "fileName": data.get("fileName", ""),
                    "isMarked": data.get("isMarked", False),
                    "updated_at": time.time(),
                }
            self._send_json({"status": "ok"})

        elif parsed.path == "/api/composition":
            handle_composition(data, self._send_json)

        elif parsed.path == "/api/assets":
            handle_assets(data, self._send_json)

        elif parsed.path == "/api/clear-pending":
            # Plugin 提取失败时清除 pending 状态，可选带 error 文本回填诊断
            err_text = data.get("error", "") or data.get("message", "")
            with _lock:
                pending_request = False
                request_created_at = 0.0
                if err_text:
                    extract_last_error = str(err_text)[:500]
            self._send_json({"status": "ok", "pending": False})

        elif parsed.path == "/api/request-list":
            # Skill 请求 plugin 遍历所有画板
            # 复用 pending_request 通道，通过特殊 nodeId __list_all__ 标识
            with _lock:
                if pending_request and not reclaim_stale_pending_locked():
                    self._send_json({"status": "conflict", "message": "已有请求在处理中"}, 409)
                    return
                pending_request = True
                pending_node_id = "__list_all__"
                request_created_at = time.time()
                artboard_list_data = None
                extract_last_error = ""
            self._send_json({"status": "ok", "pending": True})

        elif parsed.path == "/api/artboard-list":
            # Plugin 回传遍历结果 / 错误
            with _lock:
                pending_request = False
                request_created_at = 0.0
                if "error" in data:
                    artboard_list_data = {"error": data["error"], "total": 0, "artboards": []}
                else:
                    artboard_list_data = {
                        "artboards": data.get("artboards", []),
                        "total": data.get("total", 0),
                        "timestamp": time.time(),
                    }
            self._send_json({"status": "ok"})

        else:
            self._send_json({"error": "not found"}, 404)


def handle_composition(data: dict, respond):
    """处理 /api/composition 请求"""
    global pending_request, request_created_at, latest_data, extract_last_error

    node_id = data.get("nodeId", "")
    if not node_id:
        respond({"error": "missing nodeId"}, 400)
        return

    cache_dir = get_cache_dir(node_id)
    raw_dir = os.path.join(cache_dir, "raw")
    prepared_dir = os.path.join(cache_dir, "figma_extract_prepared")
    drawable_dir = os.path.join(prepared_dir, "drawable-xxhdpi")
    ensure_dir(raw_dir)
    ensure_dir(prepared_dir)
    ensure_dir(drawable_dir)

    # 保存节点树
    tree_path = os.path.join(raw_dir, "composition.json")
    with open(tree_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 保存截图
    screenshot_b64 = data.get("screenshot", "")
    if screenshot_b64:
        screenshot_path = os.path.join(cache_dir, "screenshot.png")
        save_b64_image(screenshot_b64, screenshot_path)

    # 保存元信息
    meta = {
        "nodeId": node_id,
        "fileKey": data.get("fileKey", ""),
        "fileName": data.get("fileName", ""),
        "pageName": data.get("pageName", ""),
        "name": data.get("name", ""),
        "width": data.get("width", 0),
        "height": data.get("height", 0),
        "imageCount": data.get("imageCount", 0),
        "timestamp": time.time(),
    }
    meta_path = os.path.join(raw_dir, "meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 更新全局状态
    with _lock:
        pending_request = False
        request_created_at = 0.0
        extract_last_error = ""
        expected_images = data.get("imageCount", 0)
        latest_data = {
            # 零切图画板不会有 /api/assets 上报，直接就绪，避免 poll_status 空等超时
            "ready": expected_images == 0,
            "node_id": node_id,
            "file_key": data.get("fileKey", ""),
            "file_name": data.get("fileName", ""),
            "page_name": data.get("pageName", ""),
            "name": data.get("name", ""),
            "timestamp": time.time(),
            "expected_images": expected_images,
            "received_images": 0,
        }

    respond({
        "status": "ok",
        "node_id": node_id,
        "cache_dir": cache_dir,
        "images_expected": data.get("imageCount", 0),
    })


def handle_assets(data: dict, respond):
    """处理 /api/assets 请求"""
    global latest_data

    images = data.get("images", [])
    if not images:
        respond({"error": "missing images"}, 400)
        return

    with _lock:
        node_id = latest_data.get("node_id", "")
        if not node_id:
            respond({"status": "ok", "saved": 0, "note": "no active session"})
            return

    cache_dir = get_cache_dir(node_id)
    drawable_dir = os.path.join(cache_dir, "figma_extract_prepared", "drawable-xxhdpi")
    ensure_dir(drawable_dir)

    saved = 0
    for img in images:
        img_id = img.get("id", "")
        b64 = img.get("base64", "") or img.get("data", "")
        if not b64:
            continue
        # 文件名 = img_{imageHash[:12]}.png，与 figma_bridge_to_android.py 保持一致
        # 标准化 nodeId 中的 ':' (如 "1:616") → '_'，避免文件名非法
        img_id_clean = img_id.replace(":", "_")
        img_id_short = img_id_clean[:12] if len(img_id_clean) >= 12 else img_id_clean
        filename = f"img_{img_id_short}.png"
        filepath = os.path.join(drawable_dir, filename)
        save_b64_image(b64, filepath)
        saved += 1

    with _lock:
        latest_data["received_images"] = latest_data.get("received_images", 0) + saved
        expected = latest_data.get("expected_images", 0)
        if latest_data["received_images"] >= expected:
            latest_data["ready"] = True

    respond({"status": "ok", "saved": saved, "node_id": node_id})


def cleanup_expired_cache(max_age_hours: int = 24):
    """清理过期的缓存目录"""
    now = time.time()
    count = 0
    if not os.path.isdir(CACHE_DIR):
        return 0
    for entry in os.listdir(CACHE_DIR):
        path = os.path.join(CACHE_DIR, entry)
        if not os.path.isdir(path):
            continue
        mtime = os.path.getmtime(path)
        if now - mtime > max_age_hours * 3600:
            shutil.rmtree(path, ignore_errors=True)
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description="figma-android bridge server (pull mode)")
    parser.add_argument("--port", type=int, default=7789, help="监听端口 (默认 7789)")
    args = parser.parse_args()

    ensure_dir(CACHE_DIR)
    cleaned = cleanup_expired_cache()
    if cleaned > 0:
        print(f"缓存在清理: {cleaned} 个过期目录 (>{24}h)")
    server = HTTPServer(("127.0.0.1", args.port), BridgeHandler)
    print(f"figma-android bridge server started on http://127.0.0.1:{args.port}")
    print(f"cache: {CACHE_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutdown")
        server.shutdown()


if __name__ == "__main__":
    main()
