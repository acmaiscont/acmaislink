const state = { companies: [], filter: "", initialized: false, initializing: false, loading: null, busy: false, navigationSeq: 0 };
const grid = document.querySelector("#company-grid");
const emptyState = document.querySelector("#empty-state");
const count = document.querySelector("#company-count");
const dialog = document.querySelector("#company-dialog");
const form = document.querySelector("#company-form");
const confirmDialog = document.querySelector("#confirm-dialog");
const toast = document.querySelector("#toast");
const busyOverlay = document.querySelector("#busy-overlay");
const formError = document.querySelector("#form-error");
const loadError = document.querySelector("#load-error");
const refreshButton = document.querySelector("#refresh");
const cancelOpening = document.querySelector("#cancel-opening");
let previousFocus = null;

let localToken = null;
window.bootstrapAcmais = (token) => {
  localToken = token;
  initializeApp();
};
const api = () => localToken && window.pywebview?.api ? new Proxy({}, {
  get: (_, name) => (...args) => window.pywebview.api.command(localToken, name, args)
}) : null;
const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
})[char]);

function notify(message, error = false) {
  toast.textContent = message;
  toast.className = `toast show${error ? " error" : ""}`;
  window.clearTimeout(notify.timer);
  notify.timer = window.setTimeout(() => toast.className = "toast", error ? 8000 : 4500);
}

async function loadCompanies() {
  if (state.loading) return state.loading;
  if (!api()) {
    showLoadError("A conexão com o aplicativo ainda não está pronta. Aguarde um momento e recarregue a lista.");
    return false;
  }
  refreshButton.disabled = true;
  refreshButton.textContent = "Carregando…";
  state.loading = (async () => {
    let timeout;
    try {
      const result = await Promise.race([
        api().list_companies(),
        new Promise((_, reject) => { timeout = window.setTimeout(() => reject(new Error("timeout")), 10000); }),
      ]);
      if (!result.ok) {
        showLoadError(result.error || "Não foi possível carregar a lista. Tente recarregar.");
        return false;
      }
      state.companies = result.companies;
      state.initialized = true;
      loadError.hidden = true;
      render();
      // A failure to read a one-off notice must not hide an already loaded list.
      api().consume_notice().then((noticeResult) => {
        const notice = noticeResult.notice;
        const retryCompany = state.companies.find(item => item.code === notice?.deliveryDraft?.code);
        if (retryCompany && !document.querySelector("dialog[open]") && !state.busy) {
          openDelivery(retryCompany, notice.deliveryDraft, notice.message);
        } else if (notice?.deliveryIssues?.length && !document.querySelector("dialog[open]") && !state.busy) {
          showDeliveryResult(notice);
        } else if (notice) {
          const detail = notice.deliveryIssues?.[0]?.detail;
          notify(detail ? `${notice.message} ${detail} Consulte o histórico.` : notice.message, notice.error);
        }
      }).catch(() => {});
      return true;
    } catch {
      showLoadError("Não foi possível carregar a lista. Use Recarregar lista para tentar novamente.");
      return false;
    } finally {
      window.clearTimeout(timeout);
      refreshButton.disabled = false;
      refreshButton.textContent = "Recarregar lista";
      state.loading = null;
    }
  })();
  return state.loading;
}

function showLoadError(message) {
  loadError.textContent = message;
  loadError.hidden = false;
  if (!state.initialized) count.textContent = "Lista indisponível";
}

function setBusy(active, title = "Abrindo documentos", message = "Conectando ao SharePoint e validando o acesso…") {
  if (active && !state.busy) previousFocus = document.activeElement;
  state.busy = active;
  document.querySelector("#busy-title").textContent = title;
  document.querySelector("#busy-message").textContent = message;
  busyOverlay.hidden = !active;
  document.querySelector('main').inert = active;
  document.querySelector('header').inert = active;
  document.querySelector('footer').inert = active;
  if (active) cancelOpening.focus();
  else if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
}

function nextPaint() {
  return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
}

function closeCompanyForm() {
  dialog.close("cancel");
  form.reset();
  formError.hidden = true;
}

