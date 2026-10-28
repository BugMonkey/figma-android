#!/usr/bin/env python3
"""
figma_bridge_to_android.py — Figma 插件原始数据 → android_tree.json 适配器

将插件导出的 composition.json (Raw Figma Node 树) 转换为
与 MCP 管道完全一致的 android_tree.json + source_meta.json + assets.json。

输出 schema 与 figma_prepare_android.py 完全对齐。
Agent 代码生成无感知切换。

用法:
  python3 figma_bridge_to_android.py <composition.json> [--output-dir <dir>]
"""

import json
import os
import re
import sys
import math
import hashlib
from collections import defaultdict



# Windows GBK 终端兼容：强制 stdout/stderr UTF-8
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SCALE = None  # 运行时从画板宽度计算


# ─── 工具函数 ───

def hex_color(r: float, g: float, b: float, a: float = 1.0) -> str:
    """Figma 0..1 颜色 → #RRGGBB 或 #AARRGGBB（Android Color.parseColor 约定：透明度在首位）"""
    ri, gi, bi, ai = [max(0, min(255, round(v * 255))) for v in (r, g, b, a)]
    if ai < 255:
        return f"#{ai:02x}{ri:02x}{gi:02x}{bi:02x}"
    return f"#{ri:02x}{gi:02x}{bi:02x}"


def slugify(name: str) -> str:
    """中文/特殊字符 → 下划线"""
    s = re.sub(r'[\\/:*?"<>| \'!@#$%^&()+=[\]{};,.`~]', '_', name)
    s = re.sub(r'_+', '_', s).strip('_')
    return s or 'unnamed'


def node_id_numeric(node_id: str) -> str:
    """1:616 → 1_616"""
    return node_id.replace(":", "_")


def make_android_id(name: str, node_id: str, view_type: str) -> str:
    """生成 android_id"""
    prefix_map = {
        "View": "view_shape",
        "TextView": "tv",
        "ImageView": "iv",
        "FrameLayout": "fl",
        "LinearLayout": "ll",
        "ConstraintLayout": "cl",
        "RecyclerView": "rv",
    }
    prefix = prefix_map.get(view_type, "view")
    slug = slugify(name)[:20]
    nid = node_id_numeric(node_id)
    if slug:
        return f"{prefix}_{slug}_{nid}"
    return f"{prefix}_{nid}"


# ─── 样式解析 ───

def parse_fills(fills: list, is_text_node: bool = False) -> dict:
    """解析 fills → style (background / text_color)"""
    style = {}
    if not fills:
        return style

    solid = [f for f in fills if f.get("type") == "SOLID" and f.get("visible", True) is not False]
    gradient = [f for f in fills if f.get("type", "").startswith("GRADIENT") and f.get("visible", True) is not False]
    image = [f for f in fills if f.get("type") == "IMAGE" and f.get("visible", True) is not False]

    # 对于 TEXT 节点，fills 是文字颜色，不是背景色
    if is_text_node:
        if solid:
            c = solid[0]["color"]
            a = c.get("a", 1)
            style["text_color"] = hex_color(c["r"], c["g"], c["b"], a)
        # 不设置 background
        return style

    # 非 TEXT 节点：fills = background
    if solid:
        c = solid[0]["color"]
        a = c.get("a", 1)
        style["background"] = hex_color(c["r"], c["g"], c["b"], a)

    if gradient:
        gf = gradient[0]
        stops = gf.get("gradientStops", [])
        if len(stops) >= 2:
            colors = []
            positions = []
            for s in stops:
                sc = s["color"]
                colors.append(hex_color(sc["r"], sc["g"], sc["b"], sc.get("a", 1)))
                positions.append(s.get("position", 0))
            style["background_is_gradient"] = True
            style["gradient_colors"] = colors
            style["gradient_positions"] = positions
            if not solid:
                style["background"] = colors[0]

    if image:
        imf = image[0]
        style["background_is_image"] = True
        if imf.get("imageHash"):
            style["image_hash"] = imf["imageHash"]

    return style


def parse_strokes(strokes: list, stroke_weight: float = None, stroke_align: str = None) -> dict:
    """解析 strokes → border style"""
    style = {}
    if not strokes:
        return style
    visible = [s for s in strokes if s.get("visible", True) is not False]
    if not visible:
        return style
    s = visible[0]
    c = s.get("color", {})
    if c:
        style["border_color"] = hex_color(c.get("r", 0), c.get("g", 0), c.get("b", 0), c.get("a", 1))
        style["border_style"] = "solid"
    if stroke_weight is not None and stroke_weight > 0:
        style["border_width"] = round(stroke_weight / SCALE, 1)
    return style


