// 一条命令跑完：启动浏览器 -> 唤起编辑器 -> 采集（本机环境会在命令结束时回收子进程，必须合并）
// 用法:
//   node run.mjs --seeds "kimi,通义千问" --depth 1 --out ./out
//   node run.mjs --seeds "..." --depth 2 --out ./out --profile "D:\\xhs-profile"
// 参数:
//   --chrome <路径>   默认自动探测常见安装位置
//   --profile <目录>  独立配置目录（保留登录态），默认 ./.chrome-xhs
//   --port <端口>     默认 9222
//   --keep-open <秒>  采完后保持浏览器不关（默认 0，随进程退出）
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const arg = (n, d) => { const i = argv.indexOf('--' + n); return i >= 0 ? argv[i + 1] : d; };

const SEEDS = arg('seeds', '');
const DEPTH = arg('depth', '1');
const OUT = path.resolve(arg('out', './out'));
const PORT = arg('port', '9222');
const PROFILE = path.resolve(arg('profile', './.chrome-xhs'));
const KEEP = parseInt(arg('keep-open', '0'), 10);
const CHROME = arg('chrome', [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  path.join(process.env.LOCALAPPDATA || '', 'Google', 'Chrome', 'Application', 'chrome.exe'),
].find(p => p && fs.existsSync(p)) || '');

if (!SEEDS) { console.log('用法: node run.mjs --seeds "词1,词2" [--depth 1] [--out ./out]'); process.exit(1); }
if (!CHROME) { console.log('找不到 Chrome，请用 --chrome 指定路径'); process.exit(2); }
process.env.CDP_PORT = PORT;

const sleep = ms => new Promise(r => setTimeout(r, ms));

// 已有实例则复用，否则启动
async function portAlive() {
  try { const r = await fetch(`http://127.0.0.1:${PORT}/json/version`); return r.ok; } catch { return false; }
}

let child = null;
if (await portAlive()) {
  console.log('复用已在运行的调试浏览器');
} else {
  fs.mkdirSync(PROFILE, { recursive: true });
  child = spawn(CHROME, [
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    '--no-first-run', '--no-default-browser-check',
    '--disable-blink-features=AutomationControlled',
    'https://creator.xiaohongshu.com/publish/publish?source=official',
  ], { stdio: 'ignore' });
  let ok = false;
  for (let i = 0; i < 30; i++) { await sleep(1000); if (await portAlive()) { ok = true; break; } }
  if (!ok) { console.log('CHROME_TIMEOUT: 端口未就绪'); process.exit(3); }
  console.log('浏览器已启动，端口', PORT);
  await sleep(3500);
}

function runNode(script, args) {
  return new Promise(res => {
    const p = spawn(process.execPath, [path.join(HERE, script), ...args], { stdio: 'inherit', cwd: OUT });
    p.on('exit', code => res(code ?? 1));
  });
}

fs.mkdirSync(OUT, { recursive: true });
const LOGIN_WAIT = parseInt(arg('login-wait', '360'), 10); // 等登录的秒数，默认 6 分钟
let prep = await runNode('prepare.mjs', []);

if (prep === 2 || prep === 3) {
  console.log('\n================ 需要登录（只需一次） ================');
  console.log('请在弹出的 Chrome 窗口里登录小红书。');
  console.log('建议用专门做采集的小号，别用开店的主号。');
  console.log('登录完不用回复任何东西，程序会自动检测并继续采集。');
  console.log(`最多等待 ${Math.max(1, Math.round(LOGIN_WAIT / 60))} 分钟。`);
  console.log('=====================================================\n');
  const deadline = Date.now() + LOGIN_WAIT * 1000;
  let logged = false;
  while (Date.now() < deadline) {
    await sleep(6000);
    if (await runNode('prepare.mjs', []) === 0) { logged = true; break; }
    process.stdout.write('.');
  }
  if (!logged) {
    console.log('\nLOGIN_TIMEOUT: 没等到登录。登录后再跑同一条命令就行，登录态会留着。');
    if (child) child.kill();
    process.exit(2);
  }
  console.log('\n登录成功，继续采集');
  prep = 0;
}

if (prep !== 0) { console.log('PREPARE_FAILED exit=' + prep); process.exit(prep); }

const crawlArgs = ['--seeds', SEEDS, '--depth', DEPTH, '--out', OUT];
for (const k of ['min-views', 'pause-every']) { const v = arg(k, ''); if (v) crawlArgs.push('--' + k, v); }
const code = await runNode('crawl.mjs', crawlArgs);
console.log('CRAWL_EXIT', code);

if (KEEP > 0 && child) {
  console.log(`浏览器保持 ${KEEP}s ...`);
  await sleep(KEEP * 1000);
} else if (child) {
  child.kill();
}
process.exit(code);
