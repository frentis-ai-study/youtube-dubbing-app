"""Flet 빌드용 엔트리 포인트"""
from dubbing_app.main import main
import flet as ft

ft.app(target=main)