def parse_radii(radii: dict) -> float:
    """解析 cornerRadius → corner_radius_dp"""
    if not radii:
        return 0
    r = radii.get("uniform", 0) or 0
    if not r and "t" in radii:
        r = max(radii.get("t", 0), radii.get("r", 0), radii.get("b", 0), radii.get("l", 0))
    return round(r / SCALE, 1) if r else 0


def parse_effects(effects: list) -> list:
    """解析 effects → 结构化数据"""
    result = []
    if not effects:
        return result
    for e in effects:
        item = {"type": e.get("type", "")}
        offset = e.get("offset")
        if offset:
            item["offset_x"] = offset.get("x", 0)
            item["offset_y"] = offset.get("y", 0)
        if e.get("radius") is not None:
            item["radius"] = e["radius"]
        if e.get("spread") is not None:
            item["spread"] = e["spread"]
        color = e.get("color")
        if color:
            item["color"] = hex_color(color.get("r", 0), color.get("g", 0), color.get("b", 0), color.get("a", 1))
        result.append(item)
    return result


def parse_font_weight(weight: int, font_style: str = "") -> str:
    """Figma fontWeight + style → Android textStyle"""
    w = weight or 400
    s = (font_style or "").lower()
    if "italic" in s:
        return "italic"
    if w >= 700:
        return "bold"
    if w >= 600:
        return "bold"  # semi-bold 也映射 bold
    return "normal"


# ─── 节点遍历 ───

