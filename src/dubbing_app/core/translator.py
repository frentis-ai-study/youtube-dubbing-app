"""z.ai GLM 번역 모듈 (OpenAI 호환)"""

import re
import sys
import httpx
from openai import OpenAI


# 번역 스타일별 프롬프트
TRANSLATION_PROMPTS = {
    "faithful": {
        "base": """당신은 전문 번역가입니다. YouTube 자동 자막을 정제하고 {target_lang}로 번역합니다.

## 1단계: 자동 자막 정제 (번역 전 처리)
YouTube 자동 자막은 다음 문제가 있습니다:
- 같은 문장이 여러 번 반복됨 (중복 제거 필요)
- 문장이 중간에 끊겨서 다음 줄에 이어짐 (병합 필요)
- 필러: um, uh, you know, like, basically, actually 등 (제거)
- 철자 오류, 반복 단어 (I I → I)

반드시 중복을 제거하고 완전한 문장으로 재구성하세요.

## 2단계: 번역 (원문 충실 모드)
1. 원문의 의미와 구조를 최대한 유지
2. 전문 용어는 정확하게 번역
3. 구어체로 자연스럽게 변환 (TTS용)
4. 번역문만 출력 (설명/원문 없이)""",
    },
    "natural": {
        "base": """당신은 더빙 전문 번역가입니다. YouTube 자동 자막을 정제하고 자연스러운 {target_lang} 더빙 스크립트로 변환합니다.

## 1단계: 자동 자막 정제 (번역 전 처리)
YouTube 자동 자막은 다음 문제가 있습니다:
- 같은 문장이 여러 번 반복됨 (중복 제거 필요)
- 문장이 중간에 끊겨서 다음 줄에 이어짐 (병합 필요)
- 필러: um, uh, you know, like, basically, actually 등 (제거)
- 철자 오류, 반복 단어 (I I → I)

반드시 중복을 제거하고 완전한 문장으로 재구성하세요.

## 2단계: 번역 (자연스러운 더빙 모드)
1. 한국어 화자가 말하듯이 자연스럽게 변환
2. 문장 구조를 한국어에 맞게 재배치
3. 불필요한 수식어 제거, 핵심만 전달
4. 이전 문맥을 고려한 연결어 사용
5. 번역문만 출력 (설명/원문 없이)""",
        "tones": {
            "lecture": """
## 톤: 강의체
- 존댓말 사용 (~입니다, ~해요, ~거든요)
- 청자를 배려하는 표현 (여러분, ~해볼게요)
- 설명적이고 친근한 어조""",
            "casual": """
## 톤: 대화체
- 반말 또는 친근한 존댓말 (~야, ~거든, ~잖아)
- 감탄사/추임새 자연스럽게 사용
- 일상 대화처럼 가볍게""",
            "formal": """
## 톤: 뉴스체
- 격식체 존댓말 (~습니다, ~됩니다)
- 객관적이고 정제된 표현
- 간결하고 명확한 문장""",
        },
    },
}


def get_translation_prompt(
    style: str = "natural",
    tone: str = "lecture",
    source_lang: str = "영어",
    target_lang: str = "한국어",
) -> str:
    """
    번역 스타일과 톤에 따른 시스템 프롬프트 생성

    Args:
        style: "faithful" (원문 충실) | "natural" (자연스러운 더빙)
        tone: "lecture" (강의체) | "casual" (대화체) | "formal" (뉴스체)
        source_lang: 원본 언어
        target_lang: 타겟 언어

    Returns:
        str: 시스템 프롬프트
    """
    if style not in TRANSLATION_PROMPTS:
        style = "natural"

    prompt_config = TRANSLATION_PROMPTS[style]
    base_prompt = prompt_config["base"].format(
        source_lang=source_lang,
        target_lang=target_lang,
    )

    # natural 스타일은 톤 추가
    if style == "natural" and "tones" in prompt_config:
        if tone not in prompt_config["tones"]:
            tone = "lecture"
        base_prompt += prompt_config["tones"][tone]

    return base_prompt


def preprocess_segments(segments: list[dict]) -> list[dict]:
    """
    자막 세그먼트 전처리: 중복 제거 + 문장 병합

    YouTube 자동 자막 특성:
    - 같은 텍스트가 여러 세그먼트에 걸쳐 반복됨
    - 문장이 세그먼트 경계에서 끊김

    Args:
        segments: 원본 자막 세그먼트 리스트

    Returns:
        정제된 세그먼트 리스트
    """
    if not segments:
        return []

    # 1단계: 중복 텍스트 제거
    cleaned = []
    prev_text = ""

    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue

        # 이전 세그먼트와 겹치는 부분 제거
        if prev_text and text.startswith(prev_text):
            # 완전히 포함된 경우 스킵
            if text == prev_text:
                continue
            # 앞부분이 겹치면 새로운 부분만 추출
            text = text[len(prev_text):].strip()
            if not text:
                continue

        # 이전 텍스트가 현재 텍스트에 포함된 경우
        if prev_text and prev_text in text:
            # 중복 부분 제거
            text = text.replace(prev_text, "", 1).strip()
            if not text:
                continue

        cleaned.append({
            **seg,
            "text": text,
        })
        prev_text = seg.get("text", "").strip()  # 원본 텍스트로 비교

    # 2단계: 짧은 세그먼트 병합 (문장 완성)
    merged = []
    buffer = {"text": "", "start": "", "end": ""}

    for seg in cleaned:
        text = seg.get("text", "")

        if not buffer["text"]:
            buffer = {
                "text": text,
                "start": seg.get("start", ""),
                "end": seg.get("end", ""),
            }
        else:
            # 이전 버퍼에 추가
            buffer["text"] += " " + text
            buffer["end"] = seg.get("end", "")

        # 문장 끝이면 병합 완료
        if _is_sentence_end(buffer["text"]) or len(buffer["text"]) > 200:
            merged.append(buffer)
            buffer = {"text": "", "start": "", "end": ""}

    # 남은 버퍼 추가
    if buffer["text"]:
        merged.append(buffer)

    print(f"[전처리] {len(segments)}개 → {len(merged)}개 세그먼트 (중복 제거 + 병합)", file=sys.stderr)
    return merged


