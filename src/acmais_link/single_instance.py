from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes


MUTEX_NAME = "Local\\ACMAIS_LINK_SingleInstance"
INSTALLER_MUTEX_NAME = "Local\\ACMAIS_LINK_Installer"
WINDOW_TITLE_PREFIX = "ACMAIS LINK"


class SingleInstance:
    """Own a Windows mutex and focus the existing app on duplicate launch."""

    def __init__(self) -> None:
        self._handle: int | None = None

    def acquire(self) -> bool:
        if sys.platform != "win32":
            return True
        if self._try_acquire_mutex():
            return True
        if not self._installer_running():
            if self._focus_existing_window():
                return False
            # The other process may have exited while we looked for its window.
            return self._try_acquire_mutex()
        # A silent installation owns the app mutex for the file swap. Keep a
        # quick relaunch alive until it completes instead of losing the launch.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self._focus_existing_window(attempts=1):
                return False
            time.sleep(0.1)
            if self._try_acquire_mutex():
                return True
        return False

    def _try_acquire_mutex(self) -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    @staticmethod
    def _installer_running() -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.OpenMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenMutexW(0x100000, False, INSTALLER_MUTEX_NAME)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False

    def close(self) -> None:
        if sys.platform == "win32" and self._handle:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.CloseHandle(self._handle)
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
