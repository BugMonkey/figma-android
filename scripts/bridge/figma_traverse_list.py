#!/usr/bin/env python3
"""
figma_traverse_list.py — 轻量遍历所有画板，返回元数据清单

触发 Figma 插件遍历所有页面的画板节点（Frame/Component/ComponentSet），
返回名称、ID、类型、尺寸等元数据。不导出截图和节点树，秒级返回。

用法:
  python3 figma_traverse_list.py [--port 7789] [--width 1080]

  --width 只保留指定宽度的画板（设计稿标准宽度，本项目为 1080px）。
  宽度不符的画板视为废弃稿，从 artboards 中剔除并记入 filtered_out。

输出 JSON:
  {
    "artboards": [
      { "pageName": "页面1", "pageId": "0:1",
        "name": "首页", "id": "2:141", "type": "FRAME",
        "width": 1080, "height": 2340 },
      ...
    ],
    "total": 30,
    "filtered_out": [
      { "id": "1:2", "name": "Frame 1", "width": 510, "height": 2340 },
      ...
    ]
  }

错误:
  exit 1 且 stderr 输出错误描述
"""

import json
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import URLError


def http_get(host: str, port: int, path: str, timeout: float = 5.0):
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
              timeout: float = 5.0):
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


def filter_artboards(data: dict, width) -> dict:
    """按标准宽度过滤画板；width 为 None 时原样返回。

    设计稿画板宽度应与项目规范一致（本项目为 1080px）。宽度不符的多为废弃稿
    （例如 510x2340 的 Frame 1/3/4/5/6），混进提取与代码生成只会产生噪声。
    被过滤项以 filtered_out 字段返回，便于调用方核对，而不是静默丢弃。
    """
    if not width:
        return data
    boards = data.get("artboards") or []
    kept = [a for a in boards if a.get("width") == width]
    dropped = [a for a in boards if a.get("width") != width]
    out = dict(data)
    out["artboards"] = kept
    out["total"] = len(kept)
    out["filtered_out"] = [
        {"id": a.get("id"), "name": a.get("name"),
         "width": a.get("width"), "height": a.get("height")}
        for a in dropped
    ]
    return out


def main():
    import argparse
    parser = argparse.ArgumentParser(description="遍历 Figma 所有画板")
    parser.add_argument("--port", type=int, default=7789, help="桥服务器端口")
    parser.add_argument("--width", type=int, default=None,
                        help="只保留该宽度的画板（如 1080）；不传则不过滤")
    args = parser.parse_args()

    host = "127.0.0.1"
    port = args.port

    # 1. 健康检查
    status, body = http_get(host, port, "/health", timeout=2.0)
    if status != 200:
        print("错误: 桥服务器未运行，请先执行 start", file=sys.stderr)
        sys.exit(1)

    # 2. 检查已有结果（上次遍历后未清除）
    status, body = http_get(host, port, "/api/artboard-list", timeout=3.0)
    if status == 200:
        try:
            cached = json.loads(body)
            if cached.get("artboards") and not cached.get("error"):
                print(json.dumps(filter_artboards(cached, args.width), ensure_ascii=False))
                return
        except (json.JSONDecodeError, TypeError):
            pass

    # 3. 触发新遍历请求
    status, body = http_post(host, port, "/api/request-list", timeout=3.0)
    if status != 200:
        print(f"错误: 触发遍历请求失败 (HTTP {status})", file=sys.stderr)
        sys.exit(1)

    print("已触发遍历，等待插件响应...", file=sys.stderr)

    # 4. 轮询等待结果（最多 75 秒：需覆盖插件被节流时的一次轮询 ~60s）
    deadline = time.time() + 75.0
    while time.time() < deadline:
        time.sleep(1.0)
        status, body = http_get(host, port, "/api/artboard-list", timeout=3.0)
        if status != 200:
            continue
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            continue

        if "error" in data and data["error"]:
            print(f"错误: {data['error']}", file=sys.stderr)
            sys.exit(1)

        if data.get("artboards") is not None:
            print(json.dumps(filter_artboards(data, args.width), ensure_ascii=False))
            return

    print("错误: 遍历超时 (75s)，请确认 Figma 插件面板已打开 "
          "(面板不在前台时轮询会被节流到约 60s 一次，仍可成功但更慢)", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()