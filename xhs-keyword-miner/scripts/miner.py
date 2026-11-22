# -*- coding: utf-8 -*-
"""小红书搜索下拉词采集器

用法:
    python miner.py "deepseek" "codex" --workdir ./xhs_keywords

原理:
    小红书搜索联想接口(edith.xiaohongshu.com/api/sns/web/v1/search/recommend)
    无需登录即可返回候选词，且列表按热度相关性排序。
    本脚本用真实 Chrome 打开页面并模拟键入，从响应中截获联想结果。

一次会话内完成三件事(避免重复请求):
    1. 种子词的前缀联想  -> 一级下拉词 + 每个前缀的完整有序列表
    2. 对每个一级词再联想一次 -> 同时得到「二级扩展词」和「该词的排序数据」
    3. 合并写入 data.json
"""
import argparse
import json
import os
import random
import sys
import time
from urllib.parse import quote

from playwright.sync_api import sync_playwright

DATA_FILE = "data.json"


# ---------- 存储 ----------
def load_data(workdir):
    path = os.path.join(workdir, DATA_FILE)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"seeds": [], "prefix_hits": {}, "l1_lists": {}, "rows": []}


def save_data(workdir, data):
    path = os.path.join(workdir, DATA_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


# ---------- 前缀生成 ----------
def gen_prefixes(word):
    """中文逐字取前缀；英文/数字词取关键前缀，避免产出大量无关泛词"""
    word = word.strip()
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in word)
    if has_cjk:
        return [word[:i] for i in range(1, len(word) + 1)]
    pfs = [word]
    if len(word) > 3:
        pfs.insert(0, word[:3])
    if len(word) > 6:
        pfs.insert(0, word[:5])
    return pfs


# ---------- 浏览器 ----------
CLEAR_POPUP_JS = """
() => {
  // 直接移除所有遮罩与弹窗容器（无论小红书弹什么新版弹窗都通用）
  const sels = ['.reds-mask', "i[class*='mask']", "[class*='login-mask']",
                ".login-container", "[class*='side-bar-component'] .close"];
  let n = 0;
  for (const s of sels) {
    document.querySelectorAll(s).forEach(e => { e.remove(); n++; });
  }
  return n;
}
"""


def clear_popups(page):
    """按 Escape 并移除遮罩层 DOM，避免遮罩拦截搜索框点击"""
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        page.evaluate(CLEAR_POPUP_JS)
    except Exception:
        pass
    # 兜底：点常见关闭按钮
    for sel in [".close-button", "[class*='close']"]:
        el = page.query_selector(sel)
        if el:
            try:
                el.click(timeout=1200)
                break
            except Exception:
                page.evaluate(CLEAR_POPUP_JS)


def open_page(ctx):
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.xiaohongshu.com/explore",
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    clear_popups(page)
    page.wait_for_timeout(800)
    return page


def make_suggester(page):
    captured = []

    def on_response(resp):
        if "search/recommend" in resp.url:
            try:
                captured.append((resp.url, resp.json()))
            except Exception:
                pass

    page.on("response", on_response)

    box = page.query_selector("#search-input") or page.query_selector("input[placeholder*='搜索']")
    if not box:
        raise RuntimeError(
            "未找到搜索框。可能页面被风控或改版，请在浏览器中确认 www.xiaohongshu.com 可正常打开"
        )

    def suggest(text, timeout=10.0):
        """键入文本并返回该次联想的有序词列表；失败返回 []"""
        captured.clear()
        try:
            box.click(timeout=5000)
        except Exception:
            clear_popups(page)
            try:
                box.click(timeout=5000)
            except Exception:
                return []
        page.keyboard.press("Control+a")
        page.keyboard.press("Delete")
        page.keyboard.type(text, delay=90)

        key = "keyword=" + quote(text)
        # 空格可能编码为 %20 或 +，大小写也可能被规范化
        cands = [key.lower(), key.lower().replace("%20", "+"), key.lower().replace("%20", " ")]
        deadline = time.time() + timeout
        body = None
        while time.time() < deadline:
            for u, b in reversed(captured):
                ul = u.lower()
                if any(c in ul for c in cands):
                    body = b
                    break
            if body:
                break
            page.wait_for_timeout(250)

        page.wait_for_timeout(random.uniform(700, 1300))  # 控制频率，降低风控概率
        if not body:
            return []
        items = (body.get("data") or {}).get("sug_items") or []
        return [it.get("text", "").strip() for it in items if it.get("text")]

    return suggest


# ---------- 主流程 ----------
def collect(seeds, workdir, headless=False):
    os.makedirs(workdir, exist_ok=True)
    data = load_data(workdir)
    known = {r["word"]: r for r in data["rows"]}

    new_seeds = [s.strip() for s in seeds if s.strip() and s.strip() not in data["seeds"]]
    if not new_seeds:
        print("没有新的种子词需要采集")
        return data

    profile = os.path.join(workdir, "xhs_profile")
    os.makedirs(profile, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            profile,
            channel="chrome",
            headless=headless,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = open_page(ctx)
            suggest = make_suggester(page)

            # 1) 前缀联想
            print(f"\n【1/2】种子词前缀联想（{len(new_seeds)} 个种子词）")
            for seed in new_seeds:
                for pf in gen_prefixes(seed):
                    words = suggest(pf)
                    if not words:
                        print(f"  ⚠ 前缀 {pf!r} 未取到结果")
                        continue
                    data["prefix_hits"][pf] = words
                    for w in words:
                        if w not in known:
                            known[w] = {"word": w, "tier": 1,
                                        "source": f"种子[{seed}]前缀[{pf}]"}
                            data["rows"].append(known[w])
                    print(f"  [{pf}] {len(words)} 词: {' | '.join(words)}")

            # 2) 一级词联想 -> 二级扩展词 + 排序数据
            targets = [w for w, r in known.items()
                       if r["tier"] == 1 and w not in data["l1_lists"] and len(w) <= 14]
            print(f"\n【2/2】一级词联想（{len(targets)} 个，同时产出二级扩展词与排序数据）")
            for i, w in enumerate(targets, 1):
                words = suggest(w)
                data["l1_lists"][w] = words
                added = 0
                for x in words:
                    if x and x not in known:
                        known[x] = {"word": x, "tier": 2, "source": f"二级[{w}]"}
                        data["rows"].append(known[x])
                        added += 1
                print(f"  [{i}/{len(targets)}] {w} -> 返回{len(words)} / 新增{added}")
        finally:
            ctx.close()

    data["seeds"] = data["seeds"] + new_seeds
    path = save_data(workdir, data)
    print(f"\n完成: 种子词 {len(data['seeds'])} 个 / 累计 {len(data['rows'])} 词 -> {path}")
    return data


def main():
    ap = argparse.ArgumentParser(description="小红书下拉词采集器")
    ap.add_argument("seeds", nargs="+", help="种子关键词，可多个")
    ap.add_argument("--workdir", default="./xhs_keywords", help="数据目录，默认 ./xhs_keywords")
    ap.add_argument("--headless", action="store_true", help="无头模式（默认有头，更稳）")
    args = ap.parse_args()
    workdir = os.path.abspath(args.workdir)
    try:
        collect(args.seeds, workdir, headless=args.headless)
    except Exception as e:
        print(f"\n采集失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
