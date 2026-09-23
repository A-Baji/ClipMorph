import unittest

from clipmorph.layout import validate_layout


class LayoutValidationTests(unittest.TestCase):
    def test_accepts_composable_crop_and_timed_caption(self):
        validate_layout({
            "crop": {
                "enabled": True,
                "source": {"x": 20, "y": 20, "width": 320, "height": 240},
                "placement": {"mode": "fit", "region": "top"},
            },
            "caption": {
                "enabled": True,
                "mode": "overlay",
                "region": "bottom",
                "items": [{"text": "Hi", "range": [0, 2]}],
            },
        }, 1920, 1080, 3)

    def test_rejects_invalid_layout_contracts(self):
        invalid_layouts = [
            {"crop": {"enabled": True, "source": {"x": 1800, "y": 0,
                                                        "width": 320, "height": 240}}},
            {"crop": {"enabled": True, "source": {"x": 0, "y": 0,
                                                        "width": 320, "height": 240},
                       "placement": {"mode": "fit", "region": "center"}}},
            {"caption": {"enabled": True, "text": "A", "items": [],
                          "region": "top"}},
            {"caption": {"enabled": True, "items": [
                {"text": "A", "range": [0, 2]},
                {"text": "B", "range": [1, 3]},
            ]}},
        ]
        for layout in invalid_layouts:
            with self.subTest(layout=layout):
                with self.assertRaises(ValueError):
                    validate_layout(layout, 1920, 1080, 4)


if __name__ == "__main__":
    unittest.main()
