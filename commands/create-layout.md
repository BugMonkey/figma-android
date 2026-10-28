# create-layout — 仅布局 XML

匹配："只要布局"、"只改 xml"、"不生成 Activity"

## 步骤

按 `commands/create-page.md` 执行，仅去掉「生成 Activity/Fragment 骨架」一步；数据提取、
结构确认阻塞、XML 与资源生成、编译验证、终端摘要、任务记忆写入均与 create-page 相同。

## 切图尺寸

```text
layout_width  = android_tree.json dp.w
layout_height = android_tree.json dp.h
```

## 文本

- 字号：`style.font_size_sp` → `android:textSize`
- 颜色：优先复用已有 `@color`，新色写入 `colors.xml`
- 可能溢出：加 `maxLines + ellipsize`

## 禁止

- 不创建 Fragment/Activity/ViewModel
- 不伪造缺失切图
- 不对 dp 值做二次换算
