"""더빙 파이프라인 실행"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from dubbing_app.core.config import Config
from dubbing_app.core.transcript import (
    extract_transcript,
    get_video_info,
    sanitize_filename,
    extract_video_id,
    check_existing_output,
)
from dubbing_app.core.translator import translate_full_text, check_ollama_status, check_model_loaded
from dubbing_app.core.tts import generate_tts


@dataclass
class DubbingJob:
    """더빙 작업 정보"""
    job_id: str
    url: str
    output_dir: Path
    status: str = "pending"  # pending, running, completed, error
    progress: int = 0
    current_step: str = ""
    messages: list[str] = field(default_factory=list)
    error: str | None = None
    result_files: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


def generate_job_id() -> str:
    """고유한 작업 ID 생성"""
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:20]


def run_dubbing(
    url: str,
    output_dir: Path,
    config: Config,
    on_progress: Callable[[str, int], None] | None = None,
) -> DubbingJob:
    """
    더빙 파이프라인 실행

    Args:
        url: YouTube URL
        output_dir: 출력 디렉토리
        config: 앱 설정 (API 키 포함)
        on_progress: 진행 상황 콜백 (message, progress_percent)

    Returns:
        DubbingJob: 작업 결과
    """
    job = DubbingJob(
        job_id=generate_job_id(),
        url=url,
        output_dir=output_dir,
        status="running",
    )

    def log(msg: str, progress: int = 0):
        job.messages.append(msg)
        job.progress = progress
        job.current_step = msg
        if on_progress:
            on_progress(msg, progress)

    try:
        # Step 0: Ollama 사용 시 사전 체크
        is_ollama = "localhost:11434" in config.zai_base_url
        if is_ollama:
            log("Ollama 서버 상태 확인 중...", 2)
            status = check_ollama_status(config.zai_base_url)
            if not status["available"]:
                raise Exception(f"Ollama 연결 실패: {status.get('error')}")

            model_check = check_model_loaded(config.zai_model, config.zai_base_url)
            if not model_check["loaded"]:
                raise Exception(model_check.get("error"))

            log(f"Ollama 준비 완료 (모델: {config.zai_model})", 5)

        # Step 1: 영상 정보 확인
        log("영상 정보 확인 중...", 5)

        # Video ID 추출
        video_id = extract_video_id(url)
        if not video_id:
            raise Exception("유효하지 않은 YouTube URL입니다.")

        video_info = get_video_info(url)
        title = sanitize_filename(video_info["title"])
        log(f"제목: {title} (ID: {video_id})", 10)

        # 기존 출력 확인 (단계별 재개 지원)
        existing = check_existing_output(output_dir, video_id)

        if existing and existing["resume_from"] == "done":
            log("이미 완료된 작업입니다. 스킵합니다.", 100)
            job.status = "completed"
            job.progress = 100
            job.output_dir = existing["folder"]
            job.result_files = [
                str(existing["audio_file"]) if existing["audio_file"] else "",
                str(existing["folder"] / "transcript_korean.txt"),
                str(existing["folder"] / "transcript_original.txt"),
            ]
            job.current_step = "이미 완료됨 (스킵)"
            return job

        # 출력 폴더 생성/재사용
        if existing:
            job_output_dir = existing["folder"]
            resume_from = existing["resume_from"]
            log(f"기존 작업 재개: {resume_from} 단계부터", 15)
        else:
            job_output_dir = output_dir / f"{video_id}-{title}"
            job_output_dir.mkdir(parents=True, exist_ok=True)
            resume_from = "start"

        # Step 2: 자막 추출 (또는 기존 파일 사용)
        import json
        segments_file = job_output_dir / "segments.json"

        if resume_from == "start":
            log("자막 추출 중...", 20)
            transcript_result = extract_transcript(url)

            if not transcript_result["success"]:
                raise Exception(f"자막 추출 실패: {transcript_result.get('error', '알 수 없는 오류')}")

            original_text = transcript_result["text"]
            segments = transcript_result.get("segments", [])
            log(f"자막 추출 완료 (언어: {transcript_result['language']}, {len(segments)}개 세그먼트, {len(original_text)}자)", 30)

            # 원본 자막 저장
            original_file = job_output_dir / "transcript_original.txt"
            original_file.write_text(original_text, encoding="utf-8")
            job.result_files.append(str(original_file))

            # 세그먼트 정보 저장 (재개 시 동일 청킹 유지용)
            if segments:
                segments_file.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")
        else:
            # 기존 원본 자막 사용
            log("기존 자막 파일 사용", 30)
            original_text = existing["original_text"]

            # 세그먼트 파일이 있으면 로드 (동일 청킹 유지)
            if segments_file.exists():
                segments = json.loads(segments_file.read_text(encoding="utf-8"))
                log(f"세그먼트 정보 로드 ({len(segments)}개)", 32)
            else:
                segments = []

            job.result_files.append(str(job_output_dir / "transcript_original.txt"))

        # Step 3: 한국어 번역 (또는 기존 파일 사용)
        if resume_from in ("start", "translate"):
            log("한국어로 번역 중...", 40)

            # 청크 저장 디렉토리 설정
            chunks_dir = job_output_dir / "chunks"

            def translation_progress(current, total):
                percent = 40 + int((current / total) * 30)
                log(f"번역 중... ({current}/{total} 청크)", percent)

            translation_result = translate_full_text(
                text=original_text,
                api_key=config.zai_api_key,
                base_url=config.zai_base_url,
                model=config.zai_model,
                on_progress=translation_progress,
                segments=segments if segments else None,
                chunks_dir=str(chunks_dir),
            )

            if not translation_result["success"]:
                raise Exception(f"번역 실패: {translation_result.get('error', '알 수 없는 오류')}")

            korean_text = translation_result["translated"]
            log(f"번역 완료 ({len(korean_text)}자)", 70)

            # 번역 자막 저장
            korean_file = job_output_dir / "transcript_korean.txt"
            korean_file.write_text(korean_text, encoding="utf-8")
            job.result_files.append(str(korean_file))

            # 번역 완료 후 chunks 폴더 삭제 (더 이상 필요 없음)
            if chunks_dir.exists():
                import shutil
                shutil.rmtree(chunks_dir)
                log("임시 청크 파일 정리 완료", 72)
        else:
            # 기존 번역 파일 사용
            log("기존 번역 파일 사용", 70)
            korean_text = existing["korean_text"]
            job.result_files.append(str(job_output_dir / "transcript_korean.txt"))

        # Step 4: TTS 음성 생성
        log("음성 생성 중...", 75)

        # MP3 파일명을 영상 제목으로 설정 (나중에 모아서 재생할 때 구분 가능)
        audio_file = job_output_dir / f"{title}.mp3"

        def tts_progress(msg):
            log(msg, 80)

        tts_result = generate_tts(
            text=korean_text,
            output_path=str(audio_file),
            voice=config.tts_voice,
            rate=config.tts_rate,
            on_progress=tts_progress,
        )

        if not tts_result["success"]:
            raise Exception(f"TTS 실패: {tts_result.get('error', '알 수 없는 오류')}")

        job.result_files.append(str(audio_file))
        log("음성 생성 완료!", 100)

        job.status = "completed"
        job.progress = 100

    except Exception as e:
        job.status = "error"
        job.error = str(e)
        log(f"오류: {e}", job.progress)

    return job


def find_result_files(output_dir: Path) -> list[str]:
    """출력 디렉토리에서 결과 파일 찾기"""
    result_files = []

    if not output_dir.exists():
        return result_files

    # 최신 폴더 찾기 (날짜 형식)
    subdirs = sorted(output_dir.iterdir(), reverse=True)
    for subdir in subdirs:
        if subdir.is_dir() and subdir.name[0].isdigit():
            for pattern in ["*.mp3", "*_korean.txt", "*_original.txt"]:
                result_files.extend(str(f) for f in subdir.glob(pattern))
            break

    return result_files
