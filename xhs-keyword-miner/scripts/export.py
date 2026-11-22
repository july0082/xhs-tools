# -*- coding: utf-8 -*-
"""导出器：Excel 明细 + 可上传 CSV 关键词包 + HTML 看板

用法:
    python export.py --workdir ./xhs_keywords
    python export.py --workdir ./xhs_keywords --out ./outputs

产出(默认写入 workdir/outputs/):
    小红书关键词明细.xlsx     7 个 sheet：总表/按种子汇总/核心下拉/前缀扩散/二级扩展/热度排行/指标说明
    关键词包_精选.csv         S/A 档，单列纯词，可直接上传投放平台
    关键词包_全部.csv         全量单列纯词
    关键词数据_带指标.csv     全字段，供再加工
    小红书关键词看板.html     交互式看板
"""
import argparse
import csv
import json
import os
import re

# ============ 作者署名（随产出物流传） ============
SIGN = "由「疯狂的姜柠檬」小红书采集工具包生成 · SkillHub 技能市场搜索「疯狂的姜柠檬」获取配套话题采集工具与完整打法"

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(SKILL_DIR, "assets", "dashboard.html")

HEAD_FILL = PatternFill("solid", fgColor="FF2442")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=11)
THIN = Side(style="thin", color="E8E8E8")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
GRADE_FILL = {"S": "FFE8EC", "A": "FFF3E0", "B": "FFFBE6", "C": "F4F4F6", "D": "FAFAFA"}


# ---------- 归类 ----------
def build_maps(rows):
    src_map = {r["word"]: r["source"] for r in rows}

    def seed_of(word, d=0):
        if d > 5:
            return ""
        src = src_map.get(word, "")
        m = re.search(r"种子\[(.+?)\]", src)
        if m:
            return m.group(1)
        m = re.search(r"二级\[(.+?)\]", src)
        return seed_of(m.group(1), d + 1) if m else ""

    def kind_of(r):
        if r["tier"] == 2:
            return "l2"
        m = re.search(r"种子\[(.+?)\]前缀\[(.+?)\]", r["source"])
        if m and m.group(1).strip() == m.group(2).strip():
            return "core"
        return "pre"

    return seed_of, kind_of


