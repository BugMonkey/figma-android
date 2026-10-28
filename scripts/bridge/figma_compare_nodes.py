#!/usr/bin/env python3
"""
figma_compare_nodes.py — 跨画板比对同名节点的样式与切图内容

场景：同一个组件在多个画板上出现不同状态（如底部 tab 的选中/未选中态、
同一列表项在首页与详情页的差异）。每个画板是一个独立缓存目录，逐个画板查询
再靠人脑横向对齐既慢又易漏，本脚本做一次机械化对齐 + 差异归纳。

用法:
  python3 figma_compare_nodes.py --name "icon_" --fuzzy \
    --root-ids 1:5,10:2755,10:2889,6:188 --deep 2 --project-root "$(pwd)"
  python3 figma_compare_nodes.py --name icon_tab1_sel --project-root "$(pwd)"   # 扫全部缓存

--name:      必需。要比对的图层名（配合 --fuzzy 做子串匹配）。
--fuzzy:     子串匹配（大小写不敏感），默认精确匹配。
--root-ids:  逗号分隔的根画板 nodeId 列表，限定参与比对的画板，顺序即输出顺序。
             省略则扫描 .figma/ 下全部缓存。**显式指定的画板未命中即报错退出，
             不会静默跳过**——少比一个画板会得出错误的"无差异"结论。
--deep:      名称搜索的树深度上限（根的直接子节点为第 1 层）。默认 0 = 不限深度。
             只想比对浅层元素（如底部 tab）时用它排除深层同名节点。
--project-root: .figma/ 缓存所在的项目根。Agent 应显式传入会话工作目录。

判断"两个画板的切图是不是同一张"必须看 内容签名（PNG 内容 md5），
不能看 image.file：
  - export_as_image 节点按 **节点寻址** 命名（img_<nodeId>.png），
    同一视觉在不同画板必然不同名；
  - IMAGE fill 节点按 **内容寻址** 命名（img_<imageHash>.png）。
脚本会把节点寻址的文件名差异单独提示，避免误判为"视觉不同"。

输出:
  1. 每画板一段表格: node_id | name | view_type | dp | background | border_color
     | text_color | image.file | 内容签名(md5 前 8 位，缺文件标 missing)
  2. 差异摘要: 按图层名分组，只列不一致字段
  3. 内容等价分组: 内容签名相同的节点归为一组（跨画板同图即在此体现）
"""

import hashlib
import json
import os
import sys


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

# 内容签名长度（md5 前 N 位）
SIG_LEN = 8

# 逐字段比对的字段集合。image.file 也列出，但差异会按"是否节点寻址"另行提示。
DIFF_FIELDS = ("view_type", "dp", "background", "border_color", "text_color",
               "image_file", "signature")


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


def artboard_anchor(tree: dict) -> str:
    """取树内记录的根画板 nodeId（校验用，不信目录名）"""
    root = tree.get("root") or {}
    screen = tree.get("screen") or {}
    return screen.get("artboard_id") or root.get("node_id", "")


def artboard_name(tree: dict) -> str:
    return (tree.get("root") or {}).get("name", "?")


def list_caches_hint() -> None:
    """未命中时列出可用缓存，避免 Agent 误判"没有缓存"再白跑一次 pull"""
    caches = iter_caches()
    if not caches:
        print(f"  [-] 未找到缓存（项目根: {PROJECT_ROOT}）")
        print("     先运行 figma_pull.py --project-root <项目根>")
        return
    print(f"  可用缓存 {len(caches)} 个 (项目根: {PROJECT_ROOT}):")
    for entry, prep in caches:
        tree = load_tree_silent(prep)
        if not tree:
            continue
        print(f"    - {artboard_name(tree)} ({artboard_anchor(tree)})  [{entry}]")


