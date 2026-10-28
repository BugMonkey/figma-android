// figma-android-bridge — Figma 插件 (pull 模式)
// code.js 负责：
//   1. 选中画板 → 快速导出缩略图 → 通知 UI 展示
//   2. 响应 UI 的 trigger-extract → 完整提取节点树 + 截图 + 切图
//   3. UI 负责 HTTP 通信（轮询 server pending、POST 数据）

const SERVER_URL = "http://localhost:7789";
const TARGET_DENSITY = 3; // 目标密度 xxhdpi (3x)
const BASE_WIDTH_DP = 360; // 基准画板宽度 dp
const THUMBNAIL_SCALE = 1; // 缩略图用 1x

// 根据画板宽度动态计算导出缩放
// exportScale = TARGET_DENSITY × BASE_WIDTH_DP / artboardWidth
// 1x 设计 (360px) → 3x export; 2x 设计 (720px) → 1.5x; 3x 设计 (1080px) → 1x
function getExportScale(artboardWidth) {
  var scale = (TARGET_DENSITY * BASE_WIDTH_DP) / artboardWidth;
  return Math.max(0.5, Math.min(4, Math.round(scale * 10) / 10));
}

// ─── 状态栏识别 ───
// 设计稿画板顶部常带模拟系统状态栏（时间 / 信号 / WiFi / 电池图标）。
// Android 系统会自行渲染状态栏，App 布局与切图都不需要这部分，提取时整体过滤。
// 识别依据：节点名包含状态栏关键词（覆盖 Status Bar / 状态栏 / System Bar / 裸 status 等常见命名）。
var STATUS_BAR_NAME_RE = /(status[\s_-]?bar|状态栏|system[\s_-]?bar|系统栏|^status$)/i;

function isStatusBarNode(node) {
  return !!(node && node.name && STATUS_BAR_NAME_RE.test(String(node.name)));
}

// ─── 合并组包围盒（成员并集，不裁剪） ───
// 合并组成员可能溢出父容器；裁剪不在这里做。
// 裁剪推迟到 UI Canvas 合成阶段（"先绘制、后裁剪"）：canvas 开到成员并集全尺寸，
// 全部成员按绝对坐标绘制，最后只截取画板可视区（clipRect）区域。
// 这样几何正确性只依赖绝对坐标，与父容器是否 clipsContent / 有无缩放无关。
// memberNodes 为成员节点对象数组，返回 {left,top,right,bottom}（绝对坐标）或 null。
// ─── 节点绝对包围盒（AABB） ───
// 旋转/缩放/翻转节点的 absoluteTransform 平移分量不是视觉左上角，
// 必须用局部矩形四角变换后的 min/max 取包围盒；未旋转节点与旧行为等价。
function nodeAbsAABB(node) {
  var tf = node.absoluteTransform;
  var w = (typeof node.width === 'number') ? node.width : 0;
  var h = (typeof node.height === 'number') ? node.height : 0;
  var a = 1, b = 0, c = 0, d = 1, tx = 0, ty = 0;
  var hasTf = Array.isArray(tf) && Array.isArray(tf[0]) && Array.isArray(tf[1]) &&
              tf[0].length >= 3 && tf[1].length >= 3;
  if (hasTf) {
    a = tf[0][0]; b = tf[0][1]; tx = tf[0][2];
    c = tf[1][0]; d = tf[1][1]; ty = tf[1][2];
  }
  // 四角变换：nx = a*x + b*y + tx, ny = c*x + d*y + ty
  var x0 = tx, y0 = ty;
  var x1 = a * w + tx, y1 = c * w + ty;
  var x2 = b * h + tx, y2 = d * h + ty;
  var x3 = a * w + b * h + tx, y3 = c * w + d * h + ty;
  var axisAligned = Math.round(a * 1e6) === 1000000 && Math.round(b * 1e6) === 0 &&
                    Math.round(c * 1e6) === 0 && Math.round(d * 1e6) === 1000000;
  if (axisAligned) {
    return { x: tx, y: ty, width: w, height: h };
  }
  var minX = Math.min(x0, x1, x2, x3), maxX = Math.max(x0, x1, x2, x3);
  var minY = Math.min(y0, y1, y2, y3), maxY = Math.max(y0, y1, y2, y3);
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}

function mergedGroupBounds(memberNodes) {
  if (!memberNodes || memberNodes.length === 0) return null;
  var left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
  for (var i = 0; i < memberNodes.length; i++) {
    var mn = memberNodes[i];
    if (!mn) continue;
    var r = nodeAbsAABB(mn);
    left = Math.min(left, r.x);
    top = Math.min(top, r.y);
    right = Math.max(right, r.x + r.width);
    bottom = Math.max(bottom, r.y + r.height);
  }
  if (left === Infinity) return null; // 无可见成员
  return { left: left, top: top, right: right, bottom: bottom };
}

// ─── 工具函数 ───
// 在节点子树中递归查找指定 ID 的节点
function findNodeById(root, targetId) {
  if (!root) return null;
  if (root.id === targetId) return root;
  if (root.children) {
    for (var i = 0; i < root.children.length; i++) {
      var found = findNodeById(root.children[i], targetId);
      if (found) return found;
    }
  }
  return null;
}

// 查找合并组成员所属的"直接子节点"索引（成员可能嵌套在子 Group 中）。
// 返回该直接子节点在 node.children 中的索引，用于确定合并组虚拟节点的插入位置；
// 找不到返回 -1。
function findDirectChildIndex(node, memberId) {
  if (!node || !node.children) return -1;
  for (var ci = 0; ci < node.children.length; ci++) {
    var dc = node.children[ci];
    if (dc.id === memberId) return ci;
    if (findNodeById(dc, memberId)) return ci;
  }
  return -1;
}

