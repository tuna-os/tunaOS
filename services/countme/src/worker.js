import allowlist from './allowlist.json' with { type: 'json' };

const DAY = 86400000;
const WEEK = 7 * DAY;
const dimensions = ['variant', 'flavor', 'arch', 'age_bucket'];
const keys = ['schema', ...dimensions];
const headers = { 'Access-Control-Allow-Origin': '*', 'X-Content-Type-Options': 'nosniff' };
export function weekStart(now) {
  const date = new Date(now);
  date.setUTCHours(0, 0, 0, 0);
  date.setUTCDate(date.getUTCDate() - (date.getUTCDay() + 6) % 7);
  return date.toISOString().slice(0, 10);
}
const isoDate = (ms) => new Date(ms).toISOString().slice(0, 10);
const response = (status, body = null, type = 'text/plain') => new Response(body, { status, headers: { ...headers, 'Content-Type': type, 'Cache-Control': 'no-store' } });
const json = (value) => response(200, JSON.stringify(value), 'application/json');

async function payload(request) {
  if (request.headers.get('Content-Type')?.split(';')[0].trim() !== 'application/json') throw 415;
  if (!request.body) throw 400;
  const reader = request.body.getReader();
  const parts = [];
  let length = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > 512) { await reader.cancel(); throw 413; }
      parts.push(value);
    }
    const bytes = new Uint8Array(length);
    let offset = 0;
    for (const part of parts) { bytes.set(part, offset); offset += part.length; }
    const value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
    if (!value || Array.isArray(value) || Object.keys(value).length !== keys.length || keys.some((key) => !Object.hasOwn(value, key))) throw 400;
    if (value.schema !== 1 || !Number.isInteger(value.age_bucket) || value.age_bucket < 1 || value.age_bucket > 4) throw 400;
    if (!allowlist.some((cell) => cell.variant === value.variant && cell.flavor === value.flavor && cell.arch === value.arch)) throw 400;
    return value;
  } catch (error) { throw typeof error === 'number' ? error : 400; }
}

async function report(request, env, now) {
  if (env.COLLECTION_ENABLED !== 'true') return response(503);
  const cap = Number(env.WEEKLY_REPORT_CAP);
  if (!Number.isSafeInteger(cap) || cap < 1) return response(503);
  let value;
  try { value = await payload(request); } catch (status) { return response(status); }
  const week = weekStart(now ?? Date.now());
  // changes() propagates the first statement's admission result through every margin.
  // D1 batch rollback keeps all five counters atomic on a storage failure.
  const statements = [env.DB.prepare(`INSERT INTO aggregates (week,dimension,category,count)
    SELECT ?, 'total', '*', 1 WHERE COALESCE((SELECT count FROM aggregates WHERE week=? AND dimension='total'),0) < ? AND NOT EXISTS (SELECT 1 FROM snapshots WHERE week=?)
    ON CONFLICT(week,dimension,category) DO UPDATE SET count=count+1`).bind(week, week, cap, week)];
  for (const dimension of dimensions) statements.push(env.DB.prepare(`INSERT INTO aggregates (week,dimension,category,count)
    SELECT ?, ?, ?, 1 WHERE changes()=1
    ON CONFLICT(week,dimension,category) DO UPDATE SET count=count+1`).bind(week, dimension, String(value[dimension])));
  statements.push(env.DB.prepare(`INSERT OR IGNORE INTO metadata (key,value)
    SELECT ?, 'true' WHERE (SELECT count FROM aggregates WHERE week=? AND dimension='total') >= ?`).bind('capped:' + week, week, cap));
  const results = await env.DB.batch(statements);
  return response(results[0].meta.changes === 1 ? 204 : 429);
}

