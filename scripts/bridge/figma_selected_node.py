#!/usr/bin/env python3
"""
figma_selected_node.py — 查询 Figma 当前选中的节点信息

轻量脚本，不走完整提取流程，Agent 可随时调用查询用户选中的节点。

用法:
  python3 figma_selected_node.py                          # 查询当前选中节点（依赖桥服务器）
  python3 figma_selected_node.py --node-id <id>           # 按 nodeId 从缓存查询，不依赖桥服务器
  python3 figma_selected_node.py --node-id <id> --root-id <rootId>  # 在指定根画板的缓存中查询
  python3 figma_selected_node.py --enrich <tree_dir>      # 查询+在指定 android_tree 中定位
  python3 figma_selected_node.py --port 7789              # 指定桥服务器端口

输出:
  --node-id 模式（缓存锚定）:
  - 缓存中的节点名 / node_id / view_type / android_id / dp 坐标
  - style（背景/渐变/文字色/圆角/字号/描边/不透明度）
  - 切图文件名 image.file + 尺寸（"这个节点对应哪个 PNG"的直接答案）
  - 子节点列表（同 --enrich 输出，含切图文件名与 style）

  默认模式（桥服务器查询）:
  - 桥服务器状态
  - 插件连通性
  - 当前选中的节点名 / 类型 / 父画板

  --enrich 模式下额外输出:
  - tree_path（节点树中的层级位置）
  - view_type（Android View 类型）
  - android_id（生成的 Android ID）
  - dp 坐标
"""

import json
import os
import subprocess
import sys
import time
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
CACHE_DIR = os.path.expanduser("~/.figma-android/cache")

# 项目根目录（.figma 缓存位置）。由 --project-root 显式传入，避免受 os.getcwd()
# 受 Agent cd / skill 符号链接影响。为 None 时回退 os.getcwd()。
PROJECT_ROOT = None


def project_root() -> str:
    """返回解析后的项目根目录（realpath）"""
    if PROJECT_ROOT:
        return os.path.realpath(PROJECT_ROOT)
    return os.path.realpath(os.getcwd())


