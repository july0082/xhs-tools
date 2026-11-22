// 小红书发布页话题采集：逐词输入 #关键词 -> 读下拉 -> 滚到底 -> 落 CSV
// 用法: node crawl.mjs --seeds "kimi,通义千问" --depth 1 --out ./out [--min-views 10000000] [--pause-every 20]
import { pickPage, CDP, sleep } from './cdp.mjs';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
function arg(name, def) {
  const i = argv.indexOf('--' + name);
  return i >= 0 ? argv[i + 1] : def;
}

const MAX_DEPTH = parseInt(arg('depth', '1'), 10);
const SEEDS = (arg('seeds', '') || '').split(',').map(s => s.trim()).filter(Boolean);
const MIN_VIEWS = parseInt(arg('min-views', '0'), 10);
const PAUSE_EVERY = parseInt(arg('pause-every', '20'), 10);
const OUT_DIR = path.resolve(arg('out', './out'));
const STOP_FILE = path.join(path.dirname(OUT_DIR), 'STOP');

if (!SEEDS.length) { console.log('用法: --seeds "词1,词2" [--depth 1|2|3] [--out ./out]'); process.exit(1); }
fs.mkdirSync(OUT_DIR, { recursive: true });

const STAMP = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
const CSV = path.join(OUT_DIR, `crawl-${STAMP}.csv`);

function splitCsvLine(line) {
  const out = []; let cur = '', q = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (q) {
      if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (ch === '"') q = false;
      else cur += ch;
    } else if (ch === '"') q = true;
    else if (ch === ',') { out.push(cur); cur = ''; }
    else cur += ch;
  }
  out.push(cur);
  return out;
}

// 断点续跑：读 out 目录下所有历史 CSV，收集已查询词
const doneQueries = new Set();
for (const f of (fs.existsSync(OUT_DIR) ? fs.readdirSync(OUT_DIR) : [])) {
  if (!f.endsWith('.csv')) continue;
  const lines = fs.readFileSync(path.join(OUT_DIR, f), 'utf8').replace(/^\ufeff/, '').split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) continue;
  const head = splitCsvLine(lines[0]).map(s => s.trim());
  const qi = head.indexOf('源关键词');
  const pi = head.indexOf('父关键词');
  for (const ln of lines.slice(1)) {
    const cols = splitCsvLine(ln);
    const q = qi >= 0 ? cols[qi] : (pi >= 0 ? cols[pi] : '');
    if (q) doneQueries.add(String(q).trim().toLowerCase());
  }
}
console.log(`历史：已查询 ${doneQueries.size} 个词`);

const HARVEST = `(() => {
  const items = [...document.querySelectorAll('.items .item')];
  return items.map(el => {
    const lines = (el.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
    const vLine = lines.find(s => /浏览$/.test(s)) || '';
    const name = (lines.find(s => s.startsWith('#')) || lines[0] || '').replace(/^#/, '');
    return { name, viewsText: vLine.replace(/浏览$/, '') };
  }).filter(r => r.name && r.viewsText);
})()`;
const SCROLL = `(() => { const b = document.querySelector('.items'); if (!b) return null; b.scrollTop = b.scrollHeight; return b.scrollTop; })()`;
const RISK = `(() => /滑动验证|拖动滑块|安全验证|请完成验证|操作过于频繁|账号异常/.test(document.body.innerText || ''))()`;

function parseViews(s) {
  const m = String(s).match(/(\d+(?:\.\d+)?)(万|亿)?/);
  if (!m) return 0;
  let n = parseFloat(m[1]);
  if (m[2] === '万') n *= 1e4;
  if (m[2] === '亿') n *= 1e8;
  return Math.round(n);
}

const t = await pickPage('xiaohongshu');
if (!t) { console.log('NO_PAGE'); process.exit(6); }
const c = await new CDP(t.webSocketDebuggerUrl).connect();

