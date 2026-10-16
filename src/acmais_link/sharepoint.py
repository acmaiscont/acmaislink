from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, unquote, urlparse


FOLDER_PATTERN = re.compile(r"^(?P<code>.+?)\s+-\s+(?P<name>.+)$")
NUMERIC_FOLDER_PATTERN = re.compile(r"^(?P<code>[0-9]+)\s*-\s*(?P<name>.+)$")


def _normalize_folder_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _folder_path_candidates(value: str, *, decode_passes: int) -> list[str]:
    # SharePoint may nest a percent-encoded path inside an already encoded URL.
    # Never decode indefinitely: query values were decoded once by parse_qs.
    for _ in range(decode_passes):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    return [
        candidate
        for part in reversed(value.replace("\\", "/").split("/"))
        if (candidate := _normalize_folder_name(part))
    ]


def extract_company_identity(url: str, page_heading: str = "", *, expected_code: str | None = None) -> tuple[str, str] | None:
    """Extract ``code - company name`` from a SharePoint folder URL or heading."""
    parsed = urlparse(url)
    candidates: list[str] = []
    query = {key.casefold(): values for key, values in parse_qs(parsed.query).items()}
    for key in ("id", "rootfolder"):
        folder_path = query.get(key, [""])[0]
        if folder_path:
            candidates.extend(_folder_path_candidates(folder_path, decode_passes=1))
    if page_heading:
        candidates.append(_normalize_folder_name(page_heading))
    # Some direct folder links carry the name only in the URL path. Prefer the
    # explicit query/DOM identity and use this less-specific source as fallback.
    candidates.extend(_folder_path_candidates(parsed.path, decode_passes=2))

    for candidate in candidates:
        # Numeric company codes also occur as "150-NAME" in SharePoint.
        # Keep the spaced separator mandatory for other codes, so arbitrary
        # hyphenated words (e.g. marketing-list) are not treated as companies.
        match = NUMERIC_FOLDER_PATTERN.match(candidate) or FOLDER_PATTERN.match(candidate)
        if match:
            code = match.group("code").strip()
            name = match.group("name").strip()
            if code and name and (expected_code is None or code.casefold() == expected_code.casefold()):
                return code, name
    return None


_PAGE_HELPERS = r"""
  const acmaisVisible = (item) => Boolean(item && item.getClientRects().length &&
    getComputedStyle(item).visibility !== 'hidden' && getComputedStyle(item).display !== 'none');
  const acmaisPasswordInput = () => Array.from(document.querySelectorAll('input[type="password"]'))
    .find(acmaisVisible);
  const acmaisHeading = () => {
    // Read only explicit breadcrumb/heading elements, never arbitrary page
    // text, document.title or child-frame content. Attribute names support
    // breadcrumbs whose visible text is abbreviated on a narrow window.
    const breadcrumbRoots = Array.from(document.querySelectorAll(
      '.ms-Breadcrumb, [data-automationid="breadcrumb"], [data-automation-id="breadcrumb"], ' +
      '[aria-label="breadcrumb" i], [aria-label="breadcrumbs" i], ' +
      '[aria-label="breadcrumb navigation" i], [aria-label="trilha de navegação" i], ' +
      '[aria-label="caminho de navegação" i]'
    ));
    const breadcrumbs = Array.from(new Set([
      ...document.querySelectorAll('.ms-Breadcrumb-itemLink'),
      ...breadcrumbRoots.flatMap((root) => Array.from(root.querySelectorAll('a, button, [aria-current]')))
    ]));
    const currentBreadcrumbs = breadcrumbs.filter((item) =>
      item.hasAttribute('aria-current') && item.getAttribute('aria-current') !== 'false');
    const headings = Array.from(document.querySelectorAll('h1, h2, [role="heading"]'));
    return [...currentBreadcrumbs.reverse(), ...breadcrumbs.reverse(), ...headings]
      .filter((item) => acmaisVisible(item) && !item.closest('#acmais-link-toolbar, #acmais-loading-cover'))
      .flatMap((item) => [item.getAttribute('title'), item.getAttribute('aria-label'), item.textContent])
      .map((text) => (text || '').replace(/\s+/g, ' ').trim())
      // Keep in sync with NUMERIC_FOLDER_PATTERN / FOLDER_PATTERN in Python.
      .find((text) => /^(?:[0-9]+\s*-\s*.+|.+?\s+-\s+.+)$/.test(text)) || '';
  };
"""