def walk_node(node: dict, artboard_origin: tuple, parent_dp: dict = None, is_root: bool = False) -> dict | None:
    """
    遍历插件导出的 Raw Node 树 → 标准 android_tree 节点格式
    """
    if not node or node.get("visible") is False:
        if node and node.get("visible") is False:
            name = node.get("name", "unnamed")
            nid = node.get("id", "")
            print(f"  [跳过 invisible 节点] name={name} id={nid}")
        return None

    # opacity=0 → 完全透明，视觉上不可见，丢弃
    if node.get("opacity", 1) == 0:
        name = node.get("name", "unnamed")
        nid = node.get("id", "")
        print(f"  [跳过 opacity=0 节点] name={name} id={nid}")
        return None

    ntype = node.get("type", "")
    name = node.get("name", "unnamed")
    node_id = node.get("id", "")
    rel_x = node.get("x", 0) or 0
    rel_y = node.get("y", 0) or 0
    width = node.get("width", 0) or 0
    height = node.get("height", 0) or 0
    opacity = node.get("opacity", 1)

    # 坐标换算 px → dp
    dp_x = round(rel_x / SCALE, 1)
    dp_y = round(rel_y / SCALE, 1)
    dp_w = round(width / SCALE, 1)
    dp_h = round(height / SCALE, 1)

    # 跳过零尺寸且无子节点的节点
    if dp_w <= 0 and dp_h <= 0 and not node.get("children"):
        return None

    # view_type 映射
    # 优先级：TEXT > 根画板(容器) > export_as_image > IMAGE fill > 有子节点的容器 > 纯装饰
    # export_as_image / IMAGE fill 优先于 has_children（子节点场景），与插件 collectImageNodes
    # 一致：标记为整张切图的节点导出 PNG 后不拆解子节点（INSTANCE/矢量图标/面板标记/IMAGE fill）。
    # 根画板用 is_root 强制 FrameLayout，保证整页布局仍按结构生成（根画板可能被标记切图）。
    if ntype == "TEXT":
        view_type = "TextView"
    elif is_root:
        view_type = "FrameLayout"
    elif node.get("export_as_image"):
        view_type = "ImageView"
    elif _has_image_fill(node):
        view_type = "ImageView"
    elif node.get("children") and len(node.get("children", [])) > 0:
        view_type = "FrameLayout"
    else:
        view_type = "View"

    android_id = make_android_id(name, node_id, view_type)

    result = {
        "node_id": node_id,
        "name": name,
        "view_type": view_type,
        "android_id": android_id,
        "dp": {"x": dp_x, "y": dp_y, "w": dp_w, "h": dp_h},
        "visible": node.get("visible", True) is not False,
    }

    # dp_local = 绝对坐标 - 父节点绝对坐标。插件导出的 x/y 已是相对画板的绝对坐标，
    # 父节点必须传绝对 dp，不能传父节点自己的 dp_local（那是相对祖父的，坐标系不一致）。
    if parent_dp:
        lx = round(dp_x - parent_dp.get("x", 0), 1)
        ly = round(dp_y - parent_dp.get("y", 0), 1)
        result["dp_local"] = {"x": lx, "y": ly, "w": dp_w, "h": dp_h}
    else:
        result["dp_local"] = {"x": dp_x, "y": dp_y, "w": dp_w, "h": dp_h}

    # 切图标记（通过 setPluginData 设置）
    if node.get("export_as_image"):
        result["export_as_image"] = True

    # 样式
    style_raw = node.get("style", {}) or {}
    style = {}
    is_text = ntype == "TEXT"

    # fills
    fills = style_raw.get("fills")
    if fills:
        style.update(parse_fills(fills, is_text_node=is_text))

    # strokes
    strokes = style_raw.get("strokes")
    sw = style_raw.get("strokeWeight")
    if strokes:
        style.update(parse_strokes(strokes, sw))

    # corner radius
    cr = style_raw.get("cornerRadius")
    crii = style_raw.get("cornerRadii")
    if cr is not None and cr > 0:
        cr_dp = round(cr / SCALE, 1)
        if cr_dp > 0:
            style["corner_radius_dp"] = cr_dp
    elif crii and len(crii) == 4:
        max_cr = max(crii)
        if max_cr > 0:
            style["corner_radius_dp"] = round(max_cr / SCALE, 1)

    # effects
    effects_raw = style_raw.get("effects")
    if effects_raw:
        effects = parse_effects(effects_raw)
        if effects:
            style["effects"] = effects
            # 阴影偏移补偿：DROP_SHADOW 会导致 exportAsync 导出的 PNG 比节点几何尺寸大，
            # 内容在图内产生偏移。计算 shadow_padding 供 Agent 正确设置 ImageView 尺寸/边距。
            # 阴影各方向扩展量 = radius + spread ± offset（取绝对值，不小于 0）。
            # 仅对切图导出节点计算 shadow_padding，容器节点应使用 Android elevation。
            # 存在多个阴影时取各方向最大值。
            is_export = node.get("export_as_image", False)
            if is_export:
                pad_l = pad_r = pad_t = pad_b = 0
                for eff in effects:
                    if eff.get("type") == "DROP_SHADOW":
                        dx = eff.get("offset_x", 0)
                        dy = eff.get("offset_y", 0)
                        r = eff.get("radius", 0)
                        s = eff.get("spread", 0)
                        pad_l = max(pad_l, r + s - dx)
                        pad_r = max(pad_r, r + s + dx)
                        pad_t = max(pad_t, r + s - dy)
                        pad_b = max(pad_b, r + s + dy)
                if pad_l > 0 or pad_r > 0 or pad_t > 0 or pad_b > 0:
                    style["shadow_padding"] = {
                        "left": round(pad_l / SCALE, 1),
                        "right": round(pad_r / SCALE, 1),
                        "top": round(pad_t / SCALE, 1),
                        "bottom": round(pad_b / SCALE, 1),
                    }

    # opacity
    if opacity is not None and opacity < 1:
        style["opacity"] = round(opacity, 2)

    # Auto Layout hints
    layout_mode = node.get("layoutMode")
    if layout_mode and layout_mode != "NONE":
        style["auto_layout"] = layout_mode.lower()
        if node.get("itemSpacing") is not None:
            style["item_spacing"] = round(node["itemSpacing"] / SCALE, 1)
        for pad_key in ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft"]:
            val = node.get(pad_key)
            if val is not None and val > 0:
                style["padding" if "padding" not in style else "padding"] = round(val / SCALE, 1)
                break
        if node.get("primaryAxisAlignItems"):
            style["primary_align"] = node["primaryAxisAlignItems"].lower()
        if node.get("counterAxisAlignItems"):
            style["counter_align"] = node["counterAxisAlignItems"].lower()

    # textAutoResize
    text_auto = node.get("textAutoResize")
    if text_auto:
        style["text_auto_resize"] = text_auto

    # clipsContent
    if node.get("clipsContent"):
        result["overflow"] = "hidden"

    # 文本处理
    text_content = ""
    if is_text:
        text_raw = node.get("text", {})
        text_content = text_raw.get("characters", "")
        result["text"] = text_content

        ta_h = node.get("textAlignHorizontal")
        if ta_h:
            style["text_align"] = ta_h.lower()

        # segments → 取第一个 segment 的样式，保留全部 segments 供 Agent 处理富文本
        segments = node.get("segments", [])
        if segments:
            seg = segments[0]
            fs = seg.get("fontSize")
            if fs:
                style["font_size_sp"] = round(fs / SCALE, 1)
            fn = seg.get("fontName", {})
            if fn.get("family"):
                family = fn["family"]
                fw = seg.get("fontWeight", 400)
                fs_str = fn.get("style", "")
                weight_label = parse_font_weight(fw, fs_str)
                style["font_family"] = f"{family}:{weight_label}"
                style["font_weight"] = fw
                style["text_style"] = weight_label

            # seg fills 覆盖 text_color
            seg_fills = seg.get("fills", [])
            solid_seg = [f for f in seg_fills if f.get("type") == "SOLID"]
            if solid_seg:
                sc = solid_seg[0]["color"]
                style["text_color"] = hex_color(sc["r"], sc["g"], sc["b"], sc.get("a", 1))

            lh = seg.get("lineHeight", {})
            if isinstance(lh, dict) and lh.get("value"):
                style["line_height_px"] = lh["value"]
            elif isinstance(lh, dict) and lh.get("unit") == "PERCENT" and lh.get("value") and fs:
                style["line_height_px"] = round(lh["value"] / 100 * fs)

            # 保留全部 segments 的富文本信息
            if len(segments) > 1:
                result["text_segments"] = []
                for s in segments:
                    ts = {
                        "start": s.get("start", 0),
                        "end": s.get("end", 0),
                    }
                    sfs = s.get("fontSize")
                    if sfs:
                        ts["font_size_sp"] = round(sfs / SCALE, 1)
                    sf = s.get("fontName", {})
                    if sf.get("family"):
                        ts["font_family"] = sf["family"]
                    ts["font_weight"] = s.get("fontWeight", 400)
                    sfills = s.get("fills", [])
                    sfsolid = [f for f in sfills if f.get("type") == "SOLID"]
                    if sfsolid:
                        sc = sfsolid[0]["color"]
                        ts["color"] = hex_color(sc["r"], sc["g"], sc["b"], sc.get("a", 1))
                    result["text_segments"].append(ts)

        # segment 没有覆盖时用顶层 fills 做 text_color
        if "text_color" not in style and fills:
            solid = [f for f in fills if f.get("type") == "SOLID"]
            if solid:
                c = solid[0]["color"]
                style["text_color"] = hex_color(c["r"], c["g"], c["b"], c.get("a", 1))

    # export_as_image 节点 → 整张切图，设置 image 字段指向插件导出的 PNG
    if node.get("export_as_image"):
        result["image"] = {
            "src": f"plugin://{node_id}",
            "file": f"img_{node_id[:12].replace(':', '_')}.png",
        }

    # IMAGE fill → image 字段（含 imageTransform）
    if _has_image_fill(node):
        hash_val = _get_image_hash(node)
        if hash_val:
            img_entry = {
                "src": f"plugin://{hash_val}",
                "file": f"img_{hash_val[:12]}.png",
            }
            tf = _get_image_transform(node)
            if tf:
                img_entry["transform"] = tf
            result["image"] = img_entry

    if style:
        result["style"] = style

    # 递归子节点
    # 容器类节点（FrameLayout）才遍历内部结构。export_as_image 的容器根画板
    # 尽管被标记为整张切图，但仍需解开内部结构供布局生成用。
    # 纯 ImageView/View 节点跳过子节点，保持整体作为原子切图。
    container_types = ("FrameLayout", "LinearLayout", "ConstraintLayout", "RecyclerView", "ScrollView")
    if view_type in container_types:
        children_raw = node.get("children", [])
        if children_raw:
            children = []
            for child in children_raw:
                cr = walk_node(child, artboard_origin, result["dp"])
                if cr is not None:
                    children.append(cr)
            if children:
                result["children"] = children
            # 视觉包围盒修正（Visual Bounds Fix）
            # Figma 中部分容器 Frame 的 bounds 带有透明留白（内部元素用负偏移溢出容器边界，
            # 如返回箭头 Vector2 绝对 x=28.8 而容器 bounds x=44.7）。
            # 此时 android_tree 报容器 bounds 而非视觉元素实际位置，导致无法一比一还原。
            # 修正：取子元素并集包围盒重写容器 dp/dp_local，保证与 Figma 视觉坐标一致。
            # 保护（不修正）：
            # 1. export_as_image 的切图节点——整图导出的 bounds 即正确定位，子元素仅供结构参考，
            #    其视觉位置由切图本身决定，不应按子元素包围盒改写（否则会偏离切图实际位置）。
            # 2. overflow=hidden 的容器——依赖自身 bounds 精准定位，内部溢出是 Clipping/裁切效果。
            if not node.get("export_as_image") and result.get("overflow") != "hidden":
                result = _fix_container_visual_bounds(result)

    return result


