#!/usr/bin/env python3
"""
figma_query_node.py — 在已提取的 android_tree.json 中快速查询节点

用法:
  python3 figma_query_node.py --name 隐私设置          # 按图层名搜索
  python3 figma_query_node.py --name 隐私 --fuzzy      # 图层名模糊匹配
  python3 figma_query_node.py --text 选择收货地址      # 按界面文字搜索（图层名与文字不一致时用）
  python3 figma_query_node.py --id 1:1234               # 按 node_id 精确搜索
  python3 figma_query_node.py --id 1:1234 --children   # 搜索 + 列出直接子节点
  python3 figma_query_node.py --id 1:1234 --deep 2      # 搜索 + 列出 2 级子节点
  python3 figma_query_node.py --id 1:1234 --deep 2 --styles   # 子节点附带精简样式
  python3 figma_query_node.py --id 1:805 --children --deep 2 --latest --find-root
  python3 figma_query_node.py --type ImageView          # 按 View 类型筛选
  python3 figma_query_node.py --dir <tree_dir>           # 指定 android_tree 目录
  python3 figma_query_node.py --latest --root-id 1:48    # 使用指定根画板的缓存目录
  python3 figma_query_node.py --project-root ~/proj --list-caches   # 列出项目下所有缓存
  python3 figma_query_node.py --project-root ~/proj --list-caches --match 闲置  # 按画板名过滤缓存
  python3 figma_query_node.py --assets --md5             # 列出切图清单（含 PNG 内容 md5）
  python3 figma_query_node.py --assets --latest --root-id 1:48   # 指定画板的切图清单

--project-root: .figma/ 缓存所在的项目根。Agent 应显式传入会话工作目录；
                不传则退回 os.getcwd()（cwd 在 skill 目录时会找不到缓存）。
--root-id:      显式指定根画板时**不会**回退到"最新缓存"，未命中直接报错并列出可用缓存，
                避免多会话/多画板场景下静默取到别的画板。

--find-root: 配合 --id 使用。在所有缓存(非最新)中扫描包含该 nodeId 的树，输出所属根画板信息。
当用户直接给 nodeId 但不知道它属于哪个根画板时，用此参数自动定位。
--id 在自动选择最新缓存（未显式 --dir/--root-id/--latest）且最新缓存不含该节点时，
也会自动扫描其他缓存定位所属画板，避免多画板同名场景读错板。

--children/--deep: 子节点每行附带 node_id 与绝对坐标，可直接复用于后续 --id 查询。
--styles: 配合 --children/--deep，每个子节点追加一行精简 style
          （background/text_color/corner_radius_dp/font_size_sp/font_weight/text_style/border_*/gradient_colors/opacity/effects）。
--style-raw: 命中节点额外输出完整 style JSON，用于排查白名单字段缺失（如 effects / 未采集属性）。
--text:  按节点 text 内容做大小写不敏感子串搜索。图层名与界面文字不一致时用它。

--list-caches: 列出 .figma/ 下所有缓存。--match <关键词> 按画板名 / 画板 nodeId / 缓存目录名
               做大小写不敏感的子串过滤，画板多时用来快速确认目标画板是否已提取。
--assets: 列出切图清单（node_id / 图层名 / 文件名 / dp 尺寸），数据源是 assets.json。
          加 --md5 附加每个 PNG 的内容 md5（文件缺失标 missing）。回答"这个画板的切图有哪些"
          以及"两个画板的同名切图内容是否一致"时用它，不要去手工解析 assets.json。

输出:
  匹配节点在树中的完整路径 + view_type + android_id + dp 坐标 + 切图文件名
"""

import json
import os
import sys
import glob
import hashlib
import time


# Windows GBK 终端兼容：强制 stdout/stderr UTF-8
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


# 项目根（.figma/ 缓存位置）。Agent 应显式传 --project-root，
# 否则退回 os.getcwd()——cwd 落在 skill 目录时会找不到用户项目的缓存。
PROJECT_ROOT = os.path.realpath(os.getcwd())


def set_project_root(path: str = None) -> None:
    global PROJECT_ROOT
    PROJECT_ROOT = os.path.realpath(path) if path else os.path.realpath(os.getcwd())


