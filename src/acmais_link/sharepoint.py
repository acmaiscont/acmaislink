from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse


FOLDER_PATTERN = re.compile(r"^(?P<code>.+?)\s+-\s+(?P<name>.+)$")


def extract_company_identity(url: str, page_heading: str = "") -> tuple[str, str] | None:
    """Extract ``code - company name`` from a SharePoint folder URL or heading."""
    parsed = urlparse(url)
    candidates: list[str] = []
    folder_path = parse_qs(parsed.query).get("id", [""])[0]
    if folder_path:
        candidates.extend(part.strip() for part in folder_path.replace("\\", "/").split("/") if part.strip())
    if page_heading.strip():
        candidates.append(page_heading.strip())

    for candidate in candidates:
        match = FOLDER_PATTERN.match(candidate)
        if match:
            code = match.group("code").strip()
            name = match.group("name").strip()
            if code and name:
                return code, name
    return None


def password_submission_script(password: str, allowed_origin: str | None = None) -> str:
    """Build a one-shot script for Microsoft's shared-link password page."""
    secret = json.dumps(password)
    origin_check = f"if (location.origin !== {json.dumps(allowed_origin)}) return false;" if allowed_origin else ""
    return f"""
(() => {{
  {origin_check}
  {navigation_cover_body('Validando o acesso seguro…')}
  const input = document.querySelector('input[type="password"]');
  if (!input) return false;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(input, {secret});
  input.dispatchEvent(new Event('input', {{ bubbles: true }}));
  input.dispatchEvent(new Event('change', {{ bubbles: true }}));
  const button = document.querySelector('#btnSubmitPassword') ||
    document.querySelector('button[type="submit"], input[type="submit"]') ||
    Array.from(document.querySelectorAll('button, input[type="button"]'))
      .find((item) => !item.disabled);
  if (!button) return false;
  button.click();
  return true;
}})()
"""


def password_page_present_script() -> str:
    return "Boolean(document.querySelector('input[type=\"password\"]'))"


def company_heading_script() -> str:
    return """
(() => {
  const headings = Array.from(document.querySelectorAll('h1, h2, [role="heading"]'));
  const candidate = headings.map((item) => (item.textContent || '').trim())
    .find((text) => /\\s-\\s/.test(text));
  return candidate || '';
})()
"""


def navigation_cover_body(message: str) -> str:
    text = json.dumps(message)
    return f"""
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


def navigation_cover_script(message: str = "Conectando ao SharePoint e validando o acesso…") -> str:
    return f"""
(() => {{
  {navigation_cover_body(message)}
  return true;
}})()
"""


def navigation_toolbar_script(company_label: str) -> str:
    label = json.dumps(company_label)
    return f"""
(() => {{
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
