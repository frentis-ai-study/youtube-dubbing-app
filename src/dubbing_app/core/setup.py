"""온보딩 및 자동 설정 모듈"""

import subprocess
import sys
import os
import httpx
from pathlib import Path

# Ollama 가능한 경로들 (macOS)
OLLAMA_PATHS = [
    "/opt/homebrew/bin/ollama",  # Apple Silicon Homebrew
    "/usr/local/bin/ollama",     # Intel Homebrew
    "/usr/bin/ollama",           # 시스템
    "ollama",                    # PATH에 있는 경우
]

BREW_PATHS = [
    "/opt/homebrew/bin/brew",    # Apple Silicon
    "/usr/local/bin/brew",       # Intel
]


def find_ollama_path() -> str | None:
    """Ollama 실행 파일 경로 찾기"""
    for path in OLLAMA_PATHS:
        if path == "ollama":
            # PATH에서 찾기
            try:
                result = subprocess.run(
                    ["which", "ollama"],
                    capture_output=True,
                    text=True,
                    env={**os.environ, "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:" + os.environ.get("PATH", "")},
                )
                if result.returncode == 0:
                    return result.stdout.strip()
            except Exception:
                pass
        elif Path(path).exists():
            return path
    return None


def find_brew_path() -> str | None:
    """Homebrew 실행 파일 경로 찾기"""
    for path in BREW_PATHS:
        if Path(path).exists():
            return path
    return None


def is_ollama_installed() -> bool:
    """Ollama 설치 여부 확인"""
    return find_ollama_path() is not None


def is_ollama_running() -> bool:
    """Ollama 서버 실행 여부 확인 (HTTP API 사용)"""
    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=3)
        return response.status_code == 200
    except Exception:
        return False


def get_ollama_models() -> list[str]:
    """설치된 Ollama 모델 목록 (HTTP API 사용)"""
    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        return []
    except Exception:
        # 서버 안 떠있으면 CLI 시도
        ollama_path = find_ollama_path()
        if not ollama_path:
            return []
        try:
            result = subprocess.run(
                [ollama_path, "list"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return []

            models = []
            for line in result.stdout.strip().split("\n")[1:]:  # 헤더 스킵
                if line.strip():
                    model_name = line.split()[0]
                    models.append(model_name)
            return models
        except Exception:
            return []


def has_model(model_name: str) -> bool:
    """특정 모델 설치 여부 확인"""
    models = get_ollama_models()
    # gemma3:latest, gemma3 등 다양한 형태 체크
    for m in models:
        if model_name in m or m.startswith(model_name):
            return True
    return False


def install_ollama_macos() -> tuple[bool, str]:
    """macOS에서 Ollama 설치 (Homebrew)"""
    try:
        # Homebrew 확인
        brew_path = find_brew_path()
        if not brew_path:
            return False, "Homebrew가 설치되어 있지 않습니다.\nhttps://brew.sh 에서 설치 후 다시 시도하세요."

        # Ollama 설치
        result = subprocess.run(
            [brew_path, "install", "ollama"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            return True, "Ollama 설치 완료"
        else:
            return False, f"설치 실패: {result.stderr}"
    except subprocess.TimeoutExpired:
        return False, "설치 시간 초과"
    except Exception as e:
        return False, f"설치 오류: {e}"


def start_ollama_server() -> tuple[bool, str]:
    """Ollama 서버 시작"""
    ollama_path = find_ollama_path()
    if not ollama_path:
        return False, "Ollama가 설치되어 있지 않습니다."

    try:
        # 백그라운드로 시작
        subprocess.Popen(
            [ollama_path, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # 서버 시작 대기
        import time
        for _ in range(10):
            time.sleep(1)
            if is_ollama_running():
                return True, "Ollama 서버 시작됨"
        return False, "서버 시작 시간 초과"
    except Exception as e:
        return False, f"서버 시작 실패: {e}"


def pull_model(model_name: str, on_progress=None) -> tuple[bool, str]:
    """모델 다운로드"""
    ollama_path = find_ollama_path()
    if not ollama_path:
        return False, "Ollama가 설치되어 있지 않습니다."

    try:
        process = subprocess.Popen(
            [ollama_path, "pull", model_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        output_lines = []
        for line in process.stdout:
            line = line.strip()
            output_lines.append(line)
            if on_progress:
                on_progress(line)

        process.wait()

        if process.returncode == 0:
            return True, f"{model_name} 모델 다운로드 완료"
        else:
            return False, f"다운로드 실패: {output_lines[-1] if output_lines else 'Unknown error'}"
    except Exception as e:
        return False, f"다운로드 오류: {e}"


def check_setup_status() -> dict:
    """전체 설정 상태 확인"""
    return {
        "ollama_installed": is_ollama_installed(),
        "ollama_running": is_ollama_running(),
        "has_gemma3": has_model("gemma3"),
        "models": get_ollama_models(),
    }


# 기본 추천 모델
DEFAULT_MODEL = "gemma3"
