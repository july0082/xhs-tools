# -*- coding: utf-8 -*-
"""联想热力指数计算

用法:
    python analyze.py --workdir ./xhs_keywords

指标口径:
    联想热度 heat  = 排名分 × 命中置信度
        排名分   : 联想列表按热度排序，第1名记1.0，第10名记0.1，取所有命中场景的均值
        命中置信度: 只出现1次记0.68，5次及以上记1.0（多次命中说明信号稳定）
    相关度 rel     : 压掉谐音/泛前缀噪音
        词里含种子词          -> 0.95
        前缀扩散且不含种子词  -> 0.60
        二级词               -> 父词相关度 × 0.9（递归）
    综合推荐分 score = heat × rel
    梯队          : 按 score 在同批词内取分位数（S 前5% / A 5-20% / B 20-50% / C 50-80% / D 其余）
                    S 档额外要求命中次数 >= 2
"""
import argparse
import json
import os
import re
from collections import Counter


def load(workdir):
    path = os.path.join(workdir, "data.json")
    if not os.path.exists(path):
        raise SystemExit(f"找不到 {path}，请先运行 miner.py 采集")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def grade_of(score, cuts):
    if score >= cuts["S"]:
        return "S"
    if score >= cuts["A"]:
        return "A"
    if score >= cuts["B"]:
        return "B"
    if score >= cuts["C"]:
        return "C"
    return "D"


def main():
    ap = argparse.ArgumentParser(description="计算联想热力指数")
    ap.add_argument("--workdir", default="./xhs_keywords")
    args = ap.parse_args()
    workdir = os.path.abspath(args.workdir)

    data = load(workdir)
    rows = data["rows"]
    prefix_hits = data.get("prefix_hits", {})
    l1_lists = data.get("l1_lists", {})

    # ---- 1. 汇总每个词在哪些场景出现、排第几 ----
    stat = {}
    for trig, lst in list(prefix_hits.items()) + list(l1_lists.items()):
        for i, w in enumerate(lst, start=1):
            w = (w or "").strip()
            if not w:
                continue
            s = stat.setdefault(w, {"ranks": [], "scenes": []})
            s["ranks"].append(i)
            s["scenes"].append(trig)

    if not stat:
        raise SystemExit("没有可用的排序数据，请检查采集是否成功")

    # 补齐 rows 中缺失的词（联想里出现但未被记录）
    known = {r["word"] for r in rows}
    for w, v in stat.items():
        if w not in known:
            rows.append({"word": w, "tier": 2, "source": f"二级[{v['scenes'][0]}]"})
            known.add(w)

    # ---- 2. 热度 ----
    heat = {}
    for w, v in stat.items():
        ranks = v["ranks"]
        pos = sum(max(0.0, 1 - (r - 1) / 10.0) for r in ranks) / len(ranks)
        conf = 0.6 + 0.4 * min(len(ranks), 5) / 5
        heat[w] = {
            "occ": len(ranks),
            "avg_rank": round(sum(ranks) / len(ranks), 2),
            "best_rank": min(ranks),
            "heat": round(100 * pos * conf, 1),
            "scenes": v["scenes"][:6],
        }

    # ---- 3. 相关度 ----
    src_map = {r["word"]: r["source"] for r in rows}

    def owner_seed(word, depth=0):
        if depth > 5:
            return ""
        src = src_map.get(word, "")
        m = re.search(r"种子\[(.+?)\]", src)
        if m:
            return m.group(1).strip()
        m = re.search(r"二级\[(.+?)\]", src)
        return owner_seed(m.group(1), depth + 1) if m else ""

    def relevance(word, depth=0):
        seed = owner_seed(word).lower()
        if seed and seed in word.lower():
            return 0.95
        src = src_map.get(word, "")
        if re.search(r"种子\[", src):
            return 0.60
        m = re.search(r"二级\[(.+?)\]", src)
        if m and depth < 5:
            return round(relevance(m.group(1), depth + 1) * 0.9, 4)
        return 0.55

    for w, v in heat.items():
        rel = relevance(w)
        v["rel"] = rel
        v["score"] = round(v["heat"] * rel, 1)

    # ---- 4. 梯队（分位数） ----
    svals = sorted((v["score"] for v in heat.values()), reverse=True)

    def pct(p):
        return svals[min(len(svals) - 1, int(len(svals) * p))]

    cuts = {"S": pct(0.05), "A": pct(0.20), "B": pct(0.50), "C": pct(0.80)}
    for w, v in heat.items():
        g = grade_of(v["score"], cuts)
        if g == "S" and v["occ"] < 2:
            g = "A"
        v["grade"] = g

    # ---- 5. 回写 ----
    for r in rows:
        h = heat.get(r["word"])
        for k in ("heat", "score", "rel", "grade", "occ", "avg_rank", "best_rank"):
            r[k] = h.get(k) if h else None

    data["cuts"] = cuts
    with open(os.path.join(workdir, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # ---- 6. 报告 ----
    cnt = Counter(v["grade"] for v in heat.values())
    ranked = sorted(heat.items(), key=lambda kv: -kv[1]["score"])
    print(f"已评分 {len(heat)} 词 / 总计 {len(rows)} 词")
    print("梯队分布:", {g: cnt.get(g, 0) for g in "SABCD"})
    print(f"分数阈值: S>={cuts['S']}, A>={cuts['A']}, B>={cuts['B']}, C>={cuts['C']}")
    print("\n综合推荐 Top 20:")
    for w, v in ranked[:20]:
        print(f"  {v['grade']} {v['score']:5.1f} (热度{v['heat']:.0f}×相关{v['rel']:.2f}) {w}")


if __name__ == "__main__":
    main()