def navigation_state_script() -> str:
    """Read URL, authentication form and identity in one consistent DOM snapshot."""
    return f"""
(() => {{
  {_PAGE_HELPERS}
  const acmaisNavigationSnapshot = {{
    url: location.href, hasPassword: Boolean(acmaisPasswordInput()), heading: acmaisHeading(),
    ready: document.readyState !== 'loading',
    frameCount: document.querySelectorAll('iframe, frame').length
  }};
  return acmaisNavigationSnapshot;
}})()
"""


def _navigation_guard(navigation_token: int | None, phase: str) -> str:
    if navigation_token is None:
        return ""
    token = int(navigation_token)
    # This is an ordering guard, not an authorization token. Native origin and
    # bridge checks remain mandatory; remote pages cannot grant native access.
    return f"""
  const acmaisPrevious = window.__acmaisNavigation;
  if (acmaisPrevious && (acmaisPrevious.token > {token} ||
      (acmaisPrevious.token === {token} && acmaisPrevious.phase === 'active' && {json.dumps(phase)} === 'loading'))) return false;
  window.__acmaisNavigation = {{ token: {token}, phase: {json.dumps(phase)} }};
"""


def password_submission_script(password: str, allowed_origin: str | None = None, *, navigation_token: int | None = None,
                               expected_url: str | None = None, include_cover: bool = True) -> str:
    """Build a one-shot script for Microsoft's shared-link password page."""
    secret = json.dumps(password)
    origin_check = f"if (location.origin !== {json.dumps(allowed_origin)}) return false;" if allowed_origin else ""
    document_check = f"if (location.href !== {json.dumps(expected_url)}) return false;" if expected_url else ""
    cover = navigation_cover_body('Validando o acesso seguro…', navigation_token=navigation_token) if include_cover else _navigation_guard(navigation_token, 'loading')
    return f"""
(() => {{
  {origin_check}
  {document_check}
  {_PAGE_HELPERS}
  const input = acmaisPasswordInput();
  if (!input || input.disabled || input.readOnly) return false;
  const allowedButton = (item) => acmaisVisible(item) &&
    !item.closest('#acmais-loading-cover, #acmais-link-toolbar');
  const scope = input.form || document;
  const button = [document.querySelector('#btnSubmitPassword'),
    ...scope.querySelectorAll('button[type="submit"], input[type="submit"]')].find(allowedButton) ||
    Array.from(scope.querySelectorAll('button, input[type="button"]')).find((item) =>
      allowedButton(item) && /^(continuar|avançar|verificar|entrar|abrir|acessar|continue|next|verify|submit|open|sign in|access)$/i
        .test((item.textContent || item.value || '').trim()));
  if (!button) return false;
  {cover}
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(input, {secret});
  input.dispatchEvent(new Event('input', {{ bubbles: true }}));
  input.dispatchEvent(new Event('change', {{ bubbles: true }}));
  // Some forms enable or replace their submit button only after input events.
  // A later native probe will retry if the asynchronous render is not ready yet.
  if (button.disabled || !button.isConnected) return false;
  button.click();
  return true;
}})()
"""


def password_page_present_script() -> str:
    return f"(() => {{ {_PAGE_HELPERS} return Boolean(acmaisPasswordInput()); }})()"


def company_heading_script() -> str:
    return f"(() => {{ {_PAGE_HELPERS} return acmaisHeading(); }})()"