const searchable = (value) => String(value).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-BR");
function render() {
  const term = searchable(state.filter.trim());
  const items = state.companies.filter((item) =>
    searchable(`${item.code} ${item.name}`).includes(term)
  );
  const total = state.companies.length;
  count.textContent = term && total ? `${items.length} de ${total} ${total === 1 ? "empresa" : "empresas"}`
    : `${total} ${total === 1 ? "empresa" : "empresas"}`;
  emptyState.hidden = total !== 0;
  grid.innerHTML = items.map((company) => `
    <article class="company-card">
      <div class="card-top">
        <div class="company-code">${escapeHtml(company.code)}</div>
        <div>
          <h3>${escapeHtml(company.name)}</h3>
          <span class="credential-status ${company.hasCredential ? "ready" : "missing"}">
            ${company.hasCredential ? "Acesso configurado" : "Senha não configurada"}
          </span>
        </div>
      </div>
      <div class="card-actions">
        <button class="primary send-action" data-action="deliver" data-code="${escapeHtml(company.code)}">Enviar documentos</button>
        <button class="ghost" data-action="open" data-code="${escapeHtml(company.code)}">Abrir documentos</button>
        <button class="ghost" data-action="edit" data-code="${escapeHtml(company.code)}" aria-label="Editar ${escapeHtml(company.name)}">Editar</button>
      </div>
      <div class="secondary-actions">
        <button class="text-button" data-action="external" data-code="${escapeHtml(company.code)}">Abrir no navegador</button>
        ${company.group_code ? `<button class="text-button" data-action="refresh-group" data-code="${escapeHtml(company.code)}">Atualizar grupo</button>` : ""}
        <button class="text-button" data-action="delete" data-code="${escapeHtml(company.code)}">Remover</button>
      </div>
    </article>
  `).join("");
  if (state.companies.length && !items.length) {
    grid.innerHTML = '<div class="empty-state"><h3>Nenhum resultado</h3><p>Tente buscar por outro código ou nome.</p></div>';
  }
}

function openForm(company = null) {
  if (state.busy || dialog.open) return;
  form.reset();
  formError.hidden = true;
  document.querySelector("#original-code").value = company?.code || "";
  document.querySelector("#url").value = company?.url || "";
  document.querySelector("#dialog-title").textContent = company?.group_code ? "Atualizar acesso do grupo"
    : company ? "Atualizar acesso" : "Adicionar acesso";
  document.querySelector("#identity-hint").textContent = company?.group_code
    ? `O grupo ${company.group_code} usa um link e uma senha para todas as empresas. Salvar atualiza a lista do grupo.`
    : company ? `Identificação atual: ${company.code} - ${company.name}. Ela será confirmada novamente pelo link.`
      : "Use o link de uma empresa ou de um grupo para identificar automaticamente as empresas.";
  document.querySelector("#password-hint").textContent = company ? "(deixe em branco para manter)" : "";
  document.querySelector("#password").required = !company;
  dialog.showModal();
  document.querySelector("#url").focus();
}

function showFormError(message) {
  setBusy(false);
  formError.textContent = message;
  formError.hidden = false;
  if (!dialog.open) dialog.showModal();
  formError.focus();
  formError.scrollIntoView({ block: "nearest" });
}

async function saveCompany(event) {
  event.preventDefault();
  if (state.busy || !form.reportValidity()) return;
  if (!api()) return showFormError("O aplicativo ainda está conectando. Aguarde um momento e tente novamente.");
  const payload = {
    originalCode: document.querySelector("#original-code").value,
    url: document.querySelector("#url").value,
    password: document.querySelector("#password").value,
  };
  const operation = ++state.navigationSeq;
  formError.hidden = true;
  dialog.close("validating");
  setBusy(true);
  await nextPaint();
  if (operation !== state.navigationSeq) return;
  try {
    const result = await api().begin_company_setup(payload);
    if (operation !== state.navigationSeq) return;
    if (!result.ok) showFormError(result.error || "Não foi possível validar o acesso. Confira o link e tente novamente.");
  } catch {
    if (operation === state.navigationSeq) showFormError("Não foi possível iniciar a validação. Tente novamente.");
  }
}

async function removeCompany(company) {
  if (confirmDialog.open) return;
  confirmDialog.returnValue = "cancel";
  document.querySelector("#confirm-message").textContent = `Deseja remover ${company.code} - ${company.name} deste computador?`;
  confirmDialog.showModal();
  document.querySelector("#cancel-remove").focus();
  const decision = await new Promise((resolve) => {
    confirmDialog.addEventListener("close", () => resolve(confirmDialog.returnValue), { once: true });
  });
  if (decision !== "confirm") return;
  let result;
  try { result = await api().delete_company(company.code); }
  catch { return notify("Não foi possível remover a empresa. Tente novamente.", true); }
  if (!result.ok) return notify(result.error, true);
  notify("Empresa removida.");
  await loadCompanies();
}