function margin(rows) {
  if (rows.some((row) => row.count > 0 && row.count < 10)) return { status: 'suppressed', counts: null };
  return { status: 'reported', counts: Object.fromEntries(rows.map((row) => [row.category, Math.floor(row.count / 10) * 10])) };
}
export async function publish(env, now) {
  const current = weekStart(now);
  const cutoff = isoDate(Date.parse(current) - 104 * WEEK);
  const start = await env.DB.prepare("SELECT value FROM metadata WHERE key='collection_started'").first('value');
  if (start) {
    for (let ms = Math.max(Date.parse(weekStart(start)), Date.parse(cutoff)); ms < Date.parse(current); ms += WEEK) {
      const week = isoDate(ms);
      if (await env.DB.prepare('SELECT week FROM snapshots WHERE week=?').bind(week).first()) continue;
      const end = isoDate(ms + WEEK);
      const results = await env.DB.batch([
        env.DB.prepare('SELECT dimension,category,count FROM aggregates WHERE week=?').bind(week),
        env.DB.prepare('SELECT COUNT(*) AS count FROM heartbeats WHERE hour>=? AND hour<?').bind(week, end),
        env.DB.prepare('SELECT value FROM metadata WHERE key=?').bind('capped:' + week),
      ]);
      const rows = results[0].results;
      const hours = results[1].results[0].count;
      const status = hours === 0 ? 'unavailable' : hours === 168 && results[2].results.length === 0 ? 'complete' : 'degraded';
      const total = rows.find((row) => row.dimension === 'total')?.count || 0;
      const snapshot = { week_start: week, week_end: end, status,
        total: hours === 0 ? { status: 'unavailable', count: null } : total > 0 && total < 10 ? { status: 'suppressed', count: null } : { status: 'reported', count: Math.floor(total / 10) * 10 },
        dimensions: Object.fromEntries(dimensions.map((dimension) => [dimension, hours === 0 ? { status: 'unavailable', counts: null } : margin(rows.filter((row) => row.dimension === dimension))])) };
      await env.DB.prepare('INSERT OR IGNORE INTO snapshots (week,value) VALUES (?,?)').bind(week, JSON.stringify(snapshot)).run();
    }
  }
  await env.DB.batch([
    env.DB.prepare('DELETE FROM aggregates WHERE week<?').bind(cutoff),
    env.DB.prepare('DELETE FROM snapshots WHERE week<?').bind(cutoff),
    env.DB.prepare('DELETE FROM heartbeats WHERE hour<?').bind(cutoff),
    env.DB.prepare("DELETE FROM metadata WHERE key LIKE 'capped:%' AND substr(key,8)<?").bind(cutoff),
  ]);
}
export async function scheduled(env, now) {
  if (env.COLLECTION_ENABLED === 'true') await env.DB.batch([
    env.DB.prepare("INSERT OR IGNORE INTO metadata (key,value) VALUES ('collection_started',?)").bind(new Date(now).toISOString()),
    env.DB.prepare('INSERT OR IGNORE INTO heartbeats (hour) VALUES (?)').bind(new Date(now).toISOString().slice(0, 13)),
  ]);
  await publish(env, now);
}
async function metrics(env, now) {
  const current = weekStart(now);
  const cutoff = isoDate(Date.parse(current) - 104 * WEEK);
  const results = await env.DB.batch([
    env.DB.prepare("SELECT value FROM metadata WHERE key='collection_started'"),
    env.DB.prepare('SELECT value FROM snapshots WHERE week>=? AND week<? ORDER BY week').bind(cutoff, current),
  ]);
  return { schema: 1, methodology: 'tunaos-countme-v1', generated_at: new Date(now).toISOString(), collection_started: results[0].results[0]?.value || null, weeks: results[1].results.map((row) => JSON.parse(row.value)) };
}
function csv(data) {
  const rows = ['week_start,week_end,week_status,dimension,category,status,count'];
  for (const week of data.weeks) {
    const prefix = `${week.week_start},${week.week_end},${week.status}`;
    rows.push(`${prefix},total,*,${week.total.status},${week.total.count ?? ''}`);
    for (const dimension of dimensions) {
      const margin = week.dimensions[dimension];
      if (margin.counts === null) rows.push(`${prefix},${dimension},*,${margin.status},`);
      else for (const [category, count] of Object.entries(margin.counts)) rows.push(`${prefix},${dimension},${category},${margin.status},${count}`);
    }
  }
  return rows.join('\n') + '\n';
}
export async function handleFetch(request, env, now) {
  try {
    const url = new URL(request.url);
    if (url.search) return response(400);
    if (request.method === 'POST' && url.pathname === '/v1/report') return await report(request, env, now);
    if (request.method === 'GET' && url.pathname === '/health') {
      await env.DB.prepare('SELECT 1').first();
      return json({ status: 'ok', collection_enabled: env.COLLECTION_ENABLED === 'true' });
    }
    if (request.method === 'GET' && ['/v1/metrics', '/v1/metrics.csv'].includes(url.pathname)) {
      const data = await metrics(env, now ?? Date.now());
      return url.pathname.endsWith('.csv') ? response(200, csv(data), 'text/csv') : json(data);
    }
    return response(404);
  } catch { return response(503); }
}
export default { fetch: (request, env) => handleFetch(request, env), scheduled: (event, env) => scheduled(env, event.scheduledTime) };
