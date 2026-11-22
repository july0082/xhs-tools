# AGENTS.md

> For coding agents (Codex / Claude Code / Cursor / any CLI agent):
> This repo is a toolkit of two Xiaohongshu (RED) data-collection tools. Each tool ships a
> `SKILL.md` — read it first, then follow its steps. Chinese docs; scripts run anywhere
> Python/Node + Chrome are available.

## 仓库里有什么

| 目录 | 工具 | 说明文档（先读这个） |
|---|---|---|
| `xhs-keyword-miner/` | 小红书搜索下拉词挖掘：种子词 → 联想词 → 热度分层 → Excel/CSV 词包 + 交互式看板 | `xhs-keyword-miner/SKILL.md` |
| `xhs-topic-harvest/` | 小红书话题采集：发布页话题联想（话题名+浏览量）→ 话题数据包 Excel + 标签库 CSV | `xhs-topic-harvest/SKILL.md` |

`examples/` 内有演示产出，可先看效果再决定跑不跑采集。

## 用户怎么下指令

不需要用户描述技术步骤，用户只需说目标，例如：

- 「采集"寒假衔接"相关的搜索下拉词，扩展到 500 个，出词包」
- 「用话题采集跑一遍这批种子词，生成话题数据包」

Agent 应读取对应 `SKILL.md`，按其中的流程执行（含环境检查、分批节奏、风控保护）。

## 环境要求

两个工具运行方式不同，别混用：

**xhs-keyword-miner（纯 Python，无需登录小红书）**

- Python 3.10+，`playwright`、`openpyxl`
- 本机装有 Chrome（Playwright 用系统 Chrome 通道）
- 安装：`pip install playwright openpyxl && playwright install chrome`（或直接用系统 Chrome）

**xhs-topic-harvest（Node 连接浏览器 + Python 出包，需要已登录小红书的 Chrome）**

- Node.js 18+，Python 3.10+（`openpyxl`）
- 一个**已登录小红书**的 Chrome 实例，脚本通过 CDP 连接它
- 具体唤起与连接方式见 `xhs-topic-harvest/SKILL.md`，不要自己发明连接方式

## 硬性规则（各 SKILL.md 的红线，违者会被小红书风控）

1. **逐字前缀输入**：搜索框联想必须逐字符输入触发，禁止整词粘贴
2. **随机间隔 3–8 秒、串行采集**：禁止并发、禁止压缩间隔
3. **断点续跑优先**：话题采集支持中断恢复，长任务分批跑，不要一口气跑完
4. 遇到风控报错立即停止、拉长间隔，不要加重试轰炸

## 产出物

- 关键词工具：Excel 明细（7 表）+ 投放词包 CSV + 交互式 HTML 看板
- 话题工具：话题包 Excel（总览/明细/优先级/蓝海）+ 标签库导入 CSV

所有导出内容为中文，直接交付给运营人员使用。
