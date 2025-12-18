"""테마/스킨 시스템"""

from dataclasses import dataclass
from typing import Optional

import flet as ft


@dataclass
class AppTheme:
    """앱 테마 정의"""

    name: str
    display_name: str
    is_dark: bool

    # 기본 색상
    seed_color: str
    primary: str
    accent: str

    # 배경
    background: str
    surface: str
    card_bg: str

    # 텍스트
    text_primary: str
    text_secondary: str
    text_muted: str

    # 상태 색상
    success: str
    warning: str
    error: str
    info: str

    # 보더/구분선
    border: str
    divider: str


# 프리셋 테마들
THEMES: dict[str, AppTheme] = {
    "purple-night": AppTheme(
        name="purple-night",
        display_name="Purple Night",
        is_dark=True,
        seed_color="#9C27B0",
        primary="#BB86FC",
        accent="#03DAC6",
        background="#121212",
        surface="#1E1E1E",
        card_bg="#2D2040",
        text_primary="#FFFFFF",
        text_secondary="#B3B3B3",
        text_muted="#666666",
        success="#4CAF50",
        warning="#FF9800",
        error="#CF6679",
        info="#2196F3",
        border="#3D3D3D",
        divider="#2D2D2D",
    ),
    "ocean": AppTheme(
        name="ocean",
        display_name="Ocean",
        is_dark=True,
        seed_color="#00BCD4",
        primary="#00BCD4",
        accent="#FF4081",
        background="#0A1929",
        surface="#0D2137",
        card_bg="#132F4C",
        text_primary="#FFFFFF",
        text_secondary="#B2BAC2",
        text_muted="#5A6A7A",
        success="#66BB6A",
        warning="#FFA726",
        error="#F44336",
        info="#29B6F6",
        border="#1E4976",
        divider="#173A5E",
    ),
    "github-dark": AppTheme(
        name="github-dark",
        display_name="GitHub Dark",
        is_dark=True,
        seed_color="#58A6FF",
        primary="#58A6FF",
        accent="#F78166",
        background="#0D1117",
        surface="#161B22",
        card_bg="#21262D",
        text_primary="#C9D1D9",
        text_secondary="#8B949E",
        text_muted="#484F58",
        success="#3FB950",
        warning="#D29922",
        error="#F85149",
        info="#58A6FF",
        border="#30363D",
        divider="#21262D",
    ),
    "rose": AppTheme(
        name="rose",
        display_name="Rose",
        is_dark=True,
        seed_color="#E91E63",
        primary="#F48FB1",
        accent="#80DEEA",
        background="#1A1A1A",
        surface="#242424",
        card_bg="#2E1F2F",
        text_primary="#FFFFFF",
        text_secondary="#BDBDBD",
        text_muted="#757575",
        success="#81C784",
        warning="#FFB74D",
        error="#E57373",
        info="#64B5F6",
        border="#3D2E3E",
        divider="#2D2D2D",
    ),
    "minimal-light": AppTheme(
        name="minimal-light",
        display_name="Minimal Light",
        is_dark=False,
        seed_color="#1976D2",
        primary="#1976D2",
        accent="#FF5722",
        background="#FAFAFA",
        surface="#FFFFFF",
        card_bg="#F5F5F5",
        text_primary="#212121",
        text_secondary="#666666",
        text_muted="#9E9E9E",
        success="#4CAF50",
        warning="#FF9800",
        error="#F44336",
        info="#2196F3",
        border="#E0E0E0",
        divider="#EEEEEE",
    ),
}

DEFAULT_THEME = "purple-night"


def get_theme(name: str) -> AppTheme:
    """테마 가져오기"""
    return THEMES.get(name, THEMES[DEFAULT_THEME])


def apply_theme(page: ft.Page, theme: AppTheme) -> None:
    """페이지에 테마 적용"""
    page.theme_mode = ft.ThemeMode.DARK if theme.is_dark else ft.ThemeMode.LIGHT

    color_scheme = ft.ColorScheme(
        primary=theme.primary,
        secondary=theme.accent,
        surface=theme.surface,
        background=theme.background,
        error=theme.error,
        on_primary=theme.text_primary if theme.is_dark else "#FFFFFF",
        on_secondary=theme.text_primary,
        on_surface=theme.text_primary,
        on_background=theme.text_primary,
        on_error="#FFFFFF",
        surface_variant=theme.card_bg,
        outline=theme.border,
        outline_variant=theme.divider,
    )

    page.theme = ft.Theme(
        color_scheme_seed=theme.seed_color,
        color_scheme=color_scheme,
    )

    page.bgcolor = theme.background
    page.update()


def get_status_color(theme: AppTheme, status: str) -> str:
    """상태에 따른 색상 반환"""
    colors = {
        "pending": theme.text_muted,
        "running": theme.info,
        "paused": theme.warning,
        "completed": theme.success,
        "error": theme.error,
        "cancelled": theme.text_muted,
    }
    return colors.get(status, theme.text_muted)


def get_status_icon(status: str) -> str:
    """상태에 따른 아이콘 반환"""
    icons = {
        "pending": "hourglass_empty",
        "running": "sync",
        "paused": "pause_circle",
        "completed": "check_circle",
        "error": "error",
        "cancelled": "cancel",
    }
    return icons.get(status, "help")
