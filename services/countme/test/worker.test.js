import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { Miniflare } from 'miniflare';
import { build } from 'esbuild';
import { handleFetch, scheduled, publish, weekStart } from '../src/worker.js';
import allowlist from '../src/allowlist.json' with { type: 'json' };

let mf, db;
const monday = Date.parse('2026-09-14T00:00:00Z');
const env = () => ({ DB: db, COLLECTION_ENABLED: 'true', WEEKLY_REPORT_CAP: '100000' });
const report = (value = { schema: 1, ...allowlist[0], age_bucket: 2 }, now = monday, overrides = {}) => handleFetch(new Request('https://test/v1/report', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) }), { ...env(), ...overrides }, now);
const get = (path = '/v1/metrics', now = monday + 7 * 86400000) => handleFetch(new Request('https://test' + path), env(), now);
async function clear() { await db.batch(['aggregates', 'heartbeats', 'metadata', 'snapshots'].map((table) => db.prepare(`DELETE FROM ${table}`))); }
before(async () => {
  const bundle = await build({ entryPoints: ['src/worker.js'], bundle: true, format: 'esm', write: false });
  mf = new Miniflare({ modules: true, script: bundle.outputFiles[0].text, compatibilityDate: '2026-07-30', d1Databases: ['DB'], bindings: { COLLECTION_ENABLED: 'false', WEEKLY_REPORT_CAP: '100000' } });
  db = await mf.getD1Database('DB');
  const sql = await readFile(new URL('../migrations/0001_aggregates.sql', import.meta.url), 'utf8');
  await db.batch(sql.split(';').map((s) => s.trim()).filter(Boolean).map((s) => db.prepare(s)));
});
after(async () => { await mf?.dispose(); });

