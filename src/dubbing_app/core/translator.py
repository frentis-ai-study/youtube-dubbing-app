"""z.ai GLM 번역 모듈 (OpenAI 호환)"""

import re
import sys
import httpx
from openai import OpenAI


def check_ollama_status(base_url: str = "http://localhost:11434") -> dict:
    """
    Ollama 서버 상태 확인

    Returns:
        dict: {
            "available": bool,
            "models": list[str],  # 사용 가능한 모델 목록
            "error": str (실패 시)
        }
    """
    # base_url에서 /v1 제거
    ollama_url = base_url.replace("/v1", "")

    try:
        # 모델 목록 조회
        response = httpx.get(f"{ollama_url}/api/tags", timeout=5.0)
        if response.status_code == 200:
            data = response.json()
            models = [m["name"] for m in data.get("models", [])]
            return {
                "available": True,
                "models": models,
            }
        else:
            return {
                "available": False,
                "models": [],
                "error": f"HTTP {response.status_code}",
            }
    except httpx.ConnectError:
        return {
            "available": False,
            "models": [],
            "error": "Ollama 서버에 연결할 수 없습니다. 'ollama serve' 실행 필요",
        }
    except httpx.TimeoutException:
        return {
            "available": False,
            "models": [],
            "error": "Ollama 서버 응답 시간 초과",
        }
    except Exception as e:
        return {
            "available": False,
            "models": [],
            "error": str(e),
        }


def check_model_loaded(
    model: str,
    base_url: str = "http://localhost:11434",
) -> dict:
    """
    특정 모델이 로드되어 있는지 확인하고, 없으면 pull 안내

    Returns:
        dict: {
            "loaded": bool,
            "error": str (실패 시)
        }
    """
    status = check_ollama_status(base_url)

    if not status["available"]:
        return {"loaded": False, "error": status.get("error")}

    # 모델명 정규화 (gemma3:latest -> gemma3)
    model_base = model.split(":")[0]

    for available_model in status["models"]:
        if available_model.startswith(model_base):
            return {"loaded": True}

    return {
        "loaded": False,
        "error": f"모델 '{model}'이 없습니다. 'ollama pull {model}' 실행 필요",
    }


def _time_to_seconds(time_str: str) -> float:
    """HH:MM:SS.mmm 형식을 초로 변환"""
    match = re.match(r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})", time_str)
    if match:
        h, m, s, ms = match.groups()
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    return 0.0


def _is_sentence_end(text: str) -> bool:
    """문장 끝 문자로 끝나는지 확인"""
    if not text:
        return False
    text = text.rstrip()
    return text.endswith(('.', '!', '?', '。', '！', '？', '…'))


