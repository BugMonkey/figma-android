#!/usr/bin/env python3
"""
figma_pull.py — 桥模式唯一入口

无 URL 依赖，从 bridge server 拉取 Figma 当前选中画板数据。

用法:
  python3 figma_pull.py [--port 7789] [--node-id <id>] [--force] --project-root <session_workdir>

在当前项目根目录下产出 .figma/figma_extract_{name}_{nodeId}/
--project-root 为必传参数（会话工作目录，.figma/ 缓存落盘位置）。

缓存复用：默认命中「完整且包含目标画板」的缓存时直接复用（秒级返回，不请求插件）；
设计稿已更新或需要重新拉取时加 --force。
"""

import json
import os
import shutil
import subprocess
import sys
import time
import argparse
from urllib.request import Request, urlopen
from urllib.error import URLError


# Windows GBK 终端兼容：强制 stdout/stderr UTF-8
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))

# 插件「空闲但存活」容忍窗口（秒）。
# Figma 插件 iframe 不可见时，Chromium 会把插件 setInterval 节流到约 60s 一次，
# 此时 /api/plugin-status 的 connected（要求 5s 内有轮询）为 False，但插件仍在线，
# 提取请求会在其下一次轮询时被正常消费。该窗口需覆盖一个节流周期并留余量：
# 偏小 → 误判为「插件已断开」直接退出；偏大 → 面板真的关闭时要等更久才报错。
PLUGIN_IDLE_TOLERANCE = 90.0


# ─── HTTP 工具 ───


