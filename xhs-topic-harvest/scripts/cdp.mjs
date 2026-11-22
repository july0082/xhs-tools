// 极简 CDP 客户端：零依赖（Node 18+ 自带 fetch / WebSocket）
const PORT = process.env.CDP_PORT || '9222';
const BASE = `http://127.0.0.1:${PORT}`;

export async function listTargets() {
  const r = await fetch(BASE + '/json/list');
  return r.json();
}

export async function pickPage(urlPart) {
  const ts = await listTargets();
  const pages = ts.filter(t => t.type === 'page');
  if (urlPart) {
    const hit = pages.find(t => t.url.includes(urlPart));
    if (hit) return hit;
  }
  return pages[0];
}

export class CDP {
  constructor(wsUrl) { this.wsUrl = wsUrl; this.seq = 0; this.pending = new Map(); this.handlers = new Map(); }
  on(method, fn) {
    if (!this.handlers.has(method)) this.handlers.set(method, []);
    this.handlers.get(method).push(fn);
  }
  async connect() {
    this.ws = new WebSocket(this.wsUrl);
    await new Promise((res, rej) => { this.ws.onopen = res; this.ws.onerror = () => rej(new Error('ws connect failed')); });
    this.ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.id && this.pending.has(m.id)) {
        const { res, rej } = this.pending.get(m.id);
        this.pending.delete(m.id);
        m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
      }
    };
    return this;
  }
  send(method, params = {}) {
    const id = ++this.seq;
    return new Promise((res, rej) => {
      this.pending.set(id, { res, rej });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => {
        if (this.pending.has(id)) { this.pending.delete(id); rej(new Error('timeout: ' + method)); }
      }, 30000);
    });
  }
  async eval(expression, awaitPromise = false) {
    const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + ' ' + (r.exceptionDetails.exception?.description || ''));
    return r.result.value;
  }
  close() { try { this.ws.close(); } catch {} }
}

export const sleep = (ms) => new Promise(r => setTimeout(r, ms));