def _fix_container_visual_bounds(node: dict) -> dict:
    """
    对"内容溢出容器边界"的容器修正视觉包围盒。

    触发条件：子元素向容器左侧溢出（dp_local.x 为负）。
    这类溢出通常是"原子图标容器留白"（如返回箭头 Vector2 绝对 x=28.8
    而容器 bounds x=44.7）——容器 bounds 含透明留白，视觉元素实际偏左。
    修正：仅平移 x，使最左子元素成为容器左边界，与 Figma 视觉坐标一致。

    不处理的情况（保持原样，避免误伤）：
    - overflow=hidden 的容器（根画板、被裁剪层）——bounds 是定位基准
    - 子元素向上溢出（min_dy<0，如背景层太阳/光晕装饰）——容器 y 是正确起点
    """
    children = node.get("children", [])
    if not children:
        return node

    # 子元素相对容器的最小水平偏移（仅关注左溢出）
    min_dx = min(c["dp_local"]["x"] for c in children)

    # 仅当子元素向容器左侧溢出时修正（水平留白）
    if min_dx >= 0:
        return node

    # 视觉包围盒宽度（相对原容器左上角）
    max_dx = max(c["dp_local"]["x"] + c["dp_local"]["w"] for c in children)
    vw = max(max_dx - min_dx, 0)
    if vw <= 0:
        return node

    # 新容器 x = 原容器 x + 左侧溢出量（y 保持不动）
    new_x = round(node["dp"]["x"] + min_dx, 1)

    # 更新容器 dp（仅 x / w）
    node["dp"]["x"] = new_x
    node["dp"]["w"] = round(vw, 1)

    # 平移所有子元素 dp_local.x，使最左子元素对齐新容器左边界
    for c in children:
        c["dp_local"]["x"] = round(c["dp_local"]["x"] - min_dx, 1)

    # 同步本节点 dp_local.x
    p = node.get("dp_local")
    if p is not None:
        p["x"] = round(p["x"] + min_dx, 1)
        p["w"] = round(vw, 1)

    node["_visual_bounds_fixed"] = True
    return node