def remove_duplicate_lines(text: str) -> str:
    """
    번역 결과에서 연속 중복 문장 제거

    Args:
        text: 번역된 텍스트

    Returns:
        중복 제거된 텍스트
    """
    lines = text.split('\n')
    result = []
    prev = ""

    for line in lines:
        stripped = line.strip()
        # 빈 줄은 유지
        if not stripped:
            result.append(line)
            prev = ""
            continue

        # 이전 줄과 같으면 스킵
        if stripped == prev:
            continue

        # 이전 줄이 현재 줄에 포함되면 현재 줄만 사용 (더 긴 문장 우선)
        if prev and prev in stripped:
            if result:
                result[-1] = line
            prev = stripped
            continue

        # 현재 줄이 이전 줄에 포함되면 스킵 (더 긴 문장 유지)
        if prev and stripped in prev:
            continue

        result.append(line)
        prev = stripped

    return '\n'.join(result)


def remove_fillers(text: str) -> str:
    """
    필러 및 반복 표현 제거

    Args:
        text: 원본 텍스트

    Returns:
        정제된 텍스트
    """
    import re

    # 영어 필러
    fillers = [
        r'\b(um|uh|er|ah|like|you know|I mean|so|well|basically|actually|literally)\b',
        r'\b(kind of|sort of|right\?|okay\?|yeah\?)\b',
    ]

    result = text
    for pattern in fillers:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE)

    # 연속 공백 정리
    result = re.sub(r'\s+', ' ', result).strip()

    # 반복 단어 제거 (I I → I, the the → the)
    result = re.sub(r'\b(\w+)\s+\1\b', r'\1', result, flags=re.IGNORECASE)

    return result


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
    translation_style: str = "natural",
    translation_tone: str = "lecture",
    prev_context: str = "",  # 이전 청크의 마지막 번역 (컨텍스트용)
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

            system_prompt = get_translation_prompt(
                style=translation_style,
                tone=translation_tone,
                source_lang=source_lang,
                target_lang=target_lang,
            )

            # 컨텍스트가 있으면 user 메시지에 포함
            if prev_context:
                user_content = f"""[이전 번역 컨텍스트 - 문맥 연결용, 다시 번역하지 마세요]
{prev_context}

[번역할 자막]
{text}"""
            else:
                user_content = text

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
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
    translation_style: str = "natural",
    translation_tone: str = "lecture",
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

    # 전처리: 중복 제거 + 문장 병합 + 필러 제거
    processed_segments = preprocess_segments(segments)

    # 각 세그먼트 텍스트에서 필러 제거
    for seg in processed_segments:
        seg["text"] = remove_fillers(seg.get("text", ""))

    # 시간 + 문자 수 기반으로 청크 분할
    time_chunks = split_segments_by_time(processed_segments, chunk_duration, max_chars)
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

    # 청크 텍스트 준비 + 기존 완료 청크 확인 + 컨텍스트 오버랩
    chunk_data = []
    results = [None] * total
    already_completed = 0
    prev_chunk_tail = ""  # 이전 청크의 마지막 2문장 (컨텍스트용)

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
                # 다음 청크 컨텍스트용으로 마지막 2문장 저장
                lines = chunk_text.split("\n")
                prev_chunk_tail = "\n".join(lines[-2:]) if len(lines) >= 2 else chunk_text
                continue

        chunk_data.append({
            "index": i,
            "text": chunk_text,
            "start": chunk_start,
            "prev_context": prev_chunk_tail,  # 이전 청크 원문 컨텍스트
        })

        # 다음 청크 컨텍스트용으로 마지막 2문장 저장
        lines = chunk_text.split("\n")
        prev_chunk_tail = "\n".join(lines[-2:]) if len(lines) >= 2 else chunk_text

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
            translation_style=translation_style,
            translation_tone=translation_tone,
            prev_context=chunk.get("prev_context", ""),
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

    # 후처리: 연속 중복 문장 제거
    final_text = "\n".join(results)
    final_text = remove_duplicate_lines(final_text)
    print(f"[후처리] 연속 중복 문장 제거 완료", file=sys.stderr)

    return {
        "success": True,
        "translated": final_text,
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
    translation_style: str = "natural",
    translation_tone: str = "lecture",
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
            translation_style=translation_style,
            translation_tone=translation_tone,
        )

    import json
    from pathlib import Path

    # 짧은 텍스트는 바로 번역
    if len(text) <= chunk_size:
        return translate_text(
            text, api_key, base_url, model,
            translation_style=translation_style,
            translation_tone=translation_tone,
        )

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
        result = translate_text(
            chunk, api_key, base_url, model,
            translation_style=translation_style,
            translation_tone=translation_tone,
        )

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