def split_segments_by_time(
    segments: list[dict],
    chunk_duration: int = 60,  # 1분 단위
    max_chars: int = 1500,  # 최대 문자 수 (soft limit)
    hard_limit: int = 2000,  # 절대 초과 불가
) -> list[list[dict]]:
    """
    세그먼트를 시간 + 문자 수 기준으로 청크 분할 (문장 경계 존중)

    Args:
        segments: 자막 세그먼트 리스트 [{"start": "00:00:01.000", "end": "...", "text": "..."}]
        chunk_duration: 청크 길이 (초, 기본 1분)
        max_chars: 소프트 리밋 - 이 이상이면 문장 끝에서 분할 (기본 1500자)
        hard_limit: 하드 리밋 - 문장 끝이 아니어도 강제 분할 (기본 2000자)

    Returns:
        list of segment groups
    """
    if not segments:
        return []

    chunks = []
    current_chunk = []
    chunk_start_time = 0.0
    current_chars = 0

    for seg in segments:
        seg_start = _time_to_seconds(seg["start"])
        seg_text = seg.get("text", "")
        seg_chars = len(seg_text)

        # 새 청크 시작 조건:
        # 1. 시간 초과 (chunk_duration)
        # 2. 하드 리밋 초과 (hard_limit) - 무조건 분할
        # 3. 소프트 리밋 초과 (max_chars) + 이전 세그먼트가 문장 끝
        time_exceeded = current_chunk and (seg_start - chunk_start_time) >= chunk_duration
        hard_exceeded = current_chunk and (current_chars + seg_chars) > hard_limit

        # 소프트 리밋: 현재 청크가 max_chars 이상이고, 마지막 세그먼트가 문장 끝이면 분할
        soft_exceeded = (
            current_chunk
            and current_chars >= max_chars
            and _is_sentence_end(current_chunk[-1].get("text", ""))
        )

        if time_exceeded or hard_exceeded or soft_exceeded:
            chunks.append(current_chunk)
            current_chunk = []
            chunk_start_time = seg_start
            current_chars = 0

        current_chunk.append(seg)
        current_chars += seg_chars

        # 첫 세그먼트일 때 시작 시간 설정
        if len(current_chunk) == 1 and chunk_start_time == 0.0:
            chunk_start_time = seg_start

    # 마지막 청크 추가
    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def translate_text(
    text: str,
    api_key: str,
    base_url: str = "https://api.z.ai/api/coding/paas/v4",
    model: str = "GLM-4.6",
    source_lang: str = "영어",
    target_lang: str = "한국어",
    timeout: int = 180,
    max_retries: int = 2,
) -> dict:
    """
    z.ai GLM으로 텍스트 번역 (타임아웃 및 재시도 지원)

    Args:
        text: 번역할 텍스트
        api_key: z.ai API 키
        base_url: API 엔드포인트
        model: 모델명 (GLM-4.6, GLM-4.5, GLM-4.5-air)
        source_lang: 원본 언어
        target_lang: 타겟 언어
        timeout: 타임아웃 (초)
        max_retries: 최대 재시도 횟수

    Returns:
        dict: {
            "success": bool,
            "translated": str,
            "error": str (실패 시)
        }
    """
    if not text.strip():
        return {
            "success": True,
            "translated": "",
        }

    # Ollama 사용 시 사전 체크 (API 키 불필요)
    is_ollama = "localhost:11434" in base_url
    if is_ollama:
        status = check_ollama_status(base_url)
        if not status["available"]:
            return {
                "success": False,
                "error": status.get("error", "Ollama 서버 연결 실패"),
            }
        # Ollama는 API 키 불필요 - 더미 값 사용
        api_key = api_key or "ollama"
    elif not api_key:
        return {
            "success": False,
            "error": "API 키가 설정되지 않았습니다.",
        }

    last_error = None

    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                print(f"[번역] 재시도 {attempt}/{max_retries}...", file=sys.stderr)

            print(f"[번역] 시작 ({len(text)}자)", file=sys.stderr)

            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
            )

            system_prompt = f"""당신은 전문 번역가입니다. {source_lang}를 자연스러운 {target_lang}로 번역합니다.

번역 규칙:
1. 자연스럽고 읽기 쉬운 {target_lang}로 번역
2. 원문의 의미와 뉘앙스 유지
3. 구어체로 번역 (TTS로 읽힐 예정)
4. 번역문만 출력 (설명 없이)"""

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                temperature=0.3,
            )

            translated = response.choices[0].message.content.strip()
            print(f"[번역] 완료 (결과 길이: {len(translated)}자)", file=sys.stderr)

            return {
                "success": True,
                "translated": translated,
            }

        except Exception as e:
            last_error = e
            error_type = type(e).__name__
            print(f"[번역] 오류 (시도 {attempt + 1}): {error_type}: {e}", file=sys.stderr)

            # 타임아웃이나 연결 오류면 재시도
            if "timeout" in str(e).lower() or "connection" in str(e).lower():
                continue
            else:
                # 다른 오류는 바로 실패
                break

    return {
        "success": False,
        "error": f"번역 실패 (재시도 {max_retries}회 후): {last_error}",
    }


