import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { Miniflare } from 'miniflare';
import { build } from 'esbuild';
import { handleFetch, scheduled, publish, weekStart } from '../src/worker.js';
import allowlist from '../src/allowlist.json' with { type: 'json' };

const collector = fileURLToPath(new URL('..', import.meta.url));
const docsSource = process.env.TUNAOS_DOCS_SOURCE || resolve(collector, '../../../docs');
const { default: site } = await import(pathToFileURL(resolve(docsSource, 'worker/index.js')));

test('D1 reports reach the website proxy with frozen disclosure rules', { timeout: 90000 }, async () => {
  const bundle = await build({ entryPoints: [resolve(collector, 'src/worker.js')], bundle: true, format: 'esm', write: false });
  const runtime = new Miniflare({ modules: true, script: bundle.outputFiles[0].text, compatibilityDate: '2026-07-30', d1Databases: ['DB'], bindings: { COLLECTION_ENABLED: 'false', WEEKLY_REPORT_CAP: '100000' } });
  const originalFetch = globalThis.fetch;
  try {
    const DB = await runtime.getD1Database('DB');
    const sql = await readFile(resolve(collector, 'migrations/0001_aggregates.sql'), 'utf8');
    await DB.batch(sql.split(';').map((statement) => statement.trim()).filter(Boolean).map((statement) => DB.prepare(statement)));
    const env = { DB, COLLECTION_ENABLED: 'true', WEEKLY_REPORT_CAP: '100000' };
    const now = Date.now();
    const previousWeek = Date.parse(weekStart(now)) - 7 * 86400000;
    await scheduled(env, previousWeek);
    const payload = { schema: 1, ...allowlist[0], age_bucket: 2 };
    const reports = await Promise.all(Array.from({ length: 23 }, () => handleFetch(new Request('https://test/v1/report', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }), env, previousWeek)));
    assert.ok(reports.every((response) => response.status === 204));
    await publish(env, now);
    const feed = await (await handleFetch(new Request('https://test/v1/metrics'), env, now)).text();
    // Inspect the application call, not Cloudflare's eventual HTTP transport headers.
    globalThis.fetch = async (url, options) => {
      assert.equal(url, 'https://countme.tunaos.org/v1/metrics');
      assert.deepEqual(options.headers, { Accept: 'application/json' });
      assert.equal(options.redirect, 'manual');
      return new Response(feed, { headers: { 'Content-Type': 'application/json' } });
    };
    const response = await site.fetch(new Request('https://tunaos.org/api/adoption?tracking=discard', { headers: { Cookie: 'private', 'CF-Connecting-IP': '192.0.2.1' } }), {});
    assert.equal(response.status, 200);
    const data = await response.json();
    assert.equal(data.weeks.length, 1);
    assert.equal(data.weeks[0].total.count, 20);
    assert.equal(data.weeks[0].status, 'degraded');
    assert.deepEqual(data.weeks[0].dimensions.flavor.counts, { [payload.flavor]: 20 });
    assert.equal((await site.fetch(new Request('https://tunaos.org/api/adoption', { method: 'HEAD' }), {})).status, 200);
    // Exercise native workerd Fetcher options, which differ from Node fetch.
    const siteBundle = await build({ entryPoints: [resolve(docsSource, 'worker/index.js')], bundle: true, format: 'esm', write: false });
    const native = new Miniflare({workers: [
      {name: 'site', modules: true, script: siteBundle.outputFiles[0].text, compatibilityDate: '2025-09-14', serviceBindings: {COUNTME: 'feed'}},
      {name: 'feed', modules: true, compatibilityDate: '2026-07-30', script: `export default {fetch() {return new Response(${JSON.stringify(feed)}, {headers: {'Content-Type': 'application/json'}})}};`},
    ]});
    try {
      const bound = await native.dispatchFetch('https://tunaos.org/api/adoption');
      assert.equal(bound.status, 200);
      assert.equal((await bound.json()).weeks[0].total.count, 20);
      assert.equal((await native.dispatchFetch('https://tunaos.org/api/adoption', {method: 'HEAD'})).status, 200);
    } finally {await native.dispose();}

  } finally {
    globalThis.fetch = originalFetch;
    await runtime.dispose();
  }
});
