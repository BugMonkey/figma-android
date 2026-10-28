#!/usr/bin/env python3
"""桥模式产物离线自检（不需要 Figma、不需要桥服务器）。

覆盖两个曾经静默出错的契约：
  1. dp 换算基准必须是真实根画板宽度，而不是提取根节点宽度。
     场景：按内层 Frame（300px）提取，画板 1080px（3x 设计）。
     正确：scale=3，该 Frame = 100dp；错误（旧行为）：scale 被钳到 1，得 300dp。
  2. figma_validate_tree.py 能对 v2 产物给出 success / blocked 的正确判定。
  3. 缓存复用三重门槛：文件齐全 / 适配器已修复 / 树中含目标节点。
  4. figma_query_node.py 的 CLI 契约：参数顺序无关、--root-id 严格匹配、
     查询输出直接给出切图文件名、--assets 切图清单、--list-caches --match 过滤。
  5. figma_selected_node.py 的缓存锚定输出同样给出切图文件名。
  6. figma_compare_nodes.py 跨画板比对：节点寻址文件名不可比、内容签名可比。
  7. dp_local 三层嵌套坐标（必须相对父节点绝对坐标）。
  8. --id 跨缓存自动定位、--children/--styles/--style-raw/--text 输出契约。

用法:
  python3 scripts/common/figma_selftest.py
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADAPTER = os.path.join(SKILL_DIR, "bridge", "figma_bridge_to_android.py")
VALIDATOR = os.path.join(SKILL_DIR, "common", "figma_validate_tree.py")
PULL = os.path.join(SKILL_DIR, "bridge", "figma_pull.py")
QUERY = os.path.join(SKILL_DIR, "bridge", "figma_query_node.py")
SELECTED = os.path.join(SKILL_DIR, "bridge", "figma_selected_node.py")
COMPARE = os.path.join(SKILL_DIR, "bridge", "figma_compare_nodes.py")

FAILURES = []


def check(condition: bool, message: str) -> None:
    status = "OK  " if condition else "FAIL"
    print(f"  [{status}] {message}")
    if not condition:
        FAILURES.append(message)


def make_composition(artboard_width=1080, root_width=300, root_height=120, with_artboard=True,
                     with_image=False):
    """内层 Frame 作为提取根：宽 300，其所属画板宽 1080（3x 设计）

    with_image=True 时把 icon 子节点标记为 export_as_image，适配器会写入
    image.file（节点寻址 img_<nodeId>.png），用于验证查询脚本输出切图文件名。
    """
    icon = {
        "id": "12:35", "name": "icon", "type": "RECTANGLE",
        "x": 12, "y": 12, "width": 60, "height": 60, "children": [],
    }
    if with_image:
        # 插件在导出时标记，适配器据此写 image.file = img_12_35.png
        icon["export_as_image"] = True
    composition = {
        "schemaVersion": "2.0",
        "kind": "figma-extract",
        "name": "卡片",
        "nodeId": "12:34",
        "width": root_width,
        "height": root_height,
        "requestedNodeId": "12:34",
        "nodeTree": {
            "id": "12:34",
            "name": "卡片",
            "type": "FRAME",
            "x": 0, "y": 0, "width": root_width, "height": root_height,
            "children": [
                icon,
                {
                    "id": "12:36", "name": "标题", "type": "TEXT",
                    "x": 90, "y": 24, "width": 120, "height": 36, "children": [],
                    "text": {"characters": "标题"},
                    "segments": [
                        {"start": 0, "end": 2, "fontSize": 30, "fontWeight": 500,
                         "fills": [{"type": "SOLID",
                                    "color": {"r": 0.1, "g": 0.1, "b": 0.1, "a": 1}}]},
                    ],
                },
            ],
        },
    }
    if with_artboard:
        composition["artboardId"] = "2:141"
        composition["artboardName"] = "咨询"
        composition["artboardWidth"] = artboard_width
        composition["exportScale"] = 1080 / artboard_width
    return composition


def make_nested_composition() -> dict:
    """三层嵌套：根(0,0) → 容器 x=48 → 子 x=60 → 孙 x=72（px，画板 1080 = 3x）。

    期望 dp_local：容器 16、子 4、孙 4。修复前孙会算成 20（用父节点局部坐标当原点）。
    """
    return {
        "schemaVersion": "2.0",
        "kind": "figma-extract",
        "name": "嵌套",
        "nodeId": "30:1",
        "width": 1080,
        "height": 800,
        "requestedNodeId": "30:1",
        "artboardId": "30:1",
        "artboardName": "嵌套",
        "artboardWidth": 1080,
        "exportScale": 1,
        "nodeTree": {
            "id": "30:1", "name": "嵌套", "type": "FRAME",
            "x": 0, "y": 0, "width": 1080, "height": 800,
            "children": [{
                "id": "30:2", "name": "容器", "type": "FRAME",
                "x": 48, "y": 24, "width": 300, "height": 300,
                "children": [{
                    "id": "30:3", "name": "子", "type": "FRAME",
                    "x": 60, "y": 36, "width": 120, "height": 120,
                    "children": [{
                        "id": "30:4", "name": "孙", "type": "RECTANGLE",
                        "x": 72, "y": 48, "width": 60, "height": 60, "children": [],
                    }],
                }],
            }],
        },
    }


def run_adapter(composition: dict, workdir: str) -> str:
    prepared = os.path.join(workdir, "figma_extract_prepared")
    os.makedirs(prepared, exist_ok=True)
    comp_path = os.path.join(workdir, "composition.json")
    with open(comp_path, "w", encoding="utf-8") as f:
        json.dump(composition, f, ensure_ascii=False)
    result = subprocess.run(
        [sys.executable, ADAPTER, comp_path, "--output-dir", prepared],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"adapter 失败: {result.stderr.strip()}")
    return prepared


def run_validator(prepared: str) -> dict:
    result = subprocess.run(
        [sys.executable, VALIDATOR, prepared],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"validator 输出不可解析: {result.stdout[:400]} {result.stderr[:400]}")


def load_tree(prepared: str) -> dict:
    with open(os.path.join(prepared, "android_tree.json"), encoding="utf-8") as f:
        return json.load(f)


def test_scale_basis() -> None:
    print("\n[1] dp 换算基准 = 真实根画板宽度（内层 Frame 提取场景）")
    with tempfile.TemporaryDirectory() as workdir:
        prepared = run_adapter(make_composition(artboard_width=1080, root_width=300), workdir)
        tree = load_tree(prepared)
        screen = tree["screen"]
        root = tree["root"]

        check(screen.get("scale") == 3, f"scale 应为 3（画板 1080px），实际 {screen.get('scale')}")
        check(screen.get("artboard_width_px") == 1080,
              f"artboard_width_px 应为 1080，实际 {screen.get('artboard_width_px')}")
        check(root["dp"]["w"] == 100.0, f"提取根宽度应为 100.0dp，实际 {root['dp']['w']}")
        check(root["dp"]["h"] == 40.0, f"提取根高度应为 40.0dp，实际 {root['dp']['h']}")
        check(root["children"][0]["dp"]["w"] == 20.0,
              f"子节点宽度应为 20.0dp，实际 {root['children'][0]['dp']['w']}")
        check(root["children"][1]["dp"]["x"] == 30.0,
              f"文字节点 x 应为 30.0dp，实际 {root['children'][1]['dp']['x']}")

        result = run_validator(prepared)
        joined = " | ".join(result.get("warnings", []))
        check("提取根不是顶层画板" in joined,
              f"校验脚本应提示提取根非顶层画板，实际: {joined[:200]}")


def test_scale_fallback() -> None:
    print("\n[2] 老插件（无 artboardWidth 字段）回落行为")
    with tempfile.TemporaryDirectory() as workdir:
        prepared = run_adapter(make_composition(with_artboard=False), workdir)
        screen = load_tree(prepared)["screen"]
        check(screen.get("artboard_width_px") == 300,
              f"无 artboardWidth 时应回落为提取根宽度，实际 {screen.get('artboard_width_px')}")
        check(screen.get("scale") == 1, f"scale 应为 1（钳位），实际 {screen.get('scale')}")


def test_validator_success() -> None:
    print("\n[3] 校验脚本：整块画板提取的正常产物 → success")
    with tempfile.TemporaryDirectory() as workdir:
        prepared = run_adapter(
            make_composition(artboard_width=1080, root_width=1080, root_height=2340), workdir)
        result = run_validator(prepared)
        check(result.get("status") == "success",
              f"应判定 success，实际 {result.get('status')}: {result.get('errors') or result.get('warnings')}")


def test_validator_blocked() -> None:
    print("\n[4] 校验脚本：node_id 重复 + scale 越界 → blocked")
    with tempfile.TemporaryDirectory() as workdir:
        prepared = run_adapter(make_composition(), workdir)
        tree_path = os.path.join(prepared, "android_tree.json")
        tree = load_tree(prepared)
        tree["root"]["children"][1]["node_id"] = tree["root"]["children"][0]["node_id"]
        tree["screen"]["scale"] = 9
        with open(tree_path, "w", encoding="utf-8") as f:
            json.dump(tree, f, ensure_ascii=False)

        result = run_validator(prepared)
        errors = " | ".join(result.get("errors", []))
        check(result.get("status") == "blocked", f"应判定 blocked，实际 {result.get('status')}")
        check("node_id 重复" in errors, f"应报出 node_id 重复，实际: {errors[:200]}")
        check("scale 越界" in errors, f"应报出 scale 越界，实际: {errors[:200]}")


def load_pull_module():
    spec = importlib.util.spec_from_file_location("figma_pull", PULL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cache_reuse() -> None:
    print("\n[5] 缓存复用：文件齐全 / 适配器版本 / 目标命中 三重门槛")
    pull = load_pull_module()
    with tempfile.TemporaryDirectory() as workdir:
        # 先用真实适配器产出一份可信产物作为缓存内容
        base = run_adapter(make_composition(artboard_width=1080, root_width=300), workdir)
        figma_dir = os.path.join(workdir, "proj", ".figma")

        def make_cache(entry: str, drop=(), strip_artboard: bool = False) -> None:
            prepared = os.path.join(figma_dir, entry, "figma_extract_prepared")
            os.makedirs(prepared, exist_ok=True)
            for name in os.listdir(base):
                src = os.path.join(prepared, name)
                origin = os.path.join(base, name)
                if name in drop:
                    continue
                if os.path.isdir(origin):
                    shutil.copytree(origin, src, dirs_exist_ok=True)
                else:
                    shutil.copy2(origin, src)
            if strip_artboard:
                tree_file = os.path.join(prepared, "android_tree.json")
                with open(tree_file, encoding="utf-8") as f:
                    tree = json.load(f)
                tree["screen"].pop("artboard_width_px", None)
                with open(tree_file, "w", encoding="utf-8") as f:
                    json.dump(tree, f, ensure_ascii=False)

        project_root = os.path.join(workdir, "proj")
        make_cache("figma_extract_完整")
        hit = pull.find_reusable_cache(project_root, want_node_id="12:36")
        check(hit is not None, "完整缓存且含目标子节点 → 应命中")
        check(hit is not None and hit[0].endswith("figma_extract_完整/figma_extract_prepared"),
              "命中路径应指向该缓存目录")

        check(pull.find_reusable_cache(project_root, want_node_id="99:99") is None,
              "树中不含目标节点 → 不应命中（否则会把别的画板当成本次的）")
        check(pull.find_reusable_cache(project_root, want_root_id="2:141") is not None,
              "want_root_id 匹配 screen.artboard_id → 应命中")
        check(pull.find_reusable_cache(project_root, want_root_id="9:999") is None,
              "want_root_id 不匹配 → 不应命中")
        check(pull.find_reusable_cache(project_root) is None,
              "既无 node_id 也无 root_id → 不应命中")

    with tempfile.TemporaryDirectory() as workdir:
        base = run_adapter(make_composition(artboard_width=1080, root_width=300), workdir)
        project_root = os.path.join(workdir, "proj")
        incomplete = os.path.join(project_root, ".figma", "figma_extract_缺文件",
                                  "figma_extract_prepared")
        os.makedirs(incomplete, exist_ok=True)
        for name in ("android_tree.json", "assets.json"):
            shutil.copy2(os.path.join(base, name), os.path.join(incomplete, name))
        check(load_pull_module().find_reusable_cache(project_root, want_node_id="12:36") is None,
              "缺 source_meta.json → 不应命中（切图尺寸校正会失败）")

    with tempfile.TemporaryDirectory() as workdir:
        base = run_adapter(make_composition(artboard_width=1080, root_width=300), workdir)
        project_root = os.path.join(workdir, "proj")
        legacy = os.path.join(project_root, ".figma", "figma_extract_旧适配器",
                              "figma_extract_prepared")
        os.makedirs(legacy, exist_ok=True)
        for name in os.listdir(base):
            origin = os.path.join(base, name)
            if os.path.isdir(origin):
                shutil.copytree(origin, os.path.join(legacy, name), dirs_exist_ok=True)
            else:
                shutil.copy2(origin, os.path.join(legacy, name))
        tree_file = os.path.join(legacy, "android_tree.json")
        with open(tree_file, encoding="utf-8") as f:
            tree = json.load(f)
        tree["screen"].pop("artboard_width_px", None)
        with open(tree_file, "w", encoding="utf-8") as f:
            json.dump(tree, f, ensure_ascii=False)
        check(load_pull_module().find_reusable_cache(project_root, want_node_id="12:36") is None,
              "旧适配器产物（无 artboard_width_px）→ 不应命中（dp 基准不可信）")


def test_query_node_cli() -> None:
    print("\n[6] figma_query_node.py CLI：--list-caches/--match 参数顺序无关、--root-id 严格匹配、切图文件名与 --assets")
    with tempfile.TemporaryDirectory() as workdir:
        base = run_adapter(make_composition(artboard_width=1080, root_width=300, with_image=True),
                           workdir)
        project_root = os.path.join(workdir, "proj")
        prepared = os.path.join(project_root, ".figma", "figma_extract_缓存甲",
                                "figma_extract_prepared")
        os.makedirs(prepared, exist_ok=True)
        for name in os.listdir(base):
            origin = os.path.join(base, name)
            if os.path.isdir(origin):
                shutil.copytree(origin, os.path.join(prepared, name), dirs_exist_ok=True)
            else:
                shutil.copy2(origin, os.path.join(prepared, name))

        # 参数写在 --list-caches 之后也必须生效（曾因提前 sys.exit 被忽略）
        result = subprocess.run(
            [sys.executable, QUERY, "--list-caches", "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        out = result.stdout
        check(project_root in out,
              f"--project-root 写在 --list-caches 之后应仍然生效，实际输出: {out.strip()[:200]}")
        check("缓存甲" in out, f"应列出缓存甲，实际输出: {out.strip()[:200]}")

        # --match 过滤：画板多时平铺列表会漏看目标画板（曾误判"无缓存"白跑一次 pull）
        result = subprocess.run(
            [sys.executable, QUERY, "--list-caches", "--match", "缓存甲",
             "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        out = result.stdout
        check("缓存甲" in out and "1 个缓存" in out,
              f"--match 命中时应只列命中项，实际输出: {out.strip()[:200]}")
        check("--find-root" in out, f"列表尾部应提示用 --id X --find-root 定位画板，实际: {out.strip()[:200]}")

        result = subprocess.run(
            [sys.executable, QUERY, "--list-caches", "--match", "不存在的画板",
             "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        check("没有画板名/nodeId/目录名含" in result.stdout,
              f"--match 未命中应明确说明而不是静默空列表，实际: {result.stdout.strip()[:200]}")

        # 未知参数必须硬失败：静默吞参会退化为"无过滤查最新缓存"返回看似合理结果
        # （文档已知易混点：--id 误写 --node-id）
        for script, bad_flag in ((QUERY, "--node-id"), (SELECTED, "--assets"), (COMPARE, "--id")):
            r = subprocess.run(
                [sys.executable, script, bad_flag, "1:2", "--project-root", project_root],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            )
            check(r.returncode == 2 and "未知参数" in r.stdout,
                  f"{os.path.basename(script)} 未知参数 {bad_flag} 应 exit 2 并报「未知参数」，"
                  f"实际 rc={r.returncode} out={(r.stdout + r.stderr).strip()[:150]}")
        r = subprocess.run(
            [sys.executable, QUERY, "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        check(r.returncode == 2 and "未指定查询条件" in r.stdout,
              f"query_node 完全无条件应拒绝全量查询并 exit 2，实际 rc={r.returncode}")

        # --root-id 未命中时必须报错，不能回退到最新缓存
        result = subprocess.run(
            [sys.executable, QUERY, "--root-id", "9:999", "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        check(result.returncode != 0, "--root-id 未命中应返回非零退出码")
        check("未找到根画板 9:999" in result.stdout,
              f"应明确报出未命中，实际: {result.stdout.strip()[:200]}")

        # P0-1: 查询输出必须直接给出切图文件名，否则 Agent 只能违规手工解析 assets.json
        result = subprocess.run(
            [sys.executable, QUERY, "--id", "12:35", "--children", "--deep", "1",
             "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        out = result.stdout
        check("切图" in out and "img_12_35.png" in out,
              f"节点查询应输出切图文件名 img_12_35.png，实际: {out.strip()[:300]}")

        # 子节点列表的 [IMG] 后也要跟上文件名（只给标记等于没回答"对应哪个 PNG"）
        result = subprocess.run(
            [sys.executable, QUERY, "--id", "12:34", "--children", "--deep", "1",
             "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        check("img_12_35.png" in result.stdout,
              f"子节点列表的切图项应带文件名，实际: {result.stdout.strip()[:300]}")

        # 子节点行必须带 node_id 与绝对坐标，--styles 追加精简样式，
        # 避免 Agent 为拿样式对每个子节点二次查询
        result = subprocess.run(
            [sys.executable, QUERY, "--id", "12:34", "--children", "--deep", "2", "--styles",
             "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        out = result.stdout
        check("#12:35" in out and "@(" in out,
              f"--children 子节点应带 node_id 与绝对坐标，实际: {out.strip()[:300]}")
        check("style:" in out,
              f"--styles 应输出子节点精简样式，实际: {out.strip()[:300]}")

        # --text：图层名与界面文字不一致时的搜索入口
        result = subprocess.run(
            [sys.executable, QUERY, "--text", "标题", "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        check("找到" in result.stdout and "标题" in result.stdout,
              f"--text 应按界面文字命中节点，实际: {result.stdout.strip()[:300]}")

        # --style-raw：完整 style 用于排查白名单字段缺失
        result = subprocess.run(
            [sys.executable, QUERY, "--id", "12:34", "--style-raw",
             "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        check("style_raw:" in result.stdout,
              f"--style-raw 应输出完整 style JSON，实际: {result.stdout.strip()[:300]}")

        # --list-caches 补 dp 尺寸：同名画板靠 nodeId + 尺寸区分
        result = subprocess.run(
            [sys.executable, QUERY, "--list-caches", "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        check("dp" in result.stdout and "缓存甲" in result.stdout,
              f"--list-caches 应输出画板尺寸，实际: {result.stdout.strip()[:300]}")

        # 缓存锚定查询（另一个入口）同样不能丢切图文件名
        result = subprocess.run(
            [sys.executable, SELECTED, "--node-id", "12:34", "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        check("img_12_35.png" in result.stdout,
              f"figma_selected_node.py --node-id 子节点列表应带切图文件名，实际: {result.stdout.strip()[:300]}")

        # --assets: 切图清单（兑现"不提取就能查看切图清单"），缺 PNG 时标 missing
        result = subprocess.run(
            [sys.executable, QUERY, "--assets", "--md5", "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        out = result.stdout
        check(result.returncode == 0, f"--assets 应成功，实际 exit={result.returncode}")
        check("img_12_35.png" in out and "icon" in out,
              f"--assets 应列出切图文件名与图层名，实际: {out.strip()[:300]}")
        check("missing" in out,
              f"drawable-xxhdpi 下无 PNG 时应标 missing 而不是报错，实际: {out.strip()[:300]}")


def test_dp_local_nested() -> None:
    print("\n[8] 适配器 dp_local：三层嵌套，子/孙都相对父节点绝对坐标")
    with tempfile.TemporaryDirectory() as workdir:
        prepared = run_adapter(make_nested_composition(), workdir)
        root = load_tree(prepared)["root"]
        container = root["children"][0]
        child = container["children"][0]
        grandchild = child["children"][0]

        check(container["dp_local"]["x"] == 16.0 and container["dp_local"]["y"] == 8.0,
              f"容器 dp_local 应为 (16,8)，实际 {container['dp_local']}")
        check(child["dp_local"]["x"] == 4.0 and child["dp_local"]["y"] == 4.0,
              f"子节点 dp_local 应为 (4,4)，实际 {child['dp_local']}")
        check(grandchild["dp_local"]["x"] == 4.0 and grandchild["dp_local"]["y"] == 4.0,
              f"孙节点 dp_local 应为 (4,4)，实际 {grandchild['dp_local']}")


def test_auto_locate_across_caches() -> None:
    print("\n[9] query_node：--id 未命中最新缓存时自动跨缓存定位画板")
    with tempfile.TemporaryDirectory() as workdir:
        project_root = os.path.join(workdir, "proj")
        figma_dir = os.path.join(project_root, ".figma")

        def publish(produced: str, entry: str) -> None:
            prepared = os.path.join(figma_dir, entry, "figma_extract_prepared")
            os.makedirs(prepared, exist_ok=True)
            for name in os.listdir(produced):
                origin = os.path.join(produced, name)
                dest = os.path.join(prepared, name)
                if os.path.isdir(origin):
                    shutil.copytree(origin, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(origin, dest)

        # 目标缓存乙含 99:2；随后发布缓存甲并设为最新，让 --id 先命中错误画板。
        target = run_adapter(make_nested_composition(), os.path.join(workdir, "target"))
        tree_path = os.path.join(target, "android_tree.json")
        with open(tree_path, encoding="utf-8") as f:
            tree = json.load(f)
        tree["root"]["node_id"] = "99:1"
        tree["screen"]["artboard_id"] = "99:1"
        tree["root"]["children"][0]["children"][0]["node_id"] = "99:2"
        with open(tree_path, "w", encoding="utf-8") as f:
            json.dump(tree, f, ensure_ascii=False)
        publish(target, "figma_extract_目标")

        other = run_adapter(make_composition(artboard_width=1080, root_width=300),
                            os.path.join(workdir, "other"))
        publish(other, "figma_extract_最新")
        os.utime(os.path.join(figma_dir, "figma_extract_最新", "figma_extract_prepared",
                              "android_tree.json"))

        result = subprocess.run(
            [sys.executable, QUERY, "--id", "99:2", "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        out = result.stdout
        check("已自动定位到画板" in out and "99:1" in out,
              f"--id 未命中最新缓存时应自动定位到目标画板，实际: {out.strip()[:400]}")


def test_compare_nodes() -> None:
    print("\n[7] figma_compare_nodes.py：跨画板比对（文件名为节点寻址时不可比，内容签名可比）")
    with tempfile.TemporaryDirectory() as workdir:
        project_root = os.path.join(workdir, "proj")
        figma_dir = os.path.join(project_root, ".figma")

        def publish(produced: str, entry: str) -> str:
            prepared = os.path.join(figma_dir, entry, "figma_extract_prepared")
            os.makedirs(prepared, exist_ok=True)
            for name in os.listdir(produced):
                origin = os.path.join(produced, name)
                dest = os.path.join(prepared, name)
                if os.path.isdir(origin):
                    shutil.copytree(origin, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(origin, dest)
            return prepared

        # 两个画板各自独立产出（run_adapter 会覆盖同一个 figma_extract_prepared，故分开目录）
        prepared_a = publish(
            run_adapter(make_composition(with_image=True), os.path.join(workdir, "a")),
            "figma_extract_甲")
        prepared_b = publish(
            run_adapter(make_composition(with_image=True), os.path.join(workdir, "b")),
            "figma_extract_乙")

        # 乙板换成另一个画板 + 另一个 nodeId：节点寻址文件名随之改变，但内容是同一张图
        tree_b_path = os.path.join(prepared_b, "android_tree.json")
        with open(tree_b_path, encoding="utf-8") as f:
            tree_b = json.load(f)
        tree_b["screen"]["artboard_id"] = "7:777"
        tree_b["root"]["name"] = "画板乙"
        icon_b = tree_b["root"]["children"][0]
        old_file = icon_b["image"]["file"]
        new_file = "img_99_77.png"
        icon_b["node_id"] = "99:77"
        icon_b["image"]["file"] = new_file
        with open(tree_b_path, "w", encoding="utf-8") as f:
            json.dump(tree_b, f, ensure_ascii=False)

        same_png = b"\x89PNG\r\n\x1a\n" + b"same-visual-content"
        for prepared, file_name in ((prepared_a, old_file), (prepared_b, new_file)):
            drawable = os.path.join(prepared, "drawable-xxhdpi")
            os.makedirs(drawable, exist_ok=True)
            with open(os.path.join(drawable, file_name), "wb") as f:
                f.write(same_png)

        result = subprocess.run(
            [sys.executable, COMPARE, "--name", "icon", "--fuzzy",
             "--root-ids", "2:141,7:777", "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        out = result.stdout
        check(result.returncode == 0,
              f"比对应成功，实际 exit={result.returncode} stderr={result.stderr.strip()[:200]}")
        check(old_file in out and new_file in out,
              f"两个画板的切图文件名都应列出（{old_file} / {new_file}），实际: {out.strip()[:400]}")
        check("名字不同不代表视觉不同" in out,
              f"节点寻址文件名差异必须显式提示，否则会被误判为视觉不同，实际: {out.strip()[:400]}")
        check("跨画板 2 处" in out or "跨画板 1 处" in out,
              f"相同 PNG 内容应归入跨画板等价分组（含 N 处计数），实际: {out.strip()[:400]}")
        check("missing" not in out,
              f"PNG 存在时内容签名不应为 missing，实际: {out.strip()[:400]}")

        # 显式指定的画板未命中 → 报错退出，不静默跳过（少比一个画板会得出错误的"无差异"结论）
        result = subprocess.run(
            [sys.executable, COMPARE, "--name", "icon", "--fuzzy",
             "--root-ids", "2:141,9:999", "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        check(result.returncode != 0, "--root-ids 未命中应返回非零退出码")
        check("未找到根画板 9:999" in result.stdout,
              f"应明确报出未命中，实际: {result.stdout.strip()[:200]}")

        # 只命中 1 个画板时禁止报"完全一致"——那会让调用方误以为已确认无差异而提前收工（假阴性）
        result = subprocess.run(
            [sys.executable, COMPARE, "--name", "icon", "--fuzzy",
             "--root-ids", "2:141", "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        out = result.stdout
        check("各字段完全一致" not in out,
              f"只命中 1 个画板时禁止输出'完全一致'（假阴性），实际: {out.strip()[:400]}")
        check("未形成任何交叉比对" in out,
              f"只命中 1 个画板时必须说明未形成交叉比对，实际: {out.strip()[:400]}")
        check("无法交叉比对" in out and "仅见于" in out,
              f"单板命中项必须单列并说明无法比对，实际: {out.strip()[:400]}")

        # 命中 0 个画板的板要点名，避免"一致的沉默"被当成通过
        # （把乙板图标改名，使乙板对 "icon" 零命中，而甲板仍有命中）
        with open(tree_b_path, encoding="utf-8") as f:
            tree_b = json.load(f)
        tree_b["root"]["children"][0]["name"] = "图案A"
        with open(tree_b_path, "w", encoding="utf-8") as f:
            json.dump(tree_b, f, ensure_ascii=False)

        result = subprocess.run(
            [sys.executable, COMPARE, "--name", "icon", "--fuzzy",
             "--root-ids", "2:141,7:777", "--project-root", project_root],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        out = result.stdout
        check("一个同名节点都没命中" in out and "7:777" in out,
              f"零命中画板必须被点名（含 nodeId），实际: {out.strip()[:500]}")


def main() -> int:
    print("figma-android 离线自检")
    test_scale_basis()
    test_scale_fallback()
    test_validator_success()
    test_validator_blocked()
    test_cache_reuse()
    test_query_node_cli()
    test_dp_local_nested()
    test_auto_locate_across_caches()
    test_compare_nodes()

    print()
    if FAILURES:
        print(f"结果: FAIL（{len(FAILURES)} 项未通过）")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("结果: PASS（全部通过）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())