def translate_segments(
    segments: list[dict],
    api_key: str,
    base_url: str = "https://api.z.ai/api/coding/paas/v4",
    model: str = "GLM-4.6",
    batch_size: int = 20,
    on_progress: callable = None,
) -> dict:
    """
    자막 세그먼트 배치 번역

    Args:
        segments: 자막 세그먼트 리스트
        api_key: z.ai API 키
        base_url: API 엔드포인트
        model: 모델명
        batch_size: 한 번에 번역할 세그먼트 수
        on_progress: 진행 콜백 (current, total)

    Returns:
        dict: {
            "success": bool,
            "segments": list[dict] (번역된 세그먼트),
            "full_text": str,
            "error": str (실패 시)
        }
    """
    if not segments:
        return {
            "success": True,
            "segments": [],
            "full_text": "",
        }

    translated_segments = []
    total = len(segments)

    # 배치 단위로 번역
    for i in range(0, total, batch_size):
        batch = segments[i:i + batch_size]

        # 배치 텍스트 생성 (번호 붙여서)
        batch_text = "\n".join(
            f"[{j+1}] {seg['text']}"
            for j, seg in enumerate(batch)
        )

        result = translate_text(
            text=batch_text,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )

        if not result["success"]:
            return result

        # 번역 결과 파싱
        translated_lines = result["translated"].split("\n")
        for j, seg in enumerate(batch):
            translated_text = ""
            for line in translated_lines:
                if line.strip().startswith(f"[{j+1}]"):
                    translated_text = line.strip()[len(f"[{j+1}]"):].strip()
                    break

            if not translated_text and j < len(translated_lines):
                # 번호가 없으면 순서대로 매칭
                translated_text = translated_lines[j].strip() if j < len(translated_lines) else seg["text"]

            translated_segments.append({
                **seg,
                "translated": translated_text or seg["text"],
            })

        if on_progress:
            on_progress(min(i + batch_size, total), total)

    full_text = " ".join(seg["translated"] for seg in translated_segments)

    return {
        "success": True,
        "segments": translated_segments,
        "full_text": full_text,
    }