grid.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button || button.disabled || state.busy) return;
  const company = state.companies.find((item) => item.code === button.dataset.code);
  if (!company) return;
  if (button.dataset.action === "deliver") return openDelivery(company);
  if (button.dataset.action === "edit") return openForm(company);
  if (button.dataset.action === "delete") return removeCompany(company);
  button.disabled = true;
  const external = button.dataset.action === "external";
  const refreshGroup = button.dataset.action === "refresh-group";
  const label = button.textContent;
  const operation = external ? null : ++state.navigationSeq;
  if (!external) {
    button.textContent = refreshGroup ? "Consultando…" : "Abrindo…";
    if (refreshGroup) setBusy(true, "Atualizando grupo", "Conferindo se há novas empresas no SharePoint…");
    else setBusy(true);
    await nextPaint();
  }
  try {
    if (!external && operation !== state.navigationSeq) return;
    const command = external ? "open_external" : refreshGroup ? "refresh_group" : "open_company";
    const result = await api()[command](company.code);
    if (!external && operation !== state.navigationSeq) return;
    if (!result.ok) {
      if (!external) setBusy(false);
      notify(result.error, true);
    } else if (external) notify("Link enviado ao navegador padrão.");
  } catch {
    if (!external && operation !== state.navigationSeq) return;
    if (!external) setBusy(false);
    notify("Não foi possível concluir a ação. Tente novamente.", true);
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
});

form.addEventListener("submit", saveCompany);
document.querySelector("#search").addEventListener("input", (event) => { state.filter = event.target.value; render(); });
document.querySelector("#add-company").addEventListener("click", () => openForm());
document.querySelector("#empty-add").addEventListener("click", () => openForm());
refreshButton.addEventListener("click", loadCompanies);
document.querySelector("#close-company-dialog").addEventListener("click", closeCompanyForm);
document.querySelector("#cancel-company").addEventListener("click", closeCompanyForm);
document.querySelector("#cancel-remove").addEventListener("click", () => confirmDialog.close("cancel"));
document.querySelector("#confirm-remove").addEventListener("click", () => confirmDialog.close("confirm"));
async function cancelNavigation() {
  if (!state.busy || cancelOpening.disabled) return;
  ++state.navigationSeq;
  cancelOpening.disabled = true;
  cancelOpening.textContent = "Cancelando…";
  try {
    await window.pywebview?.api.return_home();
    setBusy(false);
    form.reset();
  } catch {
    document.querySelector("#busy-message").textContent = "Não foi possível cancelar agora. Tente novamente.";
  } finally {
    cancelOpening.disabled = false;
    cancelOpening.textContent = "Cancelar abertura";
  }
}
cancelOpening.addEventListener("click", cancelNavigation);
document.addEventListener("keydown", (event) => {
  if (state.busy && event.key === "Escape") { event.preventDefault(); cancelNavigation(); }
  else if (state.busy && event.key === "Tab") { event.preventDefault(); cancelOpening.focus(); }
  else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f" && !document.querySelector("dialog[open]") && !state.busy) {
    event.preventDefault();
    document.querySelector("#search").focus();
  } else if (event.key === "Escape" && event.target.id === "search") {
    event.target.value = "";
    state.filter = "";
    render();
  }
});

const updateStatus = document.querySelector('#update-status');
const homeDocumentUrl = window.location.href;
const homeLocation = new URL(homeDocumentUrl);
const isLocalHome = homeLocation.protocol === 'file:' || (
  homeLocation.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(homeLocation.hostname)
);
let updateStatusTimer = null;
let updateStatusPending = false;
let homeDocumentActive = true;

function canReadUpdateStatus() {
  return homeDocumentActive && isLocalHome && window.location.href === homeDocumentUrl && Boolean(api());
}