def _has_image_fill(node: dict) -> bool:
    """检查节点是否有 IMAGE fill"""
    style = node.get("style", {}) or {}
    fills = style.get("fills", [])
    return any(f.get("type") == "IMAGE" and f.get("visible", True) is not False for f in fills)


def _get_image_hash(node: dict) -> str:
    """获取 IMAGE fill 的 imageHash"""
    style = node.get("style", {}) or {}
    fills = style.get("fills", [])
    for f in fills:
        if f.get("type") == "IMAGE" and f.get("visible", True) is not False:
            return f.get("imageHash", "")
    return ""


def _get_image_transform(node: dict):
    """获取 IMAGE fill 的 imageTransform（非空且非单位矩阵时返回）"""
    style = node.get("style", {}) or {}
    fills = style.get("fills", [])
    for f in fills:
        if f.get("type") == "IMAGE" and f.get("visible", True) is not False:
            tf = f.get("imageTransform")
            if tf and _is_non_identity(tf):
                return tf
    return None


def _is_non_identity(tf: list) -> bool:
    """判断 2×3 矩阵是否非单位矩阵（略去极小浮点误差）"""
    if not isinstance(tf, list) or len(tf) != 2:
        return False
    EPS = 1e-6
    expect = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    for i in (0, 1):
        if not isinstance(tf[i], list) or len(tf[i]) != 3:
            return False
        for j in (0, 1, 2):
            if abs(tf[i][j] - expect[i][j]) > EPS:
                return True
    return False


# ─── 图层去冗余 ───