// ─── 提取节点树 ───
// skipIds: Set of node IDs to skip (merge group members found at a higher level)
function extractNode(node, artboardOrigin, parentName, skipIds) {
  // 跳过在父级已被合并组消费的节点
  if (skipIds && skipIds.has(node.id)) {
    return null;
  }
  if (!node || node.visible === false) {
    if (node && node.visible === false) {
      console.warn('[跳过 invisible 节点] name=' + (node.name || 'unnamed') + ' id=' + (node.id || '') + ' parent=' + (parentName || '?'));
    }
    return null;
  }

  // opacity=0 → 完全透明，视觉上不可见，丢弃
  if (node.opacity === 0) {
    console.warn('[跳过 opacity=0 节点] name=' + (node.name || 'unnamed') + ' id=' + (node.id || '') + ' parent=' + (parentName || '?'));
    return null;
  }

  // 状态栏（系统 UI）整体过滤：不进 android_tree，不产生布局节点
  if (isStatusBarNode(node)) {
    console.warn('[跳过状态栏节点] name=' + (node.name || 'unnamed') + ' id=' + (node.id || '') + ' parent=' + (parentName || '?'));
    return null;
  }

  // 位置与尺寸一律取视觉包围盒（AABB）：旋转/缩放/翻转节点下，
  // 平移分量不是左上角（典型：180 度旋转偏移 = 节点宽、高）
  var rect = nodeAbsAABB(node);
  var relX = rect.x - artboardOrigin.x;
  var relY = rect.y - artboardOrigin.y;

  var result = {
    id: node.id,
    type: node.type,
    name: node.name,
    x: relX,
    y: relY,
    width: rect.width,
    height: rect.height,
    opacity: node.opacity,
    visible: node.visible
  };

  // 切图标记（通过插件面板 setPluginData 设置）
  if (node.getPluginData && node.getPluginData("exportAsImage") === "true") {
    result.export_as_image = true;
  }
  // Figma 原生导出设置（设计师在右侧面板添加的 Export Settings）
  if (!result.export_as_image) {
    try {
      var es = node.exportSettings;
      if (es && typeof es.length === 'number' && es.length > 0) {
        result.export_as_image = true;
        result.export_settings_source = 'figma-native';
        // 手动序列化（Figma API 对象无法被 JSON.stringify 自动序列化）
        result.exportSettings = [];
        for (var i = 0; i < es.length; i++) {
          var entry = { format: es[i].format, suffix: es[i].suffix || '' };
          if (es[i].constraint) {
            entry.constraint = { type: es[i].constraint.type, value: es[i].constraint.value };
          }
          result.exportSettings.push(entry);
        }
      }
    } catch(e) {}
  }
  // INSTANCE 组件实例：整张切图（与 collectImageNodes 一致：return 不递归子节点）
  if (!result.export_as_image && node.type === 'INSTANCE') {
    result.export_as_image = true;
    result.export_settings_source = 'instance';
  }
  // 矢量图标规则（与 collectImageNodes 保持一致：含矢量子节点、无文本、≤300x300）
  if (!result.export_as_image && node.children && node.children.length > 0) {
    var isVectorIcon = hasVectorDescendant(node) && !hasTextChild(node);
    var isIconSized = node.width <= 300 && node.height <= 300;
    if (isVectorIcon && isIconSized) {
      result.export_as_image = true;
      result.export_settings_source = 'vector-icon';
    }
  }

  // 变换矩阵 — 显式转为纯数组，避免 Figma 包裹对象过 postMessage 时触发 "Cannot unwrap symbol"
  var absTf = node.absoluteTransform;
  var hasAbsTf = Array.isArray(absTf) && Array.isArray(absTf[0]) && Array.isArray(absTf[1]) &&
                 absTf[0].length >= 3 && absTf[1].length >= 3;
  if (hasAbsTf && (absTf[0][0] !== 1 || absTf[0][1] !== 0 || absTf[1][0] !== 0 || absTf[1][1] !== 1)) {
    result.transform = [
      [absTf[0][0], absTf[0][1], absTf[0][2]],
      [absTf[1][0], absTf[1][1], absTf[1][2]]
    ];
  }

  // constraints
  if (node.constraints) {
    result.constraints = {
      horizontal: node.constraints.horizontal,
      vertical: node.constraints.vertical
    };
  }

  // Auto Layout
  if (node.layoutMode && node.layoutMode !== 'NONE') {
    result.layoutMode = node.layoutMode;
    if (node.itemSpacing != null) result.itemSpacing = node.itemSpacing;
    if (node.paddingTop != null) result.paddingTop = node.paddingTop;
    if (node.paddingRight != null) result.paddingRight = node.paddingRight;
    if (node.paddingBottom != null) result.paddingBottom = node.paddingBottom;
    if (node.paddingLeft != null) result.paddingLeft = node.paddingLeft;
    if (node.primaryAxisAlignItems) result.primaryAxisAlignItems = node.primaryAxisAlignItems;
    if (node.counterAxisAlignItems) result.counterAxisAlignItems = node.counterAxisAlignItems;
  }

  if (node.clipsContent) result.clipsContent = true;

  // 样式
  var style = {};

  // fills
  if (Array.isArray(node.fills) && node.fills.length > 0) {
    style.fills = node.fills
      .filter(function(f) { return f.visible !== false; })
      .map(serializePaint);
  }

  // strokes
  if (Array.isArray(node.strokes) && node.strokes.length > 0) {
    style.strokes = node.strokes
      .filter(function(s) { return s.visible !== false; })
      .map(serializePaint);
    style.strokeWeight = node.strokeWeight;
    if (node.strokeAlign) style.strokeAlign = node.strokeAlign;
    if (node.dashPattern && node.dashPattern.length > 0) style.dashPattern = node.dashPattern;
  }

  // 圆角
  if (typeof node.cornerRadius === 'number' && node.cornerRadius > 0) {
    style.cornerRadius = node.cornerRadius;
  } else if (node.rectangleCornerRadii && node.rectangleCornerRadii.length === 4) {
    style.cornerRadii = node.rectangleCornerRadii.slice();
  }

  // effects
  if (Array.isArray(node.effects) && node.effects.length > 0) {
    var visEffects = node.effects.filter(function(e) { return e.visible !== false; });
    if (visEffects.length > 0) {
      style.effects = visEffects.map(function(e) {
        var eff = { type: e.type };
        if (e.offset) eff.offset = { x: e.offset.x, y: e.offset.y };
        if (e.radius != null) eff.radius = e.radius;
        if (e.spread != null) eff.spread = e.spread;
        if (e.color) eff.color = { r: e.color.r, g: e.color.g, b: e.color.b, a: e.color.a };
        return eff;
      });
    }
  }

  // 文本
  if (node.type === 'TEXT') {
    result.text = { characters: node.characters };
    if (node.textAutoResize) result.textAutoResize = node.textAutoResize;
    if (node.textAlignHorizontal) result.textAlignHorizontal = node.textAlignHorizontal;
    if (node.textAlignVertical) result.textAlignVertical = node.textAlignVertical;
    if (node.paragraphIndent != null) result.paragraphIndent = node.paragraphIndent;
    if (node.paragraphSpacing != null) result.paragraphSpacing = node.paragraphSpacing;

    try {
      var segments = node.getStyledTextSegments([
        'fontSize', 'fontName', 'fontWeight', 'fills',
        'lineHeight', 'letterSpacing', 'textCase', 'textDecoration'
      ]);
      if (segments && segments.length > 0) {
        result.segments = segments.map(function(seg) {
          var s = {
            start: seg.start,
            end: seg.end,
            fontSize: seg.fontSize,
            fontWeight: seg.fontWeight
          };
          if (seg.fontName) s.fontName = { family: seg.fontName.family, style: seg.fontName.style };
          if (seg.letterSpacing) s.letterSpacing = { unit: seg.letterSpacing.unit, value: seg.letterSpacing.value };
          if (seg.lineHeight) s.lineHeight = { unit: seg.lineHeight.unit, value: seg.lineHeight.value };
          if (seg.textCase) s.textCase = seg.textCase;
          if (seg.textDecoration) s.textDecoration = seg.textDecoration;
          if (Array.isArray(seg.fills)) s.fills = seg.fills
            .filter(function(f) { return f.visible !== false; })
            .map(serializePaint);
          return s;
        });
      }
    } catch (e) {
      result.segments = [{
        start: 0,
        end: node.characters.length,
        fontSize: node.fontSize,
        fontWeight: node.fontWeight
      }];
    }
  }

  // 组件属性
  if (node.componentProperties) {
    result.componentProperties = {};
    for (var key in node.componentProperties) {
      if (node.componentProperties.hasOwnProperty(key)) {
        var prop = node.componentProperties[key];
        result.componentProperties[key] = {
          type: prop.type,
          value: prop.value
        };
      }
    }
  }

  if (Object.keys(style).length > 0) result.style = style;

  // ── 递归子节点（合并组感知） ──
  // 读取父容器的 mergeGroup_map，将合并组成员替换为单一虚拟节点
  var mergeMemberIds = new Set();
  var mergeGroupsByFirstIdx = {};

  if (node.getPluginData && node.children && node.children.length > 0) {
    var mgMapStr = node.getPluginData("mergeGroup_map");
    if (mgMapStr) {
      try {
        var mgMap = JSON.parse(mgMapStr);
        for (var mgId in mgMap) {
          if (!mgMap.hasOwnProperty(mgId)) continue;
          var members = mgMap[mgId].members;
          var memberNodes = [];
          var names = [];
          var firstIdx = Infinity;

          for (var mi = 0; mi < members.length; mi++) {
            // 递归搜索子树（不限于直接子节点），处理成员嵌套在子 Group 中的情况
            var mn = findNodeById(node, members[mi]);
            if (mn) {
              var mnRect = nodeAbsAABB(mn);
              console.warn('[mergeGroup] 找到成员: ' + mn.name + ' (' + members[mi] + ') aabb=(' + mnRect.x + ',' + mnRect.y + ' ' + mnRect.width + 'x' + mnRect.height + ') rot=' + (typeof mn.rotation === 'number' ? mn.rotation : '?'));
              mergeMemberIds.add(mn.id);
              memberNodes.push(mn);
              names.push(mn.name);
              // 找到成员所属的直接子节点索引（支持成员嵌套在子 Group 中），
              // 用于插入合并组虚拟节点；找不到则回退到 0（插到最前）。
              var dcIdx = findDirectChildIndex(node, members[mi]);
              if (dcIdx >= 0) {
                firstIdx = Math.min(firstIdx, dcIdx);
              }
            } else {
              console.warn('[mergeGroup] 未找到成员: ' + members[mi] + ' (父节点: ' + (node.name || '?') + ' ' + (node.id || '?' ) + ')');
            }
          }

          console.warn('[mergeGroup] 成员数: ' + memberNodes.length + '/' + members.length + ' 找到: ' + names.join(','));
          // 合并组虚拟节点坐标 = 成员并集（不裁剪）
          // 裁剪在 UI Canvas 合成阶段做，这里保留完整包围盒，供 android_tree 记录合并区位置。
          var mgBounds = mergedGroupBounds(memberNodes);
          if (mgBounds) {
            console.warn('[mergeGroup] 并集: (' + mgBounds.left + ',' + mgBounds.top + ')-(' + mgBounds.right + ',' + mgBounds.bottom + ') = ' + (mgBounds.right - mgBounds.left) + 'x' + (mgBounds.bottom - mgBounds.top));
          } else {
            console.warn('[mergeGroup] 并集为空，回退到父节点尺寸: ' + node.width + 'x' + node.height);
          }
          var bboxX, bboxY, bboxW, bboxH;
          if (mgBounds) {
            bboxX = mgBounds.left - artboardOrigin.x;
            bboxY = mgBounds.top - artboardOrigin.y;
            bboxW = mgBounds.right - mgBounds.left;
            bboxH = mgBounds.bottom - mgBounds.top;
          } else {
            var nSelfRect = nodeAbsAABB(node);
            bboxX = nSelfRect.x - artboardOrigin.x;
            bboxY = nSelfRect.y - artboardOrigin.y;
            bboxW = nSelfRect.width;
            bboxH = nSelfRect.height;
          }

          if (memberNodes.length > 0) {
            var mname = '合并_' + names.slice(0, 2).join('_');
            if (names.length > 2) mname += '_等' + names.length + '项';
            // 成员在直接子节点中时用其索引插入；嵌套成员用 0（插到最前面）
            var insertIdx = firstIdx < Infinity ? firstIdx : 0;
            // 附加成员原始几何（调试用）：导出合并图尺寸异常时，可对比成员坐标
            // 与合并包围盒，定位是哪个成员把 bounds 撑大。
            var debugMembers = memberNodes.map(function(mn) {
              var r = nodeAbsAABB(mn);
              return {
                id: mn.id,
                name: mn.name,
                x: mn.x,
                y: mn.y,
                width: mn.width,
                height: mn.height,
                rotation: typeof mn.rotation === 'number' ? mn.rotation : null,
                aabbX: r.x,
                aabbY: r.y,
                aabbW: r.width,
                aabbH: r.height,
              };
            });
            mergeGroupsByFirstIdx[insertIdx] = {
              id: mgId,
              name: mname,
              x: bboxX,
              y: bboxY,
              width: bboxW,
              height: bboxH,
              _debug_foundMembers: memberNodes.length,
              _debug_totalMembers: members.length,
              _debug_fallback: !mgBounds,
              _debug_members: debugMembers,
            };
          }
        }
      } catch(e) {}
    }
  }

  if (node.children && node.children.length > 0) {
    var children = [];
    for (var ci2 = 0; ci2 < node.children.length; ci2++) {
      if (mergeGroupsByFirstIdx[ci2]) {
        var mg = mergeGroupsByFirstIdx[ci2];
        children.push({
          id: mg.id,
          type: 'FRAME',
          name: mg.name,
          x: mg.x,
          y: mg.y,
          width: mg.width,
          height: mg.height,
          opacity: 1,
          visible: true,
          export_as_image: true,
          _debug_foundMembers: mg._debug_foundMembers,
          _debug_totalMembers: mg._debug_totalMembers,
          _debug_fallback: mg._debug_fallback,
          _debug_members: mg._debug_members,
        });
      } else if (!mergeMemberIds.has(node.children[ci2].id)) {
        var child = extractNode(node.children[ci2], artboardOrigin, node.name, mergeMemberIds);
        if (child) children.push(child);
      }
    }
    if (children.length > 0) result.children = children;
  }

  return result;
}

// ─── 序列化 Paint ───
// 安全克隆 Figma Proxy 包裹对象（结构化克隆会抛 "Cannot unwrap symbol"），
// 显式拷贝 2×3 和小对象，避免每处手动展开
function deepClonePaintTransform(t) {
  if (!t || !Array.isArray(t)) return t;
  return [ [t[0][0], t[0][1], t[0][2]], [t[1][0], t[1][1], t[1][2]] ];
}

