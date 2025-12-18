"""설정 관리 모듈"""

import json
from dataclasses import dataclass, asdict
from pathlib import Path


CONFIG_FILE = Path.home() / ".config" / "youtube-dubbing" / "config.json"


@dataclass
class Config:
    """앱 설정"""
    # z.ai API 설정
    zai_api_key: str = ""
    zai_base_url: str = "https://api.z.ai/api/coding/paas/v4"
    zai_model: str = "GLM-4.6"

    # 출력 설정
    output_dir: str = str(Path.home() / "Dubbing")

    # TTS 설정
    tts_voice: str = "ko-KR-SunHiNeural"
    tts_rate: str = "+0%"

    # 처리 설정
    max_workers: int = 2

    # UI 설정
    theme: str = "purple-night"


def load_config() -> Config:
    """설정 파일 로드"""
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
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
