from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes


MUTEX_NAME = "Local\\ACMAIS_LINK_SingleInstance"
INSTALLER_MUTEX_NAME = "Local\\ACMAIS_LINK_Installer"
RELAUNCH_MUTEX_NAME = MUTEX_NAME + "_Relaunch"
RESTART_REQUEST = MUTEX_NAME + "_RestartRequest"
RESTART_DECLINED = MUTEX_NAME + "_RestartDeclined"
WINDOW_TITLE_PREFIX = "ACMAIS LINK"


class SingleInstance:
    """Hand off startup between processes without running two app windows."""

    def __init__(self) -> None:
        self._handle: int | None = None
        self._events = ()
        self._listener = None
        self._stopping = threading.Event()

    def acquire(self) -> bool:
        if sys.platform != "win32":
            return True
        relaunch = self._create_mutex(RELAUNCH_MUTEX_NAME)
        if not relaunch:
            return False  # Another launcher already owns the handoff.
        try:
            return self._try_acquire_mutex() or self._take_over()
        finally:
            self._close_handle(relaunch)

    def _try_acquire_mutex(self) -> bool:
        self._handle = self._create_mutex(MUTEX_NAME)
        return bool(self._handle)

    @classmethod
    def _create_mutex(cls, name):
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            cls._close_handle(handle)
            return None
        return handle

    @staticmethod
    def _close_handle(handle):
        if handle:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle(handle)

    @classmethod
    def _mutex_exists(cls, name):
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.OpenMutexW.restype = wintypes.HANDLE
        handle = kernel32.OpenMutexW(0x100000, False, name)
        cls._close_handle(handle)
        return bool(handle)

    @staticmethod
    def _event(name, *, create=False, manual=False):
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if create:
            kernel32.CreateEventW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
            kernel32.CreateEventW.restype = wintypes.HANDLE
            return kernel32.CreateEventW(None, manual, False, name)
        kernel32.OpenEventW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.OpenEventW.restype = wintypes.HANDLE
        return kernel32.OpenEventW(0x100002, False, name)  # SYNCHRONIZE | EVENT_MODIFY_STATE

    @staticmethod
    def _signal(handle, *, reset=False):
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        change = kernel32.ResetEvent if reset else kernel32.SetEvent
        change.argtypes = (wintypes.HANDLE,)
        return bool(change(handle))

    @staticmethod
    def _wait(handle, milliseconds):
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        return kernel32.WaitForSingleObject(handle, milliseconds) == 0

    def _take_over(self):
        start = time.monotonic()
        deadline = start + 30
        while time.monotonic() < deadline:
            if self._try_acquire_mutex():
                return True
            request = self._event(RESTART_REQUEST)
            declined = self._event(RESTART_DECLINED)
            try:
                if request and declined:
                    self._focus_existing_window(attempts=1)
                    self._signal(declined, reset=True)
                    if self._signal(request):
                        return self._wait_for_handoff(declined)
            finally:
                self._close_handle(request)
                self._close_handle(declined)
            if time.monotonic() - start >= 2 and not self._mutex_exists(INSTALLER_MUTEX_NAME):
                # Older versions lack the handoff protocol. Give them a moment
                # to exit on their own and bring their window forward if found.
                if self._focus_existing_window(attempts=1):
                    self._inform("Feche a versão já aberta e abra o ACMAIS LINK novamente.")
                    return False
            time.sleep(.1)
        self._inform("O ACMAIS LINK ainda está sendo aberto ou atualizado. Tente novamente em instantes.")
        return False

    def _wait_for_handoff(self, declined):
        while not self._wait(declined, 150):
            if self._try_acquire_mutex():
                return True
        return False

    @staticmethod
    def _inform(message):
        ctypes.windll.user32.MessageBoxW(None, message, "ACMAIS LINK", 0x10030)

    def listen(self, on_restart):
        if sys.platform != "win32":
            return
        request = self._event(RESTART_REQUEST, create=True)
        declined = self._event(RESTART_DECLINED, create=True, manual=True)
        self._events = (request, declined)
        if not request or not declined:
            return

        def listen():
            while not self._stopping.is_set():
                if self._wait(request, 200) and not self._stopping.is_set():
                    try:
                        on_restart()
                    except Exception:
                        self.decline()

        self._listener = threading.Thread(target=listen, daemon=True)
        self._listener.start()

    def decline(self):
        if self._events:
            self._signal(self._events[1])

    def close(self) -> None:
        if sys.platform != "win32":
            return
        self._stopping.set()
        if self._listener is not None:
            self._listener.join()
        for handle in self._events:
            self._close_handle(handle)
        self._events = ()
        self._close_handle(self._handle)
        self._handle = None

    @staticmethod
    def _focus_existing_window(attempts: int = 40) -> bool:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        )
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
        user32.EnumWindows.restype = wintypes.BOOL
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
        user32.AttachThreadInput.restype = wintypes.BOOL
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        target: list[int] = []

        def is_acmais_process(hwnd: int) -> bool:
            process_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            process = kernel32.OpenProcess(0x1000, False, process_id.value)
            if not process:
                return False
            try:
                size = wintypes.DWORD(32768)
                path = ctypes.create_unicode_buffer(size.value)
                if not kernel32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size)):
                    return False
                return os.path.basename(path.value).casefold() == "acmais link.exe"
            finally:
                kernel32.CloseHandle(process)

        def find_window(hwnd: int, _lparam: int) -> bool:
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, len(buffer))
            if buffer.value.startswith(WINDOW_TITLE_PREFIX) and is_acmais_process(hwnd):
                target.append(hwnd)
                return False
            return True

        callback = callback_type(find_window)
        user32.ShowWindowAsync.argtypes = (wintypes.HWND, ctypes.c_int)
        user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wintypes.UINT)
        for action in (user32.BringWindowToTop, user32.SetForegroundWindow, user32.SetActiveWindow, user32.SetFocus):
            action.argtypes = (wintypes.HWND,)
        for _ in range(attempts):
            target.clear()
            user32.EnumWindows(callback, 0)
            if target:
                hwnd = target[0]
                foreground = user32.GetForegroundWindow()
                foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
                target_thread = user32.GetWindowThreadProcessId(hwnd, None)
                current_thread = kernel32.GetCurrentThreadId()
                attached_foreground = bool(
                    foreground_thread and foreground_thread != current_thread
                    and user32.AttachThreadInput(current_thread, foreground_thread, True)
                )
                attached_target = bool(
                    target_thread and target_thread != current_thread
                    and user32.AttachThreadInput(current_thread, target_thread, True)
                )
                try:
                    user32.ShowWindowAsync(hwnd, 9)  # SW_RESTORE also reveals a hidden window
                    # A short TOPMOST toggle reliably raises the window without
                    # leaving it permanently above other applications.
                    flags = 0x0001 | 0x0002 | 0x0040  # NOSIZE | NOMOVE | SHOWWINDOW
                    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, flags)
                    user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, flags)
                    user32.BringWindowToTop(hwnd)
                    user32.SetForegroundWindow(hwnd)
                    user32.SetActiveWindow(hwnd)
                    user32.SetFocus(hwnd)
                finally:
                    if attached_target:
                        user32.AttachThreadInput(current_thread, target_thread, False)
                    if attached_foreground:
                        user32.AttachThreadInput(current_thread, foreground_thread, False)
                return True
            time.sleep(0.1)
        return False
