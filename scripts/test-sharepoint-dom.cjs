/**
 * Real-browser regressions for the generated SharePoint scripts.
 * All documents below are synthetic; every browser request is intercepted.
 *
 * Requirements: Node.js, Playwright, project Python and Microsoft Edge (Windows)
 * or a Playwright Chromium browser (other platforms). No downloads are performed.
 *
 * PowerShell, if Playwright is provided by an external Node runtime:
 *   $env:NODE_PATH = '<directory containing the playwright package>'
 *   node scripts/test-sharepoint-dom.cjs --report
 *
 * Optional overrides: ACMAIS_PYTHON and ACMAIS_BROWSER (executable paths).
 * --report writes only .qa/sharepoint-dom/results.json and failure screenshots.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { createHash } = require('node:crypto');

const root = path.resolve(__dirname, '..');
const reportEnabled = process.argv.includes('--report');
const reportDirectory = path.join(root, '.qa', 'sharepoint-dom');
const generatedSource = path.join(root, 'src', 'acmais_link', 'sharepoint.py');
const sourceHash = createHash('sha256').update(fs.readFileSync(generatedSource)).digest('hex');
const origin = 'https://tenant.sharepoint.com';
const fixtureUrl = `${origin}/sites/test/Forms/AllItems.aspx?RootFolder=%2FDocuments%2F0000%20-%20Empresa%20de%20teste`;
const company = '0000 - Empresa de teste';

function generatedScripts() {
  const venvPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts' : 'bin', process.platform === 'win32' ? 'python.exe' : 'python');
  const python = process.env.ACMAIS_PYTHON || (fs.existsSync(venvPython) ? venvPython : 'python');
  const program = [
    'import json',
    'from acmais_link.sharepoint import (navigation_state_script, company_heading_script,',
    '    password_page_present_script, password_submission_script,',
    '    navigation_cover_script, navigation_toolbar_script, extract_company_identity)',
    'secret = \'fixture-"-\\\\-only\'',
    'origin = "https://tenant.sharepoint.com"',
    'tokens = (10, 11, 12)',
    'print(json.dumps({',
    '    "secret": secret,',
    '    "snapshot": navigation_state_script(),',
    '    "heading": company_heading_script(),',
    '    "passwordPresent": password_page_present_script(),',
    '    "password": password_submission_script(secret, origin, navigation_token=10),',
    '    "covers": {token: navigation_cover_script(navigation_token=token) for token in tokens},',
    '    "toolbars": {token: navigation_toolbar_script(f"0000 - Empresa de teste {token}", navigation_token=token) for token in tokens},',
    '    "literalToolbar": navigation_toolbar_script("0000 - <img src=x onerror=window.__qa.pwned=true>", navigation_token=12),',
    '    "identities": {key: extract_company_identity(origin + "/Forms/AllItems.aspx?" + key + "=%2FDocuments%2F0000%20-%20Empresa%20de%20teste%2F2026") for key in ("id", "RootFolder", "rootfolder", "ID")}',
    '}))',
  ].join('\n');
  const generated = spawnSync(python, ['-B', '-c', program], {
    cwd: root,
    encoding: 'utf8',
    windowsHide: true,
    env: {
      ...process.env,
      PYTHONUTF8: '1',
      PYTHONDONTWRITEBYTECODE: '1',
      PYTHONPATH: [path.join(root, 'src'), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
    },
  });
  if (generated.error) throw generated.error;
  assert.equal(generated.status, 0, `Could not generate browser scripts: ${generated.stderr}`);
  return JSON.parse(generated.stdout);
}

async function main() {
  let chromium;
  try { ({ chromium } = require('playwright')); }
  catch { throw new Error('Playwright not found. Install/provide Playwright and set NODE_PATH to its parent node_modules directory.'); }
  const scripts = generatedScripts();
  const launch = { headless: true };
  if (process.env.ACMAIS_BROWSER) launch.executablePath = process.env.ACMAIS_BROWSER;
  else if (process.platform === 'win32') launch.channel = 'msedge';
  const browser = await chromium.launch(launch);
  const results = [];
  if (reportEnabled) fs.mkdirSync(reportDirectory, { recursive: true });

  async function test(name, html, check, url = fixtureUrl) {
    const context = await browser.newContext({ viewport: { width: 900, height: 620 }, reducedMotion: 'reduce' });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    // fulfill() serves fixtures directly. No request reaches SharePoint or any
    // other service, including redirects, images and unexpected form navigation.
    await context.route('**/*', route => {
      if (route.request().isNavigationRequest() && route.request().url() === url) {
        return route.fulfill({ contentType: 'text/html; charset=utf-8', body: `<!doctype html><html><body>${html}</body></html>` });
      }
      return route.abort();
    });
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded' });
      await page.evaluate(() => {
        window.__qa = { returns: 0, external: 0, clicks: [], submits: 0, inputEvents: [], pwned: false };
        window.pywebview = { api: {
          return_home() { window.__qa.returns++; return Promise.resolve({ ok: true }); },
          open_current_external() { window.__qa.external++; return Promise.resolve({ ok: true }); },
        } };
        document.addEventListener('click', event => {
          const button = event.target.closest('button, input[type=submit], input[type=button]');
          if (button) window.__qa.clicks.push(button.id || button.textContent.trim());
        });
        document.addEventListener('submit', event => { event.preventDefault(); window.__qa.submits++; });
        for (const name of ['input', 'change']) {
          document.addEventListener(name, event => {
            if (event.target.matches('input[type=password]')) window.__qa.inputEvents.push(name);
          });
        }
      });
      await check(page);
      assert.deepEqual(errors, [], 'Uncaught browser JavaScript error');
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

  const passwordForm = '<form><input id="password" type="password"><input id="btnSubmitPassword" type="submit" value="Verificar"></form>';
  try {
    await test('Hidden password fields do not mark a ready folder as authentication',
      '<input type="password" hidden><input type="password" style="display:none"><div style="visibility:hidden"><input type="password"></div><h1>Documentos</h1>',
      async page => {
        assert.equal(await page.evaluate(scripts.passwordPresent), false);
        assert.equal((await page.evaluate(scripts.snapshot)).hasPassword, false);
        assert.equal(await page.evaluate(scripts.password), false);
        assert.equal(await page.locator('#acmais-loading-cover').count(), 0);
      });

    await test('Visible password and URL are read in the same DOM snapshot', passwordForm, async page => {
      const snapshot = await page.evaluate(scripts.snapshot);
      assert.equal(snapshot.url, fixtureUrl);
      assert.equal(snapshot.hasPassword, true);
      assert.equal(await page.evaluate(scripts.passwordPresent), true);
    });

    for (const selector of ['data-automationid="breadcrumb"', 'data-automation-id="breadcrumb"']) {
      await test(`Snapshot extracts visible ${selector} company breadcrumb`,
        `<h1 hidden>9999 - Hidden heading</h1><nav ${selector}><button>Documentos</button><button>${company}</button><button>2026</button></nav>`,
        async page => {
          const snapshot = await page.evaluate(scripts.snapshot);
          assert.equal(snapshot.heading, company);
          assert.equal(snapshot.hasPassword, false);
          assert.equal(snapshot.url, fixtureUrl);
        });
    }

    await test('Fluent breadcrumb works while ACMAIS overlays are excluded from identity',
      `<a class="ms-Breadcrumb-itemLink">${company}</a><div id="acmais-link-toolbar"><h2>8888 - Own toolbar</h2></div><div id="acmais-loading-cover"><h2>9999 - Own cover</h2></div>`,
      async page => {
        assert.equal(await page.evaluate(scripts.heading), company);
        await page.locator('.ms-Breadcrumb-itemLink').evaluate(element => element.remove());
        assert.equal(await page.evaluate(scripts.heading), '');
      });

    await test('RootFolder and id URL variants extract company identity', '<h1>Documentos</h1>', async page => {
      for (const [key, identity] of Object.entries(scripts.identities)) {
        assert.deepEqual(identity, ['0000', 'Empresa de teste'], `${key} identity`);
      }
    });

    await test('No submit button never clicks the injected cancel control',
      '<form><input id="password" type="password"><button type="button" id="site-cancel">Cancelar</button></form>',
      async page => {
        await page.evaluate(scripts.covers[10]);
        assert.equal(await page.evaluate(scripts.password), false);
        assert.equal(await page.locator('#password').inputValue(), '');
        assert.deepEqual(await page.evaluate(() => window.__qa.clicks), []);
        assert.equal(await page.evaluate(() => window.__qa.returns), 0);
        assert.equal(await page.locator('#acmais-loading-cover').count(), 1);
      });

    await test('Disabled or hidden submit controls do not trigger unrelated buttons',
      '<form><input id="password" type="password"><input id="btnSubmitPassword" type="submit" disabled><button type="submit" hidden>Verificar</button><button type="button">Cancelar</button></form><button type="button" id="outside">Verificar</button>',
      async page => {
        assert.equal(await page.evaluate(scripts.password), false);
        assert.deepEqual(await page.evaluate(() => window.__qa.clicks), []);
        assert.equal(await page.evaluate(() => window.__qa.returns), 0);
        assert.equal(await page.locator('#acmais-loading-cover').count(), 1);
      });

    await test('A hidden submit is not clicked or replaced with unrelated actions',
      '<form><input id="password" type="password"><input id="btnSubmitPassword" type="submit" hidden><button type="button">Cancelar</button></form>',
      async page => {
        assert.equal(await page.evaluate(scripts.password), false);
        assert.deepEqual(await page.evaluate(() => window.__qa.clicks), []);
        assert.equal(await page.locator('#acmais-loading-cover').count(), 0);
      });

    await test('No password form leaves the ready folder uncovered', '<h1>Documentos</h1>', async page => {
      assert.equal(await page.evaluate(scripts.password), false);
      assert.equal(await page.locator('#acmais-loading-cover').count(), 0);
    });

    await test('Correct password submit dispatches input/change and clicks once', passwordForm, async page => {
      assert.equal(await page.evaluate(scripts.password), true);
      assert.equal(await page.locator('#password').inputValue(), scripts.secret);
      assert.deepEqual(await page.evaluate(() => window.__qa.inputEvents), ['input', 'change']);
      assert.deepEqual(await page.evaluate(() => window.__qa.clicks), ['btnSubmitPassword']);
      assert.equal(await page.evaluate(() => window.__qa.submits), 1);
      assert.equal(await page.evaluate(() => window.__qa.returns), 0);
    });

    await test('Input events enable the initially disabled password submit',
      '<form><input id="password" type="password"><input id="btnSubmitPassword" type="submit" value="Verificar" disabled></form>',
      async page => {
        await page.evaluate(() => document.querySelector('#password').addEventListener('input', () => {
          document.querySelector('#btnSubmitPassword').disabled = false;
        }));
        assert.equal(await page.evaluate(scripts.password), true);
        assert.equal(await page.locator('#password').inputValue(), scripts.secret);
        assert.deepEqual(await page.evaluate(() => window.__qa.clicks), ['btnSubmitPassword']);
        assert.equal(await page.evaluate(() => window.__qa.submits), 1);
      });

    await test('Submit replaced during input waits for the next probe instead of clicking a detached control', passwordForm,
      async page => {
        await page.evaluate(() => document.querySelector('#password').addEventListener('input', () => {
          const oldButton = document.querySelector('#btnSubmitPassword');
          oldButton.replaceWith(oldButton.cloneNode(true));
        }, { once: true }));
        assert.equal(await page.evaluate(scripts.password), false);
        assert.deepEqual(await page.evaluate(() => window.__qa.clicks), []);
        assert.equal(await page.evaluate(scripts.password), true);
        assert.deepEqual(await page.evaluate(() => window.__qa.clicks), ['btnSubmitPassword']);
        assert.equal(await page.evaluate(() => window.__qa.submits), 1);
      });

    await test('Recognized fallback submit stays inside the password form',
      '<button type="button" id="outside">Verificar</button><form><input id="password" type="password"><button type="button" id="verify">Verificar</button></form>',
      async page => {
        assert.equal(await page.evaluate(scripts.password), true);
        assert.deepEqual(await page.evaluate(() => window.__qa.clicks), ['verify']);
      });

    await test('Wrong origin prevents password fill and injected cover', passwordForm, async page => {
      assert.equal(await page.evaluate(scripts.password), false);
      assert.equal(await page.locator('#password').inputValue(), '');
      assert.equal(await page.locator('#acmais-loading-cover').count(), 0);
      assert.deepEqual(await page.evaluate(() => window.__qa.clicks), []);
    }, 'https://another-tenant.sharepoint.com/fixture');

    await test('Same-token and older covers cannot hide a successfully opened folder', `<h1>${company}</h1>`, async page => {
      assert.equal(await page.evaluate(scripts.covers[10]), true);
      assert.equal(await page.evaluate(scripts.toolbars[11]), true);
      assert.equal(await page.evaluate(scripts.covers[10]), false);
      assert.equal(await page.evaluate(scripts.covers[11]), false);
      assert.equal(await page.locator('#acmais-loading-cover').count(), 0);
      assert.equal(await page.locator('#acmais-link-toolbar').count(), 1);
      assert.deepEqual(await page.evaluate(() => window.__acmaisNavigation), { token: 11, phase: 'active' });
    });

    await test('Older toolbar cannot overwrite a newer active company', `<h1>${company}</h1>`, async page => {
      assert.equal(await page.evaluate(scripts.toolbars[12]), true);
      assert.equal(await page.evaluate(scripts.toolbars[11]), false);
      assert.equal(await page.locator('#acmais-company-label').textContent(), `${company} 12`);
      assert.deepEqual(await page.evaluate(() => window.__acmaisNavigation), { token: 12, phase: 'active' });
    });

    await test('Older toolbar cannot dismiss the next operation loading cover', `<h1>${company}</h1>`, async page => {
      await page.evaluate(scripts.toolbars[11]);
      assert.equal(await page.evaluate(scripts.covers[12]), true);
      assert.equal(await page.evaluate(scripts.toolbars[11]), false);
      assert.equal(await page.locator('#acmais-loading-cover').count(), 1);
      assert.deepEqual(await page.evaluate(() => window.__acmaisNavigation), { token: 12, phase: 'loading' });
      assert.equal(await page.evaluate(scripts.toolbars[12]), true);
      assert.equal(await page.locator('#acmais-loading-cover').count(), 0);
    });

    await test('Stale password operation cannot fill or submit after readiness', passwordForm, async page => {
      await page.evaluate(scripts.toolbars[11]);
      assert.equal(await page.evaluate(scripts.password), false);
      assert.equal(await page.locator('#password').inputValue(), '');
      assert.deepEqual(await page.evaluate(() => window.__qa.clicks), []);
      assert.equal(await page.locator('#acmais-loading-cover').count(), 0);
    });

    await test('Repeated current loading cover remains unique and cancel works once', '<h1>Documentos</h1>', async page => {
      await page.evaluate(scripts.covers[10]);
      await page.evaluate(scripts.covers[10]);
      assert.equal(await page.locator('#acmais-loading-cover').count(), 1);
      await page.locator('#acmais-loading-cover button').click();
      assert.equal(await page.evaluate(() => window.__qa.returns), 1);
    });

    await test('Company label is literal text, never executable markup', '<h1>Documentos</h1>', async page => {
      await page.evaluate(scripts.literalToolbar);
      assert.equal(await page.locator('#acmais-company-label img').count(), 0);
      assert.equal(await page.evaluate(() => window.__qa.pwned), false);
      assert.ok((await page.locator('#acmais-company-label').textContent()).includes('<img'));
    });
  } finally {
    const report = {
      timestamp: new Date().toISOString(),
      browser: await browser.version(),
      sourceSha256: sourceHash,
      mode: 'Synthetic browser DOM fixtures; all network intercepted; no client data',
      passed: results.filter(result => result.status === 'passed').length,
      failed: results.filter(result => result.status === 'failed').length,
      results,
    };
    if (reportEnabled) fs.writeFileSync(path.join(reportDirectory, 'results.json'), JSON.stringify(report, null, 2));
    console.log(`SharePoint DOM: ${report.passed} passed, ${report.failed} failed.`);
    if (report.failed) process.exitCode = 1;
    await browser.close();
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