def load_tree_silent(tree_dir: str) -> dict | None:
    """静默读取 android_tree.json（失败返回 None，不打印）"""
    try:
        with open(os.path.join(tree_dir, "android_tree.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def iter_caches() -> list:
    """遍历 .figma/ 下所有含 android_tree.json 的缓存，返回 [(entry, prepared_dir)]"""
    figma_dir = os.path.join(PROJECT_ROOT, ".figma")
    if not os.path.isdir(figma_dir):
        return []
    caches = []
    for entry in sorted(os.listdir(figma_dir)):
        prep = os.path.join(figma_dir, entry, "figma_extract_prepared")
        if os.path.isfile(os.path.join(prep, "android_tree.json")):
            caches.append((entry, prep))
    return caches


def age_str(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} 秒"
    if seconds < 3600:
        return f"{seconds / 60:.0f} 分钟"
    return f"{seconds / 3600:.1f} 小时"


def list_caches(match: str = "") -> None:
    """打印 .figma/ 下的缓存清单（画板名 / nodeId / 提取时间）

    match 非空时按 画板名 / 画板 nodeId / 缓存目录名 做大小写不敏感的子串过滤——
    画板多时平铺列表容易漏看目标画板，过滤后未命中直接说明，
    而不是让 Agent 误判"没有缓存"再白跑一次 figma_pull.py。
    """
    caches = iter_caches()
    if not caches:
        print(f"  [-] 未找到缓存（项目根: {PROJECT_ROOT}）")
        print("     先运行 figma_pull.py --project-root <项目根>")
        return
    rows = []
    for entry, prep in caches:
        tree = load_tree_silent(prep)
        if not tree:
            print(f"    - {entry}: android_tree.json 无效")
            continue
        screen = tree.get("screen", {}) or {}
        root = tree.get("root", {}) or {}
        age = time.time() - os.path.getmtime(os.path.join(prep, "android_tree.json"))
        root_dp = root.get("dp", {}) or {}
        size = f"{root_dp.get('w', '?')}x{root_dp.get('h', '?')}dp"
        rows.append((age, root.get("name", "?"),
                     screen.get("artboard_id") or root.get("node_id", ""), size, entry))

    if match:
        kw = match.lower()
        rows = [r for r in rows
                if kw in r[1].lower() or kw in r[2].lower() or kw in r[4].lower()]
        if not rows:
            print(f"  [-] .figma/ 下 {len(caches)} 个缓存中没有画板名/nodeId/目录名含「{match}」的"
                  f"（项目根: {PROJECT_ROOT}）")
            print("     不带 --match 再列一次可看到全部画板名")
            print("     要定位某个 nodeId 属于哪个画板: --id <nodeId> --find-root")
            return

    title = f"  .figma/ 下 {len(rows)} 个缓存"
    if match:
        title += f"（画板名/nodeId/目录名含「{match}」）"
    print(f"{title} (项目根: {PROJECT_ROOT}):")
    for age, name, anchor, size, entry in sorted(rows):
        print(f"    - {name} ({anchor})  {size}  {age_str(age)}前  [{entry}]")
    print("     要定位某个 nodeId 属于哪个画板: --id <nodeId> --find-root")


def find_latest_tree_dir() -> str | None:
    """在项目 .figma/ 下找最新的 android_tree.json 所在目录"""
    candidates = []
    for entry, prep in iter_caches():
        candidates.append((os.path.getmtime(os.path.join(prep, "android_tree.json")), prep))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def find_tree_by_root_id(root_id: str) -> str | None:
    """按根画板 nodeId 精确定位缓存。

    目录名只用于快速候选，命中后必须校验树内的 root.node_id / screen.artboard_id：
    旧实现用子串匹配目录名且不校验，导致 "2:14" 会命中 "2:141" 的缓存（静默取错画板）。
    """
    if not root_id:
        return None
    matches = []
    for entry, prep in iter_caches():
        tree = load_tree_silent(prep)
        if not tree:
            continue
        screen = tree.get("screen") or {}
        root = tree.get("root") or {}
        if root_id in {root.get("node_id"), screen.get("artboard_id")}:
            matches.append((os.path.getmtime(os.path.join(prep, "android_tree.json")), prep))
    if not matches:
        return None
    matches.sort(key=lambda x: x[0], reverse=True)
    return matches[0][1]


def find_best_tree_dir(root_id: str = None) -> str | None:
    """按 root_id 匹配缓存；显式指定 root_id 却未命中时返回 None（不再静默回退到最新缓存）"""
    if root_id:
        return find_tree_by_root_id(root_id)
    return find_latest_tree_dir()


def node_exists(node: dict, target_id: str) -> bool:
    """树中（含自身）是否存在指定 node_id"""
    if not isinstance(node, dict):
        return False
    if node.get("node_id") == target_id:
        return True
    return any(node_exists(c, target_id) for c in node.get("children", []) or [])


def scan_all_caches_for_node(node_id: str) -> tuple:
    """
    在所有 .figma/ 缓存中扫描包含指定 nodeId 的 android_tree.json。
    返回 (prepared_dir, root_info_dict) 或 (None, None)。多命中时取最新的缓存。
    root_info_dict = {"name", "node_id", "artboard_id", "dp", "cache_dir"}
    """
    if not node_id:
        return None, None
    matches = []
    for entry, prep in iter_caches():
        tree = load_tree_silent(prep)
        if not tree:
            continue
        root = tree.get("root", {}) or {}
        if node_exists(root, node_id):
            screen = tree.get("screen", {}) or {}
            matches.append((os.path.getmtime(os.path.join(prep, "android_tree.json")), prep, root, screen))
    if not matches:
        return None, None
    matches.sort(key=lambda x: x[0], reverse=True)
    _, prep, root, screen = matches[0]
    return prep, {
        "name": root.get("name", "?"),
        "node_id": root.get("node_id", ""),
        "artboard_id": screen.get("artboard_id") or root.get("node_id", ""),
        "dp": root.get("dp", {}),
        "cache_dir": prep,
    }


def load_tree(tree_dir: str) -> dict | None:
    tree_path = os.path.join(tree_dir, "android_tree.json")
    if not os.path.isfile(tree_path):
        print(f"  [!] 未找到 android_tree.json: {tree_path}")
        return None
    with open(tree_path, encoding="utf-8") as f:
        return json.load(f)


# style 白名单：与 rules/android-tree-guide.md 的"能回答什么"字段表对齐。
# border_color / border_width 是线性图标描边的唯一来源，gradient_colors / opacity
# 无法由其他字段推导，缺一个 Agent 就只能去手工解析 JSON。effects=阴影/模糊，由 figma_bridge_to_android.py 注入，此前被 STYLE_KEYS 漏了。
STYLE_KEYS = (
    "background", "gradient_colors", "text_color", "corner_radius_dp",
    "font_size_sp", "font_weight", "text_style", "border_color", "border_width",
    "opacity", "effects",
)

# 内容签名长度。必须与 figma_compare_nodes.py 的 SIG_LEN 一致，
# 否则两处输出无法互相核对，Agent 会误判"同一张图签名不同"。
SIG_LEN = 8


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


def content_signature(png_path: str, length: int = 8) -> str:
    """PNG 内容 md5 前 length 位；文件缺失返回 "missing"。

    内容签名是判断"两个画板的切图视觉上是否同一张"的唯一可靠依据——文件名不可比：
    export_as_image 走节点寻址，同一视觉在不同画板必然不同名。
    """
    if not png_path or not os.path.isfile(png_path):
        return "missing"
    h = hashlib.md5()
    try:
        with open(png_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return "missing"
    return h.hexdigest()[:length]


def find_nodes(tree: dict, name: str = "", node_id: str = "",
               view_type: str = "", fuzzy: bool = False,
               max_results: int = 20, text: str = "") -> list:
    """递归搜索节点树，返回所有匹配节点"""
    results = []
    root = tree.get("root", {})

    def walk(n, path):
        cur_path = path + [n.get("name", "?")]
        match = False

        if name:
            n_name = n.get("name", "")
            if fuzzy:
                if name.lower() in n_name.lower():
                    match = True
            else:
                if n_name == name:
                    match = True

        if text:
            n_text = n.get("text", "") or ""
            if text.lower() in n_text.lower():
                match = True

        if node_id and n.get("node_id") == node_id:
            match = True

        if view_type and n.get("view_type") == view_type:
            match = True

        if match:
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


def print_result(node: dict, idx: int = 1, raw_style: bool = False):
    tags = []
    if node.get("is_image"):
        tags.append("IMG")
    if node.get("text"):
        tags.append("TEXT")
    tag_str = f"  [{','.join(tags)}]" if tags else ""

    print(f"  [{idx}] {node['name']}{tag_str}")
    print(f"       路径:      {node['path']}")
    print(f"       node_id:   {node['node_id']}")
    print(f"       view_type: {node['view_type']}")
    print(f"       android_id:{node['android_id']}")
    if node.get("text"):
        text_preview = node["text"][:40].replace("\n", "\\n")
        print(f"       文本:      {text_preview}")
    dp = node.get("dp", {})
    local = node.get("dp_local", {})
    print(f"       dp(x,y):   ({dp.get('x', '?')}, {dp.get('y', '?')})")
    print(f"       dp(w,h):   {dp.get('w', '?')} x {dp.get('h', '?')}")
    if local.get("x") != dp.get("x") or local.get("y") != dp.get("y"):
        print(f"       dp_local:  ({local.get('x', '?')}, {local.get('y', '?')})")
    style = node.get("style", {})
    if style:
        parts = []
        for k in STYLE_KEYS:
            if k in style:
                v = style[k]
                if isinstance(v, list):
                    v = "/".join(str(x) for x in v)
                parts.append(f"{k}={v}")
        if parts:
            print(f"       style:     {', '.join(parts)}")
    if raw_style:
        print(f"       style_raw: {json.dumps(style, ensure_ascii=False)}")
    # 切图文件名是"这个节点对应哪个 PNG"的唯一答案，必须直接给出，
    # 否则 Agent 只能违反禁令去手工解析 assets.json
    if node.get("image_file"):
        print(f"       切图:      {node['image_file']} "
              f"(drawable-xxhdpi, {dp.get('w', '?')}x{dp.get('h', '?')}dp)")
    elif node.get("is_image"):
        print(f"       切图:      [IMG] 标记但无 image.file（旧版产物，重跑提取可补全）")
    print()


def print_children(children: list, indent: int = 0, max_depth: int = 1,
                   show_styles: bool = False):
    """递归打印子节点列表（含 node_id 与绝对坐标，供精确查询直接复用）"""
    if max_depth <= 0 or not children:
        return
    prefix = "    " + "  " * indent
    for i, c in enumerate(children):
        dp = c.get("dp", {})
        is_img = c.get("image") is not None or c.get("export_as_image") is True
        img_file = image_file_of(c)
        text = c.get("text", "")
        tags = []
        if is_img:
            tags.append("IMG")
        if text:
            tags.append("TEXT")
        tag_str = f" [{','.join(tags)}]" if tags else ""
        if is_img:
            tag_str += f" -> {img_file}" if img_file else " -> (未记录文件名)"

        sub_count = len(c.get("children", []))
        has_sub = f" ({sub_count}个子)" if sub_count > 0 else ""
        coords = f"  #{c.get('node_id','?')} @({dp.get('x',0)},{dp.get('y',0)})"

        print(f"{prefix}{i+1:>2}. {c.get('view_type','?'):<16} {c.get('name','?'):<24}"
              f" ({dp.get('w',0)}x{dp.get('h',0)}dp){has_sub}{tag_str}{coords}")
        if text:
            preview = text[:30].replace("\n", "\\n")
            print(f"{prefix}     \"{preview}\"")
        if show_styles:
            style = c.get("style", {}) or {}
            parts = [f"{k}={style[k]}" for k in STYLE_KEYS if k in style]
            if parts:
                print(f"{prefix}     style: {', '.join(parts)}")
        if max_depth > 1 and c.get("children"):
            print_children(c["children"], indent + 1, max_depth - 1, show_styles)


def load_assets(tree_dir: str) -> dict | None:
    """静默读取 assets.json（失败返回 None）"""
    path = os.path.join(tree_dir, "assets.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def print_assets(tree_dir: str, with_md5: bool = False) -> bool:
    """打印切图清单（assets.json + drawable-xxhdpi/ 内容签名）。assets.json 缺失返回 False"""
    data = load_assets(tree_dir)
    if data is None:
        print(f"  [!] 未找到 assets.json: {os.path.join(tree_dir, 'assets.json')}")
        print("     该缓存可能不是完整产物，重跑 figma_pull.py 补齐")
        return False
    assets = data.get("assets", []) or []
    if not assets:
        print("  [-] 该画板没有切图（assets.json 为空）")
        return True
    drawable_dir = os.path.join(tree_dir, "drawable-xxhdpi")
    print(f"  切图清单 {len(assets)} 个 (来源: {tree_dir}/assets.json)")
    header = f"  {'序号':>4}  {'node_id':<10} {'图层名':<24} {'文件名':<28} {'dp(w x h)':<16}"
    if with_md5:
        header += " 内容签名(md5)"
    print(header)
    for i, a in enumerate(assets):
        name = (a.get("name", "") or "")[:22]
        file_name = a.get("file", "") or "?"
        size = f"{a.get('w', 0)}x{a.get('h', 0)}"
        line = f"  {i+1:>4}  {a.get('node_id', ''):<10} {name:<24} {file_name:<28} {size:<16}"
        if with_md5:
            # 与 figma_compare_nodes.py 用同一长度（8 位）：两处输出可以互相核对，
            # 长度不一致会让 Agent 误判"同一张图签名不同"
            line += f" {content_signature(os.path.join(drawable_dir, file_name), SIG_LEN)}"
        print(line)
    return True


def main():
    set_project_root()
    tree_dir = None
    name = ""
    node_id = ""
    view_type = ""
    text_query = ""
    fuzzy = False
    show_children = False
    show_styles = False
    style_raw = False
    deep = 1

    args = sys.argv[1:]
    i = 0
    root_id = None
    use_latest = False
    find_root = False
    list_caches_flag = False
    match_kw = ""
    assets_flag = False
    with_md5 = False
    while i < len(args):
        if args[i] == "--dir" and i + 1 < len(args):
            tree_dir = args[i + 1]
            i += 2
        elif args[i] == "--root-id" and i + 1 < len(args):
            root_id = args[i + 1]
            i += 2
        elif args[i] == "--latest":
            use_latest = True
            i += 1
        elif args[i] == "--find-root":
            find_root = True
            i += 1
        elif args[i] == "--name" and i + 1 < len(args):
            name = args[i + 1]
            i += 2
        elif args[i] == "--id" and i + 1 < len(args):
            node_id = args[i + 1]
            i += 2
        elif args[i] == "--type" and i + 1 < len(args):
            view_type = args[i + 1]
            i += 2
        elif args[i] == "--text" and i + 1 < len(args):
            text_query = args[i + 1]
            i += 2
        elif args[i] == "--children":
            show_children = True
            i += 1
        elif args[i] == "--styles":
            show_styles = True
            i += 1
        elif args[i] == "--style-raw":
            style_raw = True
            i += 1
        elif args[i] == "--deep" and i + 1 < len(args):
            show_children = True
            deep = int(args[i + 1])
            i += 2
        elif args[i] == "--project-root" and i + 1 < len(args):
            set_project_root(args[i + 1])
            i += 2
        elif args[i] == "--list-caches":
            list_caches_flag = True
            i += 1
        elif args[i] == "--match" and i + 1 < len(args):
            match_kw = args[i + 1]
            i += 2
        elif args[i] == "--assets":
            assets_flag = True
            i += 1
        elif args[i] == "--md5":
            with_md5 = True
            i += 1
        elif args[i] == "--fuzzy":
            fuzzy = True
            i += 1
        else:
            # 未知参数 = 调用笔误（如 --id 误写 --node-id）。静默吞掉会退化为
            # "无过滤查最新缓存"并返回看似合理的结果，是最危险的失败模式，必须硬失败。
            print(f"  [-] 未知参数: {args[i]}")
            print(__doc__.strip())
            sys.exit(2)

    # --list-caches 必须等参数全部解析完再执行，否则会忽略写在它后面的
    # --project-root，列出错误项目（skill 目录）的缓存
    if list_caches_flag:
        list_caches(match_kw)
        sys.exit(0)

    if not (node_id or name or view_type or text_query or assets_flag or root_id or tree_dir or use_latest):
        # 无任何查询条件也无锚定时拒绝全树转储（--root-id 单独给出仍走"未命中报错"链路）
        print("  [-] 未指定查询条件或锚定（--id/--name/--type/--text/--assets 或 "
              "--dir/--root-id/--latest 至少其一），拒绝无过滤全量查询")
        print(__doc__.strip())
        sys.exit(2)

    # --find-root: 在所有缓存中扫描，定位 nodeId 所属的根画板
    if find_root and node_id and not tree_dir and not root_id:
        scanned_dir, root_info = scan_all_caches_for_node(node_id)
        if scanned_dir and root_info:
            tree_dir = scanned_dir
            root_id = root_info.get("artboard_id") or root_info["node_id"]
            print(f"  找到所属根画板:")
            print(f"    画板: {root_info['name']} ({root_id})")
            print(f"    尺寸: {root_info['dp'].get('w', '?')} x {root_info['dp'].get('h', '?')} dp")
            print(f"    缓存: {scanned_dir}/")
            print()
        else:
            print(f"  [!] 在所有缓存中未找到节点 {node_id}")
            print(f"     请先提取根画板数据: figma_pull.py")
            list_caches()
            sys.exit(1)

    # 如果没指定 --dir，自动找缓存 (优先按 root_id 匹配)
    auto_selected = False
    if not tree_dir:
        if use_latest or root_id:
            tree_dir = find_best_tree_dir(root_id)
        else:
            tree_dir = find_latest_tree_dir()
            auto_selected = bool(tree_dir)
            if tree_dir:
                print(f"  [!] 未指定锚定（--root-id/--find-root/--dir）：按最新缓存读取 "
                      f"{os.path.basename(tree_dir)}——请确认它就是目标画板；"
                      f"多画板/预拉取场景必须显式锚定")

    if not tree_dir:
        if root_id:
            print(f"  [!] 未找到根画板 {root_id} 的缓存（显式指定 root-id 时不会回退到其他画板）")
            list_caches()
        else:
            print("  [!] 未找到 android_tree.json")
            print(f"     项目根: {PROJECT_ROOT}")
            print("     请指定 --dir <目录>，或用 --project-root <项目根> / 先运行 figma_pull.py")
        sys.exit(1)

    # 支持直接传入 figma_extract_prepared 或上层目录
    if not tree_dir.endswith("figma_extract_prepared"):
        candidate = os.path.join(tree_dir, "figma_extract_prepared")
        if os.path.isdir(candidate):
            tree_dir = candidate

    # --assets: 切图清单模式。只读 assets.json + drawable-xxhdpi/，
    # 不解析节点树——回答"这个画板有哪些切图/两个画板同名切图是否同一张"
    if assets_flag:
        print(f"  缓存目录: {tree_dir}/")
        meta_tree = load_tree_silent(tree_dir) or {}
        meta_root = meta_tree.get("root", {}) or {}
        meta_screen = meta_tree.get("screen", {}) or {}
        anchor = meta_screen.get("artboard_id") or meta_root.get("node_id", "")
        if anchor:
            print(f"  画板: {meta_root.get('name', '?')} ({anchor})")
        print()
        sys.exit(0 if print_assets(tree_dir, with_md5=with_md5) else 1)

    print(f"  搜索目录: {tree_dir}/")

    tree = load_tree(tree_dir)
    if not tree:
        sys.exit(1)

    # 自动选中最新缓存时，若该节点不在其中，按 nodeId 扫描其他缓存定位所属画板。
    # 显式 --dir / --root-id / --latest 时保持严格锚定，不做切换。
    if auto_selected and node_id and not node_exists(tree.get("root", {}), node_id):
        scanned_dir, root_info = scan_all_caches_for_node(node_id)
        if scanned_dir and root_info:
            tree_dir = scanned_dir
            root_id = root_info.get("artboard_id") or root_info["node_id"]
            print(f"  [!] 节点 {node_id} 不在最新缓存，已自动定位到画板: "
                  f"{root_info['name']} ({root_id})")
            print(f"      缓存: {scanned_dir}/")
            tree = load_tree(tree_dir)
            if not tree:
                sys.exit(1)
        else:
            print(f"  [!] 节点 {node_id} 不在最新缓存，其他缓存中也未找到")

    screen = tree.get("screen", {})
    print(f"  画板: {screen.get('width_dp', '?')} x {screen.get('height_dp', '?')} dp")
    print()

    results = find_nodes(tree, name=name, node_id=node_id,
                         view_type=view_type, fuzzy=fuzzy, text=text_query)

    if not results:
        print("  [-] 未找到匹配节点")
        if name and not text_query:
            print("      提示: 图层名可能与界面文字不同，改用 --text <界面文字> 搜索")
        sys.exit(0)

    # 按 y 坐标排序
    results.sort(key=lambda n: n["dp"].get("y", 0))

    print(f"  [✓] 找到 {len(results)} 个匹配节点:")
    print()
    for i, n in enumerate(results[:20]):
        print_result(n, i + 1, raw_style=style_raw)

    if len(results) > 20:
        print(f"  ... 还有 {len(results) - 20} 个结果未显示")

    # 子节点展开
    if show_children and results:
        for i, n in enumerate(results[:20]):
            children = n.get("children", [])
            if not children:
                continue
            if len(results) > 1:
                print(f"  ── [{i+1}] {n['name']} 的子节点 (深度 {deep}) ──")
            else:
                print(f"  ── 子节点列表 (深度 {deep}) ──")
            print_children(children, max_depth=deep, show_styles=show_styles)
            print()


if __name__ == "__main__":
    main()
