// 唤起发布页编辑器（必须先有图片才渲染图文编辑器）
// 退出码: 0 就绪 / 2 未登录 / 3 找不到上传入口 / 4 编辑器未出现 / 5 缺占位图 / 6 无页面
import { pickPage, CDP, sleep } from './cdp.mjs';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PLACEHOLDER = process.env.PLACEHOLDER || path.join(HERE, '..', 'assets', 'placeholder.png');
const PUBLISH_URL = 'https://creator.xiaohongshu.com/publish/publish?source=official';

if (!fs.existsSync(PLACEHOLDER)) {
  console.log('NO_PLACEHOLDER:', PLACEHOLDER);
  process.exit(5);
}

const t = await pickPage('xiaohongshu');
if (!t) { console.log('NO_PAGE: 浏览器里没有小红书页面'); process.exit(6); }
console.log('TARGET:', (t.url || '').slice(0, 90));

const c = await new CDP(t.webSocketDebuggerUrl).connect();
await c.send('Page.enable');

const isLogin = async () => await c.eval(`(() => {
  const txt = document.body.innerText || '';
  const path = location.pathname || '';
  if (/\\/login/.test(path)) return true;
  if (/扫码登录|登录小红书|手机号登录|短信登录|验证码登录|密码登录|收不到验证码|登录后查看/.test(txt)) return true;
  // 登录墙常见形态：二维码 + 极少量正文
  const hasQr = !!document.querySelector('canvas, img[src*="qr"], [class*="qrcode"], [class*="qr-code"]');
  if (hasQr && txt.replace(/\\s/g, '').length < 260) return true;
  return false;
})()`);

if (await isLogin()) { console.log('NOT_LOGGED_IN'); c.close(); process.exit(2); }

if (!(t.url || '').includes('/publish')) {
  await c.send('Page.navigate', { url: PUBLISH_URL });
  await sleep(7000);
  // 导航后重新判断：未登录会被重定向到 /login
  if (await isLogin()) { console.log('NOT_LOGGED_IN'); c.close(); process.exit(2); }
}
console.log('STEP: page ready');

if (await c.eval(`!!document.querySelector('.ProseMirror')`)) {
  console.log('EDITOR_READY (existing)');
  c.close();
  process.exit(0);
}

await c.eval(`(() => {
  const el = [...document.querySelectorAll('*')].find(e => e.children.length === 0 && (e.innerText || '').trim() === '上传图文');
  if (el) (el.closest('[class*="tab"]') || el).click();
  return true;
})()`);
await sleep(2500);
console.log('STEP: switched tab');

await c.send('DOM.enable');
const { root } = await c.send('DOM.getDocument', { depth: 1 });
let nodeId = 0;
for (const sel of ['input.upload-input', 'input[type="file"]']) {
  const r = await c.send('DOM.querySelector', { nodeId: root.nodeId, selector: sel });
  if (r.nodeId) { nodeId = r.nodeId; break; }
}
console.log('STEP: upload input node =', nodeId);
if (!nodeId) {
  // 找不到上传入口最常见的原因就是没登录（发布页只渲染登录墙）
  if (await isLogin()) { console.log('NOT_LOGGED_IN'); c.close(); process.exit(2); }
  console.log('NO_UPLOAD_INPUT');
  c.close();
  process.exit(3);
}

await c.send('DOM.setFileInputFiles', { nodeId, files: [PLACEHOLDER] });
console.log('STEP: file set');

for (let i = 0; i < 8; i++) {
  await sleep(2000);
  if (await c.eval(`!!document.querySelector('.ProseMirror')`)) {
    console.log('EDITOR_READY (uploaded)');
    c.close();
    process.exit(0);
  }
}
console.log('EDITOR_MISSING');
c.close();
process.exit(4);
