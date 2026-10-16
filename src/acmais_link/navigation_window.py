"""Window-local controls and bounded WebView2 reads, independent of page load.

pywebview.evaluate_js waits for its injected bridge. SharePoint can display a
usable folder long before NavigationCompleted installs that bridge (or replace
it during a redirect). Use the WebView2 API directly for our synchronous DOM
snapshots. Never expose this adapter through js_api.
"""
from __future__ import annotations

import json
import threading


class NavigationWindow:
    def __init__(self, window, return_home, open_external, select_company=None):
        self._window = window
        self._return_home = return_home
        self._open_external = open_external
        self._select_company = select_company
        self._cover = None
        self._toolbar = None
        self._label = None
        self._selector = None
        self._cancel = None
        self._company_codes = []
        self._company_code = None
        self._choices_current = lambda: False
        self._selection_pending = False

    def __getattr__(self, name):
        return getattr(self._window, name)

    def _post(self, callback):
        # All WinForms/WebView2 objects must be accessed on their UI thread.
        from System import Action
        self._window.native.BeginInvoke(Action(callback))

    def _on_ui(self, callback, timeout=3):
        done, expired = threading.Event(), threading.Event()
        result = {}

        def run():
            if expired.is_set():
                return
            try:
                result['value'] = callback()
            except Exception as exc:
                result['error'] = exc
            finally:
                done.set()

        self._post(run)
        if not done.wait(timeout):
            expired.set()
            raise TimeoutError('The window did not respond')
        if 'error' in result:
            raise result['error']
        return result.get('value')

    def evaluate_js(self, script, *, timeout=3, is_current=lambda: True):
        done, expired = threading.Event(), threading.Event()
        result = {}

        def completed(task):
            try:
                result['value'] = json.loads(str(task.Result))
            except Exception as exc:
                result['error'] = exc
            finally:
                done.set()

        def begin():
            if expired.is_set():
                return
            try:
                if not is_current():
                    done.set()
                    return
                from System import Action, String
                from System.Threading.Tasks import Task
                core = self._window.native.webview.CoreWebView2
                if core is None:
                    raise RuntimeError('WebView2 is not ready')
                core.ExecuteScriptAsync(script).ContinueWith(Action[Task[String]](completed))
            except Exception as exc:
                result['error'] = exc
                done.set()

        self._post(begin)
        if not done.wait(timeout):
            expired.set()
            raise TimeoutError('The document did not respond')
        if 'error' in result:
            raise result['error']
        return result.get('value')

    def evaluate_navigation_js(self, script, is_current):
        return self.evaluate_js(script, is_current=is_current)

    def navigate(self, url, is_current):
        def load():
            if not is_current():
                return False
            # Guard and navigation share one UI callback. A newer cancellation
            # either invalidates this callback or is applied after it; an old
            # worker can no longer navigate after the newer page was loaded.
            self._window.load_url(url)
            return True
        return self._on_ui(load)

    @staticmethod
    def _background(callback):
        # Native click handlers may never wait on JS or another UI invocation.
        threading.Thread(target=callback, daemon=True).start()

    def _company_selection_committed(self, *_):
        # SelectionChangeCommitted is user-only: filling the list or restoring
        # its selected item must not navigate. Keep the displayed company until
        # the new operation has presented its loading screen.
        if not self._select_company or self._selection_pending or not self._choices_current():
            return
        index = self._selector.SelectedIndex
        if not 0 <= index < len(self._company_codes):
            return
        code = self._company_codes[index]
        if code == self._company_code:
            return
        self._selector.SelectedIndex = (
            self._company_codes.index(self._company_code)
            if self._company_code in self._company_codes else -1
        )
        self._selection_pending = True
        is_current = self._choices_current

        def select():
            try:
                if is_current():
                    self._select_company(code)
            finally:
                self._selection_pending = False

        self._background(select)

    def set_company_choices(self, choices, current_code, is_current):
        # Only code/name labels enter the native menu; links and credentials
        # remain entirely outside these controls.
        entries, seen = [], set()
        for choice in choices:
            code = str(choice.get('code', '')).strip()
            name = ' '.join(str(choice.get('name', '')).split())
            if code and name and code not in seen:
                entries.append((code, f'{code} - {name}'))
                seen.add(code)

        def populate():
            if not is_current():
                return False
            self._create_controls()
            self._selector.BeginUpdate()
            try:
                self._company_codes = [code for code, _ in entries]
                self._company_code = current_code
                self._choices_current = is_current
                self._selector.Items.Clear()
                for _, label in entries:
                    self._selector.Items.Add(label)
                self._selector.SelectedIndex = (
                    self._company_codes.index(current_code) if current_code in self._company_codes else -1
                )
                self._selector.Enabled = bool(entries) and self._select_company is not None
            finally:
                self._selector.EndUpdate()
            return True

        return self._on_ui(populate)

    def _create_controls(self):
        if self._cover is not None:
            return
        from System.Drawing import Color, ContentAlignment, Font, FontStyle
        from System.Windows.Forms import (
            AnchorStyles, Button, ColumnStyle, ComboBox, ComboBoxStyle, DockStyle,
            FlatStyle, Label, Padding, RowStyle, SizeType, TableLayoutPanel, ToolTip,
        )
        form = self._window.native
        scale = max(1.0, float(form.DeviceDpi) / 96.0)
        px = lambda value: round(value * scale)
        cover = TableLayoutPanel()
        cover.Dock = DockStyle.Fill
        cover.BackColor = Color.FromArgb(247, 248, 250)
        cover.ColumnCount, cover.RowCount = 1, 5
        cover.ColumnStyles.Add(ColumnStyle(SizeType.Percent, 100))
        for size, height in ((SizeType.Percent, 50), (SizeType.AutoSize, 0),
                             (SizeType.AutoSize, 0), (SizeType.AutoSize, 0),
                             (SizeType.Percent, 50)):
            cover.RowStyles.Add(RowStyle(size, height))
        title = Label()
        title.Text = 'Abrindo documentos…'
        title.Font = Font('Segoe UI', 19.0, FontStyle.Bold)
        title.ForeColor = Color.FromArgb(99, 48, 132)
        title.TextAlign, title.Dock = ContentAlignment.MiddleCenter, DockStyle.Fill
        title.AutoSize = True
        title.Margin = Padding(16, 8, 16, 8)
        detail = Label()
        detail.Text = 'Conectando ao SharePoint e validando a pasta.\nVocê pode cancelar a qualquer momento.'
        detail.Font = Font('Segoe UI', 11.0)
        detail.TextAlign, detail.Dock = ContentAlignment.MiddleCenter, DockStyle.Fill
        detail.AutoSize = True
        detail.Margin = Padding(16, 8, 16, 16)
        cancel = Button()
        cancel.Text = 'Cancelar e voltar às empresas'
        cancel.Font = Font('Segoe UI', 11.0)
        cancel.AutoSize = True
        cancel.Anchor = getattr(AnchorStyles, 'None')
        cancel.Padding = Padding(12, 6, 12, 6)
        cancel.Margin = Padding(12)
        cancel.AccessibleName = 'Cancelar abertura e voltar às empresas'
        cancel.Click += lambda *_: self._background(self._return_home)
        cover.Controls.Add(title, 0, 1)
        cover.Controls.Add(detail, 0, 2)
        cover.Controls.Add(cancel, 0, 3)

        toolbar = TableLayoutPanel()
        toolbar.Dock = DockStyle.Top
        toolbar.AutoSize = False
        toolbar.Height = px(46)
        toolbar.BackColor = Color.FromArgb(35, 32, 43)
        toolbar.Padding = Padding(px(8), px(6), px(8), px(6))
        toolbar.ColumnCount, toolbar.RowCount = 3, 1
        toolbar.RowStyles.Add(RowStyle(SizeType.Percent, 100))
        toolbar.ColumnStyles.Add(ColumnStyle(SizeType.Absolute, px(96)))
        toolbar.ColumnStyles.Add(ColumnStyle(SizeType.Percent, 100))
        toolbar.ColumnStyles.Add(ColumnStyle(SizeType.Absolute, px(114)))
        selector = ComboBox()
        selector.DropDownStyle = ComboBoxStyle.DropDownList
        selector.FlatStyle = FlatStyle.Flat
        selector.BackColor = Color.FromArgb(55, 50, 66)
        selector.ForeColor = Color.White
        selector.Font = Font('Segoe UI', 10.0)
        selector.Anchor = AnchorStyles.Left | AnchorStyles.Right
        selector.Margin = Padding(px(8), 0, px(8), 0)
        selector.DropDownWidth = px(540)
        selector.MaxDropDownItems = 12
        selector.IntegralHeight = True
        selector.AccessibleName = 'Selecionar empresa'
        selector.AccessibleDescription = 'Escolha uma empresa cadastrada para abrir seus documentos nesta janela.'
        selector.TabIndex = 1
        selector.SelectionChangeCommitted += self._company_selection_committed
        tooltip = ToolTip()
        tooltip.SetToolTip(selector, 'Selecionar empresa')
        for column, text, callback in ((0, '← Empresas', self._return_home),
                                       (2, 'Navegador ↗', self._open_external)):
            button = Button()
            button.Text, button.Dock = text, DockStyle.Fill
            button.AutoSize = False
            button.Margin = Padding(0)
            button.Padding = Padding(0)
            button.FlatStyle = FlatStyle.Flat
            button.FlatAppearance.BorderSize = 0
            button.FlatAppearance.MouseOverBackColor = Color.FromArgb(69, 59, 84)
            button.FlatAppearance.MouseDownBackColor = Color.FromArgb(89, 65, 110)
            button.UseVisualStyleBackColor = False
            button.BackColor, button.ForeColor = toolbar.BackColor, Color.White
            button.Font = Font('Segoe UI', 9.0)
            button.AccessibleName = 'Voltar às empresas' if column == 0 else 'Abrir documentos no navegador'
            button.TabIndex = column
            tooltip.SetToolTip(button, button.AccessibleName)
            button.Click += lambda *_, action=callback: self._background(action)
            toolbar.Controls.Add(button, column, 0)
        toolbar.Controls.Add(selector, 1, 0)
        cover.Visible = toolbar.Visible = False
        form.Controls.Add(toolbar)
        form.Controls.Add(cover)
        self._cover, self._toolbar, self._label = cover, toolbar, selector
        self._selector, self._cancel, self._tooltip = selector, cancel, tooltip

    def show_loading(self, is_current):
        def show():
            if not is_current():
                return False
            self._create_controls()
            self._toolbar.Visible = False
            self._cover.Visible = True
            self._cover.BringToFront()
            # Refresh paints synchronously, including child controls. Merely
            # setting Visible would acknowledge before Windows displayed the
            # cover, allowing navigation/credential work to overtake feedback.
            self._window.native.PerformLayout()
            self._cover.PerformLayout()
            self._cover.Refresh()
            if self._cancel is not None:
                self._cancel.Focus()
            return bool(is_current())
        return self._on_ui(show)

    def show_folder(self, label, is_current):
        def show():
            if not is_current():
                return False
            self._create_controls()
            self._label.Text = label
            self._cover.Visible = False
            self._toolbar.Visible = True
            self._toolbar.BringToFront()
            # Docking is processed in reverse z-order. The Fill WebView must
            # follow the Top toolbar in layout, otherwise it sits underneath it.
            self._window.native.webview.BringToFront()
            return True
        return self._on_ui(show)

    def show_home(self, is_current):
        def show():
            if is_current() and self._cover is not None:
                self._cover.Visible = self._toolbar.Visible = False
        self._on_ui(show)