function serializePaint(paint) {
  var p = { type: paint.type };
  if (paint.color) {
    p.color = { r: paint.color.r, g: paint.color.g, b: paint.color.b, a: paint.color.a };
  }
  if (paint.opacity != null && paint.opacity !== 1) p.opacity = paint.opacity;
  if (paint.blendMode && paint.blendMode !== 'NORMAL') p.blendMode = paint.blendMode;
  if (paint.type === 'IMAGE') {
    if (paint.imageHash) p.imageHash = paint.imageHash;
    if (paint.scaleMode) p.scaleMode = paint.scaleMode;
    if (paint.imageTransform) {
      p.imageTransform = deepClonePaintTransform(paint.imageTransform);
    }
  }
  if (paint.type === 'GRADIENT_LINEAR' || paint.type === 'GRADIENT_RADIAL' || paint.type === 'GRADIENT_ANGULAR' || paint.type === 'GRADIENT_DIAMOND') {
    if (paint.gradientStops) {
      p.gradientStops = paint.gradientStops.map(function(s) {
        return {
          position: s.position,
          color: { r: s.color.r, g: s.color.g, b: s.color.b, a: s.color.a }
        };
      });
    }
    if (paint.gradientTransform) {
      p.gradientTransform = deepClonePaintTransform(paint.gradientTransform);
    }
  }
  return p;
}

// ─── 导出缩略图 (1x, 用于 UI 预览) ───
async function exportThumbnail(node) {
  try {
    var bytes = await node.exportAsync({
      format: 'PNG',
      constraint: { type: 'SCALE', value: THUMBNAIL_SCALE }
    });
    return figma.base64Encode(bytes);
  } catch (e) {
    return null;
  }
}

// ─── 导出截图 (动态缩放, 用于 skill) ───
async function exportScreenshot(node, scale) {
  try {
    var bytes = await node.exportAsync({
      format: 'PNG',
      constraint: { type: 'SCALE', value: scale }
    });
    return figma.base64Encode(bytes);
  } catch (e) {
    return null;
  }
}

// ─── 检查节点是否有矢量路径子节点 ───
function hasVectorDescendant(node) {
  if (!node || !node.children) return false;
  for (var i = 0; i < node.children.length; i++) {
    var c = node.children[i];
    if (['VECTOR', 'BOOLEAN_OPERATION', 'STAR', 'POLYGON', 'LINE',
         'ELLIPSE', 'RECTANGLE', 'PATH', 'VECTOR_NETWORK',
         'REGULAR_POLYGON'].indexOf(c.type) !== -1) {
      return true;
    }
    if (hasVectorDescendant(c)) return true;
  }
  return false;
}

// ─── 检查节点是否包含文本子节点 ───
function hasTextChild(node) {
  if (!node || !node.children) return false;
  for (var i = 0; i < node.children.length; i++) {
    if (node.children[i].type === 'TEXT') return true;
    if (hasTextChild(node.children[i])) return true;
  }
  return false;
}

// ─── 收集图片/图标节点（支持合并切图组，存在父容器 pluginData 上） ───
function collectImageNodes(node, out, depth, skipIds) {
  if (depth === undefined) depth = 0;
  if (!node || node.visible === false) return; // invisible 节点不产生切图
  if (node.opacity === 0) return; // opacity=0 节点也不产生切图

  // 跳过在父级已被合并组消费的节点
  if (skipIds && skipIds.has(node.id)) return;

  // 状态栏（系统 UI）整体过滤：不导出其内部的时间/信号/WiFi/电池图标切图
  if (isStatusBarNode(node)) return;

  // 读取当前节点上的 mergeGroup_map，添加合并组条目
  var mergeMemberIds = new Set();
  if (node.getPluginData && node.children) {
    var mgMapStr = node.getPluginData("mergeGroup_map");
    if (mgMapStr) {
      try {
        var mgMap = JSON.parse(mgMapStr);
        for (var mgId in mgMap) {
          if (!mgMap.hasOwnProperty(mgId)) continue;
          var members = mgMap[mgId].members;
          for (var mi2 = 0; mi2 < members.length; mi2++) {
            mergeMemberIds.add(members[mi2]);
          }
          // 合并组条目：只记录标识信息，实际导出尺寸由 exportMergeGroup 重新计算
          out.push({
            node: node,
            imageHash: mgId,
            name: mgMap[mgId].name || '合并切图',
            mergeGroupId: mgId,
            childIds: members.slice(),
            isMergedGroup: true,
          });
        }
      } catch(e) {}
    }
  }

  // 切图标记节点 + 非合并组成员 → 整张切图
  if (node.getPluginData && node.getPluginData("exportAsImage") === "true") {
    out.push({ node: node, imageHash: node.id, name: node.name, width: node.width, height: node.height });
    return;
  }
  // Figma 原生导出设置
  // 注意：不 return，继续递归子节点收集更多切图。
  // 根画板可能有原生导出设置（如设计师加了 Export Settings），
  // 但子节点（icon、图片等）仍需单独导出为切图。
  var hasExportSettings = false;
  try {
    var es = node.exportSettings;
    if (es && typeof es.length === 'number' && es.length > 0) {
      out.push({ node: node, imageHash: node.id, name: node.name, width: node.width, height: node.height });
      hasExportSettings = true;
    }
  } catch(e) {}
  if (node.type === 'INSTANCE') {
    out.push({ node: node, imageHash: node.id, name: node.name, width: node.width, height: node.height });
    return;
  }
  var fills = node.fills;
  if (Array.isArray(fills)) {
    var imageFill = fills.find(function(f) { return f.type === 'IMAGE' && f.visible !== false; });
    if (imageFill && imageFill.imageHash) {
      out.push({ node: node, imageHash: imageFill.imageHash, name: node.name, width: node.width, height: node.height });
      return;
    }
  }
  // 矢量图标
  if (node.children && node.children.length > 0 && depth > 0) {
    var isVectorIcon = hasVectorDescendant(node) && !hasTextChild(node);
    var isIconSized = node.width <= 300 && node.height <= 300;
    if (isVectorIcon && isIconSized) {
      out.push({ node: node, imageHash: node.id, name: node.name, width: node.width, height: node.height });
    }
  }
  // 递归子节点（跳过合并组成员，传递 skipIds 处理嵌套成员）
  if (node.children) {
    for (var i = 0; i < node.children.length; i++) {
      if (!mergeMemberIds.has(node.children[i].id)) {
        collectImageNodes(node.children[i], out, depth + 1, mergeMemberIds);
      }
    }
  }
}

// 向上追溯到最近的画板 (FRAME/COMPONENT/COMPONENT_SET)
function findArtboardNode(node) {
  // 从父节点开始查找，避免选中自身为 FRAME 时误判为根画板
  var cur = (node && node.parent) ? node.parent : null;
  while (cur) {
    if (cur.type === 'PAGE' || cur.type === 'DOCUMENT') {
      return null; // 父级是页面/文档 → 当前节点即根画板
    }
    if (cur.type === 'FRAME' || cur.type === 'COMPONENT' || cur.type === 'COMPONENT_SET') {
      return cur;
    }
    cur = cur.parent;
  }
  return null;
}

function findRootArtboard(node) {
  // 一直向上找，直到 parent 是 PAGE 的那个 FRAME 才是真正的根画板
  var root = null;
  var cur = node;
  while (cur) {
    if (cur.type === 'FRAME' || cur.type === 'COMPONENT' || cur.type === 'COMPONENT_SET') {
      root = cur;
    }
    cur = cur.parent;
  }
  return root;
}

// ─── Android shape drawable 代码生成 ───
// 根据选中节点的填充/描边/圆角直接生成可拷贝的 Android shape XML，
// 供开发在面板上快速复制背景 drawable 代码（对齐蓝湖的代码面板体验）。
// 单位换算与 skill normalize 阶段（rules/android-layout-rules.md 核心原则）一致：
// dp = px × 360 ÷ 画板宽度（360dp 基准：1x 设计原值，2x 设计 ÷2，3x 设计 ÷3）。

function shapeColorHex(color, extraOpacity) {
  if (!color) return null;
  var a = (color.a == null ? 1 : color.a) * (extraOpacity == null ? 1 : extraOpacity);
  if (a > 1) a = 1;
  if (a < 0) a = 0;
  function toHex(v) {
    var n = Math.round(v * 255);
    if (n < 0) n = 0;
    if (n > 255) n = 255;
    var s = n.toString(16).toUpperCase();
    return s.length < 2 ? '0' + s : s;
  }
  if (a < 0.999) {
    return '#' + toHex(a) + toHex(color.r) + toHex(color.g) + toHex(color.b);
  }
  return '#' + toHex(color.r) + toHex(color.g) + toHex(color.b);
}

function shapeFormatDp(px, dpScale) {
  var v = Math.round(px * dpScale * 100) / 100;
  return String(v) + 'dp';
}

// 生成 <gradient> 属性集；返回 { attrs: {name: value} } 或 { fallbackSolid: '#hex' } 或 null
function shapeGradientAttrs(paint, nodeWidth, nodeHeight, dpScale, nodeOpacity) {
  var stops = Array.isArray(paint.gradientStops) ? paint.gradientStops : [];
  if (stops.length === 0) return null;
  var op = (paint.opacity == null ? 1 : paint.opacity) * (nodeOpacity == null ? 1 : nodeOpacity);
  var colors = stops.map(function(s) {
    var hex = s.color ? shapeColorHex(s.color, op) : null;
    return { position: s.position, hex: hex };
  });

  var attrs = {};
  if (paint.type === 'GRADIENT_RADIAL') {
    attrs['type'] = 'radial';
    attrs['gradientRadius'] = shapeFormatDp(Math.max(nodeWidth, nodeHeight) / 2, dpScale);
  } else if (paint.type === 'GRADIENT_ANGULAR') {
    attrs['type'] = 'sweep';
  } else {
    // GRADIENT_LINEAR（GRADIENT_DIAMOND 无对应 Android 类型，按 linear 近似）
    attrs['type'] = 'linear';
  }

  if (colors.length === 1) {
    return { fallbackSolid: colors[0].hex };
  }
  attrs['startColor'] = colors[0].hex;
  attrs['endColor'] = colors[colors.length - 1].hex;
  if (colors.length === 3) attrs['centerColor'] = colors[1].hex;

  // 线性渐变几何：gradientTransform 将节点对象空间（归一化 0-1）映射到渐变空间，
  // 任意点的色标位置 t(P) = ga·X + gc·Y + ge（X/Y 为归一化坐标）。
  // Android LinearGradient 用「正交投影」算 t，要让每个像素的 t 与 Figma 严格一致，
  // 需按像素空间渐变向量 w = (ga/W, gc/H) 反推起止点：
  //   S = w·(pFirst - ge)/|w|²，E = w·(pLast - ge)/|w|²
  // （沿轴取点的做法仅在等色线⊥轴时成立，斜向渐变会整体错位。）
  if (paint.type === 'GRADIENT_LINEAR' && paint.gradientTransform) {
    var gt = paint.gradientTransform;
    var ga = gt[0][0], gc = gt[1][0], ge = gt[0][2];
    var pFirst = colors[0].position == null ? 0 : colors[0].position;
    var pLast = colors[colors.length - 1].position == null ? 1 : colors[colors.length - 1].position;
    var wx = ga / nodeWidth, wy = gc / nodeHeight;
    var wlen2 = wx * wx + wy * wy;
    if (wlen2 > 1e-12 && pLast > pFirst) {
      var kS = (pFirst - ge) / wlen2, kE = (pLast - ge) / wlen2;
      function r2(v) { return Math.round(v * 100) / 100; }
      var sx = r2(wx * kS), sy = r2(wy * kS);
      var ex = r2(wx * kE), ey = r2(wy * kE);
      // 轴向满跨度范式 → 简化为 angle 写法（更贴近手写习惯）；其余输出精确坐标
      if (sx === 0 && ex === 1 && sy === ey) {
        // 左→右为默认，省略 angle
      } else if (sx === ex && sy === 0 && ey === 1) {
        attrs['angle'] = '270'; // 上→下
      } else if (sx === ex && sy === 1 && ey === 0) {
        attrs['angle'] = '90'; // 下→上
      } else if (sy === ey && sx === 1 && ex === 0) {
        attrs['angle'] = '180'; // 右→左
      } else {
        attrs['startX'] = String(sx);
        attrs['startY'] = String(sy);
        attrs['endX'] = String(ex);
        attrs['endY'] = String(ey);
      }
    }
  }
  return { attrs: attrs };
}

