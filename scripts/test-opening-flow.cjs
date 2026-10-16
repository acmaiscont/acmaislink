/**
 * Real-browser regressions for the local document-opening UI.
 * The actual HTML/CSS/JS is served through Playwright route.fulfill; all other
 * requests are blocked. Backend calls are mocked and all company data is fake.
 *
 * Requirements: Node.js, Playwright, and Microsoft Edge (Windows), or Chromium.
 * Set NODE_PATH to a provided node_modules directory if necessary.
 * Optional: ACMAIS_BROWSER overrides the browser executable.
 * --report writes .qa/opening-flow/results.json and failure screenshots only.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');

const root = path.resolve(__dirname, '..');
const webDirectory = path.join(root, 'src', 'acmais_link', 'web');
const reportDirectory = path.join(root, '.qa', 'opening-flow');
const reportEnabled = process.argv.includes('--report');
const origin = 'http://127.0.0.1:31997';
const fixtureLink = 'https://tenant.sharepoint.com/sites/fixture';
const sourceFiles = ['index.html', 'style.css', 'app.js'];
const sourceHashes = Object.fromEntries(sourceFiles.map(filename => [filename,
  createHash('sha256').update(fs.readFileSync(path.join(webDirectory, filename))).digest('hex')]));

async function main() {
  let chromium;
  try { ({ chromium } = require('playwright')); }
  catch { throw new Error('Playwright not found. Provide Playwright and set NODE_PATH to its parent node_modules directory.'); }
  const launch = { headless: true };
  if (process.env.ACMAIS_BROWSER) launch.executablePath = process.env.ACMAIS_BROWSER;
  else if (process.platform === 'win32') launch.channel = 'msedge';
  const browser = await chromium.launch(launch);
  const results = [];
  if (reportEnabled) fs.mkdirSync(reportDirectory, { recursive: true });

  async function test(name, check) {
    const context = await browser.newContext({ viewport: { width: 1000, height: 720 }, reducedMotion: 'reduce' });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      const filename = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
      const types = { 'index.html': 'text/html; charset=utf-8', 'style.css': 'text/css; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8', 'logo.png': 'image/png' };
      if (url.origin === origin && Object.hasOwn(types, filename)) {
        return route.fulfill({ contentType: types[filename], body: fs.readFileSync(path.join(webDirectory, filename)) });
      }
      return route.abort();
    });
    await page.addInitScript(() => {
      const originalRaf = window.requestAnimationFrame.bind(window);
      window.__qa = { calls: [], cancellations: 0, frames: 0, queuedFrames: [], holdFrames: false, response: 'success' };
      window.requestAnimationFrame = callback => {
        if (!window.__qa.holdFrames) return originalRaf(callback);
        window.__qa.queuedFrames.push(callback);
        return window.__qa.queuedFrames.length;
      };
      // Flush exactly one queued animation frame on a real rendering tick. An
      // inner RAF stays queued until the next tick, so the barrier cannot pass
      // merely because the DOM changed synchronously inside the click handler.
      window.__qa.paintOneFrame = () => new Promise(resolve => originalRaf(timestamp => {
        window.__qa.frames++;
        const callbacks = window.__qa.queuedFrames.splice(0);
        for (const callback of callbacks) callback(timestamp);
        originalRaf(resolve);
      }));
      window.__qa.overlayState = () => {
        const overlay = document.querySelector('#busy-overlay');
        const style = getComputedStyle(overlay);
        const rect = overlay.getBoundingClientRect();
        return {
          visible: !overlay.hidden && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0,
          title: document.querySelector('#busy-title').textContent,
          inert: ['main', 'header', 'footer'].every(selector => document.querySelector(selector).inert),
          cancelFocused: document.activeElement.id === 'cancel-opening',
          formClosed: !document.querySelector('#company-dialog').open,
        };
      };
      window.pywebview = { api: {
        command(token, name, args) {
          if (token !== 'fixture-local-capability') return Promise.reject(new Error('Wrong local capability'));
          if (name === 'list_companies') return Promise.resolve({ ok: true, companies: [{ code: '0000', name: 'Empresa fictícia', url: 'https://tenant.sharepoint.com/sites/fixture', hasCredential: true }] });
          if (name === 'consume_notice') return Promise.resolve({ ok: true, notice: null });
          if (name === 'get_update_status') return Promise.resolve({ ok: true, status: 'idle' });
          window.__qa.calls.push({ name, args, frames: window.__qa.frames, overlay: window.__qa.overlayState() });
          if (window.__qa.response === 'reject') return Promise.reject(new Error('Fixture backend unavailable'));
          if (window.__qa.response === 'error') return Promise.resolve({ ok: false, error: 'Falha fictícia de abertura' });
          return Promise.resolve({ ok: true });
        },
        return_home() { window.__qa.cancellations++; return Promise.resolve({ ok: true }); },
      } };
    });
    try {
      await page.goto(`${origin}/`, { waitUntil: 'domcontentloaded' });
      await page.evaluate(() => window.bootstrapAcmais('fixture-local-capability'));
      await page.waitForFunction(() => document.querySelector('#company-count').textContent === '1 empresa');
      await check(page);
      assert.deepEqual(errors, [], 'Uncaught JavaScript error');
      results.push({ name, status: 'passed' });
      console.log(`PASS ${name}`);
    } catch (error) {
      const result = { name, status: 'failed', error: error.message, pageErrors: errors };
      if (reportEnabled) {
        const filename = `${String(results.length + 1).padStart(2, '0')}-failure.png`;
        await page.screenshot({ path: path.join(reportDirectory, filename), fullPage: true });
        result.screenshot = filename;
      }
      results.push(result);
      console.error(`FAIL ${name}: ${error.message}`);
    } finally { await context.close(); }
  }

  async function prepare(page, kind) {
    if (kind !== 'open') {
      await page.locator(kind === 'edit' ? '[data-action="edit"]' : '#add-company').click();
      await page.locator('#url').fill(fixtureLink);
      if (kind === 'add') await page.locator('#password').fill('fictitious-password');
    }
    await page.evaluate(() => { window.__qa.holdFrames = true; });
  }

  async function trigger(page, kind, repetitions = 1) {
    await page.evaluate(({ kind, repetitions }) => {
      for (let i = 0; i < repetitions; i++) {
        if (kind === 'open') document.querySelector('[data-action="open"]').click();
        else document.querySelector('#company-form').requestSubmit();
      }
    }, { kind, repetitions });
  }

  async function assertWaiting(page) {
    assert.deepEqual(await page.evaluate(() => window.__qa.overlayState()), {
      visible: true, title: 'Abrindo documentos', inert: true, cancelFocused: true, formClosed: true,
    });
    assert.deepEqual(await page.evaluate(() => window.__qa.calls), [], 'Backend must wait for the loading screen to paint');
  }

  async function paint(page) { await page.evaluate(() => window.__qa.paintOneFrame()); }

  async function assertUnlocked(page) {
    assert.equal(await page.locator('#busy-overlay').isVisible(), false);
    assert.equal(await page.evaluate(() => ['main', 'header', 'footer'].some(selector => document.querySelector(selector).inert)), false);
    assert.equal(await page.locator('[data-action="open"]').isDisabled(), false);
  }

  try {
    for (const kind of ['open', 'add', 'edit']) {
      await test(`${kind}: visible loading screen is painted before the backend command`, async page => {
        await prepare(page, kind);
        await trigger(page, kind);
        await assertWaiting(page);
        await paint(page);
        await assertWaiting(page);
        await paint(page);
        const calls = await page.evaluate(() => window.__qa.calls);
        assert.equal(calls.length, 1);
        assert.equal(calls[0].name, kind === 'open' ? 'open_company' : 'begin_company_setup');
        assert.equal(calls[0].frames, 2);
        assert.equal(calls[0].overlay.visible, true);
        assert.equal(calls[0].overlay.title, 'Abrindo documentos');
        if (kind === 'open') assert.deepEqual(calls[0].args, ['0000']);
        else assert.deepEqual(calls[0].args, [{ originalCode: kind === 'edit' ? '0000' : '', url: fixtureLink, password: kind === 'add' ? 'fictitious-password' : '' }]);
      });
    }

    for (const kind of ['open', 'add']) {
      await test(`${kind}: repeated clicks or submissions start only one operation`, async page => {
        await prepare(page, kind);
        await trigger(page, kind, 3);
        await assertWaiting(page);
        await paint(page);
        await paint(page);
        await trigger(page, kind, 3);
        await paint(page);
        await paint(page);
        assert.equal(await page.evaluate(() => window.__qa.calls.length), 1);
      });

      for (const elapsedFrames of [0, 1]) {
        await test(`${kind}: cancellation after ${elapsedFrames} frame(s) prevents backend opening`, async page => {
          await prepare(page, kind);
          await trigger(page, kind);
          if (elapsedFrames) await paint(page);
          await assertWaiting(page);
          await page.evaluate(() => document.querySelector('#cancel-opening').click());
          await paint(page);
          await paint(page);
          assert.deepEqual(await page.evaluate(() => window.__qa.calls), []);
          assert.equal(await page.evaluate(() => window.__qa.cancellations), 1);
          await assertUnlocked(page);
        });
      }

      for (const response of ['error', 'reject']) {
        await test(`${kind}: backend ${response} unlocks the UI and allows retry`, async page => {
          await prepare(page, kind);
          await page.evaluate(response => { window.__qa.response = response; }, response);
          await trigger(page, kind);
          await paint(page);
          await paint(page);
          await assertUnlocked(page);
          assert.equal(await page.locator(kind === 'open' ? '#toast' : '#form-error').isVisible(), true);
          if (kind === 'add') {
            assert.equal(await page.locator('#company-dialog').isVisible(), true);
            assert.equal(await page.locator('#url').inputValue(), fixtureLink);
          }
          await page.evaluate(() => { window.__qa.response = 'success'; });
          await trigger(page, kind);
          await paint(page);
          await paint(page);
          assert.equal(await page.evaluate(() => window.__qa.calls.length), 2);
          assert.equal(await page.locator('#busy-overlay').isVisible(), true);
        });
      }
    }
  } finally {
    const report = {
      timestamp: new Date().toISOString(), browser: await browser.version(), sourceSha256: sourceHashes,
      mode: 'Actual local UI; mocked backend and fictitious data; all network intercepted',
      passed: results.filter(result => result.status === 'passed').length,
      failed: results.filter(result => result.status === 'failed').length, results,
    };
    if (reportEnabled) fs.writeFileSync(path.join(reportDirectory, 'results.json'), JSON.stringify(report, null, 2));
    console.log(`Opening UI flow: ${report.passed} passed, ${report.failed} failed.`);
    if (report.failed) process.exitCode = 1;
    await browser.close();
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
