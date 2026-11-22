# -*- coding: utf-8 -*-
"""小红书话题数据包构建：合并多轮 CSV -> 去重 -> Excel 五表 + 标签库导入 CSV

用法:
  python build.py --input ./out --xlsx 包.xlsx --csv 总表.csv --taglib 标签库.csv --seeds "kimi,通义千问"
  python build.py --input a.csv b.csv --xlsx 包.xlsx
"""
try:
    import openpyxl
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "openpyxl>=3.1.0"])
    import openpyxl

import argparse, csv, os, re, hashlib, collections
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.formatting.rule import CellIsRule

# ============ 作者署名（随产出物流传） ============
SIGN = "由「疯狂的姜柠檬」小红书采集工具包生成 · SkillHub 技能市场搜索「疯狂的姜柠檬」获取配套关键词采集工具与完整打法"

# ============ 可调常量区（调整判定规则只改这里） ============
# 赛道归类：按父关键词回溯不到时，用品类词兜底
NAME_RULE = [
    ("workbuddy", r"workbuddy"),
    ("vibecoding", r"vibe\s*coding"),
    ("教师", r"教师|老师|教资|考编|编制|备课|班主任"),
    ("ai", r"(^|[^a-z])ai([^a-z]|$)|aigc|大模型|gpt|智能体|agent"),
    ("工作台", r"工作台|工作桌"),
    ("AI工具", r"deepseek|codex|claude|gemini|kimi|豆包|元宝|通义"),
]
# 工作台赛道里的家具/装修词
OFFTOPIC = r"木工|不锈钢|防静电|实验室|流水线|车间|厨房|美甲|紫竹|编绳|织女|打磨|升降|重型|家用|卧室|站立式|保鲜|超净|洁净|铝型材|千牛|单双面|收纳|改造|定制|布置|桌面|书桌|台灯"
OFFTOPIC_KW = re.compile(OFFTOPIC)
# 英文误匹配（ai -> airpods 之类）
NOISE = re.compile(r"^(airpods|airp\b|air$|air\d|airbnb|airjordan|airtouch|iphone|aivei|airiqi|aia\b|aias|aiaih)", re.I)

# 追加噪声模式（--noise 传入），用于种子词本身是人名/品牌时的撞词排除
EXTRA_NOISE = []
# 同名词种：种子词在小红书有多种语义时，只保留命中白名单的
AMBIGUOUS = {
    "muse": r"ai|模型|对话|绘画",
}
# 量级分层
TIERS = [(1_000_000_000, "头部"), (100_000_000, "腰部"), (10_000_000, "中长尾"), (0, "长尾")]
# 选题优先级可打区间
POOL_LO, POOL_HI = 1_000_000, 1_000_000_000
# 蓝海：教程/方法类词
HOWTO = re.compile(r"教程|入门|技巧|方法|怎么|如何|搭建|模板|案例|攻略|指南|实战|避坑|保姆|上手|零基础|干货|工作流|提示词")
HARDWARE = re.compile(r"学习机|学习笔|平板|耳机|手机|手表|投影|打印机|键盘|鼠标|机器人|硬件|测评|评测|推荐|价格|多少钱")
# ========================================================

XL_HEAD = "FF4472C4"; XL_HEAD_TXT = "FFFFFFFF"; XL_BORDER = "FFBFBFBF"
XL_TOP = "FFFFF2CC"; XL_WARN = "FFFCE4D6"
thin = Side(style="thin", color=XL_BORDER)
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)


def _tier(v):
    for th, name in TIERS:
        if v >= th:
            return name
    return "长尾"


def split_row(head, row):
    """兼容两种表头，统一成 dict"""
    d = dict(zip(head, row))
    if "源关键词" in d:
        return {"src": d.get("源关键词", "").strip(), "name": (d.get("话题名") or "").strip(),
                "views": int(float(d.get("浏览量") or 0)), "text": d.get("浏览量原文") or "",
                "level": 1, "ts": d.get("采集时间") or ""}
    if "父关键词" in d:
        lv = int(float(d.get("层级") or 1))
        return {"src": (d.get("父关键词") or "").strip(), "name": (d.get("话题名") or "").strip(),
                "views": int(float(d.get("浏览量") or 0)), "text": d.get("浏览量原文") or "",
                "level": lv, "ts": d.get("采集时间") or ""}
    return None


