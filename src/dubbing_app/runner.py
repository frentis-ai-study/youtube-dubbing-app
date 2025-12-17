"""Claude Code headless 호출 래퍼"""

import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator


@dataclass
class DubbingJob:
    """더빙 작업 정보"""
    job_id: str
    url: str
    output_dir: Path
    status: str = "pending"  # pending, running, completed, error
    progress: int = 0
    messages: list[str] = field(default_factory=list)
    error: str | None = None
    result_files: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


def generate_job_id() -> str:
    """고유한 작업 ID 생성"""
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:20]


def create_dubbing_prompt(url: str, output_dir: Path) -> str:
    """Claude Code에 전달할 더빙 프롬프트 생성"""
    return f"""이 YouTube 영상을 한국어로 더빙해줘.

URL: {url}
출력 위치: {output_dir}

작업 순서:
1. 영상 제목 확인하고 출력 폴더 생성 (형식: {output_dir}/YYYY-MM-DD-제목)
2. 자막 추출 (YouTube 자막 우선, 없으면 Whisper)
3. 자연스러운 한국어로 번역
4. edge-tts로 음성 파일 생성

각 단계마다 진행 상황을 알려줘."""


def run_dubbing(
    url: str,
    output_dir: Path,
    on_progress: Callable[[str], None] | None = None,
) -> DubbingJob:
    """
    Claude Code headless로 더빙 실행

    Args:
        url: YouTube URL
        output_dir: 출력 디렉토리
        on_progress: 진행 상황 콜백 (stream-json 메시지마다 호출)

    Returns:
        DubbingJob: 작업 결과
    """
    job = DubbingJob(
        job_id=generate_job_id(),
        url=url,
        output_dir=output_dir,
        status="running",
    )

    prompt = create_dubbing_prompt(url, output_dir)

    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "stream-json",
        "--allowedTools", "Bash,Read,Write,WebFetch,Glob,Grep",
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # stream-json 파싱
        for line in proc.stdout:
            if not line.strip():
                continue

            try:
                event = json.loads(line)
                event_type = event.get("type", "")

                if event_type == "assistant":
                    # 어시스턴트 메시지
                    content = event.get("message", {}).get("content", [])
                    for block in content:
                        if block.get("type") == "text":
                            msg = block.get("text", "")
                            job.messages.append(msg)
                            if on_progress:
                                on_progress(msg)

                elif event_type == "result":
                    # 최종 결과
                    job.status = "completed"
                    job.progress = 100

            except json.JSONDecodeError:
                continue

        proc.wait()

        if proc.returncode != 0:
            stderr = proc.stderr.read()
            job.status = "error"
            job.error = stderr
        else:
            # 결과 파일 확인
            job.result_files = find_result_files(output_dir)

    except FileNotFoundError:
        job.status = "error"
        job.error = "Claude Code가 설치되어 있지 않습니다. 'claude' 명령어를 확인하세요."
    except Exception as e:
        job.status = "error"
        job.error = str(e)

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
            # 결과 파일 확인
            for pattern in ["*.mp3", "*_korean.txt", "*_original.txt"]:
                result_files.extend(str(f) for f in subdir.glob(pattern))
            break

    return result_files


def stream_dubbing(
    url: str,
    output_dir: Path,
) -> Iterator[dict]:
    """
    Claude Code 출력을 제너레이터로 스트리밍

    Yields:
        dict: {"type": "progress|result|error", "data": ...}
    """
    prompt = create_dubbing_prompt(url, output_dir)

    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "stream-json",
        "--allowedTools", "Bash,Read,Write,WebFetch,Glob,Grep",
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        for line in proc.stdout:
            if not line.strip():
                continue

            try:
                event = json.loads(line)
                event_type = event.get("type", "")

                if event_type == "assistant":
                    content = event.get("message", {}).get("content", [])
                    for block in content:
                        if block.get("type") == "text":
                            yield {"type": "progress", "data": block.get("text", "")}

                elif event_type == "result":
                    yield {
                        "type": "result",
                        "data": {
                            "result": event.get("result", ""),
                            "cost": event.get("total_cost_usd", 0),
                            "duration_ms": event.get("duration_ms", 0),
                        }
                    }

            except json.JSONDecodeError:
                continue

        proc.wait()

        if proc.returncode != 0:
            stderr = proc.stderr.read()
            yield {"type": "error", "data": stderr}

    except FileNotFoundError:
        yield {"type": "error", "data": "Claude Code가 설치되어 있지 않습니다."}
    except Exception as e:
        yield {"type": "error", "data": str(e)}


def check_claude_available() -> tuple[bool, str]:
    """Claude Code 사용 가능 여부 확인"""
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr
    except FileNotFoundError:
        return False, "Claude Code가 설치되어 있지 않습니다."
    except subprocess.TimeoutExpired:
        return False, "Claude Code 응답 시간 초과"
    except Exception as e:
        return False, str(e)
