# YouTube Dubbing App

YouTube 영상을 한국어 음성으로 변환하는 앱입니다. Claude Code headless 모드를 활용하여 자막 추출, 번역, TTS를 자동으로 처리합니다.

## 요구사항

- Python 3.10+
- [Claude Code](https://claude.ai/code) 설치 및 인증
- [uv](https://docs.astral.sh/uv/) (권장)

## 설치

```bash
# 저장소 클론
git clone https://github.com/frentis-ai-study/youtube-dubbing-app.git
cd youtube-dubbing-app

# 의존성 설치
uv sync
```

## 실행

```bash
# Streamlit 앱 실행
uv run streamlit run src/dubbing_app/main.py
```

브라우저에서 `http://localhost:8501` 접속

## 사용법

1. **출력 디렉토리 설정** (사이드바)
2. **YouTube URL 입력** (한 줄에 하나씩)
3. **더빙 시작** 버튼 클릭
4. 완료되면 결과 파일 다운로드

## 구조

```
youtube-dubbing-app/
├── pyproject.toml
├── README.md
└── src/
    └── dubbing_app/
        ├── __init__.py
        ├── main.py        # Streamlit UI
        └── runner.py      # Claude Code 호출 래퍼
```

## 동작 방식

```
┌─────────────────────────────────────────┐
│            Streamlit UI                 │
│  • URL 입력, 출력 폴더 지정              │
│  • 병렬 처리, 진행 상황 표시             │
└────────────────┬────────────────────────┘
                 │ subprocess × N
                 ▼
┌─────────────────────────────────────────┐
│        Claude Code (headless)           │
│  • 자막 추출 (yt-dlp / Whisper)         │
│  • 한국어 번역 (Claude 직접 수행)        │
│  • TTS 음성 생성 (edge-tts)             │
└─────────────────────────────────────────┘
```

## 출력 형식

```
~/Dubbing/
└── 2025-12-18-영상제목/
    ├── transcript_original.txt   # 원본 자막
    ├── transcript_korean.txt     # 한국어 번역
    └── audio_korean.mp3          # 한국어 음성
```

## 라이선스

MIT