def http_get(host: str, port: int, path: str, timeout: float = 5.0) -> tuple:
    url = f"http://{host}:{port}{path}"
    req = Request(url, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace").strip()
    except URLError as e:
        return None, str(e.reason)
    except Exception as e:
        return None, str(e)


def http_post(host: str, port: int, path: str, data: dict = None,
              timeout: float = 5.0) -> tuple:
    url = f"http://{host}:{port}{path}"
    body = json.dumps(data or {}, ensure_ascii=False).encode("utf-8")
    req = Request(url, method="POST", data=body,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        return None, str(e.reason)
    except Exception as e:
        return None, str(e)


# ─── 桥服务器 ───


def get_selected_node(port: int = 7789) -> dict:
    """查询当前 Figma 中选中的节点信息（非画板级别）"""
    status, body = http_get("127.0.0.1", port, "/api/selected-node", timeout=3.0)
    if status == 200:
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            pass
    return {"selected": False, "name": "", "id": "", "type": "", "pageName": ""}


def check_bridge_health(port: int = 7789) -> bool:
    status, body = http_get("127.0.0.1", port, "/health", timeout=3.0)
    return status == 200 and body.lower() == "ok"


def check_plugin_connected(port: int = 7789) -> bool:
    """检查 plugin 是否在线（最近 5 秒内有轮询）"""
    status, body = http_get("127.0.0.1", port, "/api/plugin-status", timeout=3.0)
    if status == 200:
        try:
            data = json.loads(body)
            return data.get("connected", False)
        except json.JSONDecodeError:
            pass
    return False


def plugin_last_seen_age(port: int = 7789):
    """返回插件距上次轮询的秒数；服务器不可达或从未轮询过则返回 None。

    与 check_plugin_connected 的区别：后者只判断「5s 内是否有轮询」，
    在 iframe 被节流（约 60s 一轮询）时会误报为断连；本函数用于区分
    「真的没在跑」和「在跑只是轮询慢」。
    """
    status, body = http_get("127.0.0.1", port, "/api/plugin-status", timeout=3.0)
    if status != 200:
        return None
    try:
        last = json.loads(body).get("last_seen")
    except json.JSONDecodeError:
        return None
    if not last:
        return None
    return max(0.0, time.time() - last)


def start_bridge_server(port: int = 7789):
    server_script = os.path.join(SKILL_DIR, "figma_bridge_server.py")
    cmd = [sys.executable, server_script, "--port", str(port)]
    popen_kwargs = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True
    else:
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(cmd, **popen_kwargs)
    deadline = time.time() + 10
    while time.time() < deadline:
        if check_bridge_health(port=port):
            return proc
        time.sleep(0.5)
    return None


def request_extract(port: int = 7789, node_id: str = None, project_root: str = None) -> bool:
    """请求 plugin 提取画板。传 node_id 则按 ID 提取，否则按当前选中"""
    data = {}
    if node_id:
        data["node_id"] = node_id
    if project_root:
        data["project_root"] = project_root
    if node_id:
        status, _ = http_post("127.0.0.1", port, "/api/request-extract-by-id", data=data)
    else:
        status, _ = http_post("127.0.0.1", port, "/api/request-extract", data=data)
    return status == 200


def poll_status(port: int = 7789, interval: float = 3.0,
                max_wait: float = 120.0) -> dict | None:
    """轮询 /api/status 直到数据就绪。

    返回：就绪的 status dict；插件已回填失败原因时返回 {"error": <原因>}；超时返回 None。
    """
    deadline = time.time() + max_wait
    dots = 0
    while time.time() < deadline:
        status, body = http_get("127.0.0.1", port, "/api/status", timeout=5.0)
        if status == 200:
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {}
            if data.get("ready"):
                return data
            # fail-fast：插件提取失败时会立刻回填 extract_last_error，
            # 不检查就会一直轮询到 120s 超时（白等）。
            err = (data.get("extract_last_error") or "").strip()
            if err:
                return {"error": err}
            if dots == 0 and data.get("node_id"):
                print(f"  -> plugin 正在提取: {data.get('name', data.get('node_id', ''))}...")
        dots += 1
        if dots % 4 == 0:
            elapsed = dots * interval
            remaining = max(0, round(max_wait - elapsed))
            print(f"  等待中... ({elapsed:.0f}s, 剩余 {remaining:.0f}s)")
        time.sleep(interval)
    return None


# ─── 缓存复用 ───

CACHE_REQUIRED_FILES = ("android_tree.json", "assets.json", "source_meta.json")


def tree_contains_node(tree: dict, node_id: str) -> bool:
    """树中（含 root 自身）是否存在指定 node_id"""
    if not node_id:
        return False
    stack = [tree.get("root", {})]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        if node.get("node_id") == node_id:
            return True
        stack.extend(node.get("children", []) or [])
    return False


def format_age(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} 秒"
    if seconds < 3600:
        return f"{seconds / 60:.0f} 分钟"
    return f"{seconds / 3600:.1f} 小时"


def find_reusable_cache(project_root: str, want_node_id: str = None,
                        want_root_id: str = None):
    """查找可复用的完整缓存。

    命中条件：
      1. figma_extract_prepared/ 下三个 JSON 齐全
      2. screen.artboard_width_px 存在（旧版适配器产物 dp 基准不可信，不复用）
      3. 树中包含目标：want_node_id（任意子节点）或 want_root_id（根画板）

    返回 (prepared_dir, age_seconds, tree)；无命中返回 None。
    """
    if not want_node_id and not want_root_id:
        return None
    figma_dir = os.path.join(project_root, ".figma")
    if not os.path.isdir(figma_dir):
        return None

    best = None
    for entry in sorted(os.listdir(figma_dir)):
        prepared = os.path.join(figma_dir, entry, "figma_extract_prepared")
        if not all(os.path.isfile(os.path.join(prepared, f)) for f in CACHE_REQUIRED_FILES):
            continue
        tree_path = os.path.join(prepared, "android_tree.json")
        try:
            with open(tree_path, encoding="utf-8") as f:
                tree = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        screen = tree.get("screen") or {}
        if not screen.get("artboard_width_px"):
            continue
        if want_node_id:
            if not tree_contains_node(tree, want_node_id):
                continue
        elif screen.get("artboard_id") != want_root_id:
            continue
        mtime = os.path.getmtime(tree_path)
        if best is None or mtime > best[0]:
            best = (mtime, prepared, tree)

    if not best:
        return None
    return (best[1], time.time() - best[0], best[2])


def write_selected_node(prepared_dir: str, selected_node_info: dict) -> str | None:
    """写入选中节点信息（不定位；定位需 android_tree 就绪后调 enrich_selected_node）"""
    if not selected_node_info.get("selected"):
        return None
    path = os.path.join(prepared_dir, "selected_node.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(selected_node_info, f, indent=2, ensure_ascii=False)
    return path


# ─── 目录工具 ───


# ─── 选中节点定位 ───


def locate_node_in_tree(tree_node: dict, target_id: str = "",
                         target_name: str = "", path: list = None) -> dict | None:
    """
    在 android_tree 节点树中递归搜索匹配节点。
    优先按 node_id 精确匹配，其次按 name 模糊匹配。
    返回 {node, path, view_type, dp} 或 None。
    """
    if path is None:
        path = []

    node_id = tree_node.get("node_id", "")
    name = tree_node.get("name", "")

    # 精确匹配 node_id
    if target_id and node_id == target_id:
        return {
            "match_type": "exact_id",
            "node": tree_node,
            "path": list(path),
            "view_type": tree_node.get("view_type", ""),
            "dp": tree_node.get("dp", {}),
            "android_id": tree_node.get("android_id", ""),
        }

    # 递归子节点
    for child in tree_node.get("children", []):
        current_path = list(path) + [tree_node.get("name", "?")]
        result = locate_node_in_tree(child, target_id, target_name, current_path)
        if result:
            return result

    # 子节点没找到，回到当前节点按 name 模糊匹配（作为兜底）
    if target_name:
        name_lower = name.lower()
        target_lower = target_name.lower()
        if name_lower == target_lower or target_lower in name_lower or name_lower in target_lower:
            return {
                "match_type": "fuzzy_name",
                "node": tree_node,
                "path": list(path),
                "view_type": tree_node.get("view_type", ""),
                "dp": tree_node.get("dp", {}),
                "android_id": tree_node.get("android_id", ""),
            }

    return None


def enrich_selected_node(selected_node_path: str, tree_path: str):
    """
    读取 android_tree.json，在树中定位选中的节点，
    将结果写入 selected_node.json。
    """
    if not os.path.isfile(selected_node_path) or not os.path.isfile(tree_path):
        return

    with open(selected_node_path, encoding="utf-8") as f:
        selected = json.load(f)
    with open(tree_path, encoding="utf-8") as f:
        tree = json.load(f)

    root = tree.get("root", {})
    target_id = selected.get("id", "")
    target_name = selected.get("name", "")

    location = locate_node_in_tree(root, target_id=target_id, target_name=target_name)
    if location:
        selected["tree_location"] = location.get("match_type", "")
        selected["tree_path"] = " / ".join(location["path"]) if location["path"] else root.get("name", "?")
        selected["view_type"] = location.get("view_type", "")
        selected["android_id"] = location.get("android_id", "")
        selected["dp"] = location.get("dp", {})
        # 移除原始 node（太占空间）
        selected.pop("match_type", None)
        selected.pop("node", None)

    with open(selected_node_path, "w", encoding="utf-8") as f:
        json.dump(selected, f, indent=2, ensure_ascii=False)


def compress_screenshot(src_path: str, max_width: int = 360) -> dict | None:
    """
    将截图等比例压缩到最大宽度（默认 360px），覆盖写回。

    截图是供 LLM（Agent）预览画板全貌用的，1080px 宽原图体积大、
    token 消耗高；360px 宽足够看清布局，面积 /9、体积通常降一个量级。
    不改变图片模式（保留 RGBA），用 LANCZOS 重采样保证质量。

    返回 dict:
      {"compressed": True, "before": (w,h), "after": (w,h), "kb_before": x, "kb_after": y}
      {"compressed": False, "reason": "too_small" | "no_pil" | "error"}
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    if not os.path.isfile(src_path):
        return {"compressed": False, "reason": "error"}
    try:
        im = Image.open(src_path)
        w, h = im.size
        if w <= max_width:
            return {"compressed": False, "reason": "too_small"}
        new_h = round(h * max_width / w)
        kb_before = round(os.path.getsize(src_path) / 1024, 1)
        resized = im.resize((max_width, new_h), Image.LANCZOS)
        resized.save(src_path, "PNG", optimize=True)
        kb_after = round(os.path.getsize(src_path) / 1024, 1)
        return {
            "compressed": True,
            "before": (w, h),
            "after": (max_width, new_h),
            "kb_before": kb_before,
            "kb_after": kb_after,
        }
    except Exception:
        return {"compressed": False, "reason": "error"}


def correct_image_dimensions(prepared_dir: str) -> int:
    """
    用实测 PNG 像素覆盖 image 节点的 dp.w/h 和 assets.json 的 w/h。

    Figma 文本节点的 node.width/height（含尾随空行、行盒 padding）可能与
    exportAsync 实际导出的 PNG 像素尺寸不一致，导致 ImageView 用 fitXY 拉伸切图。
    以 PNG 实际尺寸为准修正，位置 x/y 不变（默认左上对齐）。
    """
    try:
        from PIL import Image
    except ImportError:
        return -1

    # export scale（px → dp）
    meta_path = os.path.join(prepared_dir, "source_meta.json")
    scale = 3
    if os.path.isfile(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        scale = meta.get("design", {}).get("coordinate_scale") or 3

    drawable_dir = os.path.join(prepared_dir, "drawable-xxhdpi")
    if not os.path.isdir(drawable_dir):
        return 0

    # 收集 PNG 实际像素尺寸
    png_sizes = {}
    for fname in os.listdir(drawable_dir):
        if not fname.endswith(".png"):
            continue
        try:
            with Image.open(os.path.join(drawable_dir, fname)) as im:
                png_sizes[fname] = (im.size[0], im.size[1])
        except Exception:
            pass

    if not png_sizes:
        return 0

    corrected = 0

    # 修正 android_tree.json 中 image 节点的 dp.w/h
    tree_path = os.path.join(prepared_dir, "android_tree.json")
    if os.path.isfile(tree_path):
        with open(tree_path, encoding="utf-8") as f:
            tree = json.load(f)

        def walk(n):
            nonlocal corrected
            img = n.get("image") or {}
            fname = img.get("file")
            if fname and fname in png_sizes:
                px_w, px_h = png_sizes[fname]
                new_w = round(px_w / scale, 1)
                new_h = round(px_h / scale, 1)
                for dp_key in ("dp", "dp_local"):
                    dp = n.get(dp_key)
                    if isinstance(dp, dict):
                        if abs(dp.get("w", 0) - new_w) > 0.1 or abs(dp.get("h", 0) - new_h) > 0.1:
                            dp["w"] = new_w
                            dp["h"] = new_h
                            if dp_key == "dp":
                                corrected += 1
            for c in n.get("children", []):
                walk(c)

        walk(tree.get("root", {}))
        with open(tree_path, "w", encoding="utf-8") as f:
            json.dump(tree, f, indent=2, ensure_ascii=False)

    # 修正 assets.json 的 w/h
    assets_path = os.path.join(prepared_dir, "assets.json")
    if os.path.isfile(assets_path):
        with open(assets_path, encoding="utf-8") as f:
            assets = json.load(f)
        for asset in assets.get("assets", []):
            fname = asset.get("file")
            if fname and fname in png_sizes:
                px_w, px_h = png_sizes[fname]
                asset["w"] = round(px_w / scale, 1)
                asset["h"] = round(px_h / scale, 1)
        with open(assets_path, "w", encoding="utf-8") as f:
            json.dump(assets, f, indent=2, ensure_ascii=False)

    return corrected


def slugify(text: str) -> str:
    """将中文/特殊字符转为下划线，用于目录名"""
    result = []
    for c in text:
        if c.isalnum() or c in "-_.":
            result.append(c)
        else:
            result.append("_")
    name = "".join(result)
    return name.strip("_") or "unnamed"


# ─── 主流程 ───


def main():
    parser = argparse.ArgumentParser(
        description="桥模式：从 bridge server 拉取 Figma 画板数据",
    )
    parser.add_argument("--port", type=int, default=7789,
                        help="桥服务器端口 (默认 7789)")
    parser.add_argument("--node-id", type=str, default=None,
                        help="按 nodeId 提取根画板，不依赖用户选中状态；"
                             "支持逗号分隔多个（逐个提取，同一画板会命中缓存复用）")
    parser.add_argument("--project-root", type=str, default=None,
                        help="项目根目录（.figma 缓存落盘位置）。默认 os.getcwd()，"
                             "但 Agent 应显式传入会话工作目录，避免受 cd 影响")
    parser.add_argument("--force", action="store_true",
                        help="忽略缓存复用，强制从 Figma 重新提取（设计稿已更新时使用）")
    args = parser.parse_args()

    # project_root 显式传入 > 会话 cwd。os.getcwd() 会受 Agent cd 影响，
    # 若 cwd 落在 skill 目录（可能是符号链接），缓存会跟到 skill 目录。
    if args.project_root:
        project_root = os.path.realpath(args.project_root)
    else:
        project_root = os.path.realpath(os.getcwd())

    # 多个 nodeId：逐个复用本脚本提取（同一画板的后续项会命中缓存复用），
    # 避免 Agent 为多状态画板串行调用多次、重复等待插件轮询。
    node_ids = [s.strip() for s in (args.node_id or "").split(",") if s.strip()]
    if len(node_ids) > 1:
        failed = []
        for idx, nid in enumerate(node_ids, 1):
            cmd = [sys.executable, os.path.abspath(__file__),
                   "--node-id", nid, "--port", str(args.port),
                   "--project-root", project_root]
            if args.force:
                cmd.append("--force")
            print(f"\n{'=' * 60}")
            print(f"[{idx}/{len(node_ids)}] 提取 {nid}")
            print('=' * 60)
            if subprocess.run(cmd).returncode != 0:
                failed.append(nid)
        if failed:
            print(f"\n[!] 以下 nodeId 提取失败: {', '.join(failed)}")
            sys.exit(1)
        sys.exit(0)

    print(f"项目: {project_root}")
    print()

    # ── Step 1: 检查 / 启动桥服务器 ──
    print("[1] 检查桥服务器 (localhost:{}):".format(args.port), end=" ")
    if check_bridge_health(port=args.port):
        print("已在运行")
    else:
        print("正在启动...", end=" ")
        proc = start_bridge_server(port=args.port)
        if proc is None:
            print("失败")
            sys.exit(1)
        print(f"PID {proc.pid}")

    # ── Step 1.5: 检查插件连通性 ──
    print("\n[1.5] 检查插件连通性:", end=" ")
    if check_plugin_connected(port=args.port):
        print("已连接")
    else:
        age = plugin_last_seen_age(port=args.port)
        if age is not None and age < PLUGIN_IDLE_TOLERANCE:
            # 插件仍在线，只是 iframe 不可见被节流：轮询间隔实测可达 60s+。
            # 请求会在其下一次轮询时被消费，继续等待即可，不应判为断连而中断。
            print(f"空闲 (距上次轮询 {age:.0f}s)")
            print("  提示: Figma 插件面板不在前台时，浏览器会把插件轮询节流到约 60s 一次。")
            print("        插件仍在线，提取会在其下一次轮询时被消费，继续等待。")
            print("        将 Figma 窗口置于前台并保持插件面板可见可显著加速。")
        else:
            print("未连接")
            # 区分首次安装 vs 连接断开
            configured = os.path.exists(os.path.expanduser("~/.figma-android/plugin_configured"))
            if configured:
                print("  ERROR: 插件连接已断开 (可能长时间未使用)")
                print("  解决: 在 Figma 中重新打开插件面板")
                print("    Plugins -> Development -> figma-android-bridge")
            else:
                print("  ERROR: Figma 插件未连接到桥服务器")
                print("  请确认:")
                print("    1. Figma 桌面应用已启动")
                print("    2. 已安装 figma-android-bridge 插件")
                print("    3. 插件面板处于打开状态")
            sys.exit(1)

    # ── Step 2: 查询当前选中的节点 ──
    print("\n[2] 查询当前选中节点...")
    selected_node_info = get_selected_node(port=args.port)
    file_name = selected_node_info.get("fileName", "")
    if file_name:
        print(f"  -> 文件: {file_name}")
    if selected_node_info.get("selected"):
        locked_mark = " [🔖 已标记为切图]" if selected_node_info.get("isMarked") else ""
        print(f"  -> 选中: {selected_node_info.get('name', '?')} ({selected_node_info.get('type', '?')}){locked_mark}")
    else:
        print(f"  -> (无选中节点)")

    # ── Step 2.6: 缓存复用（默认开启，--force 跳过） ──
    if not args.force:
        hit = find_reusable_cache(
            project_root,
            want_node_id=args.node_id,
            want_root_id=None if args.node_id else (selected_node_info.get("rootArtboardId") or None),
        )
        if hit:
            prepared_dir, age_s, tree = hit
            screen = tree.get("screen", {})
            print(f"\n[2.6] 命中已有缓存（{format_age(age_s)}前提取，未请求 Figma）")
            print(f"  -> 画板: {tree.get('root', {}).get('name', '?')} ({screen.get('artboard_id', '?')})")
            print(f"  -> 目录: {prepared_dir}/")
            sel_path = write_selected_node(prepared_dir, selected_node_info)
            if sel_path:
                enrich_selected_node(sel_path, os.path.join(prepared_dir, "android_tree.json"))
            print(f"  设计稿已更新需重新拉取时: 加 --force")
            return

    # ── Step 2.5: 请求提取 ──
    if args.node_id:
        print(f"\n[2.5] 请求按 nodeId 提取: {args.node_id}")
    else:
        print("\n[2.5] 请求 Figma 插件提取数据...")
        print("  请确认 Figma 插件面板已打开，且已选中目标画板")
    if not request_extract(port=args.port, node_id=args.node_id, project_root=project_root):
        print("  ERROR: 无法发送提取请求")
        sys.exit(1)
    print("  -> 请求已发送，等待插件提取...")

    # ── Step 3: 轮询 ──
    # 节流态下插件要等到下一次轮询才会消费请求（可达 60s+），提取本身也耗时，
    # 因此等待窗口需覆盖「一次节流轮询 + 提取」，不能沿用 120s。
    print(f"\n[3] 等待数据就绪... (最多 240s)")
    status_data = poll_status(port=args.port, interval=3.0, max_wait=240.0)
    if status_data and status_data.get("error"):
        print(f"\n  ERROR: 提取失败: {status_data['error']}")
        print("  处理建议:")
        print("    1. 按上面的错误文本处理（如 nodeId 无效 / 类型不符 / 面板未打开）")
        print("    2. 若错误反复出现，请用户在 Figma 中关闭并重新打开插件面板后重试")
        sys.exit(1)
    if not status_data:
        print("\n  ERROR: 超时")
        print("  请确认:")
        print("    1. Figma 插件已正确运行")
        print("    2. 已在 Figma 中选中画板 (Frame/Component)")
        print("    3. 插件面板处于打开状态")
        sys.exit(1)

    node_id = status_data.get("node_id", "")
    name = status_data.get("name", "unnamed")
    print(f"  -> 数据就绪: {name} ({node_id})")

    # ── Step 4: 读取原始数据（server 已写入项目 .figma/） ──
    safe_id = node_id.replace(":", "_")
    plugin_cache_dir = os.path.join(project_root, ".figma", f"figma_extract_plugin_{safe_id}")
    composition_path = os.path.join(plugin_cache_dir, "raw", "composition.json")
    if not os.path.isfile(composition_path):
        print(f"\n  ERROR: 未找到 composition.json: {composition_path}")
        sys.exit(1)

    # 输出目录：使用 文件名 + 画板名 + nodeId，防止多项目缓存错乱
    file_name = status_data.get("file_name", "")
    page_name = status_data.get("page_name", "")
    fname_slug = slugify(file_name) if file_name else ""
    pname_slug = slugify(page_name) if page_name else ""
    parts = [p for p in [fname_slug, slugify(name), safe_id] if p]
    dir_suffix = "_".join(parts)
    output_dir = os.path.join(
        project_root, ".figma", f"figma_extract_{dir_suffix}")
    prepared_dir = os.path.join(output_dir, "figma_extract_prepared")
    os.makedirs(prepared_dir, exist_ok=True)



    # ── Step 4.5: 保存原始选中节点信息（含在树中的定位） ──
    selected_node_path = write_selected_node(prepared_dir, selected_node_info)
    if selected_node_info.get("selected"):
        print(f"\n[4.5] 选中节点: {selected_node_info.get('name', '?')} ({selected_node_info.get('type', '?')})")
        if selected_node_info.get("parentName"):
            print(f"     父画板: {selected_node_info['parentName']}")

    # ── Step 5: 适配器 ──
    print(f"\n[5] 转换 -> android_tree.json ...")
    print(f"  输出: {prepared_dir}/")
    adapter_script = os.path.join(SKILL_DIR, "figma_bridge_to_android.py")
    result = subprocess.run(
        [sys.executable, adapter_script, composition_path,
         "--output-dir", prepared_dir],
        capture_output=True, text=True, timeout=60,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        print(f"  ERROR: figma_bridge_to_android.py 失败 (exit={result.returncode})")
        print(f"  stderr: {result.stderr.strip()}")
        sys.exit(1)
    for line in result.stdout.strip().split("\n"):
        if line.strip():
            print(f"  {line.strip()}")

    # ── Step 5.5: 在 android_tree 中定位选中节点 ──
    if selected_node_info.get("selected"):
        tree_path = os.path.join(prepared_dir, "android_tree.json")
        enrich_selected_node(selected_node_path, tree_path)
        with open(selected_node_path, encoding="utf-8") as f:
            enriched = json.load(f)
        location = enriched.get("tree_location", "")
        tree_path_str = enriched.get("tree_path", "")
        if tree_path_str:
            print(f"\n[5.5] 选中节点在树中的位置: {tree_path_str}")
            print(f"       view_type: {enriched.get('view_type', '?')}, "
                  f"android_id: {enriched.get('android_id', '?')}, "
                  f"dp: {enriched.get('dp', {})}")

    # ── Step 6: 拷贝截图 ──
    print(f"\n[6] 拷贝截图 ...")
    plugin_screenshot = os.path.join(plugin_cache_dir, "screenshot.png")
    output_screenshot = os.path.join(output_dir, "screenshot.png")
    if os.path.isfile(plugin_screenshot):
        shutil.copy2(plugin_screenshot, output_screenshot)
        size_kb = round(os.path.getsize(output_screenshot) / 1024, 1)
        print(f"  -> screenshot.png: {size_kb} KB")
        # 截图供子 agent 读图用，压缩到 360px 宽可显著降低读图 token；
        # 不装 PIL 则保留原图。
        info = compress_screenshot(output_screenshot)
        if info and info.get("compressed"):
            print(f"  -> 压缩: {info['before'][0]}x{info['before'][1]} "
                  f"-> {info['after'][0]}x{info['after'][1]} "
                  f"({info['kb_before']}KB -> {info['kb_after']}KB)")
        elif info is None:
            print(f"  -> 压缩跳过 (未安装 PIL，保留原图)")
    else:
        print(f"  -> (无截图)")

    # ── Step 7: 拷贝切图 ──
    print(f"\n[7] 拷贝切图 ...")
    plugin_drawable_dir = os.path.join(plugin_cache_dir, "figma_extract_prepared", "drawable-xxhdpi")
    output_drawable_dir = os.path.join(prepared_dir, "drawable-xxhdpi")
    if os.path.isdir(plugin_drawable_dir):
        os.makedirs(output_drawable_dir, exist_ok=True)
        png_count = 0
        for fname in os.listdir(plugin_drawable_dir):
            if fname.endswith(".png"):
                src = os.path.join(plugin_drawable_dir, fname)
                dst = os.path.join(output_drawable_dir, fname)
                shutil.copy2(src, dst)
                png_count += 1
        print(f"  -> {png_count} 个 PNG")
    else:
        print(f"  -> (无切图)")

    # ── Step 7.5: 用实测 PNG 像素修正 image 节点尺寸 ──
    print(f"\n[7.5] 校正切图尺寸 ...")
    corrected = correct_image_dimensions(prepared_dir)
    if corrected == -1:
        print(f"  -> (跳过: 未安装 PIL)")
    else:
        print(f"  -> 修正 {corrected} 个 image 节点的 w/h")

    # ── Step 8: 清理缓存 (中转数据用完即删) ──
    print(f"\n[8] 清理缓存 ...")
    if os.path.isdir(plugin_cache_dir):
        shutil.rmtree(plugin_cache_dir)
        print(f"  -> 已删除: {plugin_cache_dir}")
    else:
        print(f"  -> (无缓存)")

    # ── 完成 ──
    print(f"\n{'='*60}")
    print("完成!")
    if file_name:
        print(f"  文件: {file_name}  |  节点: {name}")
    print(f"  android_tree.json:      {prepared_dir}/android_tree.json")
    print(f"  source_meta.json:       {prepared_dir}/source_meta.json")
    print(f"  assets.json:            {prepared_dir}/assets.json")
    if selected_node_info.get("selected"):
        print(f"  selected_node.json:     {prepared_dir}/selected_node.json")
        with open(selected_node_path, encoding="utf-8") as f:
            enriched = json.load(f)
        if enriched.get("tree_path"):
            print(f"     ├─ tree_path:        {enriched['tree_path']}")
            print(f"     ├─ view_type:        {enriched.get('view_type', '?')}")
            print(f"     ├─ android_id:       {enriched.get('android_id', '?')}")
            print(f"     └─ dp:               {enriched.get('dp', {})}")
    print(f"  screenshot:             {output_screenshot} (360px, 全貌预览/子 agent 读图)")
    print()
    print(f"  切图: cp {prepared_dir}/drawable-xxhdpi/*.png <module>/src/main/res/drawable-xxhdpi/")
    print(f"        <module> 按宿主项目实际承载模块替换（如 app / mod_trade）")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
