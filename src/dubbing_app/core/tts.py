"""edge-tts 음성 생성 모듈"""

import asyncio
from pathlib import Path

import edge_tts


# 한국어 음성 목록
KOREAN_VOICES = {
    "ko-KR-SunHiNeural": {"gender": "Female", "desc": "자연스러운 여성 음성 (기본)"},
    "ko-KR-InJoonNeural": {"gender": "Male", "desc": "차분한 남성 음성"},
}

DEFAULT_VOICE = "ko-KR-SunHiNeural"


async def _generate_tts_async(text: str, output_path: str, voice: str, rate: str) -> None:
    """비동기 TTS 생성"""
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(output_path)


def generate_tts(
    text: str,
    output_path: str,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
    on_progress: callable = None,
) -> dict:
    """
    한국어 텍스트를 음성으로 변환

    Args:
        text: 변환할 텍스트
        output_path: 출력 MP3 파일 경로
        voice: 음성 ID
        rate: 속도 조절 (예: +10%, -20%)
        on_progress: 진행 콜백 (message)

    Returns:
        dict: {
            "success": bool,
            "path": str,
            "error": str (실패 시)
        }
    """
    if not text.strip():
        return {
            "success": False,
            "error": "텍스트가 비어 있습니다.",
        }

    try:
        max_chunk_size = 5000  # edge-tts 제한

        if len(text) <= max_chunk_size:
            if on_progress:
                on_progress(f"변환 중... (길이: {len(text)}자)")

            asyncio.run(_generate_tts_async(text, output_path, voice, rate))

            if on_progress:
                on_progress(f"완료: {output_path}")

            return {
                "success": True,
                "path": output_path,
            }
        else:
            # 청크로 나누어 처리
            chunks = _split_text_into_chunks(text, max_chunk_size)

            if on_progress:
                on_progress(f"총 {len(chunks)}개 청크로 분할됨")

            temp_files = []
            for i, chunk in enumerate(chunks):
                temp_path = f"{output_path}.part{i}.mp3"

                if on_progress:
                    on_progress(f"청크 {i+1}/{len(chunks)} 변환 중...")

                asyncio.run(_generate_tts_async(chunk, temp_path, voice, rate))
                temp_files.append(temp_path)

            # 병합
            if on_progress:
                on_progress("파일 병합 중...")

            _merge_audio_files(temp_files, output_path)

            # 임시 파일 삭제
            for f in temp_files:
                Path(f).unlink(missing_ok=True)

            if on_progress:
                on_progress(f"완료: {output_path}")

            return {
                "success": True,
                "path": output_path,
            }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def _split_text_into_chunks(text: str, max_size: int) -> list[str]:
    """텍스트를 문장 단위로 청크 분할"""
    import re

    sentences = re.split(r"(?<=[.!?。？！])\s+", text)
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 <= max_size:
            current_chunk += (" " if current_chunk else "") + sentence
        else:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = sentence

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _merge_audio_files(input_files: list[str], output_path: str) -> None:
    """MP3 파일들을 병합 (순수 Python - 바이너리 concat)"""
    # MP3는 단순 바이너리 연결로 병합 가능 (같은 설정일 때)
    with open(output_path, "wb") as outfile:
        for input_file in input_files:
            with open(input_file, "rb") as infile:
                outfile.write(infile.read())


async def list_voices() -> list[dict]:
    """사용 가능한 한국어 음성 목록"""
    voices = await edge_tts.list_voices()
    korean_voices = [v for v in voices if v["Locale"].startswith("ko-")]
    return korean_voices


def get_voice_options() -> dict:
    """음성 옵션 반환"""
    return KOREAN_VOICES