def simplify_tree(node: dict) -> dict:
    """
    移除无意义嵌套：
    - 空 GROUP/FRAME
    - 只有一个子节点的冗余容器（子节点视口与父相同）
    """
    children = node.get("children", [])
    if not children:
        return node

    # 递归先处理子节点
    simplified = []
    for child in children:
        sc = simplify_tree(child)
        if sc is not None:
            simplified.append(sc)

    # 去空
    if not simplified and node.get("view_type") not in ("TextView", "ImageView"):
        return None

    node["children"] = simplified
    return node


# ─── Regions 检测 ───

def detect_regions(root: dict) -> list:
    """基于 y 坐标聚类自动划分视觉区域"""
    all_nodes = []

    def collect(n):
        all_nodes.append(n)
        for c in n.get("children", []):
            collect(c)

    collect(root)

    if not all_nodes:
        return []

    # 按 y 排序
    sorted_nodes = sorted(all_nodes, key=lambda n: n["dp"]["y"])

    # 简化：按 y 坐标 50dp 阈值聚簇
    regions = []
    current_region = None

    for n in sorted_nodes:
        dp = n["dp"]
        y = dp["y"]
        h = dp["h"]
        cy = y + h / 2  # center y

        if current_region is None:
            current_region = {"y_start": y, "y_end": y + h, "nodes": [n]}
        elif y - current_region["y_end"] > 50:  # 间隙 > 50dp → 新区域
            regions.append(current_region)
            current_region = {"y_start": y, "y_end": y + h, "nodes": [n]}
        else:
            current_region["y_end"] = max(current_region["y_end"], y + h)
            current_region["nodes"].append(n)

    if current_region:
        regions.append(current_region)

    # 命名
    region_names = [
        "状态栏区", "顶部操作区", "Banner 区", "优惠充值区",
        "工具栏区", "大家都在买区", "商品列表区", "支付方式区",
        "底部按钮区", "底部 Tab 区"
    ]

    result = []
    for i, r in enumerate(regions):
        name = region_names[i] if i < len(region_names) else f"区域 {i + 1}"
        result.append({
            "id": f"region_{i}",
            "name": name,
            "y_range_dp": [round(r["y_start"], 1), round(r["y_end"], 1)],
            "fixed": i == 0 or i == len(regions) - 1,
            "children_ids": [n["node_id"] for n in r["nodes"]],
        })

    return result


# ─── 重复模式检测 ───

def detect_repeat_groups(root: dict) -> list:
    """
    轻量检测：扫描两级（root.children + 容器子节点），
    按结构签名匹配连续兄弟节点。
    不做业务裁决，不判断 RecyclerView vs 内联。
    目的：给结构确认环节提供可提问的素材。

    匹配规则：view_type + children_count + auto_layout 三者全相同。

    两级策略：
    - Level 0: root.children — 页面顶层重复（商品卡片、商品格子）
    - Level 1: 容器型 root.children[i].children — 嵌套重复（充值入口、tab 图标）

    过滤：
    - 跳过 View（背景/装饰层）
    - 跳过 TextView（标题/价格语义差异大，容易误判）
    - 跳过无子节点的 FrameLayout（空容器）
    - 跳过深度 > 1 的子结构（避免 item 内部噪音）
    """
    groups = []

    def sig(n: dict) -> str:
        vt = n.get("view_type", "?")
        cc = len(n.get("children", []))
        al = (n.get("style", {}) or {}).get("auto_layout", "")
        return f"{vt}|c{cc}|{al}"

    def is_skippable(n: dict) -> bool:
        vt = n.get("view_type", "?")
        if vt == "View":
            return True
        if vt == "TextView":
            return True
        if vt == "FrameLayout" and not n.get("children"):
            return True
        return False

    def layout_direction(nodes: list) -> str:
        first_y = nodes[0]["dp"]["y"]
        return "horizontal" if all(abs(n["dp"]["y"] - first_y) < 10 for n in nodes[1:]) else "vertical"

    def scan_children(children, parent):
        if len(children) < 2:
            return
        i = 0
        while i < len(children):
            if is_skippable(children[i]):
                i += 1
                continue
            s = sig(children[i])
            j = i + 1
            while j < len(children) and sig(children[j]) == s:
                j += 1
            run_len = j - i
            if run_len >= 2:
                run_nodes = children[i:j]
                groups.append({
                    "parent_node_id": parent.get("node_id", ""),
                    "parent_name": parent.get("name", ""),
                    "count": run_len,
                    "layout_hint": layout_direction(run_nodes),
                    "signature": s,
                    "item_names": [n.get("name", "") for n in run_nodes],
                    "node_ids": [n.get("node_id", "") for n in run_nodes],
                    "y_range_dp": [
                        min(n["dp"]["y"] for n in run_nodes),
                        max(n["dp"]["y"] + n["dp"]["h"] for n in run_nodes),
                    ],
                    "item_size_dp": {
                        "w": run_nodes[0]["dp"]["w"],
                        "h": run_nodes[0]["dp"]["h"],
                    },
                })
            i = j

    # Level 0
    scan_children(root.get("children", []), root)

    # Level 1
    for rc in root.get("children", []):
        if rc.get("children") and len(rc["children"]) >= 2:
            scan_children(rc["children"], rc)

    return groups


