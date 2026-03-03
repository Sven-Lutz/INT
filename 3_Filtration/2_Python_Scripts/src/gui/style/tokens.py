from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Mapping

@dataclass(frozen=True)
class ThemeTokens:
    bg0: str; bg1: str; bg2: str; bg3: str
    text0: str; text1: str; text2: str
    accent: str; good: str; bad: str; warn: str; border: str
    r_sm: int; r_md: int; r_lg: int
    s1: int; s2: int; s3: int; s4: int
    fs_title: int; fs_section: int; fs_label: int; fs_value: int; fs_hint: int; fs_chip: int

def industrial_dark_v2() -> ThemeTokens:
    # "High-Tech Chroma" Theme
    return ThemeTokens(
        bg0="#090B10",  # Very deep midnight blue/black
        bg1="#111520",  # Panels
        bg2="#1A202C",  # Elevated Cards
        bg3="#0F141E",  # Inputs

        text0="#F8FAFC",  # Bright white
        text1="#94A3B8",  # Silver
        text2="#64748B",  # Muted grey

        accent="#00E5FF",  # Neon Cyan
        good="#00E676",    # Neon Green
        bad="#FF1744",     # Neon Red/Pink
        warn="#FF9100",    # Neon Orange/Amber

        border="#2D3748",  # Soft border

        r_sm=4, r_md=8, r_lg=12,  # Slightly sharper corners
        s1=6, s2=10, s3=12, s4=16,
        fs_title=14, fs_section=13, fs_label=12, fs_value=14, fs_hint=11, fs_chip=11,
    )

def industrial_light() -> ThemeTokens:
    return ThemeTokens(
        bg0="#F9FAFB", bg1="#F3F4F6", bg2="#FFFFFF", bg3="#E5E7EB",
        text0="#111827", text1="#4B5563", text2="#9CA3AF",
        accent="#0284C7", good="#059669", bad="#DC2626", warn="#D97706",
        border="#D1D5DB", r_sm=6, r_md=12, r_lg=16,
        s1=6, s2=10, s3=12, s4=16,
        fs_title=14, fs_section=13, fs_label=12, fs_value=14, fs_hint=11, fs_chip=11,
    )

_DARK = industrial_dark_v2()
_LIGHT = industrial_light()

THEMES: Dict[str, Mapping[str, str]] = {
    "dark": {k: getattr(_DARK, k) for k in _DARK.__annotations__ if isinstance(getattr(_DARK, k), str)},
    "light": {k: getattr(_LIGHT, k) for k in _LIGHT.__annotations__ if isinstance(getattr(_LIGHT, k), str)},
}