def resolve_artboards(root_ids: list) -> list:
    """解析参与比对的画板，返回 [{"name","anchor","entry","prep","tree"}]。

    root_ids 为空 → 扫全部缓存（按画板名排序）。
    root_ids 非空 → 逐个按树内 root.node_id / screen.artboard_id 精确匹配；
    任一未命中即整体报错退出，不静默跳过（少比一个画板会得出错误的"无差异"结论）。
    """
    caches = iter_caches()
    if not caches:
        return []

    if not root_ids:
        boards = []
        for entry, prep in caches:
            tree = load_tree_silent(prep)
            if not tree:
                print(f"    [!] {entry}: android_tree.json 无效，跳过")
                continue
            boards.append({"name": artboard_name(tree), "anchor": artboard_anchor(tree),
                           "entry": entry, "prep": prep, "tree": tree})
        boards.sort(key=lambda b: b["name"])
        return boards

    by_anchor = {}
    for entry, prep in caches:
        tree = load_tree_silent(prep)
        if not tree:
            continue
        anchor = artboard_anchor(tree)
        # 命中多个缓存时保留最新的那个
        mtime = os.path.getmtime(os.path.join(prep, "android_tree.json"))
        prev = by_anchor.get(anchor)
        if prev is None or mtime > prev["mtime"]:
            by_anchor[anchor] = {"name": artboard_name(tree), "anchor": anchor,
                                 "entry": entry, "prep": prep, "tree": tree,
                                 "mtime": mtime}

    boards = []
    missing = []
    for rid in root_ids:
        hit = by_anchor.get(rid)
        if hit is None:
            missing.append(rid)
            continue
        boards.append({k: hit[k] for k in ("name", "anchor", "entry", "prep", "tree")})

    if missing:
        print(f"  [!] 未找到根画板 {'、'.join(missing)} 的缓存（显式指定时不会回退到其他画板）")
        list_caches_hint()
        sys.exit(1)
    return boards


def image_file_of(node: dict) -> str:
    """取节点的切图文件名（image.file）。无切图为空串。"""
    img = node.get("image")
    if isinstance(img, dict):
        return img.get("file", "") or ""
    return ""


def is_node_addressed(node: dict, file_name: str) -> bool:
    """切图文件名是否按节点寻址（同一视觉跨画板必然不同名）。

    权威依据是节点的 export_as_image 标记（适配器据此用 nodeId 命名）；
    旧版产物可能缺该标记，此时用文件名形态兜底判断：节点寻址名由
    img_<nodeId 前 12 位>.png 生成，nodeId 含冒号，替换后必带下划线。
    """
    if node.get("export_as_image"):
        return True
    stem = file_name[:-4] if file_name.endswith(".png") else file_name
    if not stem.startswith("img_"):
        return False
    return "_" in stem[4:]


