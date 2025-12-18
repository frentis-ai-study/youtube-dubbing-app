"""YouTube 자막 추출 모듈"""

import re
import tempfile
from pathlib import Path

import yt_dlp


def extract_transcript(url: str, lang: str = "en") -> dict:
    """
    YouTube에서 자막 추출

    Args:
        url: YouTube URL
        lang: 자막 언어 (기본: en)

    Returns:
        dict: {
            "success": bool,
            "title": str,
            "text": str,
            "segments": list[dict],
            "language": str,
            "is_auto_generated": bool,
            "error": str (실패 시)
        }
    """
    lang_priority = [lang, "en", "en-US", "en-GB", "ko", "ja"]

    ydl_opts = {
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": lang_priority,
        "subtitlesformat": "vtt",
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get("title", "unknown")

        subtitles = info.get("subtitles", {})
        auto_captions = info.get("automatic_captions", {})
        available_langs = list(subtitles.keys()) + list(auto_captions.keys())

        if not available_langs:
            return {
                "success": False,
                "error": "자막 없음",
                "title": title,
                "available_langs": [],
            }

        # 우선순위대로 자막 찾기
        selected_lang = None
        is_auto = False
        for check_lang in lang_priority:
            if check_lang in subtitles:
                selected_lang = check_lang
                is_auto = False
                break
            elif check_lang in auto_captions:
                selected_lang = check_lang
                is_auto = True
                break

        if not selected_lang:
            if subtitles:
                selected_lang = list(subtitles.keys())[0]
                is_auto = False
            else:
                selected_lang = list(auto_captions.keys())[0]
                is_auto = True

        # 자막 다운로드
        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts_download = {
                "writesubtitles": not is_auto,
                "writeautomaticsub": is_auto,
                "subtitleslangs": [selected_lang],
                "subtitlesformat": "vtt",
                "skip_download": True,
                "outtmpl": f"{tmpdir}/sub",
                "quiet": True,
                "no_warnings": True,
            }

            with yt_dlp.YoutubeDL(ydl_opts_download) as ydl2:
                ydl2.download([url])

            vtt_files = list(Path(tmpdir).glob("*.vtt"))
            if not vtt_files:
                return {
                    "success": False,
                    "error": "자막 파일 생성 실패",
                    "title": title,
                    "available_langs": available_langs,
                }

            vtt_content = vtt_files[0].read_text(encoding="utf-8")
            text, segments = _parse_vtt(vtt_content)

            return {
                "success": True,
                "title": title,
                "language": selected_lang,
                "is_auto_generated": is_auto,
                "text": text,
                "segments": segments,
                "available_langs": available_langs,
            }


def _parse_vtt(vtt_content: str) -> tuple[str, list[dict]]:
    """VTT 자막 파싱"""
    lines = vtt_content.split("\n")
    segments = []
    current_text = []

    time_pattern = re.compile(r"(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})")

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = time_pattern.match(line)

        if match:
            start_time = match.group(1)
            end_time = match.group(2)

            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip() and not time_pattern.match(lines[i].strip()):
                clean_line = re.sub(r"<[^>]+>", "", lines[i].strip())
                if clean_line:
                    text_lines.append(clean_line)
                i += 1

            if text_lines:
                text = " ".join(text_lines)
                if not segments or segments[-1]["text"] != text:
                    segments.append({
                        "start": start_time,
                        "end": end_time,
                        "text": text,
                    })
                    current_text.append(text)
        else:
            i += 1

    full_text = " ".join(current_text)
    return full_text, segments


def extract_with_whisper(audio_path: str, model: str = "base") -> dict:
    """
    Whisper로 음성 인식

    Args:
        audio_path: 오디오 파일 경로
        model: Whisper 모델 (tiny/base/small/medium/large)

    Returns:
        dict: 자막 정보
    """
    try:
        import whisper
    except ImportError:
        return {
            "success": False,
            "error": "Whisper가 필요합니다. 설치: pip install openai-whisper",
        }

    model_obj = whisper.load_model(model)
    result = model_obj.transcribe(audio_path)

    segments = []
    for seg in result.get("segments", []):
        segments.append({
            "start": _format_time(seg["start"]),
            "end": _format_time(seg["end"]),
            "text": seg["text"].strip(),
        })

    return {
        "success": True,
        "title": Path(audio_path).stem,
        "language": result.get("language", "unknown"),
        "is_auto_generated": True,
        "text": result.get("text", ""),
        "segments": segments,
    }


def _format_time(seconds: float) -> str:
    """초를 HH:MM:SS.mmm 형식으로 변환"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def get_video_info(url: str) -> dict:
    """
    YouTube 영상 정보 가져오기

    Returns:
        dict: {
            "title": str,
            "duration": int (초),
            "uploader": str (채널명),
            "channel_url": str,
            "thumbnail": str (썸네일 URL),
            "video_id": str,
            "url": str (원본 URL),
            "description": str (영상 설명, 처음 200자),
        }
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        video_id = info.get("id", "")

        # 썸네일: 최고 품질 선택
        thumbnail = info.get("thumbnail", "")
        if not thumbnail and video_id:
            # 기본 YouTube 썸네일 URL
            thumbnail = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

        # 설명: 처음 200자만 (너무 길면 UI 깨짐)
        description = info.get("description", "") or ""
        if len(description) > 200:
            description = description[:200] + "..."

        return {
            "title": info.get("title", "unknown"),
            "duration": info.get("duration", 0),
            "uploader": info.get("uploader", info.get("channel", "unknown")),
            "channel_url": info.get("channel_url", info.get("uploader_url", "")),
            "thumbnail": thumbnail,
            "video_id": video_id,
            "url": url,
            "description": description,
        }


def sanitize_filename(title: str) -> str:
    """파일명에 사용할 수 없는 문자 제거"""
    title = re.sub(r'[<>:"/\\|?*]', "", title)
    title = re.sub(r"\s+", " ", title).strip()
    if len(title) > 50:
        title = title[:50]
    return title


def extract_video_id(url: str) -> str | None:
    """
    YouTube URL에서 video ID 추출

    지원 형식:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    - https://www.youtube.com/v/VIDEO_ID
    """
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([a-zA-Z0-9_-]{11})",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def check_existing_output(output_dir: Path, video_id: str) -> dict | None:
    """
    기존 출력 폴더 확인 (단계별 진행 상황 포함)

    Returns:
        dict: {
            "folder": Path,
            "has_audio": bool,
            "has_korean": bool,
            "has_original": bool,
            "is_complete": bool,
            "resume_from": str,  # "start", "translate", "tts", "done"
            "original_text": str | None,
            "korean_text": str | None,
            "audio_file": Path | None,  # MP3 파일 경로
        }
        또는 None (폴더 없음)
    """
    # video_id로 시작하는 폴더 찾기
    if not output_dir.exists():
        return None

    for folder in output_dir.iterdir():
        if folder.is_dir() and folder.name.startswith(video_id):
            # MP3 파일 찾기 (제목.mp3 또는 audio_korean.mp3)
            mp3_files = list(folder.glob("*.mp3"))
            audio_file = mp3_files[0] if mp3_files else None

            korean_file = folder / "transcript_korean.txt"
            original_file = folder / "transcript_original.txt"

            has_audio = audio_file is not None
            has_korean = korean_file.exists()
            has_original = original_file.exists()

            # 재개 지점 결정
            if has_audio and has_korean:
                resume_from = "done"
            elif has_korean:
                resume_from = "tts"
            elif has_original:
                resume_from = "translate"
            else:
                resume_from = "start"

            return {
                "folder": folder,
                "has_audio": has_audio,
                "has_korean": has_korean,
                "has_original": has_original,
                "is_complete": has_audio and has_korean,
                "resume_from": resume_from,
                "original_text": original_file.read_text(encoding="utf-8") if has_original else None,
                "korean_text": korean_file.read_text(encoding="utf-8") if has_korean else None,
                "audio_file": audio_file,
            }

    return None