if (!await c.eval(`!!document.querySelector('.ProseMirror')`)) {
  console.log('NO_EDITOR: 请先运行 prepare.mjs');
  c.close();
  process.exit(1);
}

const visited = new Set(doneQueries);
const queue = [];
function pushJob(kw, level) {
  const k = String(kw || '').trim().toLowerCase();
  if (!k || visited.has(k)) return;
  visited.add(k);
  queue.push({ kw: String(kw).trim(), level });
}

for (const s of SEEDS) pushJob(s, 0);
console.log(`待查关键词：${queue.length} 个（跳过已采 ${doneQueries.size} 个）| 深度 ${MAX_DEPTH}`);

// 追加前确保文件以换行结尾，避免与上一行粘连
fs.writeFileSync(CSV, '\ufeff层级,父关键词,话题名,浏览量,浏览量原文,采集时间\n', 'utf8');

async function clearEditor() {
  await c.eval(`(() => {
    const ed = document.querySelector('.ProseMirror');
    ed.focus();
    const r = document.createRange();
    r.selectNodeContents(ed);
    const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    return true;
  })()`);
  for (const type of ['keyDown', 'keyUp']) {
    await c.send('Input.dispatchKeyEvent', { type, key: 'Delete', code: 'Delete', windowsVirtualKeyCode: 46, nativeVirtualKeyCode: 46 });
  }
  await sleep(350);
}

async function harvest() {
  await sleep(1300);
  const map = new Map();
  let idle = 0;
  for (let round = 0; round < 30; round++) {
    const rows = await c.eval(HARVEST);
    let added = 0;
    for (const r of rows) if (!map.has(r.name)) { map.set(r.name, r); added++; }
    if (added === 0) idle++; else idle = 0;
    if (idle >= 3) break;
    await c.eval(SCROLL);
    await sleep(400);
  }
  return [...map.values()];
}

const collected = [];
let sincePause = 0;
const t0 = Date.now();

while (queue.length) {
  if (fs.existsSync(STOP_FILE)) { console.log('检测到 STOP，停止'); break; }
  if (await c.eval(RISK)) { console.log('!! 检测到验证/风控提示，已停止'); break; }

  const job = queue.shift();
  try {
    await clearEditor();
    for (const ch of '#' + job.kw) {
      await c.send('Input.insertText', { text: ch });
      await sleep(60 + Math.random() * 70);
    }
    const items = await harvest();
    const ts = new Date().toISOString();
    const fresh = items.map(it => ({
      level: job.level + 1, parent: job.kw, name: it.name,
      views: parseViews(it.viewsText), viewsText: it.viewsText, ts,
    }));
    collected.push(...fresh);
    if (fresh.length) {
      fs.appendFileSync(CSV, fresh.map(r =>
        [r.level, r.parent, r.name, r.views, r.viewsText, r.ts]
          .map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')
      ).join('\n') + '\n', 'utf8');
    }
    const mins = ((Date.now() - t0) / 60000).toFixed(1);
    console.log(`L${job.level} [剩${queue.length}] ${job.kw} -> ${items.length}条 | 累计${collected.length} | ${mins}min`);

    if (job.level + 1 < MAX_DEPTH) {
      for (const it of items) {
        if (it.views >= MIN_VIEWS) pushJob(it.name, job.level + 1);
      }
    }
  } catch (e) {
    console.log(`[ERR] ${job.kw}: ${e.message}`);
  }

  sincePause++;
  if (sincePause >= PAUSE_EVERY) {
    sincePause = 0;
    const wait = 25000 + Math.random() * 20000;
    console.log(`   -- 批次休息 ${(wait / 1000).toFixed(0)}s --`);
    await sleep(wait);
  } else {
    await sleep(1200 + Math.random() * 1300);
  }
}

console.log('\n=== 结束 ===');
console.log('数据行:', collected.length, '| CSV:', CSV);
c.close();