async function refreshUpdateStatus() {
  if (!canReadUpdateStatus() || updateStatusPending) return;
  updateStatusPending = true;
  let timeout;
  try {
    // The native background service owns downloads and installation. The home UI
    // only reads its status and never starts or prompts for an update.
    const result = await Promise.race([
      api().get_update_status(),
      new Promise((_, reject) => { timeout = window.setTimeout(() => reject(new Error('timeout')), 5000); }),
    ]);
    if (canReadUpdateStatus()) {
      if (result?.ok) updateStatus.textContent = result.status === 'disabled' ? 'Atualizações automáticas indisponíveis'
        : result.status === 'ready' ? 'Atualização pronta · será aplicada ao fechar' : 'Atualizações automáticas';
    }
  } catch {
    // Preserve the displayed mode when the native status is unavailable.
  } finally {
    window.clearTimeout(timeout);
    updateStatusPending = false;
  }
}

const deliveryDialog = document.querySelector("#delivery-dialog");
const deliveryForm = document.querySelector("#delivery-form");
const deliverySector = document.querySelector("#delivery-sector");
const deliveryKind = document.querySelector("#delivery-kind");
const deliveryPeriod = document.querySelector("#delivery-period");
const periodShortcuts = document.querySelectorAll(".period-shortcuts button");
const deliveryError = document.querySelector("#delivery-error");
const deliverySubmit = document.querySelector("#submit-delivery");
const chooseFiles = document.querySelector("#choose-delivery-files");
const chooseFolder = document.querySelector("#choose-delivery-folder");
const historyDialog = document.querySelector("#history-dialog");
let draft = null;
let choosingFiles = false;

function fillOptions(select, values) {
  select.replaceChildren(new Option("Selecione", ""), ...values.map(value => new Option(value, value)));
}

function updateDeliveryPreview() {
  const [year, month] = deliveryPeriod.value.split("-");
  const valid = Boolean(draft?.files.length && deliveryForm.checkValidity());
  const destination = document.querySelector("#delivery-destination");
  destination.hidden = !valid;
  deliverySubmit.disabled = !valid || choosingFiles;
  if (valid) {
    const parts = [`${draft.company.code} - ${draft.company.name}`, year, `${month}-${year}`, deliverySector.value, deliveryKind.value];
    document.querySelector("#delivery-path").textContent = parts.join(" / ");
  }
}

function showDeliveryError(message) {
  deliveryError.textContent = message;
  deliveryError.hidden = false;
}

function renderDeliveryFiles(files) {
  const list = document.querySelector("#delivery-files-list");
  list.replaceChildren(...files.map(filename => {
    const item = document.createElement("li");
    item.textContent = filename;
    return item;
  }));
  list.hidden = !files.length;
  document.querySelector("#delivery-files-summary").textContent = files.length === 1
    ? "1 item selecionado" : `${files.length} itens selecionados`;
}

async function openDelivery(company, saved = null, message = "") {
  if (!api() || deliveryDialog.open) return;
  const next = { company, files: [], catalog: {}, periods: {} };
  draft = next;
  deliveryForm.reset();
  deliveryError.hidden = true;
  fillOptions(deliverySector, []);
  fillOptions(deliveryKind, []);
  document.querySelector("#delivery-company").textContent = `${company.code} - ${company.name}`;
  document.querySelector("#delivery-files-summary").textContent = "Até 30 arquivos avulsos ou 300 itens por pasta. Limite de 100 MB por arquivo.";
  document.querySelector("#delivery-files-list").hidden = true;
  document.querySelector("#delivery-suggestion").hidden = true;
  chooseFolder.disabled = chooseFiles.disabled = true;
  periodShortcuts.forEach(button => { button.disabled = true; });
  updateDeliveryPreview();
  deliveryDialog.showModal();
  try {
    const options = await api().delivery_options();
    if (!deliveryDialog.open || draft !== next) return;
    if (!options.ok) throw Error();
    next.catalog = options.catalog;
    next.periods = { currentPeriod: options.currentPeriod, previousPeriod: options.previousPeriod };
    periodShortcuts.forEach(button => { button.disabled = !next.periods[button.dataset.period]; });
    fillOptions(deliverySector, Object.keys(next.catalog));
    if (saved) {
      next.files = saved.files;
      deliverySector.value = saved.sector;
      fillOptions(deliveryKind, next.catalog[saved.sector] || []);
      deliveryKind.value = saved.kind;
      deliveryPeriod.value = saved.period;
      renderDeliveryFiles(next.files);
      showDeliveryError(message);
      updateDeliveryPreview();
    }
    chooseFolder.disabled = chooseFiles.disabled = false;
    chooseFiles.focus();
  } catch {
    if (deliveryDialog.open && draft === next) showDeliveryError("Não foi possível carregar as opções de envio.");
  }
}