def http_get(host: str, port: int, path: str, timeout: float = 5.0) -> tuple:
    url = f"http://{host}:{port}{path}"
    try:
        with urlopen(Request(url, method="GET"), timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace").strip()
    except URLError as e:
        return None, str(e.reason)
    except Exception as e:
        return None, str(e)


def check_bridge_health(port: int = 7789) -> bool:
    status, body = http_get("127.0.0.1", port, "/health", timeout=3.0)
    return status == 200 and body.lower() == "ok"


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


def query_selected_node(port: int = 7789) -> dict:
    """查询 /api/selected-node"""
    status, body = http_get("127.0.0.1", port, "/api/selected-node", timeout=3.0)
    if status == 200:
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            pass
    return {"selected": False, "error": body if body else "no response"}


def query_plugin_status(port: int = 7789) -> dict:
    """查询插件轮询状态"""
    status, body = http_get("127.0.0.1", port, "/api/plugin-status", timeout=3.0)
    if status == 200:
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            pass
    return {"connected": False}


def find_latest_enriched(path: str = None) -> dict | None:
    """
    搜索最近的 selected_node.json，
    优先用 --enrich 指定的目录，否则搜索 .figma/figma_extract_* 目录。
    """
    if path:
        candidates = [path]
    else:
        root = project_root()
        figma_root = os.path.join(root, ".figma")
        if not os.path.isdir(figma_root):
            return None
        # 按 mtime 排序，取最新的
        dirs = []
        for entry in os.listdir(figma_root):
            full = os.path.join(figma_root, entry)
            if full.startswith(os.path.join(figma_root, "figma_extract_")) and os.path.isdir(full):
                prepared = os.path.join(full, "figma_extract_prepared")
                sne = os.path.join(prepared, "selected_node.json")
                if os.path.isfile(sne):
                    dirs.append((os.path.getmtime(sne), sne))
        if not dirs:
            return None
        dirs.sort(key=lambda x: x[0], reverse=True)
        candidates = [d[1] for d in dirs[:3]]  # 查最近 3 次缓存

    for p in candidates:
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("selected"):
                return data
    return None


def find_android_tree(path_or_dir: str) -> dict | None:
    """从 selected_node.json 路径或 prepared 目录定位 android_tree.json"""
    if os.path.isdir(path_or_dir):
        tree_path = os.path.join(path_or_dir, "android_tree.json")
    else:
        tree_path = os.path.join(os.path.dirname(path_or_dir), "android_tree.json")
    if os.path.isfile(tree_path):
        with open(tree_path, encoding="utf-8") as f:
            return json.load(f)
    return None


def scan_all_caches_for_node(node_id: str) -> tuple:
    """
    在所有 .figma/ 缓存中扫描包含指定 nodeId 的 android_tree.json。
    返回 (prepared_dir, root_info_dict) 或 (None, None)。
    """
    if not node_id:
        return None, None
    root = project_root()
    figma_dir = os.path.join(root, ".figma")
    if not os.path.isdir(figma_dir):
        return None, None

    for entry in os.listdir(figma_dir):
        prep = os.path.join(figma_dir, entry, "figma_extract_prepared")
        tree_path = os.path.join(prep, "android_tree.json")
        if not os.path.isfile(tree_path):
            continue
        try:
            with open(tree_path, encoding="utf-8") as f:
                tree = json.load(f)
            root = tree.get("root", {})

            def exists(n, tid):
                if n.get("node_id") == tid:
                    return True
                for c in n.get("children", []):
                    if exists(c, tid):
                        return True
                return False

            if exists(root, node_id):
                dp = root.get("dp", {})
                return prep, {
                    "name": root.get("name", "?"),
                    "node_id": root.get("node_id", ""),
                    "dp": dp,
                    "cache_dir": prep,
                }
        except Exception:
            pass
    return None, None


# style 白名单：与 rules/android-tree-guide.md 的"能回答什么"字段表对齐。
# border_color / border_width 是线性图标描边的唯一来源，gradient_colors / opacity
# 无法由其他字段推导，缺一个 Agent 就只能去手工解析 JSON。effects=阴影/模糊，由 figma_bridge_to_android.py 注入，此前被 STYLE_KEYS 漏了。
STYLE_KEYS = (
    "background", "gradient_colors", "text_color", "corner_radius_dp",
    "font_size_sp", "border_color", "border_width", "opacity", "effects",
)


def image_file_of(node: dict) -> str:
    """取节点的切图文件名（image.file）。无切图为空串。

    export_as_image 节点由适配器写入 image.file（img_<nodeId>.png，节点寻址）；
    IMAGE fill 节点写入 image.file（img_<imageHash>.png，内容寻址）。旧版产物可能
    只有 export_as_image 标记而没有 image 字段，此时返回空串由调用方提示"未记录"。
    """
    img = node.get("image")
    if isinstance(img, dict):
        return img.get("file", "") or ""
    return ""


def style_parts(style: dict) -> str:
    """把 style 按白名单拍平成一行（无命中字段返回空串）"""
    if not style:
        return ""
    parts = []
    for k in STYLE_KEYS:
        if k in style:
            v = style[k]
            if isinstance(v, list):
                v = "/".join(str(x) for x in v)
            parts.append(f"{k}={v}")
    return ", ".join(parts)


def image_tag(node: dict) -> str:
    """切图标记 + 文件名的统一写法，供列表和详情共用"""
    if node.get("image_file"):
        return f"[IMG] -> {node['image_file']}"
    if node.get("is_image"):
        return "[IMG] -> (未记录文件名)"
    return ""


def find_nodes(tree: dict, node_id: str = "") -> list:
    """在树中搜索匹配 node_id 的节点，返回列表"""
    results = []
    root = tree.get("root", {})

    def walk(n, path):
        cur_path = path + [n.get("name", "?")]
        if node_id and n.get("node_id") == node_id:
            dp = n.get("dp", {})
            local = n.get("dp_local", {})
            is_image = n.get("image") is not None or n.get("export_as_image") is True
            results.append({
                "name": n.get("name", "?"),
                "node_id": n.get("node_id", ""),
                "view_type": n.get("view_type", "?"),
                "android_id": n.get("android_id", ""),
                "text": n.get("text", ""),
                "dp": dp,
                "dp_local": local,
                "path": " / ".join(cur_path),
                "depth": len(cur_path),
                "is_image": is_image,
                "image_file": image_file_of(n),
                "children": n.get("children", []),
                "style": n.get("style", {}) or {},
            })
        for c in n.get("children", []):
            walk(c, cur_path)

    walk(root, [])
    return results


def list_children(tree: dict, target_id: str) -> list:
    """在 android_tree 中定位节点并返回其子节点列表"""
    def walk(n):
        if n.get("node_id") == target_id:
            children = n.get("children", [])
            result = []
            for c in children:
                dp = c.get("dp", {})
                style = c.get("style", {}) or {}
                is_image = c.get("image") is not None or c.get("export_as_image")
                result.append({
                    "name": c.get("name", "?"),
                    "view_type": c.get("view_type", "?"),
                    "android_id": c.get("android_id", "?"),
                    "dp": dp,
                    "text": c.get("text", ""),
                    "is_image": is_image,
                    "image_file": image_file_of(c),
                    "style": style,
                })
            return result
        for c in n.get("children", []):
            r = walk(c)
            if r is not None:
                return r
        return None
    return walk(tree.get("root", {}))


def _load_children_from_cache(node_id: str, enrich_path: str = None) -> list | None:
    """从已有的 android_tree.json 缓存中查询子节点"""
    candidates = []
    if enrich_path and os.path.isfile(enrich_path):
        candidates.append(enrich_path)

    root = project_root()
    figma_root = os.path.join(root, ".figma")
    if os.path.isdir(figma_root):
        for entry in os.listdir(figma_root):
            full = os.path.join(figma_root, entry)
            if full.startswith(os.path.join(figma_root, "figma_extract_")) and os.path.isdir(full):
                prepared = os.path.join(full, "figma_extract_prepared")
                tree_path = os.path.join(prepared, "android_tree.json")
                if os.path.isfile(tree_path):
                    candidates.append(prepared)

    if not candidates:
        return None

    for prepared_dir in candidates:
        tree = find_android_tree(prepared_dir)
        if tree:
            result = list_children(tree, node_id)
            if result is not None:
                return result
    return None


def _extract_root_and_get_children(port: int, root_id: str, target_id: str) -> list | None:
    """调 figma_pull.py --node-id 提取根画板，完成后从缓存读子节点"""
    pull_script = os.path.join(SKILL_DIR, "figma_pull.py")
    print(f"  -> 调 figma_pull.py --node-id {root_id}")
    cmd = [sys.executable, pull_script, "--port", str(port), "--node-id", root_id]
    if PROJECT_ROOT:
        cmd += ["--project-root", PROJECT_ROOT]
    result = subprocess.run(
        cmd,
        capture_output=True, text=True, timeout=180,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        print(f"  [!] figma_pull.py 失败 (exit={result.returncode})")
        return None
    print(f"  -> 提取完成")
    return _load_children_from_cache(target_id)


def main():
    port = 7789
    enrich_path = None
    anchor_node_id = None
    anchor_root_id = None

    # 解析参数
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        elif args[i] == "--enrich" and i + 1 < len(args):
            enrich_path = args[i + 1]
            i += 2
        elif args[i] == "--node-id" and i + 1 < len(args):
            anchor_node_id = args[i + 1]
            i += 2
        elif args[i] == "--root-id" and i + 1 < len(args):
            anchor_root_id = args[i + 1]
            i += 2
        elif args[i] == "--project-root" and i + 1 < len(args):
            global PROJECT_ROOT
            PROJECT_ROOT = args[i + 1]
            i += 2
        else:
            # 未知参数硬失败：静默吞参只会退化成错误锚定的查询
            print(f"[-] 未知参数: {args[i]}")
            print(__doc__.strip())
            sys.exit(2)

    # --node-id 模式：缓存锚定，跳过桥服务器查询
    if anchor_node_id:
        print("=" * 56)
        print(f"  Figma 缓存节点查询 (锚定模式)")
        print("=" * 56)
        print()
        print(f"  查询 node_id: {anchor_node_id}")
        if anchor_root_id:
            print(f"  限定根画板:  {anchor_root_id}")
        print()

        # 在缓存中查找节点
        root_id_for_search = anchor_root_id

        # 如果指定了 root-id，只搜索该根画板的缓存
        if root_id_for_search:
            safe_id = root_id_for_search.replace(":", "_")
            root = project_root()
            figma_root = os.path.join(root, ".figma")
            target_prep = None
            if os.path.isdir(figma_root):
                for entry in os.listdir(figma_root):
                    if safe_id in entry:
                        prep = os.path.join(figma_root, entry, "figma_extract_prepared")
                        if os.path.isfile(os.path.join(prep, "android_tree.json")):
                            target_prep = prep
                            break
            if not target_prep:
                print(f"  [!] 未找到根画板 {root_id_for_search} 的缓存")
                print(f"     请确认已提取该画板数据")
                sys.exit(1)

            tree = find_android_tree(target_prep)
            if tree:
                children = list_children(tree, anchor_node_id)
                root_info = {"name": tree.get("root", {}).get("name", "?"), "node_id": tree.get("root", {}).get("node_id", "")}
            else:
                print(f"  [!] android_tree.json 读取失败: {target_prep}")
                sys.exit(1)
        else:
            # 未指定 root-id：扫描所有缓存
            scanned, root_info = scan_all_caches_for_node(anchor_node_id)
            if not scanned:
                print(f"  [!] 在所有缓存中未找到节点 {anchor_node_id}")
                print(f"     请先提取该画板数据")
                sys.exit(1)
            tree = find_android_tree(scanned)
            children = list_children(tree, anchor_node_id) if tree else None
            print(f"  定位到缓存: {scanned}/")
            print(f"  根画板:     {root_info['name']} ({root_info['node_id']})")
            print()

        if tree:
            # 查找节点自身信息
            results = find_nodes(tree, node_id=anchor_node_id)
            if results:
                n = results[0]
                print(f"  [✓] 节点信息:")
                print(f"      ├─ 名称:        {n['name']}")
                print(f"      ├─ node_id:     {n['node_id']}")
                print(f"      ├─ view_type:   {n['view_type']}")
                print(f"      ├─ android_id:  {n['android_id']}")
                dp = n.get("dp", {})
                print(f"      ├─ dp(x,y):     ({dp.get('x', '?')}, {dp.get('y', '?')})")
                print(f"      ├─ dp(w,h):     {dp.get('w', '?')} x {dp.get('h', '?')}")
                if n.get("text"):
                    print(f"      ├─ 文本:        {n['text'][:40]}")
                sp = style_parts(n.get("style", {}))
                if sp:
                    print(f"      ├─ style:       {sp}")
                # 切图文件名是"这个节点对应哪个 PNG"的唯一答案，必须直接给出
                if n.get("image_file"):
                    print(f"      ├─ 切图:        {n['image_file']} "
                          f"(drawable-xxhdpi, {dp.get('w', '?')}x{dp.get('h', '?')}dp)")
                elif n.get("is_image"):
                    print(f"      ├─ [IMG] 标记但无 image.file（旧版产物，重跑提取可补全）")
                print(f"      └─ 路径:        {n['path']}")
                print()

        # 输出子节点列表（同 --enrich 模式）
        if children is not None:
            print(f"  ── 子节点列表 ──")
            if not children:
                print(f"     (无子节点)")
            else:
                for i, c in enumerate(children):
                    tag = image_tag(c)
                    text = f'"{c["text"][:16]}"' if c.get("text") else ""
                    line = (f"     {i+1:>2}. {c['view_type']:<16} {c['name']:<24} "
                            f"({c['dp'].get('w',0)}x{c['dp'].get('h',0)}dp) {tag} {text}")
                    print(line.rstrip())
                    csp = style_parts(c.get("style", {}))
                    if csp:
                        print(f"         style: {csp}")
        sys.exit(0)

    # 默认模式：桥服务器查询（原有逻辑）
    print("=" * 56)
    print(f"  Figma 选中节点查询")
    print("=" * 56)
    print()

    # 1. 检查桥服务器
    if not check_bridge_health(port=port):
        print(f"  [!] 桥服务器 localhost:{port} 未运行，正在启动...")
        proc = start_bridge_server(port=port)
        if proc is None:
            print(f"  [!] 启动失败")
            sys.exit(1)
        print(f"  [✓] 已启动 (PID {proc.pid})")
    else:
        print(f"  [✓] 桥服务器 localhost:{port} 运行中")

    # 2. 插件连通性
    plugin_status = query_plugin_status(port=port)
    if plugin_status.get("connected"):
        print(f"  [✓] Figma 插件已连接")
    else:
        print(f"  [!] Figma 插件未连接")
        print(f"       请打开 Figma 插件面板")
        print()

    # 3. 查询选中节点（含 stale 检查）
    print()
    node = query_selected_node(port=port)

    if not node.get("selected"):
        print(f"  [-] Figma 中未选中节点")
        if enrich_path:
            enriched = find_latest_enriched(enrich_path)
        else:
            enriched = find_latest_enriched()
        if enriched:
            print()
            print(f"  ── 最近一次有记录的选中节点 ──")
            print(f"     名称:        {enriched.get('name', '?')}")
            print(f"     类型:        {enriched.get('type', '?')}")
            if enriched.get("parentName"):
                print(f"     所属画板:    {enriched['parentName']}")
            root_id = enriched.get("rootArtboardId", "")
            root_name = enriched.get("rootArtboardName", "")
            if root_id:
                print(f"     根画板:      {root_name} ({root_id})")
            if enriched.get("tree_path"):
                print(f"     树中位置:    {enriched['tree_path']}")
                print(f"     View类型:    {enriched.get('view_type', '?')}")
                print(f"     Android ID:  {enriched.get('android_id', '?')}")
                dp = enriched.get("dp", {})
                if dp:
                    print(f"     dp坐标:      ({dp.get('x', '?')}, {dp.get('y', '?')}) {dp.get('w', '?')}x{dp.get('h', '?')}")
        sys.exit(0)

    # 格式化输出
    parent_id = node.get("parentId", "")
    node_id = node.get("id", "")
    root_id = node.get("rootArtboardId", "")
    root_name = node.get("rootArtboardName", "")
    # 根画板判定：自己是整个层级的顶级 FRAME（rootArtboardId 为自己或为空）
    is_root = (not root_id) or (root_id == node_id)

    print(f"  [\u2713] 当前选中节点:")
    print(f"      {chr(0x2500) * 48}")
    print(f"      名称:        {node.get('name', '?')}")
    print(f"      Figma ID:    {node_id}")
    print(f"      类型:        {node.get('type', '?')}")
    if node.get("pageName"):
        print(f"      页面:        {node['pageName']}")
    print(f"      选中数:      {node.get('count', 1)}")
    if not is_root:
        # 子节点：显示直接父级 + 根画板链
        if node.get("parentName"):
            print(f"      所属画板:    {node['parentName']} ({parent_id})")
        if root_name and root_name != node.get("parentName"):
            print(f"      根画板:      {root_name} ({root_id})")
    else:
        print(f"      所属画板:    (无，选中即根画板)")
    print(f"      {chr(0x2500) * 48}")

    # 4. 尝试从已有的 android_tree.json 缓存中查询子节点
    child_list = _load_children_from_cache(node_id, enrich_path)

    # 5. 无缓存且知道根画板 → 自动提取根画板
    if child_list is None and root_id and root_id != node_id:
        print()
        print(f"  [*] 无缓存数据，正在自动提取根画板: {root_name} ({root_id})...")
        child_list = _extract_root_and_get_children(port, root_id, node_id)
        # 提取完后重新判定，如果是根画板则通过 enrich 再查一遍
        if child_list is None:
            print(f"  [!] 自动提取失败，无法获取子节点信息")
            sys.exit(1)

    # 6. 输出子节点列表
    if child_list is not None:
        print()
        print(f"  ── 子节点列表 ──")
        if not child_list:
            print(f"     (无子节点)")
        else:
            for i, c in enumerate(child_list):
                tag = image_tag(c)
                text = f'"{c["text"][:16]}"' if c.get("text") else ""
                line = (f"     {i+1:>2}. {c['view_type']:<16} {c['name']:<24} "
                        f"({c['dp'].get('w',0)}x{c['dp'].get('h',0)}dp) {tag} {text}")
                print(line.rstrip())
                csp = style_parts(c.get("style", {}))
                if csp:
                    print(f"         style: {csp}")

    if not is_root:
        print()
        print(f"  [!] 当前选中非根画板 (根: {root_name} {root_id})")
        print(f"      Agent: 需要提取时调 figma_pull.py --node-id {root_id} --project-root \"$(pwd)\"")
    elif child_list is None:
        print()
        print(f"  [!] 未找到缓存且无法自动提取")
        print(f"      提示: 运行 figma_pull.py --project-root \"$(pwd)\" 完成提取后会自动定位")

    print()


if __name__ == "__main__":
    main()
