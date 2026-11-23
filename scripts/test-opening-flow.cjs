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
const fixtureVersion = '9.8.7';
const fixtureHome = `/index-v${fixtureVersion}.html`;
const sourceFiles = ['index.html', 'style.css', 'app.js'];
const sourceHashes = Object.fromEntries(sourceFiles.map(filename => [filename,
  createHash('sha256').update(fs.readFileSync(path.join(webDirectory, filename))).digest('hex')]));

async function main() {
  let chromium;
  try { ({ chromium } = require(process.env.ACMAIS_PLAYWRIGHT || 'playwright')); }
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
      const filename = url.pathname === fixtureHome ? 'index.html' : url.pathname.slice(1);
      const types = { 'index.html': 'text/html; charset=utf-8', 'style.css': 'text/css; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8', 'logo.png': 'image/png' };
      if (url.origin === origin && Object.hasOwn(types, filename)) {
        const source = filename === 'logo.png' && !fs.existsSync(path.join(webDirectory, filename))
          ? path.join(webDirectory, '..', 'assets', filename) : path.join(webDirectory, filename);
        const body = filename === 'index.html'
          ? fs.readFileSync(source, 'utf8').replaceAll('__ACMAIS_VERSION__', fixtureVersion) : fs.readFileSync(source);
        return route.fulfill({ contentType: types[filename], body });
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
          if (name === 'consume_notice') {
            const notice = window.__qa.notice;
            window.__qa.notice = null;
            return Promise.resolve({ ok: true, notice });
          }
          if (name === 'get_update_status') return Promise.resolve({ ok: true, status: 'idle' });
          if (name === 'delivery_options') return Promise.resolve({ ok: true, catalog: { Fiscal: ['NF - Vendas', 'NF - Compras'], 'Contábil': ['Extratos', 'Outros documentos'] }, currentPeriod: '2026-11', previousPeriod: '2026-10' });
          if (name === 'choose_delivery_folder') return Promise.resolve({ ok: true, files: ['Banco/Extrato.ofx', 'Banco/Anexos/'], suggestion: { sector: 'Contábil', kind: 'Extratos', period: null } });
          if (name === 'choose_delivery_files') return Promise.resolve({ ok: true, files: ['notas.xml'], suggestion: { sector: 'Fiscal', kind: null, period: '2026-10' } });
          if (name === 'recent_deliveries') return Promise.resolve({ ok: true, receipts: [
            { filename: '<b>documento.xml</b>', status: 'sent', company: '0000 - Empresa fictícia', destination: '2026 / 10-2026 / Fiscal', recorded_at: '2026-11-19T20:00:00Z' },
            { id: 11, canOpen: true, filename: 'pendente.pdf', status: 'uncertain', company: '0000 - Empresa fictícia', destination: '2026 / 10-2026 / Contábil', recorded_at: '2026-11-19T20:00:00Z' },
            { id: 12, canOpen: true, filename: 'extrato.ofx', status: 'failed', detail: 'Já existe um arquivo com o mesmo nome nessa pasta.', company: '0000 - Empresa fictícia', destination: '2026 / 10-2026 / Contábil', recorded_at: '2026-11-19T20:00:00Z' },
          ] });
          window.__qa.calls.push({ name, args, frames: window.__qa.frames, overlay: window.__qa.overlayState() });
          if (window.__qa.response === 'reject') return Promise.reject(new Error('Fixture backend unavailable'));
          if (window.__qa.response === 'error') return Promise.resolve({ ok: false, error: 'Falha fictícia de abertura' });
          return Promise.resolve({ ok: true });
        },
        return_home() { window.__qa.cancellations++; return Promise.resolve({ ok: true }); },
      } };
    });
    try {
      await page.goto(`${origin}${fixtureHome}`, { waitUntil: 'domcontentloaded' });
      const title = `ACMAIS LINK · v${fixtureVersion}`;
      assert.equal(await page.title(), title);
      assert.equal(await page.locator('#app-identity').textContent(), title);
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
    await test('guided delivery suggests sector and period, and waits for a confirmed type and paint', async page => {
      await page.locator('[data-action="deliver"]').click();
      await page.locator('#choose-delivery-files').click();
      await page.locator('#delivery-files-list li').waitFor();
      assert.equal(await page.locator('#delivery-sector').inputValue(), 'Fiscal');
      assert.equal(await page.locator('#delivery-period').inputValue(), '2026-10');
      assert.equal(await page.locator('#submit-delivery').isDisabled(), true);
      await page.locator('#delivery-kind').selectOption('NF - Vendas');
      assert.match(await page.locator('#delivery-path').textContent(), /2026 \/ 10-2026 \/ Fiscal \/ NF - Vendas/);
      if (reportEnabled) await page.screenshot({ path: path.join(reportDirectory, 'delivery-desktop.png') });
      await page.setViewportSize({ width: 360, height: 480 });
      assert.equal(await page.locator('#submit-delivery').isVisible(), true);
      assert.equal(await page.locator('#delivery-dialog').evaluate(el => el.scrollWidth <= el.clientWidth + 1), true);
      if (reportEnabled) await page.screenshot({ path: path.join(reportDirectory, 'delivery-compact.png') });
      await page.evaluate(() => { window.__qa.holdFrames = true; });
      await page.locator('#submit-delivery').click();
      assert.equal(await page.locator('#busy-title').textContent(), 'Preparando envio');
      assert.deepEqual(await page.evaluate(() => window.__qa.calls), []);
      await paint(page);
      await paint(page);
      const calls = await page.evaluate(() => window.__qa.calls);
      assert.equal(calls.length, 1);
      assert.deepEqual(calls[0].args, ['0000', { sector: 'Fiscal', kind: 'NF - Vendas', period: '2026-10' }]);
    });

    await test('folder selection shows nested paths and suggests the accounting statement destination', async page => {
      await page.locator('[data-action="deliver"]').click();
      await page.locator('#choose-delivery-folder').click();
      await page.locator('#delivery-files-list li').first().waitFor();
      assert.deepEqual(await page.locator('#delivery-files-list li').allTextContents(), ['Banco/Extrato.ofx', 'Banco/Anexos/']);
      assert.equal(await page.locator('#delivery-sector').inputValue(), 'Contábil');
      assert.equal(await page.locator('#delivery-kind').inputValue(), 'Extratos');
      assert.equal(await page.locator('#delivery-period').inputValue(), '');
      assert.equal(await page.locator('#submit-delivery').isDisabled(), true);
    });

    await test('delivery can be closed without required data and no upload starts', async page => {
      await page.locator('[data-action="deliver"]').click();
      await page.locator('#delivery-dialog').getByRole('button', { name: 'Cancelar', exact: true }).click();
      assert.equal(await page.locator('#delivery-dialog').isVisible(), false);
      assert.deepEqual(await page.evaluate(() => window.__qa.calls), []);
    });

    await test('period shortcuts select the month and update the destination', async page => {
      await page.locator('[data-action="deliver"]').click();
      await page.locator('#choose-delivery-folder').click();
      await page.getByRole('button', { name: 'Esse mês', exact: true }).click();
      assert.equal(await page.locator('#delivery-period').inputValue(), '2026-11');
      assert.match(await page.locator('#delivery-path').textContent(), /2026 \/ 11-2026/);
      await page.getByRole('button', { name: 'Mês anterior', exact: true }).click();
      assert.equal(await page.locator('#delivery-period').inputValue(), '2026-10');
      assert.match(await page.locator('#delivery-path').textContent(), /2026 \/ 10-2026/);
    });

    await test('delivery result identifies the duplicate file and reason', async page => {
      await page.evaluate(() => {
        window.__qa.notice = { message: '0 enviados, 1 com falha', error: true, deliveryIssues: [
          { filename: 'extrato.ofx', status: 'failed', detail: 'Já existe um arquivo com o mesmo nome nessa pasta.' },
        ] };
      });
      await page.locator('#refresh').click();
      await page.locator('#delivery-result[open]').waitFor();
      assert.equal(await page.locator('#delivery-result-list strong').textContent(), 'extrato.ofx');
      assert.match(await page.locator('#delivery-result-list .receipt-detail').textContent(), /mesmo nome/);
      await page.locator('#delivery-result .dialog-actions button').click();
      assert.equal(await page.locator('#delivery-result').isVisible(), false);
    });

    await test('history preserves failure reasons and displays names as text', async page => {
      await page.locator('#open-history').click();
      await page.locator('#history-list li').first().waitFor();
      assert.deepEqual(await page.locator('.receipt-status').allTextContents(), ['Enviado', 'A confirmar', 'Falhou']);
      assert.match(await page.locator('#history-list .receipt-detail').textContent(), /mesmo nome/);
      assert.equal(await page.locator('#history-list b').count(), 0);
      assert.match(await page.locator('#history-list').textContent(), /<b>documento\.xml<\/b>/);
      if (reportEnabled) await page.screenshot({ path: path.join(reportDirectory, 'history.png') });
      await page.locator('#history-list li').filter({ hasText: 'extrato.ofx' }).getByRole('button', { name: 'Conferir pasta' }).click();
      await page.waitForFunction(() => window.__qa.calls.length === 1);
      const [call] = await page.evaluate(() => window.__qa.calls);
      assert.equal(call.name, 'open_delivery_folder');
      assert.deepEqual(call.args, [12]);
    });

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