def translate_by_segments(
    segments: list[dict],
    api_key: str,
    base_url: str = "https://api.z.ai/api/coding/paas/v4",
    model: str = "GLM-4.6",
    chunk_duration: int = 60,  # 1분 단위
    max_chars: int = 1500,  # 소프트 리밋 (문장 끝에서 분할)
    max_parallel: int = 3,  # 동시 번역 수
    on_progress: callable = None,
    chunks_dir: str | None = None,  # 청크 저장 디렉토리
) -> dict:
    """
    세그먼트를 시간 기반으로 청크 분할하여 병렬 번역

    Args:
        segments: 자막 세그먼트 리스트
        api_key: API 키
        base_url: API 엔드포인트
        model: 모델명
        chunk_duration: 청크 길이 (초, 기본 1분)
        max_chars: 소프트 리밋 - 문장 끝에서 분할 (기본 1500자)
        max_parallel: 동시 번역 수 (기본 3)
        on_progress: 진행 콜백 (current, total)
        chunks_dir: 청크 저장 디렉토리 (지정 시 청크별 파일로 저장하여 재개 지원)

    Returns:
        dict: {
            "success": bool,
            "translated": str,
            "error": str (실패 시)
        }
    """
    import json
    from pathlib import Path
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if not segments:
        return {"success": True, "translated": ""}

    # 시간 + 문자 수 기반으로 청크 분할
    time_chunks = split_segments_by_time(segments, chunk_duration, max_chars)
    total = len(time_chunks)
    print(f"[번역] 총 {total}개 청크로 분할됨 ({chunk_duration}초/{max_chars}자 문장경계, 병렬 {max_parallel}개)", file=sys.stderr)

    # 청크 디렉토리 설정
    chunks_path = Path(chunks_dir) if chunks_dir else None
    if chunks_path:
        chunks_path.mkdir(parents=True, exist_ok=True)
        # 메타 정보 저장
        meta_file = chunks_path / "_meta.json"
        meta_data = {
            "total": total,
            "chunk_duration": chunk_duration,
            "max_chars": max_chars,
            "model": model,
        }
        meta_file.write_text(json.dumps(meta_data, ensure_ascii=False, indent=2))

    # 청크 텍스트 준비 + 기존 완료 청크 확인
    chunk_data = []
    results = [None] * total
    already_completed = 0

    for i, chunk_segments in enumerate(time_chunks):
        chunk_text = "\n".join(seg["text"] for seg in chunk_segments)
        chunk_start = chunk_segments[0]["start"] if chunk_segments else "00:00:00"

        # 기존 완료 청크 확인
        if chunks_path:
            chunk_file = chunks_path / f"chunk_{i:03d}.txt"
            if chunk_file.exists():
                results[i] = chunk_file.read_text(encoding="utf-8")
                already_completed += 1
                print(f"[번역] 청크 {i+1}/{total} 이미 완료 (스킵)", file=sys.stderr)
                continue

        chunk_data.append({
            "index": i,
            "text": chunk_text,
            "start": chunk_start,
        })

    # 모든 청크가 이미 완료된 경우
    if not chunk_data:
        print(f"[번역] 모든 청크가 이미 완료됨 ({total}개)", file=sys.stderr)
        if on_progress:
            on_progress(total, total)
        return {
            "success": True,
            "translated": "\n".join(results),
        }

    if already_completed > 0:
        print(f"[번역] {already_completed}개 청크 재사용, {len(chunk_data)}개 번역 필요", file=sys.stderr)

    # 병렬 번역
    completed = already_completed
    error_result = None

    def translate_and_save(chunk: dict) -> dict:
        """청크 번역 후 파일 저장"""
        result = translate_text(
            chunk["text"],
            api_key,
            base_url,
            model,
        )

        # 성공 시 파일 저장
        if result["success"] and chunks_path:
            chunk_file = chunks_path / f"chunk_{chunk['index']:03d}.txt"
            chunk_file.write_text(result["translated"], encoding="utf-8")

        return result

    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        futures = {}
        for chunk in chunk_data:
            future = executor.submit(translate_and_save, chunk)
            futures[future] = chunk

        for future in as_completed(futures):
            chunk = futures[future]
            idx = chunk["index"]

            try:
                result = future.result()

                if not result["success"]:
                    error_result = result
                    # 나머지 작업 취소
                    for f in futures:
                        f.cancel()
                    break

                results[idx] = result["translated"]
                completed += 1

                print(f"[번역] 청크 {idx+1}/{total} 완료 ({chunk['start']}~)", file=sys.stderr)

                if on_progress:
                    on_progress(completed, total)

            except Exception as e:
                error_result = {"success": False, "error": str(e)}
                break

    if error_result:
        return error_result

    return {
        "success": True,
        "translated": "\n".join(results),
    }