def collect(inputs):
    files = []
    for p in inputs:
        if os.path.isdir(p):
            files += [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.endswith(".csv")]
        elif os.path.isfile(p):
            files.append(p)
    raw = []
    for f in files:
        with open(f, encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
        if not rows:
            continue
        head = [h.strip() for h in rows[0]]
        for r in rows[1:]:
            if not r:
                continue
            d = split_row(head, r)
            if d and d["name"]:
                raw.append(d)
    return raw, files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", nargs="+", required=True, help="目录或 CSV 文件")
    ap.add_argument("--xlsx", default="小红书话题数据包.xlsx")
    ap.add_argument("--csv", default="小红书话题总表.csv")
    ap.add_argument("--taglib", default="", help="标签库 13 列导入 CSV 输出路径")
    ap.add_argument("--seeds", default="", help="种子关键词，逗号分隔（用于赛道回溯）")
    ap.add_argument("--noise", action="append", default=[],
                    help="追加噪声正则（可重复传入），命中标为「噪声」。种子词是人名/品牌时用它排除撞词")
    ap.add_argument("--drop", default="",
                    help="删除正则：命中的话题直接从产出中剔除（用于按产品方向过滤，如 --drop '寒假工|寒假实习'）")
    a = ap.parse_args()

    for _p in a.noise:
        EXTRA_NOISE.append(re.compile(_p, re.I))
        print(f"[noise] 追加排除规则: {_p}")

    seeds = [s.strip() for s in a.seeds.split(",") if s.strip()]
    raw, files = collect(a.input)
    if not raw:
        raise SystemExit("没有读到数据，检查 --input")

    seed_map = {s.lower(): s for s in seeds}
    queried = {r["src"].lower() for r in raw}

    # 关键词 -> 所属种子集合：沿「话题名也是被查询过的关键词」这条边迭代传播，最多 6 轮
    kw_seed = {}
    for r in raw:
        kw_seed.setdefault(r["src"], set()).add(r["src"])
    for _ in range(6):
        changed = False
        for r in raw:
            if r["name"].strip().lower() not in queried:
                continue
            s = kw_seed.get(r["src"])
            if not s:
                continue
            tgt = kw_seed.setdefault(r["name"].strip(), set())
            if not s <= tgt:
                tgt |= s
                changed = True
        if not changed:
            break

    def seed_of(kw):
        s = kw_seed.get(kw)
        if s:
            for sd in sorted(s):
                if sd.lower() in seed_map:
                    return seed_map[sd.lower()]
        return None

    def track(d):
        # 1) 话题名本身即种子词
        t = seed_of(d["name"])
        if t:
            return t
        # 2) 按来源关键词回溯到种子
        for src in sorted(d["sources"]):
            t = seed_of(src)
            if t:
                return t
        # 3) 品类词规则
        for t, pat in NAME_RULE:
            if re.search(pat, d["name"], re.I):
                return t
        return "其他"

    def relevant(name, tr):
        if NOISE.search(name) or any(p.search(name) for p in EXTRA_NOISE):
            return "噪声(联想误匹配)"
        if tr.lower() in AMBIGUOUS and not re.search(AMBIGUOUS[tr.lower()], name, re.I):
            return "偏离(语义无关)"
        if tr == "工作台" and OFFTOPIC_KW.search(name):
            return "偏离(家具/装修)"
        return "相关"

    # 去重：精确名去重（不做 lowercase，避免 #VibeCoding 与 #vibecoding 被误并）
    merged = {}
    for r in raw:
        k = r["name"].strip()
        cur = merged.get(k)
        if cur is None:
            merged[k] = {"name": k, "views": r["views"], "text": r["text"], "level": r["level"],
                         "ts": r["ts"], "sources": {r["src"]}}
        else:
            cur["sources"].add(r["src"])
            cur["level"] = min(cur["level"], r["level"])
            if r["views"] > cur["views"]:
                cur.update({"views": r["views"], "text": r["text"], "ts": r["ts"]})

    data = list(merged.values())
    if a.drop:
        _drop = re.compile(a.drop)
        _kept = [d for d in data if not _drop.search(d["name"])]
        print(f"[drop] 剔除 {len(data) - len(_kept)} 条（规则: {a.drop}）")
        data = _kept
    for d in data:
        d["track"] = track(d)
        d["tier"] = _tier(d["views"])
        d["rel"] = relevant(d["name"], d["track"])
    data.sort(key=lambda x: -x["views"])

    trk = collections.Counter(d["track"] for d in data)
    tier_cnt = collections.Counter(d["tier"] for d in data)
    rel_cnt = collections.Counter(d["rel"] for d in data)
    kws = {r["src"] for r in raw} | set(seeds)
    now = max((d["ts"] for d in data), default="")[:10]

    wb = Workbook()

    # ---------------- 总览 ----------------
    ws = wb.active
    ws.title = "总览"
    ws.sheet_view.showGridLines = False
    ws["A1"] = "小红书话题数据包 · 总览"
    ws["A1"].font = Font(size=18, bold=True, color="FF2F5597")
    ws.merge_cells("A1:F1")
    ws["A2"] = f"采集时间：{now} ｜ 采集方式：创作平台发布页话题联想（每词上限 50 条）｜ 数据为采集时点快照"
    ws["A2"].font = Font(size=10, color="FF808080")
    ws.merge_cells("A2:F2")
    ws.row_dimensions[1].height = 28

    ws["A4"] = "核心指标"
    ws["A4"].font = Font(bold=True, size=12, color="FF2F5597")
    metrics = [
        ("种子关键词", len(seeds) if seeds else len(kws)),
        ("已查询关键词总数", len(kws)),
        ("原始采集行数", len(raw)),
        ("去重后话题数", len(data)),
        ("重复率", f"{1 - len(data) / len(raw):.1%}"),
        ("相关话题数", rel_cnt.get("相关", 0)),
        ("需排除：家具/装修", rel_cnt.get("偏离(家具/装修)", 0)),
        ("需排除：语义无关", rel_cnt.get("偏离(语义无关)", 0)),
        ("需排除：联想噪声", rel_cnt.get("噪声(联想误匹配)", 0)),
        ("浏览量合计", sum(d["views"] for d in data)),
    ]
    r = 5
    for k, v in metrics:
        ws.cell(row=r, column=1, value=k).font = Font(bold=True)
        c = ws.cell(row=r, column=2, value=v)
        if isinstance(v, int) and v > 10000:
            c.number_format = "#,##0"
        r += 1

    ws.cell(row=r + 1, column=1, value="赛道分布（按种子词）").font = Font(bold=True, size=12, color="FF2F5597")
    heads = ["赛道", "话题数", "浏览量合计", "最大话题", "最大浏览量"]
    hdr = r + 2
    for i, h in enumerate(heads):
        c = ws.cell(row=hdr, column=1 + i, value=h)
        c.font = Font(bold=True, color=XL_HEAD_TXT)
        c.fill = PatternFill("solid", fgColor=XL_HEAD)
        c.alignment = Alignment(horizontal="center")
        c.border = BORDER
    r = hdr + 1
    for t, cnt in trk.most_common():
        sub = [d for d in data if d["track"] == t and d["rel"] == "相关"]
        if not sub:
            continue
        top = max(sub, key=lambda x: x["views"])
        ws.cell(row=r, column=1, value=t).border = BORDER
        ws.cell(row=r, column=2, value=len(sub)).border = BORDER
        ws.cell(row=r, column=2).alignment = Alignment(horizontal="center")
        c = ws.cell(row=r, column=3, value=sum(d["views"] for d in sub))
        c.number_format = "#,##0"; c.border = BORDER
        ws.cell(row=r, column=4, value=top["name"]).border = BORDER
        c = ws.cell(row=r, column=5, value=top["views"])
        c.number_format = "#,##0"; c.border = BORDER
        r += 1

    ws.cell(row=r + 1, column=1, value="量级分布").font = Font(bold=True, size=12, color="FF2F5597")
    r += 2
    for t in ["头部", "腰部", "中长尾", "长尾"]:
        ws.cell(row=r, column=1, value=t).border = BORDER
        c = ws.cell(row=r, column=2, value=tier_cnt.get(t, 0))
        c.alignment = Alignment(horizontal="center"); c.border = BORDER
        r += 1

    ws.cell(row=r + 2, column=1, value="使用说明").font = Font(bold=True, size=12, color="FF2F5597")
    notes = [
        "1. 每个关键词只能拿到 50 条联想话题，这是平台发布页的硬上限（实测滚到底无更多加载）。",
        "2. 「赛道」按父关键词逐级回溯判定，回溯不到时用品类词兜底；「其他」多为跨赛道长尾。",
        "3. 「相关性」列标出需排除的词：家具/装修、语义无关（同名词种）、联想噪声（ai→airpods 之类），选题与蓝海只统计「相关」。",
        "4. 浏览量是平台展示的累计曝光口径，不等于搜索需求；选题时结合笔记数一起看竞争度。",
        "5. 派生列为算好的静态值（本机无公式引擎），数据为采集时点快照。",
    ]
    for i, n in enumerate(notes):
        cell = ws.cell(row=r + 3 + i, column=1, value=n)
        cell.font = Font(size=10, color="FF595959")
        ws.merge_cells(start_row=r + 3 + i, start_column=1, end_row=r + 3 + i, end_column=6)
    for col, w in zip("ABCDEF", [22, 14, 16, 26, 16, 14]):
        ws.column_dimensions[col].width = w

    # ---------------- 话题明细 ----------------
    ws2 = wb.create_sheet("话题明细")
    COLS2 = ["序号", "话题名", "浏览量", "浏览量原文", "量级", "赛道", "来源关键词", "层级", "相关性", "采集时间"]
    for i, h in enumerate(COLS2):
        c = ws2.cell(row=1, column=1 + i, value=h)
        c.font = Font(bold=True, color=XL_HEAD_TXT)
        c.fill = PatternFill("solid", fgColor=XL_HEAD)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = BORDER
    ws2.row_dimensions[1].height = 22
    for i, d in enumerate(data, 1):
        rr = i + 1
        ws2.cell(row=rr, column=1, value=i).alignment = Alignment(horizontal="center")
        ws2.cell(row=rr, column=2, value=d["name"])
        c = ws2.cell(row=rr, column=3, value=d["views"]); c.number_format = "#,##0"
        ws2.cell(row=rr, column=4, value=d["text"])
        ws2.cell(row=rr, column=5, value=d["tier"]).alignment = Alignment(horizontal="center")
        ws2.cell(row=rr, column=6, value=d["track"]).alignment = Alignment(horizontal="center")
        ws2.cell(row=rr, column=7, value="、".join(sorted(d["sources"]))[:80])
        ws2.cell(row=rr, column=8, value=d["level"]).alignment = Alignment(horizontal="center")
        ws2.cell(row=rr, column=9, value=d["rel"]).alignment = Alignment(horizontal="center")
        ws2.cell(row=rr, column=10, value=str(d["ts"])[:19].replace("T", " "))
        for cc in range(1, 11):
            ws2.cell(row=rr, column=cc).border = BORDER
            if d["rel"] != "相关":
                ws2.cell(row=rr, column=cc).fill = PatternFill("solid", fgColor=XL_WARN)
    ws2.freeze_panes = "A2"
    ws2.auto_filter.ref = f"A1:J{len(data) + 1}"
    for col, w in zip("ABCDEFGHIJ", [7, 40, 14, 14, 9, 11, 34, 7, 16, 19]):
        ws2.column_dimensions[col].width = w
    rng = f"E2:E{len(data) + 1}"
    ws2.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"头部"'], fill=PatternFill("solid", fgColor="FFF8CBAD")))
    ws2.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"腰部"'], fill=PatternFill("solid", fgColor="FFFFE699")))

    # ---------------- 关键词汇总 ----------------
    ws3 = wb.create_sheet("关键词汇总")
    COLS3 = ["来源关键词", "话题数", "浏览量合计", "中位浏览量", "最大话题", "最大浏览量", ">1000万话题数", "赛道"]
    for i, h in enumerate(COLS3):
        c = ws3.cell(row=1, column=1 + i, value=h)
        c.font = Font(bold=True, color=XL_HEAD_TXT)
        c.fill = PatternFill("solid", fgColor=XL_HEAD)
        c.alignment = Alignment(horizontal="center")
        c.border = BORDER
    agg = collections.defaultdict(list)
    for x in raw:
        agg[x["src"]].append(x)
    rows3 = []
    for kw, lst in agg.items():
        vs = sorted((x["views"] for x in lst), reverse=True)
        top = max(lst, key=lambda x: x["views"])
        rows3.append({"kw": kw, "n": len(lst), "sum": sum(vs), "med": vs[len(vs) // 2],
                      "top": top["name"], "topv": top["views"],
                      "big": sum(1 for v in vs if v > 10_000_000),
                      "tr": track({"name": kw, "sources": {kw}})})
    rows3.sort(key=lambda x: -x["sum"])
    for i, d in enumerate(rows3, 2):
        ws3.cell(row=i, column=1, value=d["kw"]).border = BORDER
        ws3.cell(row=i, column=2, value=d["n"]).border = BORDER
        ws3.cell(row=i, column=2).alignment = Alignment(horizontal="center")
        for col, key in [(3, "sum"), (4, "med"), (6, "topv")]:
            c = ws3.cell(row=i, column=col, value=d[key]); c.number_format = "#,##0"; c.border = BORDER
        ws3.cell(row=i, column=5, value=d["top"]).border = BORDER
        ws3.cell(row=i, column=7, value=d["big"]).border = BORDER
        ws3.cell(row=i, column=7).alignment = Alignment(horizontal="center")
        ws3.cell(row=i, column=8, value=d["tr"]).border = BORDER
        ws3.cell(row=i, column=8).alignment = Alignment(horizontal="center")
    ws3.freeze_panes = "A2"
    ws3.auto_filter.ref = f"A1:H{len(rows3) + 1}"
    for col, w in zip("ABCDEFGH", [32, 9, 16, 14, 34, 15, 14, 11]):
        ws3.column_dimensions[col].width = w

    # ---------------- 选题优先级 ----------------
    ws4 = wb.create_sheet("选题优先级")
    ws4["A1"] = "选题优先级 Top 60（已剔除偏离/噪声，取 100万~10亿浏览的可打区间，按浏览量降序）"
    ws4["A1"].font = Font(bold=True, size=13, color="FF2F5597")
    ws4.merge_cells("A1:G1")
    COLS4 = ["排名", "话题名", "浏览量", "量级", "赛道", "竞争度参考", "打法建议"]
    for i, h in enumerate(COLS4):
        c = ws4.cell(row=3, column=1 + i, value=h)
        c.font = Font(bold=True, color=XL_HEAD_TXT)
        c.fill = PatternFill("solid", fgColor=XL_HEAD)
        c.alignment = Alignment(horizontal="center")
        c.border = BORDER
    ADVICE = {"头部": "流量天花板高但被大号占满，适合蹭活动/挂话题，不做主攻",
              "腰部": "有量但竞争激烈，靠差异化切入（真实案例/反常识）",
              "中长尾": "推荐主攻：需求明确、竞争可控，能吃到搜索流量",
              "长尾": "精准但容量小，适合做合集/系列里的补充话题"}
    pool = [d for d in data if d["rel"] == "相关" and POOL_LO <= d["views"] <= POOL_HI][:60]
    for i, d in enumerate(pool, 1):
        rr = i + 3
        ws4.cell(row=rr, column=1, value=i).alignment = Alignment(horizontal="center")
        ws4.cell(row=rr, column=2, value=d["name"])
        c = ws4.cell(row=rr, column=3, value=d["views"]); c.number_format = "#,##0"
        ws4.cell(row=rr, column=4, value=d["tier"]).alignment = Alignment(horizontal="center")
        ws4.cell(row=rr, column=5, value=d["track"]).alignment = Alignment(horizontal="center")
        ws4.cell(row=rr, column=6, value={"头部": "极激烈", "腰部": "激烈", "中长尾": "中等", "长尾": "较低"}[d["tier"]]).alignment = Alignment(horizontal="center")
        ws4.cell(row=rr, column=7, value=ADVICE[d["tier"]])
        for cc in range(1, 8):
            ws4.cell(row=rr, column=cc).border = BORDER
            if i <= 10:
                ws4.cell(row=rr, column=cc).fill = PatternFill("solid", fgColor=XL_TOP)
    ws4.freeze_panes = "A4"
    for col, w in zip("ABCDEFG", [7, 40, 15, 9, 11, 12, 52]):
        ws4.column_dimensions[col].width = w

    # ---------------- 蓝海机会 ----------------
    ws5 = wb.create_sheet("蓝海机会")
    ws5["A1"] = "蓝海机会：教程/方法类话题，浏览量 50万~5000万（需求已起量、竞争未饱和）"
    ws5["A1"].font = Font(bold=True, size=13, color="FF2F5597")
    ws5.merge_cells("A1:F1")
    COLS5 = ["话题名", "浏览量", "赛道", "机会类型", "为什么现在是机会", "优先级"]
    for i, h in enumerate(COLS5):
        c = ws5.cell(row=3, column=1 + i, value=h)
        c.font = Font(bold=True, color=XL_HEAD_TXT)
        c.fill = PatternFill("solid", fgColor=XL_HEAD)
        c.alignment = Alignment(horizontal="center")
        c.border = BORDER
    blue = [d for d in data if d["rel"] == "相关" and HOWTO.search(d["name"])
            and not HARDWARE.search(d["name"]) and 500_000 <= d["views"] <= 50_000_000]
    blue.sort(key=lambda x: -x["views"])
    blue = blue[:80]
    for i, d in enumerate(blue, 4):
        ws5.cell(row=i, column=1, value=d["name"]).border = BORDER
        c = ws5.cell(row=i, column=2, value=d["views"]); c.number_format = "#,##0"; c.border = BORDER
        ws5.cell(row=i, column=3, value=d["track"]).border = BORDER
        ws5.cell(row=i, column=4, value="教程/方法类").border = BORDER
        ws5.cell(row=i, column=5, value="浏览量已过千万级说明需求真实，但话题集中度低，长尾笔记仍能分发").border = BORDER
        pr = "P0 立刻做" if d["views"] <= 5_000_000 else ("P1 本月做" if d["views"] <= 20_000_000 else "P2 借势做")
        ws5.cell(row=i, column=6, value=pr).border = BORDER
        ws5.cell(row=i, column=6).alignment = Alignment(horizontal="center")
    ws5.freeze_panes = "A4"
    for col, w in zip("ABCDEF", [40, 15, 11, 14, 56, 12]):
        ws5.column_dimensions[col].width = w

    # ---------------- 生成信息（作者署名） ----------------
    wsg = wb.create_sheet("生成信息")
    wsg["A1"] = "作者"
    wsg["B1"] = "关于这套工具"
    for c in ("A1", "B1"):
        wsg[c].font = Font(bold=True)
    wsg["A2"] = "疯狂的姜柠檬"
    wsg["B2"] = SIGN
    wsg.column_dimensions["A"].width = 16
    wsg.column_dimensions["B"].width = 100

    wb.save(a.xlsx)
    print(f"[ok] xlsx -> {a.xlsx} | 去重话题 {len(data)} | 关键词 {len(kws)}")

    # ---------------- 总表 CSV ----------------
    with open(a.csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["源关键词", "话题名", "浏览量", "浏览量原文", "采集时间"])
        for d in data:
            w.writerow(["、".join(sorted(d["sources"])), d["name"], d["views"], d["text"], d["ts"]])
        w.writerow([""])
        w.writerow([SIGN])
    print(f"[ok] csv  -> {a.csv}")

    # ---------------- 标签库导入 CSV ----------------
    if a.taglib:
        def fmt(ts):
            ts = str(ts)
            return ts[:19].replace("T", " ") if ts else ""
        with open(a.taglib, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["id", "name", "views", "size", "created_at", "used", "heat",
                                              "use_count", "avg_likes", "category", "source", "topic_id", "views_at"])
            w.writeheader()
            for i, d in enumerate(data, 1):
                w.writerow({
                    "id": i, "name": d["name"], "views": d["views"], "size": "",
                    "created_at": fmt(d["ts"]), "used": 0, "heat": "", "use_count": 0, "avg_likes": "",
                    "category": d["track"], "source": "小红书创作平台-话题联想",
                    "topic_id": int(hashlib.md5(d["name"].encode("utf-8")).hexdigest()[:12], 16),
                    "views_at": fmt(d["ts"]),
                })
        print(f"[ok] taglib -> {a.taglib}")

    print("赛道:", dict(trk))
    print("相关性:", dict(rel_cnt))
    print("输入文件:", len(files))


if __name__ == "__main__":
    main()