def style_header(ws, ncol):
    for c in range(1, ncol + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 26


def autofit(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


# ---------- Excel ----------
def export_excel(data, rows, out_path):
    seeds = data["seeds"]
    seed_of, kind_of = build_maps(rows)
    KIND_CN = {"core": "核心下拉词", "pre": "前缀扩散词", "l2": "二级扩展词"}

    groups = {s: {"core": [], "pre": [], "l2": []} for s in seeds}
    for r in rows:
        s, k = seed_of(r["word"]), kind_of(r)
        if s in groups:
            groups[s][k].append(r["word"])

    wb = Workbook()

    # 总表
    ws = wb.active
    ws.title = "下拉词总表"
    ws.append(["序号", "关键词", "类型", "归属种子词", "综合推荐分", "联想热度",
               "相关度", "梯队", "出现次数", "平均名次", "采集来源"])
    for i, r in enumerate(rows, 1):
        ws.append([i, r["word"], KIND_CN[kind_of(r)], seed_of(r["word"]),
                   r.get("score"), r.get("heat"), r.get("rel"), r.get("grade"),
                   r.get("occ"), r.get("avg_rank"), r["source"]])
    style_header(ws, 11)
    autofit(ws, [6, 26, 14, 16, 12, 11, 9, 8, 11, 11, 30])
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            cell.border = BORDER

    # 按种子汇总
    ws2 = wb.create_sheet("按种子词汇总")
    ws2.append(["种子词", "核心下拉", "前缀扩散", "二级扩展", "合计", "S/A 档数", "核心下拉词一览"])
    for s in seeds:
        g = groups[s]
        sa = sum(1 for k in ("core", "pre", "l2")
                 for w in g[k]
                 if next((r.get("grade") for r in rows if r["word"] == w), None) in ("S", "A"))
        ws2.append([s, len(g["core"]), len(g["pre"]), len(g["l2"]),
                    len(g["core"]) + len(g["pre"]) + len(g["l2"]), sa, " / ".join(g["core"])])
    style_header(ws2, 7)
    autofit(ws2, [14, 12, 12, 12, 9, 11, 70])
    for row in ws2.iter_rows(min_row=2, max_row=ws2.max_row):
        for cell in row:
            cell.border = BORDER
        ws2.cell(row=row[0].row, column=7).alignment = Alignment(wrap_text=True, vertical="center")

    # 三个分表
    specs = [
        ("核心下拉词", "core", ["归属种子词", "下拉词", "综合推荐分", "梯队"]),
        ("前缀扩散词", "pre", ["归属种子词", "扩散词", "触发前缀", "综合推荐分", "梯队"]),
        ("二级扩展词", "l2", ["归属种子词", "扩展词", "扩展来源", "综合推荐分", "梯队"]),
    ]
    for title, key, header in specs:
        wsx = wb.create_sheet(title)
        wsx.append(header)
        for r in rows:
            if kind_of(r) != key:
                continue
            base = [seed_of(r["word"]), r["word"]]
            if key == "pre":
                m = re.search(r"前缀\[(.+?)\]", r["source"])
                base.append(m.group(1) if m else "")
            elif key == "l2":
                base.append(r["source"])
            base += [r.get("score"), r.get("grade")]
            wsx.append(base)
        style_header(wsx, len(header))
        autofit(wsx, [16, 30, 22, 12, 8][:len(header)])

    # 热度排行
    ws6 = wb.create_sheet("热度排行")
    ws6.append(["排名", "关键词", "综合推荐分", "联想热度", "相关度", "梯队",
                "出现次数", "平均名次", "最佳名次", "归属种子词", "类型"])
    ranked = sorted([r for r in rows if r.get("score") is not None], key=lambda r: -r["score"])
    for i, r in enumerate(ranked, 1):
        ws6.append([i, r["word"], r["score"], r["heat"], r["rel"], r["grade"],
                    r["occ"], r["avg_rank"], r.get("best_rank"),
                    seed_of(r["word"]), KIND_CN[kind_of(r)]])
        fill = GRADE_FILL.get(r["grade"])
        if fill:
            ws6.cell(row=ws6.max_row, column=6).fill = PatternFill("solid", fgColor=fill)
    style_header(ws6, 11)
    autofit(ws6, [6, 26, 12, 11, 9, 8, 11, 11, 11, 16, 14])

    # 指标说明
    ws7 = wb.create_sheet("指标说明")
    for row in [
        ["指标", "含义", "怎么用"],
        ["综合推荐分", "联想热度 × 相关度。用来压掉谐音/泛前缀噪音（如 muse → 木薯糖水）", "优先按这一列排序"],
        ["联想热度", "0-100。出现次数广度 + 联想列表平均名次加权得出", "反映词在搜索联想中的活跃度"],
        ["相关度", "0.55-0.95。词含种子词=0.95；前缀扩散不含种子词=0.60；二级按父词×0.9 递归", "低于 0.7 多为噪音，可忽略"],
        ["梯队", "S(前5%)/A(5-20%)/B(20-50%)/C(50-80%)/D(其余)，按综合推荐分分位数分层", "S/A 优先投入"],
        ["出现次数", "该词在多少个不同联想场景下被返回", "越多说明越贴近真实输入路径"],
        ["平均名次", "所有出现场景中的平均排序位置（1 最靠前）", "越接近 1 越热"],
        ["核心下拉词", "完整输入种子词时的联想", "最贴近用户真实搜索意图"],
        ["前缀扩散词", "输入到一半时的联想（如输入 cod 出现 cod乙女系列）", "噪音较多，注意甄别"],
        ["二级扩展词", "对下拉词再次联想得到", "挖长尾需求"],
        ["", "", ""],
        ["重要提醒", "本表为「联想热力指数」，基于搜索建议排序的相对值，不是小红书官方搜索量",
         "需要权威月搜索量，请登录聚光平台「关键词规划工具」查询"],
        ["", "", ""],
        ["作者", SIGN, ""],
    ]:
        ws7.append(row)
    style_header(ws7, 3)
    autofit(ws7, [16, 76, 46])
    for row in ws7.iter_rows(min_row=2, max_row=ws7.max_row):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    wb.save(out_path)
    return out_path


# ---------- CSV ----------
def export_csvs(rows, outdir):
    ranked = sorted(rows, key=lambda r: r.get("score") or 0, reverse=True)
    words_all = [r["word"] for r in ranked if r["word"]]
    elite = [r["word"] for r in ranked if r.get("grade") in ("S", "A")]

    p1 = os.path.join(outdir, "关键词包_精选.csv")
    with open(p1, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        for x in elite:
            w.writerow([x])
        w.writerow([""])
        w.writerow([SIGN])

    p2 = os.path.join(outdir, "关键词包_全部.csv")
    with open(p2, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        for x in words_all:
            w.writerow([x])
        w.writerow([""])
        w.writerow([SIGN])

    seed_of, kind_of = build_maps(rows)
    KIND_CN = {"core": "核心下拉", "pre": "前缀扩散", "l2": "二级扩展"}
    p3 = os.path.join(outdir, "关键词数据_带指标.csv")
    with open(p3, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["关键词", "综合推荐分", "联想热度", "相关度", "梯队",
                    "类型", "归属种子词", "出现次数", "平均名次"])
        for r in ranked:
            w.writerow([r["word"], r.get("score"), r.get("heat"), r.get("rel"),
                        r.get("grade"), KIND_CN[kind_of(r)], seed_of(r["word"]),
                        r.get("occ"), r.get("avg_rank")])
        w.writerow([""])
        w.writerow([SIGN] + [""] * 8)
    return p1, p2, p3, len(elite), len(words_all)


# ---------- HTML ----------
def export_html(data, rows, out_path):
    seeds = data["seeds"]
    seed_of, kind_of = build_maps(rows)

    payload = []
    for s in seeds:
        g = {"seed": s, "core": [], "pre": [], "l2": []}
        for r in rows:
            if seed_of(r["word"]) == s:
                g[kind_of(r)].append({"w": r["word"], "h": r.get("heat"),
                                      "sc": r.get("score"), "g": r.get("grade")})
        payload.append(g)

    top = [{"w": r["word"], "h": r.get("score"), "g": r.get("grade"), "s": seed_of(r["word"])}
           for r in rows if r.get("score") is not None]
    top.sort(key=lambda x: -x["h"])

    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    html = (html.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
                .replace("__TOP__", json.dumps(top[:50], ensure_ascii=False))
                .replace("__TOTAL__", str(len(rows)))
                .replace("__SCORED__", str(sum(1 for r in rows if r.get("score") is not None)))
                .replace("__SCNT__", str(sum(1 for r in rows if r.get("grade") == "S")))
                .replace("__NSEED__", str(len(seeds))))
    sign_html = ('<div style="text-align:center;padding:14px 0 20px;color:#888;font-size:12px;">'
                 + SIGN + '</div>')
    html = html.replace("</body>", sign_html + "\n</body>")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="导出 Excel / CSV / 看板")
    ap.add_argument("--workdir", default="./xhs_keywords")
    ap.add_argument("--out", default=None, help="输出目录，默认 workdir/outputs")
    args = ap.parse_args()

    workdir = os.path.abspath(args.workdir)
    outdir = os.path.abspath(args.out or os.path.join(workdir, "outputs"))
    os.makedirs(outdir, exist_ok=True)

    with open(os.path.join(workdir, "data.json"), encoding="utf-8") as f:
        data = json.load(f)
    rows = data["rows"]

    if not any(r.get("score") is not None for r in rows):
        raise SystemExit("数据尚未计算热度，请先运行 analyze.py")

    xlsx = export_excel(data, rows, os.path.join(outdir, "小红书关键词明细.xlsx"))
    p1, p2, p3, n_elite, n_all = export_csvs(rows, outdir)
    html = export_html(data, rows, os.path.join(outdir, "小红书关键词看板.html"))

    print(f"种子词 {len(data['seeds'])} 个 / 共 {len(rows)} 词")
    print(f"  Excel  : {xlsx}")
    print(f"  精选CSV: {p1}  ({n_elite} 词)")
    print(f"  全量CSV: {p2}  ({n_all} 词)")
    print(f"  指标CSV: {p3}")
    print(f"  看板   : {html}")


if __name__ == "__main__":
    main()
