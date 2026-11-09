from __future__ import annotations

from ui.typography import (
    DEFAULT_FONT_SIZE,
    FONT_SIZE_CHOICES,
    current_font_size,
    font_scale,
    normalize_font_size,
    scale_stylesheet,
    scaled_point_size,
    set_current_font_size,
)


def test_font_size_preferences_are_bounded_to_clear_modes():
    assert FONT_SIZE_CHOICES == (11, 13, 15, 17)
    assert normalize_font_size(13) == 13
    assert normalize_font_size(14) == 13
    assert normalize_font_size(16.8) == 17
    assert normalize_font_size(99) == 17
    assert normalize_font_size("not a size") == DEFAULT_FONT_SIZE


def test_font_scaling_preserves_a_standard_default_and_scales_large_text():
    try:
        assert font_scale(13) == 1.0
        assert scaled_point_size(12, 13) == 12
        assert font_scale(17) > 1.3
        assert scaled_point_size(12, 17) == 16
    finally:
        set_current_font_size(DEFAULT_FONT_SIZE)
    assert current_font_size() == DEFAULT_FONT_SIZE


def test_stylesheet_scaling_changes_type_and_control_height_only():
    qss = (
        "QLabel { font-size: 13px; color: #fff; }\n"
        "QPushButton { min-height: 38px; border: 1px solid #000; }"
    )
    scaled = scale_stylesheet(qss, 17)
    assert "font-size: 17px" in scaled
    assert "min-height: 50px" in scaled
    assert "color: #fff" in scaled
    assert "border: 1px solid #000" in scaled
    assert scale_stylesheet(qss, 13) == qss