deliverySector.addEventListener("change", () => {
  fillOptions(deliveryKind, draft?.catalog[deliverySector.value] || []);
  updateDeliveryPreview();
});
deliveryForm.addEventListener("input", updateDeliveryPreview);
periodShortcuts.forEach(button => button.addEventListener("click", () => {
  const period = draft?.periods[button.dataset.period];
  if (period) {
    deliveryPeriod.value = period;
    if (draft.appliedSuggestion) draft.appliedSuggestion.period = null;
    updateDeliveryPreview();
  }
}));
async function chooseDeliveryItems(folder) {
  if (!draft || choosingFiles) return;
  const active = draft;
  choosingFiles = chooseFolder.disabled = chooseFiles.disabled = true;
  deliveryError.hidden = true;
  updateDeliveryPreview();
  try {
    const result = folder ? await api().choose_delivery_folder() : await api().choose_delivery_files();
    if (!deliveryDialog.open || draft !== active) return;
    if (!result.ok) return showDeliveryError(result.error);
    if (result.cancelled) return;
    active.files = result.files;
    renderDeliveryFiles(active.files);
    const previous = active.appliedSuggestion;
    if (previous && previous.sector === deliverySector.value && previous.kind === deliveryKind.value
        && previous.period === deliveryPeriod.value) {
      deliverySector.value = "";
      fillOptions(deliveryKind, []);
      deliveryPeriod.value = "";
    }
    active.appliedSuggestion = null;
    const suggest = result.suggestion && !deliverySector.value && !deliveryKind.value;
    const hint = document.querySelector("#delivery-suggestion");
    if (suggest) {
      const { sector, kind, period } = result.suggestion;
      deliverySector.value = sector;
      fillOptions(deliveryKind, active.catalog[sector] || []);
      deliveryKind.value = kind || "";
      if (!deliveryPeriod.value && period) deliveryPeriod.value = period;
      active.appliedSuggestion = { sector, kind: deliveryKind.value, period: period || "" };
      hint.textContent = kind ? "Confira o destino sugerido antes de enviar."
        : "Confira os campos sugeridos e selecione o tipo de documento.";
    }
    const different = result.suggestion && !suggest && (result.suggestion.sector !== deliverySector.value
      || (result.suggestion.kind && result.suggestion.kind !== deliveryKind.value));
    if (different) {
      const { sector, kind } = result.suggestion;
      hint.textContent = `Os itens sugerem ${kind ? `${sector} / ${kind}` : sector}. Confira o destino selecionado.`;
    }
    hint.hidden = !(suggest || different);
  } catch {
    if (draft === active) showDeliveryError(folder ? "Não foi possível selecionar a pasta." : "Não foi possível selecionar os arquivos.");
  } finally {
    choosingFiles = false;
    if (deliveryDialog.open && draft === active) {
      chooseFolder.disabled = chooseFiles.disabled = false;
      updateDeliveryPreview();
    }
  }
}
chooseFiles.addEventListener("click", () => chooseDeliveryItems(false));
chooseFolder.addEventListener("click", () => chooseDeliveryItems(true));
deliveryForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (state.busy || deliverySubmit.disabled || !draft || !deliveryForm.reportValidity()) return;
  const { company } = draft;
  const payload = { sector: deliverySector.value, kind: deliveryKind.value, period: deliveryPeriod.value };
  const operation = ++state.navigationSeq;
  deliveryDialog.close();
  setBusy(true, "Preparando envio", "Conectando ao SharePoint e conferindo o destino…");
  await nextPaint();
  if (operation !== state.navigationSeq) return;
  try {
    const result = await api().begin_delivery(company.code, payload);
    if (operation !== state.navigationSeq || result.ok) return;
    setBusy(false);
    deliveryDialog.showModal();
    showDeliveryError(result.error);
  } catch {
    if (operation !== state.navigationSeq) return;
    setBusy(false);
    deliveryDialog.showModal();
    showDeliveryError("Não foi possível iniciar o envio.");
  }
});
document.querySelectorAll("[data-close]").forEach(button => button.addEventListener("click", () => {
  document.getElementById(button.dataset.close).close();
}));

