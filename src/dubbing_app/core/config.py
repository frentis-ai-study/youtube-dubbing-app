"""설정 관리 모듈"""

import json
from dataclasses import dataclass, asdict
from pathlib import Path


CONFIG_FILE = Path.home() / ".config" / "youtube-dubbing" / "config.json"


@dataclass
class Config:
    """앱 설정"""
    # AI 엔진 선택 (ollama / zai)
    ai_engine: str = "ollama"

    # Ollama 설정
    ollama_model: str = "gemma3:latest"
    ollama_base_url: str = "http://localhost:11434"

    # API 설정 (Ollama 기본값)
    zai_api_key: str = "ollama"  # Ollama는 API 키 불필요
    zai_base_url: str = "http://localhost:11434/v1"  # Ollama 기본
    zai_model: str = "gemma3:latest"

    # 출력 설정
    output_dir: str = str(Path.home() / "Dubbing")

    # TTS 설정
    tts_voice: str = "ko-KR-SunHiNeural"
    tts_rate: str = "+0%"

    # 처리 설정
    max_workers: int = 2

    # UI 설정
    theme: str = "purple-night"

    # 번역 스타일 설정
    translation_style: str = "natural"  # "faithful" (원문 충실) | "natural" (자연스러운 더빙)
    translation_tone: str = "lecture"   # "lecture" (강의체) | "casual" (대화체) | "formal" (뉴스체)

    # 자막 언어 설정
    source_lang: str = "en"  # 기본 자막 언어


def load_config() -> Config:
    """설정 파일 로드 (누락된 필드는 기본값 사용)"""
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            # 기본값과 병합 (새 필드 호환성)
            default = Config()
            for key in default.__dataclass_fields__:
                if key not in data:
                    data[key] = getattr(default, key)
            return Config(**data)
        except (json.JSONDecodeError, TypeError):
            pass
    return Config()


def save_config(config: Config) -> None:
    """설정 파일 저장"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