// 单个 paint → shape 填充元素（solid/gradient），顶层缩进为 0；无法表达返回 null
function shapeFillBody(paint, node, dpScale, nodeOpacity) {
  if (paint.type === 'SOLID') {
    var fop = (paint.opacity == null ? 1 : paint.opacity) * nodeOpacity;
    return '<solid android:color="' + shapeColorHex(paint.color, fop) + '" />';
  }
  if (paint.type === 'GRADIENT_LINEAR' || paint.type === 'GRADIENT_RADIAL' ||
      paint.type === 'GRADIENT_ANGULAR' || paint.type === 'GRADIENT_DIAMOND') {
    var g = shapeGradientAttrs(paint, node.width, node.height, dpScale, nodeOpacity);
    if (g && g.fallbackSolid) {
      return '<solid android:color="' + g.fallbackSolid + '" />';
    }
    if (g && g.attrs) {
      var keys = Object.keys(g.attrs).sort();
      var lines = [];
      for (var gi = 0; gi < keys.length; gi++) {
        lines.push('    android:' + keys[gi] + '="' + g.attrs[keys[gi]] + '"');
      }
      return '<gradient\n' + lines.join('\n') + ' />';
    }
  }
  return null;
}

// 多行元素块统一加缩进
function shapeIndent(text, indent) {
  return text.split('\n').map(function(l) { return indent + l; }).join('\n');
}