def navigation_cover_body(message: str, *, navigation_token: int | None = None) -> str:
    text = json.dumps(message)
    return f"""
  {_navigation_guard(navigation_token, 'loading')}
  document.getElementById('acmais-loading-cover')?.remove();
  const acmaisCover = document.createElement('div');
  acmaisCover.id = 'acmais-loading-cover';
  acmaisCover.setAttribute('role', 'status');
  acmaisCover.innerHTML = `
    <div style="width:min(430px,88vw);padding:34px;border-radius:18px;background:#fff;
      border:1px solid #dde2e6;box-shadow:0 24px 70px rgba(0,0,0,.18);text-align:center">
      <div style="width:42px;height:42px;margin:0 auto 18px;border:4px solid rgba(99,48,132,.18);
        border-top-color:#633084;border-radius:50%;animation:acmais-spin .8s linear infinite"></div>
      <h2 style="margin:0 0 8px;color:#252527;font:700 24px 'Segoe UI',sans-serif">Abrindo documentos</h2>
      <p style="margin:0;color:#67717a;font:15px/1.5 'Segoe UI',sans-serif">${{{text}}}</p>
    </div>`;
  Object.assign(acmaisCover.style, {{
    position:'fixed',inset:'0',zIndex:'2147483647',display:'grid',placeItems:'center',
    background:'#f4f6f8',fontFamily:'Segoe UI, sans-serif'
  }});
  const acmaisStyle = document.createElement('style');
  acmaisStyle.textContent = '@keyframes acmais-spin {{ to {{ transform:rotate(360deg) }} }}';
  acmaisCover.appendChild(acmaisStyle);
  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.textContent = 'Cancelar e voltar às empresas';
  cancel.style.cssText = 'margin-top:20px;padding:10px 16px;border:0;border-radius:8px;cursor:pointer';
  cancel.onclick = () => window.pywebview?.api.return_home();
  acmaisCover.firstElementChild.appendChild(cancel);
  (document.body || document.documentElement).appendChild(acmaisCover);
"""


def navigation_cover_script(message: str = "Conectando ao SharePoint e validando o acesso…", *, navigation_token: int | None = None) -> str:
    return f"""
(() => {{
  {navigation_cover_body(message, navigation_token=navigation_token)}
  return true;
}})()
"""


def navigation_toolbar_script(company_label: str, *, navigation_token: int | None = None) -> str:
    label = json.dumps(company_label)
    return f"""
(() => {{
  {_navigation_guard(navigation_token, 'active')}
  document.getElementById('acmais-loading-cover')?.remove();
  document.getElementById('acmais-link-toolbar')?.remove();
  const bar = document.createElement('div');
  bar.id = 'acmais-link-toolbar';
  bar.setAttribute('role', 'navigation');
  bar.innerHTML = `
    <button id="acmais-home" type="button">← Empresas</button>
    <span id="acmais-company-label"></span>
    <button id="acmais-browser" type="button">Abrir no navegador</button>
  `;
  bar.querySelector('#acmais-company-label').textContent = {label};
  Object.assign(bar.style, {{
    position: 'fixed', top: '12px', left: '50%', transform: 'translateX(-50%)',
    zIndex: '2147483647', display: 'flex', alignItems: 'center', gap: '12px',
    padding: '8px 10px', borderRadius: '12px', background: '#252527', color: '#fff',
    boxShadow: '0 8px 28px rgba(0,0,0,.28)', fontFamily: 'Segoe UI, sans-serif',
    fontSize: '13px', maxWidth: 'calc(100vw - 24px)'
  }});
  for (const button of bar.querySelectorAll('button')) {{
    Object.assign(button.style, {{
      border: '0', borderRadius: '8px', padding: '8px 11px', cursor: 'pointer',
      background: '#f5740b', color: '#fff', fontWeight: '700'
    }});
  }}
  bar.querySelector('#acmais-home').onclick = () => window.pywebview.api.return_home();
  bar.querySelector('#acmais-browser').onclick = () => window.pywebview.api.open_current_external();
  document.body.appendChild(bar);
  return true;
}})()
"""
