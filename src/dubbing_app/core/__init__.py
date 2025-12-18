"""Core modules for YouTube dubbing"""

from dubbing_app.core.transcript import extract_transcript, extract_with_whisper
from dubbing_app.core.translator import translate_text
from dubbing_app.core.tts import generate_tts
from dubbing_app.core.config import Config, load_config, save_config

__all__ = [
    "extract_transcript",
    "extract_with_whisper",
    "translate_text",
    "generate_tts",
    "Config",
    "load_config",
    "save_config",
]
