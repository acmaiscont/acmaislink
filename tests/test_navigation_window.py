import sys
import types
import unittest
from unittest.mock import Mock, patch

from acmais_link.navigation_window import NavigationWindow


class Generic:
    def __getitem__(self, _):
        return lambda callback: callback


class TaskResult:
    def __init__(self, value='null', error=None, complete=True):
        self.value, self.error, self.complete = value, error, complete

    @property
    def Result(self):
        if self.error:
            raise self.error
        return self.value

    def ContinueWith(self, callback):
        if self.complete:
            callback(self)


class NavigationWindowTests(unittest.TestCase):
    def setUp(self):
        self.core = Mock()
        self.raw = Mock()
        self.raw.native.webview.CoreWebView2 = self.core
        self.window = NavigationWindow(self.raw, Mock(), Mock())
        self.window._post = lambda callback: callback()
        system = types.ModuleType('System')
        system.Action, system.String = Generic(), str
        tasks = types.ModuleType('System.Threading.Tasks')
        tasks.Task = Generic()
        patched = patch.dict(sys.modules, {'System': system, 'System.Threading.Tasks': tasks})
        patched.start()
        self.addCleanup(patched.stop)

    def test_read_never_depends_on_pywebview_bridge_or_loaded_event(self):
        self.core.ExecuteScriptAsync.return_value = TaskResult('{"heading":"0000 - Teste","ready":true}')
        self.assertEqual(self.window.evaluate_js('snapshot()')['heading'], '0000 - Teste')
        self.raw.evaluate_js.assert_not_called()
        self.core.ExecuteScriptAsync.assert_called_once_with('snapshot()')

    def test_null_during_redirect_is_not_parsed_as_a_folder(self):
        self.core.ExecuteScriptAsync.return_value = TaskResult()
        self.assertIsNone(self.window.evaluate_js('snapshot()'))

    def test_cancelled_operation_cannot_inject_a_queued_password(self):
        self.assertIsNone(self.window.evaluate_navigation_js('password()', lambda: False))
        self.core.ExecuteScriptAsync.assert_not_called()

    def test_cancelled_navigation_does_not_load_an_old_document(self):
        self.assertFalse(self.window.navigate('https://tenant.sharepoint.com/old', lambda: False))
        self.raw.load_url.assert_not_called()

    def test_navigation_guard_is_checked_when_ui_callback_runs(self):
        current = True
        def dispatch(callback):
            nonlocal current
            current = False  # Cancelled after worker queued, before UI executes.
            return callback()
        self.window._on_ui = dispatch
        self.assertFalse(self.window.navigate('https://tenant.sharepoint.com/old', lambda: current))
        self.raw.load_url.assert_not_called()

    def test_current_navigation_preserves_framework_url_resolution(self):
        self.assertTrue(self.window.navigate('file:///home/index.html', lambda: True))
        self.raw.load_url.assert_called_once_with('file:///home/index.html')

    def test_native_task_failure_and_malformed_result_release_waiter(self):
        for task in (TaskResult(error=RuntimeError('disposed')), TaskResult('{')):
            with self.subTest(task=task):
                self.core.ExecuteScriptAsync.return_value = task
                with self.assertRaises((RuntimeError, ValueError)):
                    self.window.evaluate_js('snapshot()', timeout=.01)

    def test_never_waits_forever_for_a_native_script(self):
        self.core.ExecuteScriptAsync.return_value = TaskResult(complete=False)
        with self.assertRaises(TimeoutError):
            self.window.evaluate_js('snapshot()', timeout=.01)

    def test_expired_queued_script_is_not_executed_later(self):
        queue = []
        self.window._post = queue.append
        with self.assertRaises(TimeoutError):
            self.window.evaluate_js('password()', timeout=.01)
        queue[0]()
        self.core.ExecuteScriptAsync.assert_not_called()

    def test_expired_queued_ui_action_is_not_executed_later(self):
        queue, action = [], Mock()
        self.window._post = queue.append
        with self.assertRaises(TimeoutError):
            self.window._on_ui(action, timeout=.01)
        queue[0]()
        action.assert_not_called()

    def test_stale_native_controls_cannot_cover_a_new_navigation(self):
        self.window._create_controls = Mock()
        self.assertFalse(self.window.show_loading(lambda: False))
        self.assertFalse(self.window.show_folder('Old company', lambda: False))
        self.assertFalse(self.window.set_company_choices([{'code': '1', 'name': 'Old'}], '1', lambda: False))
        self.window._create_controls.assert_not_called()

    def test_cover_is_painted_before_loading_is_acknowledged(self):
        calls = []
        self.window._create_controls = Mock()
        self.window._cover = Mock()
        self.window._toolbar = Mock()
        self.window._cancel = Mock()
        self.raw.native.PerformLayout.side_effect = lambda: calls.append('form-layout')
        self.window._cover.PerformLayout.side_effect = lambda: calls.append('cover-layout')
        self.window._cover.Refresh.side_effect = lambda: calls.append('paint')
        self.window._cancel.Focus.side_effect = lambda: calls.append('focus-cancel')
        self.assertTrue(self.window.show_loading(lambda: True))
        calls.append('acknowledged')
        self.assertEqual(calls, ['form-layout', 'cover-layout', 'paint', 'focus-cancel', 'acknowledged'])

    def test_cancel_during_paint_does_not_acknowledge_loading(self):
        current = True
        def cancel():
            nonlocal current
            current = False
        self.window._create_controls = Mock()
        self.window._cover, self.window._toolbar = Mock(), Mock()
        self.window._cover.Refresh.side_effect = cancel
        self.assertFalse(self.window.show_loading(lambda: current))

    def test_paint_failure_does_not_acknowledge_loading(self):
        self.window._create_controls = Mock()
        self.window._cover, self.window._toolbar = Mock(), Mock()
        self.window._cover.Refresh.side_effect = RuntimeError('disposed')
        with self.assertRaises(RuntimeError):
            self.window.show_loading(lambda: True)

    def setup_selector(self):
        self.window._create_controls = Mock()
        self.window._selector = Mock()
        self.window._select_company = Mock()
        self.window._background = Mock()
        self.assertTrue(self.window.set_company_choices([
            {'code': '0000', 'name': 'Teste', 'password': 'must-not-appear'},
            {'code': '150', 'name': '\r\nEMPRESA EXEMPLO DE SERVICOS LTDA'},
            {'code': '150', 'name': 'Duplicate'},
            {'code': '', 'name': 'Invalid'},
        ], '0000', lambda: True))

    def test_populating_selector_preserves_codes_and_never_opens_company(self):
        self.setup_selector()
        self.assertEqual(self.window._company_codes, ['0000', '150'])
        self.assertEqual(self.window._selector.SelectedIndex, 0)
        self.assertEqual([call.args[0] for call in self.window._selector.Items.Add.call_args_list], [
            '0000 - Teste', '150 - EMPRESA EXEMPLO DE SERVICOS LTDA',
        ])
        self.window._selector.BeginUpdate.assert_called_once_with()
        self.window._selector.EndUpdate.assert_called_once_with()
        self.window._select_company.assert_not_called()
        self.window._background.assert_not_called()

    def test_committed_company_selection_opens_in_background_once(self):
        self.setup_selector()
        self.window._selector.SelectedIndex = 1
        self.window._company_selection_committed()
        self.assertEqual(self.window._selector.SelectedIndex, 0)
        self.window._select_company.assert_not_called()
        self.window._selector.SelectedIndex = 1
        self.window._company_selection_committed()
        self.window._background.assert_called_once()
        self.window._background.call_args.args[0]()
        self.window._select_company.assert_called_once_with('150')
        self.assertFalse(self.window._selection_pending)

    def test_selecting_same_company_or_no_company_is_noop(self):
        self.setup_selector()
        for index in (0, -1, 3):
            with self.subTest(index=index):
                self.window._selector.SelectedIndex = index
                self.window._company_selection_committed()
        self.window._background.assert_not_called()

    def test_stale_selector_event_cannot_open_company(self):
        self.setup_selector()
        self.window._selector.SelectedIndex = 1
        self.window._choices_current = lambda: False
        self.window._company_selection_committed()
        self.window._background.assert_not_called()

    def test_cancelled_queued_company_selection_cannot_open_company(self):
        self.setup_selector()
        current = True
        self.window._choices_current = lambda: current
        self.window._selector.SelectedIndex = 1
        self.window._company_selection_committed()
        current = False
        self.window._background.call_args.args[0]()
        self.window._select_company.assert_not_called()
        self.assertFalse(self.window._selection_pending)

    def test_selection_callback_failure_releases_pending_flag(self):
        self.setup_selector()
        self.window._selector.SelectedIndex = 1
        self.window._select_company.side_effect = RuntimeError('closed')
        self.window._company_selection_committed()
        with self.assertRaises(RuntimeError):
            self.window._background.call_args.args[0]()
        self.assertFalse(self.window._selection_pending)

    def test_native_cover_removed_on_success_and_home(self):
        self.window._create_controls = Mock()
        self.window._cover = Mock()
        self.window._toolbar = Mock()
        self.window._label = Mock()
        self.assertTrue(self.window.show_loading(lambda: True))
        self.assertTrue(self.window._cover.Visible)
        self.assertTrue(self.window.show_folder('0000 - Teste', lambda: True))
        self.assertFalse(self.window._cover.Visible)
        self.assertTrue(self.window._toolbar.Visible)
        self.raw.native.webview.BringToFront.assert_called_once_with()
        self.assertEqual(self.window._label.Text, '0000 - Teste')
        self.window.show_home(lambda: True)
        self.assertFalse(self.window._toolbar.Visible)
