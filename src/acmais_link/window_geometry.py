from __future__ import annotations

import ctypes
import logging
import math
import sys
from ctypes import wintypes
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkArea:
    """Primary monitor's available rectangle in physical pixels."""

    left: int
    top: int
    width: int
    height: int
    scale: float


@dataclass(frozen=True)
class WindowGeometry:
    """Outer window bounds in the logical pixels expected by pywebview."""

    width: int
    height: int
    min_size: tuple[int, int]
    x: int | None = None
    y: int | None = None
    maximized: bool = False


def fit_window_to_work_area(area: WorkArea) -> WindowGeometry:
    if area.width <= 0 or area.height <= 0 or not math.isfinite(area.scale) or area.scale <= 0:
        raise ValueError("Invalid display work area or scale")

    # Round inward: WinForms later multiplies these values by DPI / 96.
    left = math.ceil(area.left / area.scale)
    top = math.ceil(area.top / area.scale)
    available_width = math.floor((area.left + area.width) / area.scale) - left
    available_height = math.floor((area.top + area.height) / area.scale) - top
    if available_width <= 0 or available_height <= 0:
        raise ValueError("Display work area is too small")

    # Leave some desktop visible, but do not enforce margins on a tiny display.
    width = min(1080, max(1, available_width - min(32, available_width // 10)))
    height = min(720, max(1, available_height - min(32, available_height // 10)))
    return WindowGeometry(
        width=width,
        height=height,
        min_size=(min(480, width), min(360, height)),
        x=left + (available_width - width) // 2,
        y=top + (available_height - height) // 2,
    )


def _windows_work_area() -> WorkArea:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetProcessDPIAware.argtypes = ()
    user32.SetProcessDPIAware.restype = wintypes.BOOL
    # The pywebview WinForms backend makes the same declaration. Do it before
    # measuring, so the query and the eventual window use identical DPI units.
    # False is harmless if the executable manifest already declared awareness.
    user32.SetProcessDPIAware()

    user32.SystemParametersInfoW.argtypes = (
        wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT,
    )
    user32.SystemParametersInfoW.restype = wintypes.BOOL
    rectangle = wintypes.RECT()
    if not user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rectangle), 0):
        raise ctypes.WinError(ctypes.get_last_error())

    user32.GetDpiForSystem.argtypes = ()
    user32.GetDpiForSystem.restype = wintypes.UINT
    dpi = user32.GetDpiForSystem()
    if not dpi:
        raise OSError("Windows did not return the system DPI")
    return WorkArea(
        left=rectangle.left,
        top=rectangle.top,
        width=rectangle.right - rectangle.left,
        height=rectangle.bottom - rectangle.top,
        scale=dpi / 96,
    )


def initial_window_geometry() -> WindowGeometry:
    """Fit the initial Windows window without changing desktop settings."""
    if sys.platform == "win32":
        try:
            return fit_window_to_work_area(_windows_work_area())
        except (AttributeError, OSError, TypeError, ValueError):
            logging.getLogger(__name__).warning(
                "Não foi possível consultar a área útil; iniciando maximizado."
            )
    # Let the window manager fit an unknown display rather than risk starting
    # outside it when display APIs are unavailable (e.g. a remote-session race).
    return WindowGeometry(960, 640, (320, 240), maximized=True)