# ─── Colors / Texts 收集 ───

def collect_colors(root: dict) -> dict:
    """收集所有颜色"""
    colors = {}

    def walk(n):
        st = n.get("style", {}) or {}
        for key in ("background", "text_color", "border_color"):
            val = st.get(key)
            if val and val.startswith("#"):
                colors[val] = colors.get(val, 0) + 1
        for c in n.get("children", []):
            walk(c)

    walk(root)
    return colors


def collect_texts(root: dict) -> list:
    """收集所有文本"""
    texts = []

    def walk(n):
        txt = n.get("text", "")
        if txt:
            texts.append({
                "node_id": n["node_id"],
                "text": txt,
                "font_size_sp": (n.get("style", {}) or {}).get("font_size_sp"),
                "text_color": (n.get("style", {}) or {}).get("text_color"),
            })
        for c in n.get("children", []):
            walk(c)

    walk(root)
    return texts


def count_nodes(node: dict) -> int:
    count = 1
    for c in node.get("children", []):
        count += count_nodes(c)
    return count


# ─── 主函数 ───

def build_android_tree(composition: dict) -> dict:
    global SCALE

    # 兼容两种格式:
    # A) 新插件格式: { width, height, name, nodeId, nodeTree: {...}, ... }
    # B) 旧 Figma-Bridge 格式: { children: [{ width, height, name, id, ... }], ... }
    node_tree = composition.get("nodeTree")
    width_px = composition.get("width", 0)
    height_px = composition.get("height", 0)
    name = composition.get("name", "页面")
    node_id = composition.get("nodeId", "")
    # dp 换算基准：优先用插件上报的真实根画板宽度（artboardWidth）。
    # 提取根是子节点（内层 Frame）时 composition.width 只是该节点宽度，
    # 用它算 scale 会得到错误倍数，且全树 dp 静默偏差。老插件无该字段时退回 width_px。
    artboard_width_px = composition.get("artboardWidth") or width_px

    if (not width_px or not height_px) and composition.get("children"):
        artboard = composition["children"][0]
        node_tree = node_tree or artboard
        width_px = width_px or artboard.get("width", 0)
        height_px = height_px or artboard.get("height", 0)
        name = name if name != "页面" else artboard.get("name", name)
        node_id = node_id or artboard.get("id", "")

    if not width_px or not height_px or not node_tree:
        raise ValueError("composition missing width/height or nodeTree")

    # 动态计算 scale（支持 360/375/414 等不同设计宽度），基准为真实根画板宽度
    SCALE = round(artboard_width_px / 360, 1) if artboard_width_px <= 500 else round(artboard_width_px / 360)
    if SCALE < 1:
        SCALE = 1
    if SCALE > 4:
        SCALE = 4

    if width_px and abs(artboard_width_px - width_px) > 1:
        print(f"  [警告] 提取根不是顶层画板: 提取根 {width_px:.0f}px / 画板 {artboard_width_px:.0f}px，"
              f"dp 已按画板宽度换算 (scale={SCALE})")

    width_dp = round(width_px / SCALE, 1)
    height_dp = round(height_px / SCALE, 1)

    artboard_origin = (0, 0)

    # 遍历节点树（根画板强制容器，即使被标记 export_as_image）
    root = walk_node(node_tree, artboard_origin, is_root=True)

    if root is None:
        raise ValueError("Failed to walk node tree")

    # 去冗余
    root = simplify_tree(root)
    # 重复模式检测（供结构确认环节提问用，不做业务裁决）
    repeat_groups = detect_repeat_groups(root)


    # regions
    regions = detect_regions(root)

    # colors / texts
    colors = collect_colors(root)
    texts = collect_texts(root)
    total_nodes = count_nodes(root)

    tree = {
        "schema_version": "2.0",
        "screen": {
            "width_px": width_px,
            "width_dp": width_dp,
            "height_px": height_px,
            "height_dp": height_dp,
            "scale": SCALE,
            # 真实根画板宽度/ID：dp 换算基准，同时也是"本缓存为当前版适配器产物"的标记
            "artboard_width_px": artboard_width_px,
            "artboard_id": composition.get("artboardId", "") or node_id,
        },
        "root": root,
        "regions": regions,
        "repeat_groups": repeat_groups,
        "colors": colors,
        "texts": texts,
    }
    return tree