test('deployment keeps request logging and preview surfaces disabled', async () => {
  const configuration = JSON.parse(await readFile(new URL('../wrangler.jsonc', import.meta.url), 'utf8'));
  // Workers enable observability by default; each explicit control must survive deployment edits.
  assert.equal(configuration.observability.enabled, false);
  assert.equal(configuration.observability.logs.enabled, false);
  assert.equal(configuration.observability.logs.invocation_logs, false);
  assert.equal(configuration.workers_dev, false);
  assert.equal(configuration.preview_urls, false);
  assert.equal(configuration.send_metrics, false);
});
test('real Worker boundary is disabled by default and has safe health', async () => {
  assert.equal((await mf.dispatchFetch('https://test/v1/report', { method: 'POST', body: '{}' })).status, 503);
  assert.deepEqual(await (await mf.dispatchFetch('https://test/health')).json(), { status: 'ok', collection_enabled: false });
});
test('HTTP runtime accepts reports and exports no open-week data', async () => {
  const bundle = await build({ entryPoints: ['src/worker.js'], bundle: true, format: 'esm', write: false });
  const runtime = new Miniflare({ modules: true, script: bundle.outputFiles[0].text, compatibilityDate: '2026-07-30', d1Databases: ['DB'], bindings: { COLLECTION_ENABLED: 'true', WEEKLY_REPORT_CAP: '100000' } });
  try {
    const storage = await runtime.getD1Database('DB');
    const sql = await readFile(new URL('../migrations/0001_aggregates.sql', import.meta.url), 'utf8');
    await storage.batch(sql.split(';').map((part) => part.trim()).filter(Boolean).map((part) => storage.prepare(part)));
    const result = await runtime.dispatchFetch('https://test/v1/report', { method: 'POST', headers: { 'Content-Type': 'application/json', 'CF-Connecting-IP': '192.0.2.1' }, body: JSON.stringify({ schema: 1, ...allowlist[0], age_bucket: 1 }) });
    assert.equal(result.status, 204);
    assert.equal(await storage.prepare("SELECT count FROM aggregates WHERE dimension='total'").first('count'), 1);
    assert.deepEqual((await (await runtime.dispatchFetch('https://test/v1/metrics')).json()).weeks, []);
  } finally { await runtime.dispose(); }
});
test('UTC Monday boundary and concurrent atomic increments', async () => {
  await clear();
  assert.equal(weekStart('2026-09-20T23:59:59Z'), '2026-09-14');
  assert.equal(weekStart('2026-09-21T00:00:00Z'), '2026-09-21');
  const results = await Promise.all(Array.from({ length: 40 }, () => report()));
  assert.ok(results.every((result) => result.status === 204));
  const rows = (await db.prepare('SELECT * FROM aggregates').all()).results;
  assert.equal(rows.length, 5);
  assert.ok(rows.every((row) => row.count === 40));
  const tables = (await db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%'").all()).results.map((r) => r.name);
  assert.deepEqual(tables.sort(), ['aggregates', 'heartbeats', 'metadata', 'snapshots']);
});
test('rollback failure never leaves partial aggregate increments', async () => {
  await clear();
  await db.prepare("CREATE TRIGGER fail_test BEFORE INSERT ON aggregates WHEN NEW.dimension='arch' BEGIN SELECT RAISE(ABORT,'synthetic storage failure'); END").run();
  assert.equal((await report()).status, 503);
  assert.equal(await db.prepare('SELECT COUNT(*) AS n FROM aggregates').first('n'), 0);
  await db.prepare('DROP TRIGGER fail_test').run();
});
test('strict categorical validation and streamed byte limit', async () => {
  await clear();
  const valid = { schema: 1, ...allowlist[0], age_bucket: 2 };
  for (const bad of [{ ...valid, ip: 'test' }, { ...valid, schema: 2 }, { ...valid, age_bucket: 1.5 }, { ...valid, flavor: 'unknown' }, [], null, { ...valid, arch: '' }]) assert.equal((await report(bad)).status, 400);
  const stream = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(300)); controller.enqueue(new Uint8Array(300)); controller.close(); } });
  assert.equal((await handleFetch(new Request('https://test/v1/report', { method: 'POST', body: stream, duplex: 'half', headers: { 'Content-Type': 'application/json', 'Content-Length': '1' } }), env(), monday)).status, 413);
  assert.equal((await handleFetch(new Request('https://test/v1/report', { method: 'POST', body: '{}'}), env(), monday)).status, 415);
  assert.equal(await db.prepare('SELECT COUNT(*) AS n FROM aggregates').first('n'), 0);
});
test('global admission cap is atomic under concurrency and disable switch applies', async () => {
  await clear();
  const results = await Promise.all(Array.from({ length: 30 }, () => report(undefined, monday, { WEEKLY_REPORT_CAP: '10' })));
  assert.equal(results.filter((r) => r.status === 204).length, 10);
  assert.equal(results.filter((r) => r.status === 429).length, 20);
  assert.ok((await db.prepare('SELECT count FROM aggregates').all()).results.every((r) => r.count === 10));
  assert.equal((await report(undefined, monday, { COLLECTION_ENABLED: 'false' })).status, 503);
  await db.prepare("INSERT INTO metadata VALUES ('collection_started',?)").bind(new Date(monday).toISOString()).run();
  await db.batch(Array.from({ length: 168 }, (_, i) => db.prepare('INSERT INTO heartbeats VALUES (?)').bind(new Date(monday + i * 3600000).toISOString().slice(0, 13))));
  await publish(env(), monday + 7 * 86400000);
  assert.equal((await (await get()).json()).weeks[0].status, 'degraded');
});
test('closed snapshots suppress whole small margins consistently across JSON and CSV', async () => {
  await clear();
  await scheduled(env(), monday);
  for (let i = 0; i < 20; i++) await report({ schema: 1, ...allowlist[0], age_bucket: i === 0 ? 1 : 2 });
  await publish(env(), monday + 7 * 86400000);
  const data = await (await get()).json();
  assert.equal(data.weeks.length, 1);
  assert.equal(data.weeks[0].status, 'degraded');
  assert.deepEqual(data.weeks[0].total, { status: 'reported', count: 20 });
  assert.deepEqual(data.weeks[0].dimensions.age_bucket, { status: 'suppressed', counts: null });
  const text = await (await get('/v1/metrics.csv')).text();
  assert.match(text, /age_bucket,\*,suppressed,/);
  assert.doesNotMatch(text, /age_bucket,[12],/);
  assert.equal((await get('/v1/metrics?variant=yellowfin')).status, 400);
  assert.equal((await report()).status, 429);
  const first = data.weeks[0];
  await db.prepare('UPDATE aggregates SET count=999').run();
  await publish(env(), monday + 7 * 86400000);
  assert.deepEqual((await (await get()).json()).weeks[0], first);
});
test('current week hidden, zero requires health, missing health unavailable', async () => {
  await clear();
  await scheduled(env(), monday);
  assert.deepEqual((await (await get('/v1/metrics', monday)).json()).weeks, []);
  await publish(env(), monday + 14 * 86400000);
  const weeks = (await (await get('/v1/metrics', monday + 14 * 86400000)).json()).weeks;
  assert.deepEqual(weeks[0].total, { status: 'reported', count: 0 });
  assert.equal(weeks[1].status, 'unavailable');
  assert.deepEqual(weeks[1].total, { status: 'unavailable', count: null });
  await clear();
  assert.equal((await (await get()).json()).collection_started, null);
});
test('168 persisted hourly samples describe cron coverage; retention prunes all weekly state', async () => {
  await clear();
  await db.prepare("INSERT INTO metadata VALUES ('collection_started',?)").bind(new Date(monday).toISOString()).run();
  await db.batch(Array.from({ length: 168 }, (_, i) => db.prepare('INSERT INTO heartbeats VALUES (?)').bind(new Date(monday + i * 3600000).toISOString().slice(0, 13))));
  await publish(env(), monday + 7 * 86400000);
  assert.equal((await (await get()).json()).weeks[0].status, 'complete');
  await report();
  await publish(env(), monday + 106 * 7 * 86400000);
  assert.equal(await db.prepare('SELECT COUNT(*) n FROM aggregates').first('n'), 0);
  assert.equal(await db.prepare('SELECT COUNT(*) n FROM heartbeats').first('n'), 0);
  assert.equal(await db.prepare('SELECT COUNT(*) n FROM snapshots').first('n'), 104);
});