// ─── Android TextView 代码生成 ───
// 选中 TEXT 节点时生成可拷贝的 TextView XML：字号按 sp（换算同 shape 的 dp 规则），
// 字色/粗体/对齐/字距/行距取自 Figma 文本样式（混排时取第一个 styled segment）。
function escapeXmlAttr(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// XML 注释不允许连续连字符，替换为破折号
function escapeXmlComment(s) {
  return String(s == null ? '' : s).replace(/-{2,}/g, '—');
}

// android:text 值转义：XML 属性中的裸换行/制表符会被解析器归一成空格，
// 先转为 Android 字面转义（\n / \t），反斜杠本身先翻倍保持原义
function escapeAndroidText(s) {
  return String(s == null ? '' : s)
    .replace(/\\/g, '\\\\')
    .replace(/\r\n|\r|\n/g, '\\n')
    .replace(/\t/g, '\\t');
}

// Figma 的 lineHeight 是对象 {unit: 'PIXELS'|'PERCENT'|'AUTO', value}，解析为 px；
// AUTO 或缺失返回 null（交由调用方按字号估算）
function resolveLineHeightPx(lineHeight, fontSize) {
  if (!lineHeight || typeof lineHeight !== 'object') return null;
  if (lineHeight.unit === 'PIXELS' && typeof lineHeight.value === 'number') return lineHeight.value;
  if (lineHeight.unit === 'PERCENT' && typeof lineHeight.value === 'number' && fontSize > 0) {
    return lineHeight.value / 100 * fontSize;
  }
  return null;
}

function buildAndroidTextXml(node) {
  try {
    if (!node || node.type !== 'TEXT') return null;
    var artboard = findRootArtboard(node);
    var dpScale = (artboard && artboard.width > 0) ? BASE_WIDTH_DP / artboard.width : 1;
    var nodeOpacity = node.opacity == null ? 1 : node.opacity;

    // 混排文本的 fontSize/fontWeight 等可能是 mixed，优先取第一个 styled segment
    var fontSize = typeof node.fontSize === 'number' ? node.fontSize : null;
    var fontWeight = typeof node.fontWeight === 'number' ? node.fontWeight : null;
    var fontName = (node.fontName && node.fontName.family) ? node.fontName : null;
    var letterSpacing = (node.letterSpacing && typeof node.letterSpacing === 'object') ? node.letterSpacing : null;
    var textCase = typeof node.textCase === 'string' ? node.textCase : null;
    var fills = Array.isArray(node.fills) ? node.fills : null;
    try {
      var segs = node.getStyledTextSegments(['fontSize', 'fontWeight', 'fontName', 'fills', 'letterSpacing', 'textCase']);
      if (segs && segs.length > 0) {
        if (fontSize == null) fontSize = segs[0].fontSize;
        if (fontWeight == null) fontWeight = segs[0].fontWeight;
        if (!fontName && segs[0].fontName) fontName = segs[0].fontName;
        if (!letterSpacing && segs[0].letterSpacing && typeof segs[0].letterSpacing === 'object') {
          letterSpacing = segs[0].letterSpacing;
        }
        if (!textCase && typeof segs[0].textCase === 'string') textCase = segs[0].textCase;
        if ((!fills || fills.length === 0) && Array.isArray(segs[0].fills)) fills = segs[0].fills;
      }
    } catch (e) { console.warn('getStyledTextSegments failed:', e); }

    var lines = [
      '    android:layout_width="wrap_content"',
      '    android:layout_height="wrap_content"',
      '    android:text="' + escapeXmlAttr(escapeAndroidText(node.characters)) + '"'
    ];

    // 字色：首个可见 solid；渐变文本退化为第一色标
    var visFills = (fills || []).filter(function(f) { return f.visible !== false; });
    var tc = null;
    for (var fi = visFills.length - 1; fi >= 0; fi--) {
      if (visFills[fi].type === 'SOLID') {
        tc = shapeColorHex(visFills[fi].color, (visFills[fi].opacity == null ? 1 : visFills[fi].opacity) * nodeOpacity);
        break;
      }
      if (visFills[fi].gradientStops && visFills[fi].gradientStops.length > 0) {
        tc = shapeColorHex(visFills[fi].gradientStops[0].color, nodeOpacity);
        break;
      }
    }
    if (tc) lines.push('    android:textColor="' + tc + '"');

    // 字号：px → sp（换算规则同 dp）
    if (typeof fontSize === 'number' && fontSize > 0) {
      lines.push('    android:textSize="' + shapeFormatDp(fontSize, dpScale).replace('dp', 'sp') + '"');
    }

    // 字重映射：普通(400)默认省略；medium(500) → sans-serif-medium；粗体(≥600) → textStyle=bold
    var styleStr = (fontName && fontName.style) ? String(fontName.style) : '';
    var isBold = (typeof fontWeight === 'number' && fontWeight >= 600) ||
      /bold|semibold|heavy/i.test(styleStr);
    var isMedium = !isBold && ((typeof fontWeight === 'number' && fontWeight === 500) ||
      /medium/i.test(styleStr));
    var styles = [];
    if (isBold) styles.push('bold');
    if (/italic/i.test(styleStr)) styles.push('italic');
    if (styles.length > 0) lines.push('    android:textStyle="' + styles.join('|') + '"');
    if (isMedium) lines.push('    android:fontFamily="sans-serif-medium"');

    // 水平对齐（LEFT 为默认，省略）
    if (node.textAlignHorizontal === 'CENTER') lines.push('    android:gravity="center"');
    else if (node.textAlignHorizontal === 'RIGHT') lines.push('    android:gravity="end"');

    // 大写转换
    if (textCase === 'UPPER') lines.push('    android:textAllCaps="true"');

    // 行数截断：优先 Figma 原生截断设置；否则匹配设计惯例「末尾 … + 固定 N 行高」
    var maxLines = null;
    if (node.textTruncation === 'ENDING' && typeof node.maxLines === 'number' && node.maxLines > 0) {
      maxLines = node.maxLines;
    } else if (/(…|\.\.\.)\s*$/.test(node.characters || '')) {
      var lhPx = resolveLineHeightPx(node.lineHeight, typeof fontSize === 'number' ? fontSize : 0);
      var lineH = (lhPx != null && lhPx > 0)
        ? lhPx
        : (typeof fontSize === 'number' && fontSize > 0 ? fontSize * 1.4 : 0);
      if (lineH > 0 && typeof node.height === 'number' && isFinite(node.height)) {
        var est = Math.round(node.height / lineH);
        if (est >= 2) maxLines = est; // 单行末尾 … 多为文案本身，不视为截断
      }
    }
    if (maxLines != null) {
      lines.push('    android:maxLines="' + maxLines + '"');
      lines.push('    android:ellipsize="end"');
    }

    // 字距：Figma px/% → Android em（fontSize 比例）
    if (letterSpacing && typeof fontSize === 'number' && fontSize > 0) {
      var em = null;
      if (letterSpacing.unit === 'PERCENT') em = (letterSpacing.value || 0) / 100;
      else if (letterSpacing.unit === 'PIXELS') em = (letterSpacing.value || 0) / fontSize;
      if (em && Math.abs(em) >= 0.005) {
        lines.push('    android:letterSpacing="' + (Math.round(em * 100) / 100) + '"');
      }
    }

    // 固定行高 → lineSpacingExtra（行高 - 字号，可为负以还原紧排）；AUTO/未设置时不输出
    if (typeof fontSize === 'number' && fontSize > 0) {
      var lhFixed = resolveLineHeightPx(node.lineHeight, fontSize);
      if (lhFixed != null) {
        var extra = (lhFixed - fontSize) * dpScale;
        if (Math.abs(extra) >= 0.5) {
          lines.push('    android:lineSpacingExtra="' + shapeFormatDp(lhFixed - fontSize, dpScale) + '"');
        }
      }
    }

    // 首行注释为文字内容（复制后可识别文案）
    return '<!-- ' + escapeXmlComment(node.characters) + ' -->\n' +
      '<TextView\n' + lines.join('\n') + ' />';
  } catch (e) {
    return null;
  }
}

// 节点 → Android 代码分发：TEXT → TextView，其余 → shape/layer-list
function buildAndroidCodeXml(node, artboard) {
  if (node && node.type === 'TEXT') return buildAndroidTextXml(node);
  return buildAndroidShapeXml(node, artboard);
}

// 生成节点对应的 Android drawable XML（单层填充 → shape，多层填充 → layer-list）；
// 无法表达时返回 null
function buildAndroidShapeXml(node, artboard) {
  try {
    if (!node) return null;
    // 矢量/文本/切线类节点不适合用 shape 表达
    var SKIP_TYPES = ['TEXT', 'LINE', 'VECTOR', 'BOOLEAN_OPERATION', 'STAR', 'POLYGON', 'SLICE', 'SECTION'];
    if (SKIP_TYPES.indexOf(node.type) !== -1) return null;

    if (!artboard) artboard = findRootArtboard(node);
    var dpScale = (artboard && artboard.width > 0) ? BASE_WIDTH_DP / artboard.width : 1;
    var nodeOpacity = node.opacity == null ? 1 : node.opacity;

    var fills = Array.isArray(node.fills)
      ? node.fills.filter(function(f) { return f.visible !== false; })
      : [];
    // 顶层填充是图片 → drawable 无法表达（应走切图），跳过
    if (fills.length > 0 && fills[fills.length - 1].type === 'IMAGE') return null;
    // 可表达的填充（底 → 顶，Figma fills 数组 index 0 为最底层）
    var expressible = fills.filter(function(f) {
      return f.type === 'SOLID' || f.type === 'GRADIENT_LINEAR' || f.type === 'GRADIENT_RADIAL' ||
             f.type === 'GRADIENT_ANGULAR' || f.type === 'GRADIENT_DIAMOND';
    });

    // 圆角（椭圆节点无圆角概念）
    var cornersBody = null;
    if (node.type !== 'ELLIPSE') {
      if (typeof node.cornerRadius === 'number' && node.cornerRadius > 0) {
        cornersBody = '<corners android:radius="' + shapeFormatDp(node.cornerRadius, dpScale) + '" />';
      } else if (node.rectangleCornerRadii && node.rectangleCornerRadii.length === 4) {
        var r = node.rectangleCornerRadii; // [topLeft, topRight, bottomRight, bottomLeft]
        if (r[0] > 0 || r[1] > 0 || r[2] > 0 || r[3] > 0) {
          cornersBody = '<corners\n' +
            '    android:topLeftRadius="' + shapeFormatDp(r[0], dpScale) + '"\n' +
            '    android:topRightRadius="' + shapeFormatDp(r[1], dpScale) + '"\n' +
            '    android:bottomRightRadius="' + shapeFormatDp(r[2], dpScale) + '"\n' +
            '    android:bottomLeftRadius="' + shapeFormatDp(r[3], dpScale) + '" />';
        }
      }
    }

    // 描边（Android shape 描边居中于边缘，Figma strokeAlign 差异忽略）
    var strokeBody = null;
    var strokes = Array.isArray(node.strokes)
      ? node.strokes.filter(function(s) { return s.visible !== false; })
      : [];
    if (strokes.length > 0 && typeof node.strokeWeight === 'number' && node.strokeWeight > 0) {
      var st = strokes[strokes.length - 1];
      var stColor = null;
      if (st.type === 'SOLID') {
        stColor = shapeColorHex(st.color, (st.opacity == null ? 1 : st.opacity) * nodeOpacity);
      } else if (st.gradientStops && st.gradientStops.length > 0) {
        // 渐变描边无法用 shape stroke 表达，退化为第一色标
        stColor = shapeColorHex(st.gradientStops[0].color, nodeOpacity);
      }
      if (stColor) {
        var sLines = [
          '    android:width="' + shapeFormatDp(node.strokeWeight, dpScale) + '"',
          '    android:color="' + stColor + '"'
        ];
        if (node.dashPattern && node.dashPattern.length > 0 && node.dashPattern[0] > 0) {
          sLines.push('    android:dashWidth="' + shapeFormatDp(node.dashPattern[0], dpScale) + '"');
          sLines.push('    android:dashGap="' + shapeFormatDp(node.dashPattern.length > 1 ? node.dashPattern[1] : node.dashPattern[0], dpScale) + '"');
        }
        strokeBody = '<stroke\n' + sLines.join('\n') + ' />';
      }
    }

    var shapeInnerAttr = node.type === 'ELLIPSE' ? ' android:shape="oval"' : '';
    var skipped = fills.length - expressible.length; // 被省略的填充数（如图片填充）

    // ── 多层填充 → layer-list：每个填充一个 item，自底向上绘制，与 Figma 叠放顺序一致 ──
    if (expressible.length >= 2) {
      var items = [];
      for (var ei = 0; ei < expressible.length; ei++) {
        var fbody = shapeFillBody(expressible[ei], node, dpScale, nodeOpacity);
        if (!fbody) continue;
        var parts = [shapeIndent(fbody, '            ')];
        // 每层都带圆角，保证叠加后各层都被圆角裁剪；描边只放最顶层
        if (cornersBody) parts.push(shapeIndent(cornersBody, '            '));
        if (strokeBody && ei === expressible.length - 1) {
          parts.push(shapeIndent(strokeBody, '            '));
        }
        items.push('    <item>\n' +
          '        <shape' + shapeInnerAttr + '>\n' +
          parts.join('\n') + '\n' +
          '        </shape>\n' +
          '    </item>');
      }
      if (items.length === 0) return null;
      var skipNote = skipped > 0
        ? '\n<!-- ' + skipped + ' 个无法用 drawable 表达的填充（如图片）已省略 -->'
        : '';
      return '<?xml version="1.0" encoding="utf-8"?>\n' +
        '<layer-list xmlns:android="http://schemas.android.com/apk/res/android">' + skipNote + '\n' +
        items.join('\n') + '\n' +
        '</layer-list>';
    }

    // ── 单填充 / 无填充 → 普通 shape ──
    var fillBody = expressible.length === 1
      ? shapeFillBody(expressible[0], node, dpScale, nodeOpacity)
      : null;
    if (!fillBody && !cornersBody && !strokeBody) return null;
    var bodies = [];
    if (fillBody) bodies.push(shapeIndent(fillBody, '    '));
    if (cornersBody) bodies.push(shapeIndent(cornersBody, '    '));
    if (strokeBody) bodies.push(shapeIndent(strokeBody, '    '));

    return '<?xml version="1.0" encoding="utf-8"?>\n' +
      '<shape xmlns:android="http://schemas.android.com/apk/res/android"' + shapeInnerAttr + '>\n' +
      bodies.join('\n') + '\n' +
      '</shape>';
  } catch (e) {
    return null;
  }
}

function sendSelectionInfo() {
  var selection = figma.currentPage.selection;
  if (!selection || selection.length === 0) {
    figma.ui.postMessage({
      type: 'selection-info',
      selected: false,
      text: '未选中任何节点'
    });
    return;
  }

  var first = selection[0];
  var artboard = findArtboardNode(first);
  var rootArtboard = findRootArtboard(first);
  var exportable = typeof first.exportAsync === 'function';
  var pageName = figma.currentPage && figma.currentPage.name ? figma.currentPage.name : '';
  var fileName = (figma.root && figma.root.name) ? figma.root.name : '';
  var isMarked = first.getPluginData && first.getPluginData("exportAsImage") === "true";

  // 收集全部选中节点
  var allSelectedNodes = [];
  for (var i = 0; i < selection.length; i++) {
    var s = selection[i];
    allSelectedNodes.push({
      name: s.name,
      id: s.id,
      type: s.type,
      isMarked: s.getPluginData ? s.getPluginData("exportAsImage") === "true" : false,
    });
  }

  // 检测合并组状态：检查父容器的 mergeGroup_map
  var inMergeGroup = false;
  var mergeGroupId = '';
  var mergeMembers = [];
  var mergeParentId = '';
  var firstParent = first.parent;
  if (firstParent && firstParent.getPluginData && firstParent.type !== 'PAGE') {
    try {
      var mgMapStr = firstParent.getPluginData("mergeGroup_map");
      if (mgMapStr) {
        var mgMap = JSON.parse(mgMapStr);
        if (selection.length === 1) {
          for (var mgId2 in mgMap) {
            if (!mgMap.hasOwnProperty(mgId2)) continue;
            var members2 = mgMap[mgId2].members;
            if (members2.indexOf(first.id) !== -1) {
              inMergeGroup = true;
              mergeGroupId = mgId2;
              mergeMembers = members2;
              mergeParentId = firstParent.id;
              break;
            }
          }
        } else {
          var selIdsSorted = allSelectedNodes.map(function(n) { return n.id; }).sort().join(',');
          for (var mgId3 in mgMap) {
            if (!mgMap.hasOwnProperty(mgId3)) continue;
            var mSorted = mgMap[mgId3].members.slice().sort().join(',');
            if (mSorted === selIdsSorted) {
              inMergeGroup = true;
              mergeGroupId = mgId3;
              mergeMembers = mgMap[mgId3].members;
              mergeParentId = firstParent.id;
              break;
            }
          }
        }
      }
    } catch(e) {}
  }

  // Android 代码：TEXT → TextView，其余 → shape/layer-list；单选直接生成，多选逐节点注释拼接
  var shapeCode = '';
  var codeKind = '';
  if (selection.length === 1) {
    shapeCode = buildAndroidCodeXml(first) || '';
    codeKind = first.type === 'TEXT' ? 'text' : 'shape';
  } else {
    var shapeParts = [];
    var textCnt = 0;
    var commonArtboard = findRootArtboard(first); // 多选同画板，只查一次父链
    for (var shi = 0; shi < selection.length; shi++) {
      if (selection[shi].type === 'TEXT') textCnt++;
      var shXml = buildAndroidCodeXml(selection[shi], commonArtboard);
      if (shXml) {
        shapeParts.push('<!-- 节点: ' + escapeXmlComment(selection[shi].name) + '[' + escapeXmlComment(selection[shi].id) + '] -->\n' + shXml);
      }
    }
    shapeCode = shapeParts.join('\n\n');
    codeKind = textCnt === selection.length ? 'text' : (textCnt === 0 ? 'shape' : 'mixed');
  }

  figma.ui.postMessage({
    type: 'selection-info',
    selected: true,
    name: first.name,
    id: first.id,
    nodeType: first.type,
    count: selection.length,
    allNodes: allSelectedNodes,
    parentName: artboard ? artboard.name : '',
    parentId: artboard ? artboard.id : '',
    rootArtboardName: rootArtboard ? rootArtboard.name : '',
    rootArtboardId: rootArtboard ? rootArtboard.id : '',
    exportable: exportable,
    pageName: pageName,
    fileName: fileName,
    isMarked: isMarked,
    inMergeGroup: inMergeGroup,
    mergeGroupId: mergeGroupId,
    mergeMembers: mergeMembers,
    mergeParentId: mergeParentId,
    shapeCode: shapeCode,
    codeKind: codeKind,
    text: '选中: ' + first.name + ' (' + first.type + ')' +
      (artboard ? ' ← ' + artboard.name : '')
  });
}

// ─── 缩略图发送给 UI ───
async function sendThumbnail() {
  var selection = figma.currentPage.selection;
  if (!selection || selection.length === 0) {
    figma.ui.postMessage({ type: 'thumbnail', clear: true, text: '' });
    return;
  }
  if (selection.length > 1) {
    // 多选：为每个选中节点导出 1x 预览图，发送到 UI 展示可折叠列表
    var previews = [];
    for (var si = 0; si < selection.length; si++) {
      var sn = selection[si];
      try {
        var sb64 = null;
        if (typeof sn.exportAsync === 'function') {
          var sbytes = await sn.exportAsync({
            format: 'PNG',
            constraint: { type: 'SCALE', value: 1 }
          });
          sb64 = figma.base64Encode(sbytes);
        }
        previews.push({
          name: sn.name,
          id: sn.id,
          type: sn.type,
          width: Math.round(sn.width),
          height: Math.round(sn.height),
          screenshot: sb64
        });
      } catch(e) {
        previews.push({
          name: sn.name,
          id: sn.id,
          type: sn.type,
          width: Math.round(sn.width),
          height: Math.round(sn.height),
          screenshot: null
        });
      }
    }
    figma.ui.postMessage({ type: 'multi-node-previews', previews: previews });
    return;
  }

  var root = selection[0];

  // 单选合并组内节点 → 显示整组合并预览
  if (root.parent && root.parent.getPluginData) {
    try {
      var mgMapStr = root.parent.getPluginData("mergeGroup_map");
      if (mgMapStr) {
        var mgMap = JSON.parse(mgMapStr);
        for (var mgId in mgMap) {
          if (!mgMap.hasOwnProperty(mgId)) continue;
          if (mgMap[mgId].members.indexOf(root.id) !== -1) {
            // 属于合并组 → 异步加载整组预览
            doMergePreview(mgMap[mgId].members);
            return;
          }
        }
      }
    } catch(e) {}
  }

  var artboard = findArtboardNode(root);
  // 嵌套 Frame/Component（非顶级画板）→ 导出 1x 子节点预览
  if ((root.type === 'FRAME' || root.type === 'COMPONENT' || root.type === 'COMPONENT_SET')
      && artboard && artboard.id !== root.id) {
    try {
      var bytes = await root.exportAsync({
        format: 'PNG',
        constraint: { type: 'SCALE', value: 1 }
      });
      var b64 = figma.base64Encode(bytes);
      figma.ui.postMessage({
        type: 'subnode-preview',
        screenshot: b64,
        name: root.name,
        nodeType: root.type,
        width: Math.round(root.width),
        height: Math.round(root.height),
      });
    } catch (e) {
      figma.ui.postMessage({ type: 'subnode-preview', clear: true });
    }
    return;
  }
  if (root.type !== 'FRAME' && root.type !== 'COMPONENT' && root.type !== 'COMPONENT_SET') {
    // 子节点（非 FRAME/COMPONENT） → 导出 1x 预览图
    try {
      var bytes = await root.exportAsync({
        format: 'PNG',
        constraint: { type: 'SCALE', value: 1 }
      });
      var b64 = figma.base64Encode(bytes);
      figma.ui.postMessage({
        type: 'subnode-preview',
        screenshot: b64,
        name: root.name,
        nodeType: root.type,
        width: Math.round(root.width),
        height: Math.round(root.height),
      });
    } catch (e) {
      figma.ui.postMessage({ type: 'subnode-preview', clear: true });
    }
    return;
  }

  // 快速导出缩略图
  figma.ui.postMessage({ type: 'thumbnail', text: '正在生成预览...' });

  try {
    var thumbBase64 = await exportThumbnail(root);
    figma.ui.postMessage({
      type: 'thumbnail',
      name: root.name,
      nodeId: root.id,
      width: Math.round(root.width),
      height: Math.round(root.height),
      screenshot: thumbBase64,
      text: root.name + ' (' + Math.round(root.width) + 'x' + Math.round(root.height) + ')'
    });
  } catch (e) {
    figma.ui.postMessage({
      type: 'thumbnail',
      clear: true,
      text: root.name + ' (' + Math.round(root.width) + 'x' + Math.round(root.height) + ') [预览失败]'
    });
  }
}

// ─── 完整提取 (响应 skill 的 request-extract 或 extract-by-id) ───
async function doFullExtract(targetNode, requestedNodeId) {
  // 如果指定了 targetNode（extract-by-id），直接用它；否则从 selection 获取
  var root = targetNode || null;
  if (!root) {
    var selection = figma.currentPage.selection;
    if (!selection || selection.length === 0) {
      figma.ui.postMessage({ type: 'extract-error', text: '未选中画板，请在 Figma 中选中目标画板' });
      return;
    }
    if (selection.length > 1) {
      figma.ui.postMessage({ type: 'extract-error', text: '请只选中一个节点' });
      return;
    }
    root = selection[0];
  }
  if (root.type !== 'FRAME' && root.type !== 'COMPONENT' && root.type !== 'COMPONENT_SET') {
    figma.ui.postMessage({ type: 'extract-error', text: '请选中画板 (Frame/Component)，当前类型: ' + root.type });
    return;
  }

  figma.ui.postMessage({ type: 'status', text: '正在提取设计数据...' });

  try {
    // 缩放基准必须是真实根画板的宽度，而不是提取根节点自身的宽度：
    // 提取根是内层节点（如卡片 Frame）时，用节点宽度算 scale 会得到错误的
    // exportScale 与 dp 换算倍数，且全树静默偏大/偏小。见 adapter 的 artboardWidth。
    var artboard = findRootArtboard(root) || root;
    var exportScale = getExportScale(artboard.width);
    currentExportScale = exportScale;
    if (artboard.id !== root.id) {
      figma.ui.postMessage({ type: 'status', text: '提取根: ' + root.name + ' (' + root.id + ')，缩放基准画板: ' + artboard.name + ' (' + artboard.id + ')' });
    }
    figma.ui.postMessage({ type: 'status', text: '导出缩放: ' + exportScale + 'x (基准画板 ' + Math.round(artboard.width) + 'px)' });

    var rootRect = nodeAbsAABB(root);
    var artboardOrigin = { x: rootRect.x, y: rootRect.y };
    var tree = extractNode(root, artboardOrigin);
    var screenshotBase64 = await exportScreenshot(root, exportScale);
    var fileKey = figma.fileKey || '';
    var fileName = (figma.root && figma.root.name) ? figma.root.name : '';
    var pageName = figma.currentPage && figma.currentPage.name ? figma.currentPage.name : '';

    // 收集图片节点并导出（合并组：导出各成员 PNG + 坐标，由 UI Canvas 合成）
    var images = [];
    collectImageNodes(root, images);
    var exportedImages = [];
    for (var i = 0; i < images.length; i++) {
      var item = images[i];
      try {
        if (item.isMergedGroup && item.childIds && item.childIds.length > 0) {
          // 取所有成员节点，委托给统一的合并组导出函数
          var memberNodesArr = [];
          for (var ci0 = 0; ci0 < item.childIds.length; ci0++) {
            try {
              var n0 = await figma.getNodeByIdAsync(item.childIds[ci0]);
              if (n0) memberNodesArr.push(n0);
            } catch(e) {}
          }
          var mgPayload = await exportMergeGroup(memberNodesArr, root, exportScale);
          if (mgPayload && mgPayload.nodeImages && mgPayload.nodeImages.length > 0) {
            exportedImages.push({
              id: item.mergeGroupId,
              name: item.name || '合并切图',
              data: '',
              isMergedGroup: true,
              childImages: mgPayload.nodeImages,
              canvasW: mgPayload.canvasW,
              canvasH: mgPayload.canvasH,
              clipRectPx: mgPayload.clipRectPx,
            });
          }
        } else {
          var node = item.node;
          if (node && typeof node.exportAsync === 'function') {
            var bytes = await node.exportAsync({ format: 'PNG', constraint: { type: 'SCALE', value: exportScale } });
            exportedImages.push({ id: item.imageHash, name: item.name, data: figma.base64Encode(bytes) });
          }
        }
      } catch(e) {}
    }

    // 发送到 UI（UI 负责 POST 到 server）
    // Figma 插件沙箱的 postMessage 用结构化克隆序列化 payload，
    // 若 nodeTree 中残留 Figma 包裹对象（Proxy，含 Symbol 内部槽），
    // 会抛 "Cannot unwrap symbol"。用 JSON 往返剥离所有非可序列化值。
    var safePayload;
    try {
      safePayload = JSON.parse(JSON.stringify({
        schemaVersion: '2.0',
        kind: 'figma-extract',
        fileKey: fileKey,
        fileName: fileName,
        pageName: pageName,
        name: root.name,
        nodeId: root.id,
        width: root.width,
        height: root.height,
        // dp 换算基准：始终是真实根画板，而非提取根节点（见 doFullExtract 顶部注释）
        artboardId: artboard.id,
        artboardName: artboard.name,
        artboardWidth: artboard.width,
        exportScale: exportScale,
        requestedNodeId: requestedNodeId || '',
        nodeTree: tree,
        screenshot: screenshotBase64,
        imageCount: exportedImages.length,
        imageIds: images.map(function(item) { return item.imageHash; }),
        images: exportedImages
      }));
    } catch (cloneErr) {
      figma.ui.postMessage({ type: 'extract-error', text: '序列化失败: ' + (cloneErr.message || String(cloneErr)) });
      return;
    }
    figma.ui.postMessage({ type: 'composition-ready', payload: safePayload });

  } catch (e) {
    figma.ui.postMessage({ type: 'extract-error', text: '提取失败: ' + (e.message || String(e)) });
  }
}

// 当前导出缩放（doFullExtract 时更新，exportImages 复用）
var currentExportScale = TARGET_DENSITY;

// ─── 图片导出（响应 UI 请求） ───
async function exportImages(imageIds) {
  var items = [];
  var BATCH_SIZE = 8;
  var scale = currentExportScale;
  for (var i = 0; i < imageIds.length; i += BATCH_SIZE) {
    var batch = imageIds.slice(i, i + BATCH_SIZE);
    var results = await Promise.all(batch.map(async function(imageId) {
      try {
        var node = null;
        try { node = figma.getNodeById(imageId); } catch(e) {}
        if (node && typeof node.exportAsync === 'function') {
          var bytes = await node.exportAsync({ format: 'PNG', constraint: { type: 'SCALE', value: scale } });
          return { id: imageId, data: figma.base64Encode(bytes) };
        }
      } catch(e) {}
      try {
        var img = figma.getImageByHash(imageId);
        if (img) {
          var bytes = await img.getBytesAsync();
          return { id: imageId, data: figma.base64Encode(bytes) };
        }
      } catch(e) {}
      return null;
    }));
    results.forEach(function(r) { if (r) items.push(r); });
  }
  figma.ui.postMessage({ type: 'image-export:result', items: items });
}

// ─── 导出当前选中的节点（UI 下载切图，支持多选） ───
async function exportSelectedNodes() {
  var selection = figma.currentPage.selection;
  if (!selection || selection.length === 0) {
    figma.ui.postMessage({ type: 'node-export:error', text: '未选中任何节点' });
    return;
  }

  // 从根画板确定正确导出缩放
  var artboard = findRootArtboard(selection[0]);
  var exportScale = artboard ? getExportScale(artboard.width) : TARGET_DENSITY;

  // 单节点 → 直接下载单张 PNG
  if (selection.length === 1) {
    var node = selection[0];
    if (!node || typeof node.exportAsync !== 'function') {
      figma.ui.postMessage({ type: 'node-export:error', text: '该节点不可导出' });
      return;
    }
    try {
      var bytes = await node.exportAsync({
        format: 'PNG',
        constraint: { type: 'SCALE', value: exportScale }
      });
      figma.ui.postMessage({
        type: 'node-export:single-result',
        data: figma.base64Encode(bytes),
        name: node.name || 'export',
      });
    } catch (e) {
      figma.ui.postMessage({ type: 'node-export:error', text: '导出失败: ' + (e.message || String(e)) });
    }
    return;
  }

  // 多节点 → 逐一下发，最后打包 ZIP
  var exportedCount = 0;
  var failCount = 0;
  for (var i = 0; i < selection.length; i++) {
    var node = selection[i];
    if (!node || typeof node.exportAsync !== 'function') {
      failCount++;
      continue;
    }
    try {
      var bytes = await node.exportAsync({
        format: 'PNG',
        constraint: { type: 'SCALE', value: exportScale }
      });
      var b64 = figma.base64Encode(bytes);
      figma.ui.postMessage({
        type: 'node-export:result',
        data: b64,
        name: (node.name || ('export_' + (i + 1))) + '_' + (i + 1),
        width: node.width,
        height: node.height,
      });
      exportedCount++;
    } catch (e) {
      failCount++;
    }
  }

  if (exportedCount === 0) {
    figma.ui.postMessage({ type: 'node-export:error', text: '所有选中节点均导出失败' });
  } else if (failCount > 0) {
    figma.ui.postMessage({ type: 'node-export:complete', exported: exportedCount, failed: failCount });
  } else {
    figma.ui.postMessage({ type: 'node-export:complete', exported: exportedCount, failed: 0 });
  }
}

// ─── 合并预览（标记为切图后自动触发） ───
async function doMergePreview(nodeIds) {
  if (!nodeIds || nodeIds.length < 2) return;
  try {
    var nodes = [];
    for (var i = 0; i < nodeIds.length; i++) {
      var n = await figma.getNodeByIdAsync(nodeIds[i]);
      if (n) nodes.push(n);
    }
    if (nodes.length < 2) {
      figma.ui.postMessage({ type: 'status', text: '合并预览: 有效节点不足 ' + nodes.length + '/' + nodeIds.length });
      return;
    }
    var result = await buildMergeStitchPayload(nodes);
    if (!result) {
      figma.ui.postMessage({ type: 'status', text: '合并预览: 合成数据生成失败' });
      return;
    }
    figma.ui.postMessage({
      type: 'merge-preview',
      nodeImages: result.nodeImages,
      mergeW: result.mergeW,
      mergeH: result.mergeH,
      nodeCount: result.nodeImages.length,
      canvasW: result.canvasW,
      canvasH: result.canvasH,
      clipRectPx: result.clipRectPx,
    });
  } catch(e) {
    figma.ui.postMessage({ type: 'status', text: '合并预览失败: ' + (e.message || String(e)) });
  }
}

// ─── 合并组成员按 Z 轴顺序排序 ───
// 成员数组顺序决定导出顺序，进而决定 UI Canvas 绘制顺序（后绘制者盖住先绘制者）。
// Figma 图层树 parent.children 索引是 Z 轴：children[0] 最底层（背景），children[last] 最顶层（前景）。
// 而合并组成员是从拖选顺序（selection 自前向后）存储的，直接作为绘制顺序时，
// 背景可能排在文字之后被后画而盖住文字 —— 表现为"合并后只能看到背景"。
// 统一按 parent.children 索引升序重排，保证底层背景先画、前景文字后画，与 Figma 视觉一致。
function sortByZOrder(nodes) {
  if (!nodes || nodes.length < 2) return nodes;
  return nodes.slice().sort(function(a, b) {
    if (!a || !b) return 0;
    var pa = a.parent, pb = b.parent;
    if (pa && pb && pa === pb && pa.children) {
      return pa.children.indexOf(a) - pa.children.indexOf(b);
    }
    return 0;
  });
}

// ─── 共享：合并组导出（统一提取/预览/下载三路的合并切图逻辑） ───
// nodes: 成员 Figma 节点数组（已 resolve）
// artboard: 根画板节点（用于 clipRect 计算），可为 null
// exportScale: 导出缩放（已从画板宽度计算）
// 返回 { nodeImages, mergeW, mergeH, canvasW, canvasH, clipRectPx } 或 null
async function exportMergeGroup(nodes, artboard, exportScale) {
  if (!nodes || nodes.length === 0) return null;
  // 按 Z 轴顺序重排成员，保证背景在下层、前景文字在上层
  nodes = sortByZOrder(nodes);

  // 成员并集包围盒（绝对坐标，不裁剪）
  var mgBounds = mergedGroupBounds(nodes);
  var originX, originY, mergeW, mergeH;
  if (mgBounds) {
    originX = mgBounds.left;
    originY = mgBounds.top;
    mergeW = mgBounds.right - mgBounds.left;
    mergeH = mgBounds.bottom - mgBounds.top;
  } else {
    // 回退：成员原始 bounds 并集
    var rMinX = Infinity, rMinY = Infinity, rMaxX = -Infinity, rMaxY = -Infinity;
    for (var i = 0; i < nodes.length; i++) {
      var n0 = nodes[i];
      var r0 = nodeAbsAABB(n0);
      rMinX = Math.min(rMinX, r0.x);
      rMinY = Math.min(rMinY, r0.y);
      rMaxX = Math.max(rMaxX, r0.x + r0.width);
      rMaxY = Math.max(rMaxY, r0.y + r0.height);
    }
    originX = rMinX; originY = rMinY;
    mergeW = rMaxX - rMinX; mergeH = rMaxY - rMinY;
  }

  // 画板可视区（相对并集原点的偏移）——UI 合成后只截取这块区域
  var clipRectPx = null;
  if (artboard) {
    var abRect = nodeAbsAABB(artboard);
    clipRectPx = {
      x: Math.round((abRect.x - originX) * exportScale),
      y: Math.round((abRect.y - originY) * exportScale),
      w: Math.max(0, Math.round(abRect.width * exportScale)),
      h: Math.max(0, Math.round(abRect.height * exportScale))
    };
  }

  // 导出每个成员
  var nodeImages = [];
  for (var i = 0; i < nodes.length; i++) {
    var n = nodes[i];
    if (!n || typeof n.exportAsync !== 'function') continue;
    try {
      var bytes = await n.exportAsync({
        format: 'PNG',
        constraint: { type: 'SCALE', value: exportScale }
      });
      var rn = nodeAbsAABB(n);
      nodeImages.push({
        data: figma.base64Encode(bytes),
        name: n.name,
        w: rn.width * exportScale,
        h: rn.height * exportScale,
        // 相对并集原点（不裁剪）；溢出部分由 UI canvas 截取 clipRect 时自然裁掉
        offsetX: (rn.x - originX) * exportScale,
        offsetY: (rn.y - originY) * exportScale,
      });
    } catch(e) {}
  }

  if (nodeImages.length === 0) return null;

  var canvasW = Math.max(1, Math.round(mergeW * exportScale));
  var canvasH = Math.max(1, Math.round(mergeH * exportScale));
  var MAX_CANVAS = 4096;
  if (canvasW > MAX_CANVAS || canvasH > MAX_CANVAS) {
    console.warn('[exportMergeGroup] 合并组 canvas 尺寸 ' + canvasW + 'x' + canvasH + ' 超过 ' + MAX_CANVAS + ' 上限，全部成员可能画板外');
    canvasW = Math.min(canvasW, MAX_CANVAS);
    canvasH = Math.min(canvasH, MAX_CANVAS);
  }

  console.warn('[exportMergeGroup] 成员数=' + nodes.length + ' mergeW=' + mergeW + ' mergeH=' + mergeH + ' exportScale=' + exportScale + ' → canvas=' + canvasW + 'x' + canvasH + ' clipRectPx=' + JSON.stringify(clipRectPx));

  return {
    nodeImages: nodeImages,
    mergeW: mergeW * exportScale,
    mergeH: mergeH * exportScale,
    canvasW: canvasW,
    canvasH: canvasH,
    clipRectPx: clipRectPx,
  };
}

// ─── 预览/下载用：导出节点列表并生成合并拼接数据 ───
// 薄包装：从 nodes 反查画板 + 算 exportScale，然后委托给 exportMergeGroup
async function buildMergeStitchPayload(nodes) {
  var artboard = findRootArtboard(nodes[0]);
  var scale = artboard ? getExportScale(artboard.width) : TARGET_DENSITY;
  return await exportMergeGroup(nodes, artboard, scale);
}

// ─── 生命周期 ───
figma.showUI(__html__, { width: 360, height: 420, themeColors: true });

// 缩略图防抖
var _thumbnailTimer = null;
function scheduleThumbnail() {
  if (_thumbnailTimer) clearTimeout(_thumbnailTimer);
  _thumbnailTimer = setTimeout(function() { sendThumbnail(); }, 200);
}

// ─── 遍历所有画板（轻量，仅返回元数据） ───
async function listAllArtboards() {
  try {
    var allPages = figma.root.children;
    var currentPageId = figma.currentPage.id;
    var artboards = [];
    for (var pi = 0; pi < allPages.length; pi++) {
      var page = allPages[pi];
      if (page.id !== currentPageId) {
        await page.loadAsync();
      }
      for (var ci = 0; ci < page.children.length; ci++) {
        var child = page.children[ci];
        if (child.type === 'FRAME' || child.type === 'COMPONENT' || child.type === 'COMPONENT_SET') {
          artboards.push({
            pageName: page.name,
            pageId: page.id,
            name: child.name,
            id: child.id,
            type: child.type,
            width: Math.round(child.width),
            height: Math.round(child.height),
          });
        }
      }
    }
    figma.ui.postMessage({
      type: 'artboard-list',
      artboards: artboards,
      total: artboards.length,
    });
  } catch (e) {
    figma.ui.postMessage({
      type: 'artboard-list-error',
      text: '遍历画板失败: ' + (e.message || String(e)),
    });
  }
}

// 选中变化 → 更新缩略图 + 选中节点信息
figma.on('selectionchange', function() {
  sendSelectionInfo();
  scheduleThumbnail();
});

// 插件启动时立即检查是否有预选中
var initialSelection = figma.currentPage.selection;
if (initialSelection && initialSelection.length >= 1) {
  // 发送选中节点信息（任意类型）
  sendSelectionInfo();
  var node = initialSelection[0];
  if (node.type === 'FRAME' || node.type === 'COMPONENT' || node.type === 'COMPONENT_SET') {
    scheduleThumbnail();
  }
}

// UI 消息处理
figma.ui.onmessage = async function(msg) {
  if (!msg) return;
  switch (msg.type) {
    case 'trigger-extract':
      // UI 检测到 server 有 pending 请求 → 执行完整提取
      doFullExtract();
      break;
    case 'extract':
      // 兼容手动触发
      doFullExtract();
      break;
    case 'extract-by-id':
      // 按 nodeId 提取，不依赖当前选中状态
      // 特殊值 __list_all__ = 遍历所有画板（由 request-list 触发）
      if (msg.nodeId === '__list_all__') {
        listAllArtboards();
        break;
      }
      try {
        var raw = await figma.getNodeByIdAsync(msg.nodeId);
        if (!raw) {
          figma.ui.postMessage({ type: 'extract-error', text: '节点未找到: ' + msg.nodeId });
          break;
        }
        // 无论 nodeId 指向画板还是子节点，一律提取其所属根画板：
        // 子节点（含内层 Frame）自身不是 dp 换算基准，按它提取会得到错误的 scale；
        // 且缓存以整块画板为单位，后续按任意子节点 nodeId 都能查到。
        var artboard = findRootArtboard(raw);
        if (!artboard) {
          figma.ui.postMessage({ type: 'extract-error', text: '节点 ' + msg.nodeId + ' 未找到所属画板' });
          break;
        }
        if (artboard.id !== raw.id) {
          figma.ui.postMessage({ type: 'status', text: '节点 ' + msg.nodeId + ' 所属画板: ' + artboard.name + ' (' + artboard.id + ')' });
        }
        doFullExtract(artboard, msg.nodeId);
      } catch(e) {
        figma.ui.postMessage({ type: 'extract-error', text: 'extract-by-id 失败: ' + (e.message || String(e)) });
      }
      break;
    case 'export-images':
      exportImages(msg.ids || []);
      break;
    case 'mark-export':
      // 多选时在父容器上创建合并组；单选时直接标记节点
      try {
        var ids = msg.nodeIds || (msg.nodeId ? [msg.nodeId] : []);
        if (ids.length === 0) break;

        if (ids.length === 1) {
          var targeted = await figma.getNodeByIdAsync(ids[0]);
          if (targeted && targeted.setPluginData) {
            targeted.setPluginData("exportAsImage", "true");
          }
        } else {
          // 多选：验证同一父容器
          var firstN = await figma.getNodeByIdAsync(ids[0]);
          if (!firstN || !firstN.parent || firstN.parent.type === 'PAGE') {
            figma.ui.postMessage({ type: 'extract-error', text: '父容器无效，无法合并标记。' });
            break;
          }
          var parentN = firstN.parent;
          var sameParent = true;
          for (var mi = 1; mi < ids.length; mi++) {
            var mn = await figma.getNodeByIdAsync(ids[mi]);
            if (!mn || !mn.parent || mn.parent.id !== parentN.id) {
              sameParent = false;
              break;
            }
          }
          if (!sameParent) {
            figma.ui.postMessage({ type: 'extract-error', text: '选中节点不在同一父容器中，无法合并标记。' });
            break;
          }

          // 检查这些节点是否已经属于某个合并组
          var existingMap = {};
          if (parentN.getPluginData) {
            try { existingMap = JSON.parse(parentN.getPluginData("mergeGroup_map") || '{}'); } catch(e) {}
          }
          var idsSorted = ids.slice().sort().join(',');
          var alreadyMerged = false;
          for (var ek in existingMap) {
            if (!existingMap.hasOwnProperty(ek)) continue;
            var emSorted = existingMap[ek].members.slice().sort().join(',');
            if (emSorted === idsSorted) {
              alreadyMerged = true;
              figma.ui.postMessage({ type: 'status', text: '这些节点已属于合并组: ' + (existingMap[ek].name || ek) });
              // 刷新预览
              try { await doMergePreview(ids); } catch(e) {}
              break;
            }
          }
          if (alreadyMerged) {
            sendSelectionInfo();
            break;
          }

          // 在父容器上创建新合并组
          var mgId = 'mg_' + Date.now().toString(36);
          var memNames = [];
          var originalStates = {};
          for (var mj = 0; mj < ids.length; mj++) {
            var mn2 = await figma.getNodeByIdAsync(ids[mj]);
            if (mn2) {
              memNames.push(mn2.name);
              originalStates[mn2.id] = mn2.getPluginData ? mn2.getPluginData("exportAsImage") === "true" : false;
              if (mn2.setPluginData) mn2.setPluginData("exportAsImage", "");
            }
          }
          var mgName = '合并_' + memNames.slice(0, 2).join('_');
          if (memNames.length > 2) mgName += '_等' + memNames.length + '项';
          existingMap[mgId] = { members: ids, name: mgName, originalStates: originalStates };
          if (parentN.setPluginData) {
            parentN.setPluginData("mergeGroup_map", JSON.stringify(existingMap));
          }
        }
        sendSelectionInfo();
        // 多选时自动触发合并预览
        if (ids.length > 1) {
          try { await doMergePreview(ids); } catch(e) {}
        }
      } catch(e) {
        figma.ui.postMessage({ type: 'extract-error', text: '标记失败: ' + (e.message || String(e)) });
      }
      break;
    case 'unmark-export':
      // 仅处理单节点取消标记（非合并组场景）
      try {
        var uid = msg.nodeId;
        if (uid) {
          var ut = await figma.getNodeByIdAsync(uid);
          if (ut && ut.setPluginData) ut.setPluginData("exportAsImage", "");
        }
        sendSelectionInfo();
      } catch(e) {}
      break;
    case 'unmark-merge-group':
      // 删除指定合并组，不影响其他合并组
      try {
        var upN = msg.parentId ? await figma.getNodeByIdAsync(msg.parentId) : null;
        if (!upN) {
          figma.ui.postMessage({ type: 'extract-error', text: '取消合并失败: 父容器未找到' });
          break;
        }
        if (!upN.getPluginData) {
          figma.ui.postMessage({ type: 'extract-error', text: '取消合并失败: 父容器不支持 pluginData' });
          break;
        }
        var mgMap2 = JSON.parse(upN.getPluginData("mergeGroup_map") || '{}');
        var targetGroup = mgMap2[msg.mergeGroupId];
        var memberIds = targetGroup ? targetGroup.members : [];
        var originalStates = targetGroup ? (targetGroup.originalStates || {}) : {};
        delete mgMap2[msg.mergeGroupId];
        var keysLeft = Object.keys(mgMap2).length;
        upN.setPluginData("mergeGroup_map", keysLeft > 0 ? JSON.stringify(mgMap2) : "");
        // 恢复成员节点到合并前的原始导出状态
        for (var ri = 0; ri < memberIds.length; ri++) {
          try {
            var rn = await figma.getNodeByIdAsync(memberIds[ri]);
            if (rn && rn.setPluginData) {
              rn.setPluginData("exportAsImage", originalStates[rn.id] ? "true" : "");
            }
          } catch(e) {}
        }
        figma.ui.postMessage({ type: 'status', text: '已取消合并组: 剩余 ' + keysLeft + ' 组，恢复 ' + memberIds.length + ' 个独立切图' });
        sendSelectionInfo();
        scheduleThumbnail();
      } catch(e) {
        figma.ui.postMessage({ type: 'extract-error', text: '取消合并失败: ' + (e.message || String(e)) });
      }
      break;
    case 'export-selected-node':
      exportSelectedNodes();
      break;
    case 're-extract':
      // 面板"重新提取"按钮：一步完成提取 + 桥服务器自动跑 adapter
      try {
        var rawN = await figma.getNodeByIdAsync(msg.nodeId);
        if (!rawN) {
          figma.ui.postMessage({ type: 'extract-error', text: '节点未找到: ' + msg.nodeId });
          break;
        }
        figma.ui.postMessage({ type: 'status', text: '正在重新提取...' });
        await doFullExtract(rawN);
        // 注：doFullExtract 完成后 UI 会收到 composition-ready，由 sendToServer 接管
      } catch(e) {
        figma.ui.postMessage({ type: 'extract-error', text: '重新提取失败: ' + (e.message || String(e)) });
      }
      break;
    case 'list-artboards':
      listAllArtboards();
      break;
    case 'get-merge-preview':
      // UI 标记为切图后自动触发：导出各节点供 UI 合成预览
      doMergePreview(msg.nodeIds);
      break;
    case 'close':
      figma.closePlugin();
      break;
  }
};
