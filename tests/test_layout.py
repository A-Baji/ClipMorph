import unittest

from clipmorph.layout import materialize_generated_captions
from clipmorph.layout import normalize_layout
from clipmorph.layout import validate_layout


class LayoutValidationTests(unittest.TestCase):
    def test_accepts_composable_crop_and_timed_caption(self):
        validate_layout({
            "crop": {
                "enabled": True,
                "source": {"x": 20, "y": 20, "width": 320, "height": 240},
                "sizing": {"mode": "fit", "dimensions": {"width": 320, "height": 240}},
                "composition": {"mode": "overlay", "placement": "top"},
            },
            "captions": {"overlay": {"items": [{
                "text": "Hi", "placement": "bottom", "range": [0, 2],
            }]}},
        }, 1920, 1080, 3)

    def test_rejects_invalid_layout_contracts(self):
        invalid_layouts = [
            {"crop": {"enabled": True, "source": {"x": 1800, "y": 0,
                                                        "width": 320, "height": 240}}},
            {"crop": {"enabled": True, "source": {"x": 0, "y": 0,
                "width": 320, "height": 240}, "sizing": {"mode": "native"},
                "composition": {"mode": "stacked", "placement": {"x": 500, "y": 500}}}},
            {"captions": {"overlay": {"items": [
                {"text": "A", "typography": {"color": 5}},
            ]}}},
            {"captions": {"stacked": {"items": [
                {"text": "A", "range": [0, 2]},
                {"text": "B", "range": [1, 3]},
            ]}}},
        ]
        for layout in invalid_layouts:
            with self.subTest(layout=layout):
                with self.assertRaises(ValueError):
                    validate_layout(layout, 1920, 1080, 4)


class DocumentedLayoutContractTests(unittest.TestCase):
    def test_crop_sizing_and_composition_are_independent(self):
        validate_layout({
            "crop": {
                "enabled": True,
                "source": {"x": 0, "y": 0, "width": 640, "height": 480},
                "sizing": {"mode": "fit", "dimensions": {"width": 400, "height": 300}},
                "composition": {"mode": "overlay", "placement": "center"},
            },
        }, 1920, 1080)

    def test_overlay_coordinates_and_stacked_vertical_placement(self):
        validate_layout({
            "crop": {
                "enabled": True,
                "source": {"x": 0, "y": 0, "width": 640, "height": 480},
                "sizing": {"mode": "native"},
                "composition": {"mode": "overlay", "placement": {"x": 540, "y": 960}},
            },
            "captions": {
                "overlay": {"items": [{
                    "text": "Overlay", "placement": {"x": 540, "y": 1700},
                    "typography": {"size": 48, "color": None},
                }]},
                "stacked": {
                    "placement": {"y": 950},
                    "panel": {"color": "black",
                              "padding": {"left": 24, "top": 12}},
                    "items": [{"text": "Stacked", "range": [0, 2]}],
                },
            },
        }, 1920, 1080, 4)

    def test_rejects_invalid_stacked_overlap_overflow_and_item_layout_fields(self):
        invalid_layouts = [
            {"crop": {"enabled": True, "source": {"x": 0, "y": 0,
                "width": 640, "height": 480}, "sizing": {"mode": "native"},
                "composition": {"mode": "stacked", "placement": {"x": 10, "y": 20}}}},
            {"captions": {"overlay": {"items": [{
                "text": "overflow", "placement": {"x": 1070, "y": 1900},
                "dimensions": {"width": 100, "height": 100}}]}}},
            {"captions": {"stacked": {"items": [
                {"text": "A", "range": [0, 2]},
                {"text": "B", "range": [1, 3]},
            ]}}},
            {"captions": {"overlay": {"items": [{
                "text": "This text cannot fit", "placement": "center",
                "dimensions": {"width": 10, "height": 10},
            }]}}},
            {"captions": {"stacked": {
                "dimensions": {"width": 20, "height": 20},
                "items": [{"text": "This stacked text cannot fit"}],
            }}},
            {"captions": {"stacked": {"items": [{
                "text": "A", "placement": "top"}]}}},
        ]
        for layout in invalid_layouts:
            with self.subTest(layout=layout):
                with self.assertRaises(ValueError):
                    validate_layout(layout, 1920, 1080, 4)

    def test_generated_caption_materialization_replaces_only_generated_items(self):
        initial = normalize_layout({"captions": {"overlay": {"items": [
            {"text": "Authored", "placement": "top"},
        ]}}})
        segments = [{"id": "segment-1", "start": 1, "end": 2,
                     "text": "Generated", "typography": {"size": 40}}]

        first = materialize_generated_captions(initial, "overlay", segments)
        second = materialize_generated_captions(first, "overlay", segments)
        items = second["captions"]["overlay"]["items"]

        self.assertEqual([item["text"] for item in items], ["Authored", "Generated"])
        self.assertEqual(items[1]["transcript_segment_id"], "segment-1")
        self.assertEqual(items[1]["typography"]["size"], 40)


if __name__ == "__main__":
    unittest.main()
