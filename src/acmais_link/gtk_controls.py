"""GTK chrome shown outside the SharePoint document."""
from gi.repository import Gtk, Pango


class GtkControls:
    def __init__(self, browser, return_home, open_external, select_company):
        self._web = browser.window.get_child()
        browser.window.remove(self._web)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        browser.window.add(root)

        self._bar = Gtk.Box(spacing=8, margin=8)
        self._button(self._bar, "Empresas", return_home)
        self._selector = Gtk.ComboBoxText()
        self._selector.set_hexpand(True)
        for cell in self._selector.get_cells():
            cell.set_property("ellipsize", Pango.EllipsizeMode.END)
        self._bar.pack_start(self._selector, True, True, 0)
        self._change = self._selector.connect("changed", self._changed, select_company)
        self._button(self._bar, "Abrir no navegador", open_external)

        self._cover = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                              halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self._title = Gtk.Label()
        self._detail = Gtk.Label(wrap=True)
        self._spinner = Gtk.Spinner()
        self._progress = Gtk.ProgressBar()
        self._cancel = self._button(self._cover, "Cancelar", return_home, pack=False)
        for widget in (self._title, self._detail, self._spinner, self._progress, self._cancel):
            self._cover.pack_start(widget, False, False, 0)

        root.pack_start(self._bar, False, False, 0)
        root.pack_start(self._web, True, True, 0)
        root.pack_start(self._cover, True, True, 0)
        root.show()

    @staticmethod
    def _button(box, text, action, *, pack=True):
        button = Gtk.Button(label=text)
        button.connect("clicked", lambda _widget: action())
        if pack:
            box.pack_start(button, False, False, 0)
        return button

    @staticmethod
    def _changed(selector, select_company):
        code = selector.get_active_id()
        if code is not None:
            select_company(code)

    def set_choices(self, choices, current):
        with self._selector.handler_block(self._change):
            self._selector.remove_all()
            for item in choices:
                self._selector.append(item["code"], f"{item['code']} - {item['name']}")
            self._selector.set_active_id(current)

    def show_loading(self, title, detail, cancel):
        self._bar.hide()
        self._web.hide()
        self._title.set_text(title)
        self._cancel.set_label(cancel)
        self._cover.show_all()
        self.update_loading(detail, None)
        self._cancel.grab_focus()
        return True

    def update_loading(self, detail, fraction):
        self._detail.set_text(detail)
        if fraction is None:
            self._progress.hide()
            self._spinner.show()
            self._spinner.start()
        else:
            self._spinner.stop()
            self._spinner.hide()
            self._progress.set_fraction(fraction)
            self._progress.show()

    def show_home(self):
        self._spinner.stop()
        self._cover.hide()
        self._bar.hide()
        self._web.show()

    def show_folder(self, _label):
        self.show_home()
        self._bar.show_all()
        return True