async function checkReceiptFolder(receiptId) {
  if (!api() || state.busy) return;
  historyDialog.close();
  const operation = ++state.navigationSeq;
  setBusy(true);
  await nextPaint();
  if (operation !== state.navigationSeq) return;
  try {
    const result = await api().open_delivery_folder(receiptId);
    if (operation !== state.navigationSeq || result.ok) return;
    setBusy(false);
    notify(result.error, true);
  } catch {
    if (operation !== state.navigationSeq) return;
    setBusy(false);
    notify("Não foi possível abrir a pasta do histórico.", true);
  }
}

function receiptRow(receipt) {
  const labels = { sent: "Enviado", failed: "Falhou", uncertain: "A confirmar" };
  const row = document.createElement("li");
  const filename = document.createElement("strong");
  const status = document.createElement("span");
  filename.textContent = receipt.filename;
  status.className = `receipt-status ${receipt.status}`;
  status.textContent = labels[receipt.status] || labels.uncertain;
  row.append(filename, status);
  if (receipt.detail) {
    const detail = document.createElement("small");
    detail.className = "receipt-detail";
    detail.textContent = receipt.detail;
    row.append(detail);
  }
  return row;
}

function showDeliveryResult(notice) {
  document.querySelector("#delivery-result-summary").textContent = notice.message;
  document.querySelector("#delivery-result-list").replaceChildren(...notice.deliveryIssues.map(receiptRow));
  document.querySelector("#delivery-result").showModal();
}

document.querySelector("#open-history").addEventListener("click", async () => {
  if (historyDialog.open) return;
  const list = document.querySelector("#history-list");
  const message = document.querySelector("#history-message");
  list.replaceChildren();
  message.textContent = "Carregando histórico…";
  historyDialog.showModal();
  try {
    const result = await api()?.recent_deliveries();
    if (!result?.ok) throw Error();
    message.textContent = result.receipts.length ? "" : "Nenhum envio registrado neste computador.";
    list.replaceChildren(...result.receipts.map(receipt => {
      const row = receiptRow(receipt);
      const details = document.createElement("small");
      details.textContent = [receipt.company, receipt.destination, new Date(receipt.recorded_at).toLocaleString("pt-BR")].join(" · ");
      row.append(details);
      if (receipt.status !== "sent" && receipt.canOpen && Number.isInteger(receipt.id)) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "text-button receipt-folder";
        button.textContent = "Conferir pasta";
        button.addEventListener("click", () => checkReceiptFolder(receipt.id));
        row.append(button);
      }
      return row;
    }));
  } catch {
    message.textContent = "Não foi possível carregar o histórico. Feche e tente novamente.";
  }
});

function startUpdateStatusPolling() {
  if (updateStatusTimer !== null || !canReadUpdateStatus()) return;
  refreshUpdateStatus();
  updateStatusTimer = window.setInterval(refreshUpdateStatus, 30000);
}

window.addEventListener('pagehide', () => {
  homeDocumentActive = false;
  window.clearInterval(updateStatusTimer);
  updateStatusTimer = null;
});
window.addEventListener('pageshow', () => {
  homeDocumentActive = true;
  startUpdateStatusPolling();
});
dialog.addEventListener("cancel", () => { form.reset(); formError.hidden = true; });
async function initializeApp() {
  if (state.initialized || state.initializing || !api()) return;
  startUpdateStatusPolling();
  state.initializing = true;
  try {
    state.initialized = await loadCompanies();
    if (state.initialized) window.clearInterval(apiWaitTimer);
  } finally {
    state.initializing = false;
  }
}

window.addEventListener("pywebviewready", initializeApp);
const apiWaitTimer = window.setInterval(() => {
  initializeApp();
}, 500);
window.setTimeout(() => {
  if (!state.initialized) {
    window.clearInterval(apiWaitTimer);
    showLoadError('Não foi possível conectar ao aplicativo. Use Recarregar lista para tentar novamente.');
  }
}, 15000);
if (new URLSearchParams(window.location.search).has("preview")) {
  state.initialized = true;
  window.clearInterval(apiWaitTimer);
  state.companies = [
    { code: "0000", name: "Empresa de demonstração", url: "https://tenant.sharepoint.com/example", hasCredential: true },
    { code: "1024", name: "Comercial Horizonte", url: "https://tenant.sharepoint.com/example", hasCredential: true },
    { code: "2048", name: "Grupo Contábil Aurora", url: "https://tenant.sharepoint.com/example", hasCredential: false },
  ];
  render();
}
