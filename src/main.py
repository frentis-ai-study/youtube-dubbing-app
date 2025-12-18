"""Flet 빌드용 엔트리 포인트

Flet build는 src/main.py를 엔트리포인트로 사용합니다.
이 파일이 src/ 폴더에 있어야 dubbing_app 패키지도 함께 패키징됩니다.
"""
from dubbing_app.main import main
import flet as ft

ft.app(target=main)