def content_signature(png_path: str, length: int = SIG_LEN) -> str:
    """PNG 内容 md5 前 length 位；文件缺失返回 "missing"。

    内容是判断"两个画板的切图是不是同一张"的唯一可靠依据——文件名不可比：
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


def collect_nodes(tree: dict, name: str, fuzzy: bool, max_depth: int,
                  drawable_dir: str, sig_cache: dict) -> list:
    """按名称收集节点（含切图文件名与内容签名）。

    `max_depth`: 0 表示不限深度。深度语义：根=0, 根的直接子节点=1, 以此类推。
    """
    results = []
    root = tree.get("root", {})
    needle = name.lower()

    def walk(n, path, depth):
        cur_path = path + [n.get("name", "?")]
        n_name = n.get("name", "")
        if (fuzzy and needle in n_name.lower()) or (not fuzzy and n_name == name):
            dp = n.get("dp", {}) or {}
            style = n.get("style", {}) or {}
            file_name = image_file_of(n)
            png_path = os.path.join(drawable_dir, file_name) if file_name else ""
            if png_path and png_path not in sig_cache:
                sig_cache[png_path] = content_signature(png_path)
            results.append({
                "node_id": n.get("node_id", ""),
                "name": n_name,
                "path": " / ".join(cur_path),
                "view_type": n.get("view_type", "?"),
                "dp": f"{dp.get('w', 0)}x{dp.get('h', 0)}",
                "background": style.get("background", "-"),
                "border_color": style.get("border_color", "-"),
                "text_color": style.get("text_color", "-"),
                "image_file": file_name or "-",
                "signature": sig_cache.get(png_path, "-") if png_path else "-",
                "node_addressed": bool(file_name) and is_node_addressed(n, file_name),
            })
        if max_depth and depth >= max_depth:
            return
        for c in n.get("children", []) or []:
            walk(c, cur_path, depth + 1)

    walk(root, [], 0)
    return results


def cell(value, width: int) -> str:
    """定宽单元格（超宽截断，中文按显示宽度较接近的两倍估算）"""
    s = str(value)
    if len(s) > width:
        s = s[:width - 1] + "…"
    return s.ljust(width)


def print_board_table(board: dict, nodes: list) -> None:
    print(f"  ── 画板: {board['name']} ({board['anchor']}) ──")
    if not nodes:
        print("     (无同名节点)")
        print()
        return
    print("     " + " ".join([
        cell("node_id", 10), cell("name", 20), cell("view_type", 12),
        cell("dp", 13), cell("background", 10), cell("border_color", 13),
        cell("text_color", 11), cell("image.file", 20), "内容签名",
    ]))
    for n in nodes:
        print("     " + " ".join([
            cell(n["node_id"], 10), cell(n["name"], 20), cell(n["view_type"], 12),
            cell(n["dp"], 13), cell(n["background"], 10), cell(n["border_color"], 13),
            cell(n["text_color"], 11), cell(n["image_file"], 20), n["signature"],
        ]))
    print()


def print_diff_summary(all_nodes: list, boards: list) -> None:
    """按图层名分组，只列不一致字段。

    必须显式区分「交叉比过」与「只有一个画板命中」——后者无法比对，
    若笼统报"完全一致"会让调用方误以为已确认无差异而提前收工（假阴性）。
    """
    by_name = {}
    for board, node in all_nodes:
        by_name.setdefault(node["name"], []).append((board, node))

    print("  ── 差异摘要 ──")
    inconsistent_names = 0
    single_board_names = []
    node_addressed_hint = False
    for name in sorted(by_name):
        entries = by_name[name]
        if len(entries) < 2:
            single_board_names.append(entries[0])
            continue
        lines = []
        for field in DIFF_FIELDS:
            values = []
            for board, node in entries:
                tag = f"{board['name']}({board['anchor']})"
                values.append((tag, str(node.get(field, "-"))))
            if len({v for _, v in values}) > 1:
                detail = " | ".join(f"{t}={v}" for t, v in values)
                lines.append(f"      - {field}: {detail}")
                if field == "image_file" and any(n["node_addressed"] for _, n in entries):
                    node_addressed_hint = True
        if lines:
            inconsistent_names += 1
            print(f"    名称 {name}（{len(entries)} 个画板）:")
            for line in lines:
                print(line)

    if inconsistent_names == 0:
        cross_checked = [name for name in by_name if len(by_name[name]) >= 2]
        if cross_checked:
            print(f"    (交叉比对的 {len(cross_checked)} 个图层名，各字段完全一致)")
        else:
            print("    (没有图层名在 >= 2 个画板中同时命中，本次实际未形成任何交叉比对)")

    if node_addressed_hint:
        print("    ⚠️ 上面 image_file 的差异包含「节点寻址」文件（img_<nodeId>.png）：")
        print("       同一视觉在不同画板必然不同名，名字不同不代表视觉不同——")
        print("       判断是否同一张图请看下方「内容等价分组」的内容签名，不要看文件名。")

    if single_board_names:
        print("    ⚠️ 仅在 1 个画板命中，无法交叉比对（其余画板没有同名节点，"
              "可能是图层改名/删除，或该画板未参与）:")
        for board, node in single_board_names[:10]:
            print(f"        - {node['name']} 仅见于 {board['name']}({board['anchor']})  "
                  f"node_id={node['node_id']}")

    empty_boards = [b for b in boards
                    if not any(b["anchor"] == ab["anchor"] for ab, _ in all_nodes)]
    if empty_boards:
        print("    ⚠️ 以下画板一个同名节点都没命中——比对结论对这些画板不成立，"
              "先确认图层名/深度是否写对:")
        for b in empty_boards:
            print(f"        - {b['name']} ({b['anchor']})")
    print()


def print_equivalence_groups(all_nodes: list) -> None:
    """内容签名相同的节点归组（跨画板同图在这里体现）"""
    print("  ── 内容等价分组（内容签名相同 = 同一张图） ──")
    groups = {}
    missing = []
    for board, node in all_nodes:
        sig = node["signature"]
        if sig in ("-", ""):
            continue
        if sig == "missing":
            missing.append((board, node))
            continue
        groups.setdefault(sig, []).append((board, node))

    cross_board = 0
    for sig in sorted(groups):
        members = groups[sig]
        if len(members) < 2:
            continue
        boards = {b["anchor"] for b, _ in members}
        marker = "跨画板" if len(boards) > 1 else "同画板"
        if len(boards) > 1:
            cross_board += 1
        detail = ", ".join(f"{b['name']}({b['anchor']})/{n['name']}" for b, n in members)
        print(f"    [{sig}] {marker} {len(members)} 处: {detail}")

    if cross_board == 0:
        print("    (没有跨画板的内容相同切图)")
    if missing:
        print(f"    [!] {len(missing)} 个切图文件在 drawable-xxhdpi/ 中缺失，无法比对内容:")
        for board, node in missing[:10]:
            print(f"        - {board['name']}({board['anchor']})/{node['name']} "
                  f"image.file={node['image_file']}")
    print()


def main():
    set_project_root()
    name = ""
    fuzzy = False
    root_ids_raw = ""
    deep = 0

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--name" and i + 1 < len(args):
            name = args[i + 1]
            i += 2
        elif args[i] == "--root-ids" and i + 1 < len(args):
            root_ids_raw = args[i + 1]
            i += 2
        elif args[i] == "--deep" and i + 1 < len(args):
            deep = int(args[i + 1])
            i += 2
        elif args[i] == "--project-root" and i + 1 < len(args):
            set_project_root(args[i + 1])
            i += 2
        elif args[i] == "--fuzzy":
            fuzzy = True
            i += 1
        else:
            print(f"[-] 未知参数: {args[i]}")
            print(__doc__.strip())
            sys.exit(2)

    if not name:
        print("  [!] 必须指定 --name <图层名>（配合 --fuzzy 做子串匹配）")
        print(__doc__)
        sys.exit(2)

    root_ids = [r.strip() for r in root_ids_raw.split(",") if r.strip()]

    print()
    print(f"  跨画板节点比对：name=\"{name}\"{'（模糊）' if fuzzy else '（精确）'}")
    if deep:
        print(f"  搜索深度: 前 {deep} 层")
    if root_ids:
        print(f"  指定画板: {'、'.join(root_ids)}")
    else:
        print(f"  指定画板: 未指定 → 扫描 .figma/ 下全部缓存")
    print()

    boards = resolve_artboards(root_ids)
    if not boards:
        print(f"  [!] 没有可参与比对的画板")
        list_caches_hint()
        sys.exit(1)

    all_nodes = []
    sig_cache = {}
    for board in boards:
        nodes = collect_nodes(board["tree"], name, fuzzy, deep,
                              os.path.join(board["prep"], "drawable-xxhdpi"), sig_cache)
        print_board_table(board, nodes)
        for node in nodes:
            all_nodes.append((board, node))

    if not all_nodes:
        print(f"  [-] 所有画板中都没有名称{'包含' if fuzzy else '等于'}「{name}」的节点")
        print("     先用 figma_query_node.py --name <关键词> --fuzzy 确认图层实际叫什么")
        sys.exit(0)

    print(f"  参与比对: {len(boards)} 个画板 / 命中 {len(all_nodes)} 个节点")
    print()
    print_diff_summary(all_nodes, boards)
    print_equivalence_groups(all_nodes)


if __name__ == "__main__":
    main()