def build_source_meta(composition: dict, tree: dict) -> dict:
    width_px = composition.get("width", 0)
    height_px = composition.get("height", 0)
    screen = tree.get("screen", {})
    node_count = tree.get("root") and count_nodes(tree["root"]) or 0
    text_count = len(tree.get("texts", []))
    img_count = len([a for a in tree.get("root", {}).get("children", []) if _has_image_fill(a)])
    region_count = len(tree.get("regions", []))

    return {
        "source": "figma_bridge_to_android.py v2",
        "file": {
            "file_key": composition.get("fileKey", ""),
            "file_name": composition.get("fileName", ""),
            "page_name": composition.get("pageName", ""),
        },
        "design": {
            "width_px": float(width_px),
            "width_dp": screen.get("width_dp", 360),
            "height_px": float(height_px),
            "height_dp": screen.get("height_dp", 800),
            "density": "xxhdpi",
            # 必须保留小数：scale 非整数时（如 400px 画板 → 1.1）取整会让
            # 切图尺寸校正（correct_image_dimensions）与实际 dp 换算不一致
            "coordinate_scale": SCALE,
        },
        "stats": {
            "total_elements": node_count,
            "text_elements": text_count,
            "image_assets": img_count,
            "regions": region_count,
        },
    }


def build_assets(tree: dict) -> dict:
    assets = []

    def walk(n):
        img = n.get("image")
        if img and img.get("file"):
            assets.append({
                "name": n.get("name", ""),
                "file": img["file"],
                "src": img.get("src", ""),
                "node_id": n.get("node_id", ""),
                "w": n.get("dp", {}).get("w", 0),
                "h": n.get("dp", {}).get("h", 0),
                "format": "png",
            })
        for c in n.get("children", []):
            walk(c)

    walk(tree.get("root", {}))
    return {
        "schema_version": "1.0",
        "assets": assets,
    }


# ─── CLI ───

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_path = sys.argv[1]
    output_dir = None
    if "--output-dir" in sys.argv:
        idx = sys.argv.index("--output-dir")
        if idx + 1 < len(sys.argv):
            output_dir = sys.argv[idx + 1]

    with open(input_path, encoding="utf-8") as f:
        composition = json.load(f)

    ag = composition.get("name", "画板")
    w = composition.get("width", 0)
    h = composition.get("height", 0)
    print(f"画板: {ag} ({w} x {h})")

    # 生成 android_tree
    tree = build_android_tree(composition)

    if not output_dir:
        base_dir = os.path.dirname(os.path.abspath(input_path))
        output_dir = os.path.join(base_dir, "figma_extract_prepared")
    os.makedirs(output_dir, exist_ok=True)

    # source_meta.json
    meta = build_source_meta(composition, tree)
    meta_path = os.path.join(output_dir, "source_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"  source_meta.json -> {output_dir}/")

    # android_tree.json
    tree_path = os.path.join(output_dir, "android_tree.json")
    with open(tree_path, "w", encoding="utf-8") as f:
        json.dump(tree, f, indent=2, ensure_ascii=False)
    node_count = count_nodes(tree["root"])
    print(f"  android_tree.json -> {output_dir}/ ({node_count} nodes)")

    # assets.json
    assets = build_assets(tree)
    asset_path = os.path.join(output_dir, "assets.json")
    with open(asset_path, "w", encoding="utf-8") as f:
        json.dump(assets, f, indent=2, ensure_ascii=False)
    print(f"  assets.json -> {output_dir}/ ({len(assets['assets'])} assets)")

    print(f"\n完成! Schema version: 2.0, scale: {SCALE}")
    return output_dir


if __name__ == "__main__":
    main()
