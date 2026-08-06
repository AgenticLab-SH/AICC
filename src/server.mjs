import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ActionError, createActionController } from './actions.mjs';
import { openLocalApp } from './apps.mjs';
import { toolCatalog } from './catalog.mjs';
import { collectStatus } from './status.mjs';
import { openaiUsageStatus } from './openai-usage.mjs';
import { runTask } from './tasks.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const publicRoot = path.join(root, 'public');
const host = process.env.AICC_HOST || '127.0.0.1';
const port = Number(process.env.AICC_PORT || 4381);
const contentTypes = new Map([
  ['.html', 'text/html; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.css', 'text/css; charset=utf-8'],
  ['.canvas', 'application/json; charset=utf-8'],
  ['.svg', 'image/svg+xml']
]);

function json(res, status, payload) {
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    'x-content-type-options': 'nosniff'
  });
  res.end(JSON.stringify(payload));
}

function staticFile(res, pathname) {
  const requested = pathname === '/' ? 'index.html' : pathname.slice(1);
  const resolved = path.resolve(publicRoot, requested);
  if (!resolved.startsWith(`${publicRoot}${path.sep}`) || !fs.existsSync(resolved) || !fs.statSync(resolved).isFile()) {
    json(res, 404, { ok: false, error: 'not found' });
    return;
  }
  res.writeHead(200, {
    'content-type': contentTypes.get(path.extname(resolved)) || 'application/octet-stream',
    'cache-control': 'no-store',
    'x-content-type-options': 'nosniff',
    'content-security-policy': "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'"
  });
  fs.createReadStream(resolved).pipe(res);
}

function isLoopback(address) {
  return address === '127.0.0.1' || address === '::1' || address === '::ffff:127.0.0.1';
}

function isSameOrigin(req) {
  const origin = req.headers.origin;
  if (!origin) return true;
  try {
    const parsed = new URL(origin);
    return parsed.host === req.headers.host && (parsed.protocol === 'http:' || parsed.protocol === 'https:');
  } catch {
    return false;
  }
}

async function readJson(req, maxBytes = 16_384) {
  const chunks = [];
  let bytes = 0;
  for await (const chunk of req) {
    bytes += chunk.length;
    if (bytes > maxBytes) throw new ActionError('request_too_large', '요청이 너무 큽니다.', 413);
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { throw new ActionError('invalid_json', 'JSON 요청을 읽을 수 없습니다.'); }
}

function actionFailure(res, error) {
  const status = error instanceof ActionError ? error.status : 500;
  const code = error instanceof ActionError ? error.code : 'internal_error';
  return json(res, status, { ok: false, code, error: error.message });
}

function requestAllowed(req, res) {
  if (!isLoopback(req.socket.remoteAddress)) {
    json(res, 403, { ok: false, code: 'loopback_required', error: '로컬 요청만 허용됩니다.' });
    return false;
  }
  if (!isSameOrigin(req)) {
    json(res, 403, { ok: false, code: 'same_origin_required', error: '같은 로컬 화면에서 보낸 요청만 허용됩니다.' });
    return false;
  }
  if (!String(req.headers['content-type'] ?? '').toLowerCase().startsWith('application/json')) {
    json(res, 415, { ok: false, code: 'json_required', error: 'JSON 요청만 허용됩니다.' });
    return false;
  }
  return true;
}

export function createServer(options = {}) {
  const statusCollector = options.collectStatus ?? collectStatus;
  const actionController = options.actionController ?? createActionController(options.actions);
  const statusCacheTtlMs = options.statusCacheTtlMs ?? 10_000;
  let statusCache = null;
  let statusCacheAt = 0;
  let statusInFlight = null;
  const currentStatus = async () => {
    if (statusCache && Date.now() - statusCacheAt < statusCacheTtlMs) return statusCache;
    if (statusInFlight) return statusInFlight;
    const pending = Promise.resolve(statusCollector()).then(result => {
      statusCache = result;
      statusCacheAt = Date.now();
      return result;
    });
    statusInFlight = pending;
    try { return await pending; }
    finally { if (statusInFlight === pending) statusInFlight = null; }
  };
  return http.createServer(async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host || `${host}:${port}`}`);
    if (req.method === 'GET' && url.pathname === '/healthz') return json(res, 200, { ok: true, mode: 'local-control' });
    if (req.method === 'GET' && url.pathname === '/api/status') {
      try { return json(res, 200, await currentStatus()); }
      catch (error) { return json(res, 500, { ok: false, error: error.message }); }
    }
    if (req.method === 'GET' && url.pathname === '/api/catalog') {
      return json(res, 200, { ok: true, ...toolCatalog() });
    }
    if (req.method === 'GET' && url.pathname === '/api/actions') {
      return json(res, 200, { ok: true, actions: actionController.list() });
    }
    if (req.method === 'GET' && url.pathname === '/api/openai-usage') {
      try { return json(res, 200, await (options.openaiUsageStatus ?? openaiUsageStatus)()); }
      catch (error) { return json(res, 500, { ok: false, error: error.message }); }
    }
    if (req.method === 'POST' && url.pathname === '/api/tasks/run') {
      if (!requestAllowed(req, res)) return;
      try {
        const body = await readJson(req);
        const result = await (options.runTask ?? runTask)(body.taskId);
        // A completed diagnostic may legitimately report findings (`ok: false`).
        // Keep that result distinct from a transport or execution failure so the
        // dashboard can show the diagnostic output instead of hiding it behind
        // an HTTP error.
        return json(res, 200, result);
      } catch (error) {
        return actionFailure(res, error);
      }
    }
    if (req.method === 'POST' && url.pathname === '/api/apps/open') {
      if (!requestAllowed(req, res)) return;
      try {
        const body = await readJson(req);
        return json(res, 200, await (options.openLocalApp ?? openLocalApp)(body.appId));
      } catch (error) {
        return actionFailure(res, error);
      }
    }
    if (req.method === 'POST' && (url.pathname === '/api/actions/preview' || url.pathname === '/api/actions/execute')) {
      if (!requestAllowed(req, res)) return;
      try {
        const body = await readJson(req);
        const result = url.pathname.endsWith('/preview')
          ? await actionController.preview(body.action, body.args)
          : await actionController.execute(body.confirmationToken);
        return json(res, result.ok ? 200 : 409, result);
      } catch (error) {
        return actionFailure(res, error);
      }
    }
    if (req.method !== 'GET' && req.method !== 'HEAD') return json(res, 405, { ok: false, error: 'method not allowed' });
    return staticFile(res, url.pathname);
  });
}

export function startServer(options = {}) {
  const server = createServer(options);
  const listenHost = options.host ?? host;
  const listenPort = options.port ?? port;
  server.listen(listenPort, listenHost, () => {
    const address = server.address();
    const actualPort = typeof address === 'object' && address ? address.port : listenPort;
    console.log(`AI Control Center: http://${listenHost}:${actualPort}`);
    console.log('Mode: local-control');
  });
  return server;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) startServer();
