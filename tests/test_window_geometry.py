import unittest
from unittest.mock import patch

from acmais_link.window_geometry import WorkArea, fit_window_to_work_area, initial_window_geometry


class WindowGeometryTests(unittest.TestCase):
    def assert_fits(self, area, geometry):
        self.assertGreaterEqual(geometry.x * area.scale, area.left)
        self.assertGreaterEqual(geometry.y * area.scale, area.top)
        self.assertLessEqual((geometry.x + geometry.width) * area.scale, area.left + area.width)
        self.assertLessEqual((geometry.y + geometry.height) * area.scale, area.top + area.height)
        self.assertLessEqual(geometry.min_size[0], geometry.width)
        self.assertLessEqual(geometry.min_size[1], geometry.height)

    def test_large_display_keeps_preferred_size(self):
        area = WorkArea(0, 0, 1920, 1040, 1)
        geometry = fit_window_to_work_area(area)
        self.assertEqual((geometry.width, geometry.height), (1080, 720))
        self.assertEqual(geometry.min_size, (480, 360))
        self.assert_fits(area, geometry)

    def test_laptop_and_high_dpi_stay_inside_work_area(self):
        for scale in (1, 1.25, 1.5, 1.75, 2, 2.5):
            with self.subTest(scale=scale):
                area = WorkArea(0, 0, 1366, 728, scale)
                geometry = fit_window_to_work_area(area)
                self.assert_fits(area, geometry)
                self.assertLess(geometry.height * scale, area.height)

    def test_left_or_top_taskbar_preserves_available_origin(self):
        for area in (WorkArea(65, 0, 1301, 768, 1.5), WorkArea(0, 61, 1366, 707, 1.75)):
            with self.subTest(area=area):
                self.assert_fits(area, fit_window_to_work_area(area))

    def test_tiny_display_also_reduces_minimum_size(self):
        area = WorkArea(0, 0, 640, 440, 2)
        geometry = fit_window_to_work_area(area)
        self.assertLess(geometry.min_size[0], 480)
        self.assertLess(geometry.min_size[1], 360)
        self.assert_fits(area, geometry)

    def test_unavailable_display_api_uses_maximized_fallback(self):
        with patch("acmais_link.window_geometry.sys.platform", "win32"), \
             patch("acmais_link.window_geometry._windows_work_area", side_effect=OSError("unavailable")):
            geometry = initial_window_geometry()
        self.assertTrue(geometry.maximized)
        self.assertIsNone(geometry.x)
        self.assertIsNone(geometry.y)
        self.assertEqual(geometry.min_size, (320, 240))

    def test_invalid_display_measurements_use_fallback(self):
        for area in (WorkArea(0, 0, 0, 720, 1), WorkArea(0, 0, 1080, 720, 0),
                     WorkArea(0, 0, 1080, 720, float("nan"))):
            with self.subTest(area=area), patch("acmais_link.window_geometry.sys.platform", "win32"), \
                 patch("acmais_link.window_geometry._windows_work_area", return_value=area):
                self.assertTrue(initial_window_geometry().maximized)


if __name__ == "__main__":
    unittest.main()
