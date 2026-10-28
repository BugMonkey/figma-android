#!/usr/bin/env python3
"""校验桥模式产物 android_tree.json / assets.json 的结构与数值质量。

设计目标：单条命令回答"这份提取产物能不能直接用来写布局"。
校验对象是 figma_bridge_to_android.py 的**实际产出**（schema_version 2.0），
不再包含已废弃的 design_tree / MCP 通道产物。
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Windows GBK 终端兼容：强制 stdout/stderr UTF-8
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# 适配器可能产出的视图类型（其余类型记 warning，不阻塞）
KNOWN_VIEW_TYPES = {
    "FrameLayout", "LinearLayout", "ConstraintLayout", "RelativeLayout",
    "View", "TextView", "ImageView", "RecyclerView", "NestedScrollView",
    "ScrollView", "ViewGroup", "Button", "EditText",
}

DP_KEYS = ("x", "y", "w", "h")


def read_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
            return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def add(items: List[str], message: str) -> None:
    items.append(message)


def resolve_prepared_dir(extract_dir: Path) -> Path:
    """接受 extract 目录或 figma_extract_prepared 目录"""
    if extract_dir.name == "figma_extract_prepared" or (extract_dir / "android_tree.json").is_file():
        return extract_dir
    candidate = extract_dir / "figma_extract_prepared"
    if candidate.is_dir():
        return candidate
    return extract_dir


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_node(node: Any, path: str, screen: Dict[str, Any], drawable_dir: Path,
               seen_ids: Dict[str, str], errors: List[str], warnings: List[str],
               depth: int = 0) -> None:
    if not isinstance(node, dict):
        add(errors, f"{path} 必须是对象")
        return

    node_id = node.get("node_id")
    if not node_id:
        add(errors, f"{path} 缺少 node_id")
    elif node_id in seen_ids:
        add(errors, f"{path} node_id 重复: {node_id}（首次出现于 {seen_ids[node_id]}）")
    else:
        seen_ids[node_id] = path

    if not node.get("android_id"):
        add(warnings, f"{path} 缺少 android_id（生成 XML 需要 ID）")

    view_type = node.get("view_type")
    if not view_type:
        add(errors, f"{path} 缺少 view_type")
    elif view_type not in KNOWN_VIEW_TYPES:
        add(warnings, f"{path} view_type 不常见: {view_type}")

    dp = node.get("dp")
    if not isinstance(dp, dict):
        add(errors, f"{path} 缺少 dp 坐标")
    else:
        for key in DP_KEYS:
            value = dp.get(key)
            if not is_number(value):
                add(errors, f"{path}.dp.{key} 不是数值: {value!r}")
        # 分隔线在 Figma 里表达为「0 厚度 + stroke」：竖线 dp.w==0、横线 dp.h==0，
        # 视觉粗细由 style.border_width 承载。这是正确表达，不是尺寸错误。
        # 必须豁免，否则任何含分隔线的画板都会被判 blocked，而 blocked 会禁止生成代码；
        # 列表分隔线极为常见（本仓库 33 份产物中 5 份因此被误判），代价过高。
        style = node.get("style")
        border_w = style.get("border_width") if isinstance(style, dict) else None
        is_line = is_number(border_w) and border_w > 0
        if is_number(dp.get("w")) and dp["w"] <= 0 and not is_line:
            add(errors, f"{path}.dp.w 必须为正数: {dp['w']}")
        if is_number(dp.get("h")) and dp["h"] <= 0 and not is_line:
            add(errors, f"{path}.dp.h 必须为正数: {dp['h']}")
        max_w = screen.get("width_dp")
        max_h = screen.get("height_dp")
        if is_number(dp.get("w")) and is_number(max_w) and dp["w"] > max_w + 1:
            add(warnings, f"{path}.dp.w {dp['w']} 超出画板宽度 {max_w}")
        if is_number(dp.get("h")) and is_number(max_h) and dp["h"] > max_h + 1:
            add(warnings, f"{path}.dp.h {dp['h']} 超出画板高度 {max_h}")

    image = node.get("image")
    if isinstance(image, dict) and image:
        file_name = image.get("file")
        if not file_name:
            add(errors, f"{path} 有 image 字段但缺少 file")
        elif not (drawable_dir / file_name).is_file():
            add(warnings, f"{path} 切图文件不存在: drawable-xxhdpi/{file_name}")

    if view_type == "TextView" and not node.get("text"):
        add(warnings, f"{path} 是 TextView 但 text 为空")

    for index, child in enumerate(node.get("children", []) or []):
        check_node(child, f"{path}.children[{index}]", screen, drawable_dir,
                   seen_ids, errors, warnings, depth + 1)


def validate(extract_dir: Path) -> Dict[str, Any]:
    prepared = resolve_prepared_dir(extract_dir)
    tree_path = prepared / "android_tree.json"
    assets_path = prepared / "assets.json"
    meta_path = prepared / "source_meta.json"
    drawable_dir = prepared / "drawable-xxhdpi"

    errors: List[str] = []
    warnings: List[str] = []

    tree = read_json(tree_path)
    if not tree:
        add(errors, f"缺少 android_tree.json 或文件无效: {tree_path}")
        return {
            "status": "blocked",
            "extract_dir": str(prepared),
            "errors": errors,
            "warnings": warnings,
            "files": {"android_tree": str(tree_path)},
        }

    if tree.get("schema_version") != "2.0":
        add(errors, f"android_tree.schema_version 必须为 2.0，实际: {tree.get('schema_version')!r}")

    screen = tree.get("screen")
    if not isinstance(screen, dict):
        add(errors, "android_tree.screen 缺失")
        screen = {}
    else:
        for key in ("width_px", "width_dp", "height_px", "height_dp", "scale"):
            if not is_number(screen.get(key)):
                add(errors, f"android_tree.screen.{key} 不是数值: {screen.get(key)!r}")
        scale = screen.get("scale")
        if is_number(scale):
            if scale < 1 or scale > 4:
                add(errors, f"android_tree.screen.scale 越界（应在 1~4）: {scale}")
            width_px, width_dp = screen.get("width_px"), screen.get("width_dp")
            if is_number(width_px) and is_number(width_dp) and width_px > 0:
                expected = round(width_px / scale, 1)
                if abs(expected - width_dp) > 0.2:
                    add(errors, f"screen.width_dp ({width_dp}) 与 width_px/scale ({expected}) 不一致")
        if not is_number(screen.get("artboard_width_px")):
            add(warnings, "screen.artboard_width_px 缺失：该缓存由旧版适配器产出，"
                          "dp 换算基准可能不可信，建议用 figma_pull.py --force 重新提取")
        elif is_number(screen.get("width_px")) and abs(screen["artboard_width_px"] - screen["width_px"]) > 1:
            add(warnings, f"提取根不是顶层画板（提取根 {screen['width_px']}px / "
                          f"画板 {screen['artboard_width_px']}px），dp 已按画板宽度换算")

    root = tree.get("root")
    if not isinstance(root, dict) or not root:
        add(errors, "android_tree.root 缺失")
    else:
        seen_ids: Dict[str, str] = {}
        check_node(root, "root", screen, drawable_dir, seen_ids, errors, warnings)
        if not root.get("children"):
            add(warnings, "android_tree.root 无 children（画板可能为空或提取异常）")

    for key, expect_type in (("regions", list), ("repeat_groups", list),
                             ("texts", list), ("colors", dict)):
        if key in tree and not isinstance(tree.get(key), expect_type):
            add(errors, f"android_tree.{key} 类型应为 {expect_type.__name__}")

    # assets.json 与磁盘切图交叉校验
    if assets_path.is_file():
        assets = read_json(assets_path)
        items = assets.get("assets")
        if not isinstance(items, list):
            add(errors, "assets.json.assets 缺失或类型错误")
        else:
            for index, asset in enumerate(items):
                if not isinstance(asset, dict):
                    add(errors, f"assets.assets[{index}] 必须是对象")
                    continue
                file_name = asset.get("file")
                if not file_name:
                    add(errors, f"assets.assets[{index}] 缺少 file")
                elif not (drawable_dir / file_name).is_file():
                    add(errors, f"assets.assets[{index}] 切图文件不存在: drawable-xxhdpi/{file_name}")
                if not asset.get("node_id"):
                    add(warnings, f"assets.assets[{index}] 缺少 node_id（无法追溯到 Figma 节点）")
    else:
        add(warnings, "缺少 assets.json（画板可能无切图）")

    # source_meta 与 screen 的换算因子交叉校验
    if meta_path.is_file():
        meta = read_json(meta_path)
        coordinate_scale = (meta.get("design") or {}).get("coordinate_scale")
        scale = screen.get("scale")
        if is_number(coordinate_scale) and is_number(scale) and abs(coordinate_scale - scale) > 0.05:
            add(errors, f"source_meta.coordinate_scale ({coordinate_scale}) 与 "
                        f"screen.scale ({scale}) 不一致（切图尺寸校正会算错）")
    else:
        add(warnings, "缺少 source_meta.json")

    status = "success"
    if errors:
        status = "blocked"
    elif warnings:
        status = "warning"

    return {
        "status": status,
        "extract_dir": str(prepared),
        "errors": errors,
        "warnings": warnings,
        "files": {
            "android_tree": str(tree_path),
            "assets": str(assets_path),
            "source_meta": str(meta_path),
        },
    }


def to_markdown(result: Dict[str, Any]) -> str:
    lines = [
        "# Figma 产物校验报告",
        "",
        f"- status: `{result['status']}`",
        f"- extract_dir: `{result['extract_dir']}`",
        "",
        "## Errors",
    ]
    lines.extend([f"- {item}" for item in result["errors"]] or ["- 无"])
    lines.append("")
    lines.append("## Warnings")
    lines.extend([f"- {item}" for item in result["warnings"]] or ["- 无"])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 bridge 模式产物 (android_tree.json / assets.json)")
    parser.add_argument("extract_dir", help="figma_extract 目录或 figma_extract_prepared 目录")
    parser.add_argument("--target", choices=["android", "all"], default="android",
                        help="校验目标（桥模式仅 android 产物）")
    parser.add_argument("--write-report", nargs="?", const="tree_validation_report.md")
    args = parser.parse_args()

    result = validate(Path(args.extract_dir))
    if args.write_report:
        report_path = Path(args.write_report)
        if not report_path.is_absolute():
            report_path = Path(result["extract_dir"]) / report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(to_markdown(result), encoding="utf-8")
        result["report"] = str(report_path)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] != "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())