"""AppKit chrome shown outside the SharePoint document."""
import AppKit as AK
import objc


class AcmaisActionTarget(AK.NSObject):
    @objc.signature(b"v@:@")
    def invoke_(self, sender):
        self.action(sender)


class CocoaControls:
    BAR_HEIGHT = 48

    def __init__(self, browser, return_home, open_external, select_company):
        self._web = browser.webview
        frame = browser.window.contentView().bounds()
        self._root = AK.NSView.alloc().initWithFrame_(frame)
        self._root.setWantsLayer_(True)
        self._root.layer().setBackgroundColor_(AK.NSColor.windowBackgroundColor().CGColor())
        browser.window.setContentView_(self._root)
        self._root.addSubview_(self._web)
        self._web.setAutoresizingMask_(AK.NSViewWidthSizable | AK.NSViewHeightSizable)
        self._targets = []
        self._codes = []
        self._current = None

        self._selector = AK.NSPopUpButton.alloc().initWithFrame_pullsDown_(AK.NSZeroRect, False)
        self._selector.widthAnchor().constraintLessThanOrEqualToConstant_(390).setActive_(True)
        self._bind(self._selector, lambda sender: self._select(sender, select_company))
        self._bar = self._stack([
            self._button("Empresas", return_home),
            self._selector,
            self._button("Abrir no navegador", open_external),
        ])
        self._bar.centerXAnchor().constraintEqualToAnchor_(self._root.centerXAnchor()).setActive_(True)
        self._bar.topAnchor().constraintEqualToAnchor_constant_(self._root.topAnchor(), 10).setActive_(True)
        self._bar.leadingAnchor().constraintGreaterThanOrEqualToAnchor_constant_(self._root.leadingAnchor(), 8).setActive_(True)
        self._bar.trailingAnchor().constraintLessThanOrEqualToAnchor_constant_(self._root.trailingAnchor(), -8).setActive_(True)

        self._title = AK.NSTextField.labelWithString_("")
        self._title.setFont_(AK.NSFont.boldSystemFontOfSize_(17))
        self._detail = AK.NSTextField.labelWithString_("")
        self._progress = AK.NSProgressIndicator.alloc().initWithFrame_(AK.NSZeroRect)
        self._progress.setMaxValue_(1.0)
        self._progress.setUsesThreadedAnimation_(True)
        self._progress.widthAnchor().constraintEqualToConstant_(240).setActive_(True)
        self._cancel = self._button("Cancelar", return_home)
        self._cover = self._stack([self._title, self._detail, self._progress, self._cancel], vertical=True)
        self._cover.centerXAnchor().constraintEqualToAnchor_(self._root.centerXAnchor()).setActive_(True)
        self._cover.centerYAnchor().constraintEqualToAnchor_(self._root.centerYAnchor()).setActive_(True)

    def _stack(self, views, *, vertical=False):
        stack = AK.NSStackView.stackViewWithViews_(views)
        stack.setOrientation_(AK.NSUserInterfaceLayoutOrientationVertical if vertical
                              else AK.NSUserInterfaceLayoutOrientationHorizontal)
        stack.setSpacing_(12)
        stack.setTranslatesAutoresizingMaskIntoConstraints_(False)
        self._root.addSubview_(stack)
        return stack

    def _bind(self, button, action):
        target = AcmaisActionTarget.new()
        target.action = action
        self._targets.append(target)
        button.setTarget_(target)
        button.setAction_("invoke:")

    def _button(self, title, action):
        button = AK.NSButton.buttonWithTitle_target_action_(title, None, None)
        self._bind(button, lambda _sender: action())
        return button

    def _select(self, sender, select_company):
        index = sender.indexOfSelectedItem()
        if 0 <= index < len(self._codes) and self._codes[index] != self._current:
            select_company(self._codes[index])

    def set_choices(self, choices, current):
        self._current = current
        self._codes = [item["code"] for item in choices]
        self._selector.removeAllItems()
        for item in choices:
            self._selector.addItemWithTitle_(f"{item['code']} - {item['name']}")
        if current in self._codes:
            self._selector.selectItemAtIndex_(self._codes.index(current))

    def _show_web(self, toolbar):
        self._progress.stopAnimation_(None)
        self._cover.setHidden_(True)
        self._bar.setHidden_(not toolbar)
        frame = self._root.bounds()
        height = frame.size.height - (self.BAR_HEIGHT if toolbar else 0)
        self._web.setFrame_(AK.NSMakeRect(0, 0, frame.size.width, max(0, height)))
        self._web.setHidden_(False)

    def show_home(self):
        self._show_web(False)

    def show_folder(self, _label):
        self._show_web(True)
        return True

    def show_loading(self, title, detail, cancel):
        self._web.setHidden_(True)
        self._bar.setHidden_(True)
        self._title.setStringValue_(title)
        self._cancel.setTitle_(cancel)
        self._cover.setHidden_(False)
        self.update_loading(detail, None)
        self._root.window().makeFirstResponder_(self._cancel)
        return True

    def update_loading(self, detail, fraction):
        self._detail.setStringValue_(detail)
        if fraction is None:
            self._progress.setIndeterminate_(True)
            self._progress.startAnimation_(None)
        else:
            self._progress.stopAnimation_(None)
            self._progress.setIndeterminate_(False)
            self._progress.setDoubleValue_(fraction)