def translate_full_text(
    text: str,
    api_key: str,
    base_url: str = "https://api.z.ai/api/coding/paas/v4",
    model: str = "GLM-4.6",
    chunk_size: int = 2000,
    on_progress: callable = None,
    segments: list[dict] = None,  # 세그먼트가 있으면 시간 기반 번역 사용
    chunks_dir: str | None = None,  # 청크 저장 디렉토리
) -> dict:
    """
    긴 텍스트를 청크 단위로 번역

    Args:
        text: 번역할 텍스트
        api_key: API 키
        base_url: API 엔드포인트
        model: 모델명
        chunk_size: 청크 크기 (문자 수, 세그먼트 없을 때만 사용)
        on_progress: 진행 콜백 (current, total)
        segments: 자막 세그먼트 (있으면 시간 기반 번역)
        chunks_dir: 청크 저장 디렉토리 (재개 지원)

    Returns:
        dict: {
            "success": bool,
            "translated": str,
            "error": str (실패 시)
        }
    """
    # 세그먼트가 있으면 시간 기반 번역 사용
    if segments:
        return translate_by_segments(
            segments=segments,
            api_key=api_key,
            base_url=base_url,
            model=model,
            on_progress=on_progress,
            chunks_dir=chunks_dir,
        )

    import json
    from pathlib import Path

    # 짧은 텍스트는 바로 번역
    if len(text) <= chunk_size:
        return translate_text(text, api_key, base_url, model)

    # 문장 단위로 청크 분할 (fallback)
    chunks = _split_into_chunks(text, chunk_size)
    total = len(chunks)
    print(f"[번역] 총 {total}개 청크로 분할됨 ({len(text)}자)", file=sys.stderr)

    # 청크 디렉토리 설정
    chunks_path = Path(chunks_dir) if chunks_dir else None
    if chunks_path:
        chunks_path.mkdir(parents=True, exist_ok=True)
        # 메타 정보 저장
        meta_file = chunks_path / "_meta.json"
        meta_data = {
            "total": total,
            "chunk_size": chunk_size,
            "model": model,
            "type": "text_based",
        }
        meta_file.write_text(json.dumps(meta_data, ensure_ascii=False, indent=2))

    # 기존 완료 청크 확인 + 번역
    translated_chunks = [None] * total
    already_completed = 0

    for i, chunk in enumerate(chunks):
        # 기존 완료 청크 확인
        if chunks_path:
            chunk_file = chunks_path / f"chunk_{i:03d}.txt"
            if chunk_file.exists():
                translated_chunks[i] = chunk_file.read_text(encoding="utf-8")
                already_completed += 1
                print(f"[번역] 청크 {i+1}/{total} 이미 완료 (스킵)", file=sys.stderr)
                continue

        print(f"[번역] 청크 {i+1}/{total} 번역 중...", file=sys.stderr)
        result = translate_text(chunk, api_key, base_url, model)

        if not result["success"]:
            return result

        translated_chunks[i] = result["translated"]

        # 청크 파일 저장
        if chunks_path:
            chunk_file = chunks_path / f"chunk_{i:03d}.txt"
            chunk_file.write_text(result["translated"], encoding="utf-8")

        if on_progress:
            on_progress(i + 1, total)

    if already_completed > 0:
        print(f"[번역] {already_completed}개 청크 재사용, {total - already_completed}개 번역 완료", file=sys.stderr)

    return {
        "success": True,
        "translated": "\n".join(translated_chunks),
    }


def _split_into_chunks(text: str, max_size: int) -> list[str]:
    """
    텍스트를 문장 단위로 청크 분할 (문장이 끊어지지 않도록)

    분할 우선순위:
    1. 줄바꿈 (자막의 자연스러운 구분)
    2. 문장 종결 부호 (. ! ? 등)
    3. 쉼표, 세미콜론 등
    """
    import re

    # 1단계: 줄바꿈 기준으로 먼저 분할
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    # 줄이 없으면 문장 단위로 분할
    if not lines:
        # 다양한 문장 종결 부호 지원 (영어, 한국어, 중국어 등)
        sentences = re.split(r'(?<=[.!?。！？])\s*', text)
        lines = [s.strip() for s in sentences if s.strip()]

    chunks = []
    current_chunk = ""

    for line in lines:
        # 현재 줄 자체가 max_size보다 크면 문장/구 단위로 분할
        if len(line) > max_size:
            # 현재 청크가 있으면 먼저 저장
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""

            # 긴 줄을 문장 단위로 분할
            sub_sentences = re.split(r'(?<=[.!?。！？,;，；])\s*', line)
            for sub in sub_sentences:
                sub = sub.strip()
                if not sub:
                    continue
                if len(current_chunk) + len(sub) + 1 <= max_size:
                    current_chunk += (" " if current_chunk else "") + sub
                else:
                    if current_chunk:
                        chunks.append(current_chunk)
                    # 문장 자체가 max_size보다 크면 어쩔 수 없이 단어 단위로 분할
                    if len(sub) > max_size:
                        words = sub.split()
                        current_chunk = ""
                        for word in words:
                            if len(current_chunk) + len(word) + 1 <= max_size:
                                current_chunk += (" " if current_chunk else "") + word
                            else:
                                if current_chunk:
                                    chunks.append(current_chunk)
                                current_chunk = word
                    else:
                        current_chunk = sub
        else:
            # 현재 청크에 추가 가능한지 확인
            if len(current_chunk) + len(line) + 1 <= max_size:
                current_chunk += ("\n" if current_chunk else "") + line
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line

    if current_chunk:
        chunks.append(current_chunk)

    return chunks
