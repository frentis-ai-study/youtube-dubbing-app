# YouTube Dubbing App

[![Release](https://img.shields.io/github/v/release/frentis-ai-study/youtube-dubbing-app?style=flat-square)](https://github.com/frentis-ai-study/youtube-dubbing-app/releases/latest)
[![License](https://img.shields.io/github/license/frentis-ai-study/youtube-dubbing-app?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS-blue?style=flat-square)](https://github.com/frentis-ai-study/youtube-dubbing-app/releases)
[![Python](https://img.shields.io/badge/python-3.10+-green?style=flat-square)](https://www.python.org/)

YouTube 영상의 자막을 추출하고 한국어로 번역하여 음성으로 변환하는 macOS 네이티브 앱입니다.

## Download

**[최신 버전 다운로드](https://github.com/frentis-ai-study/youtube-dubbing-app/releases/latest)**

DMG 파일을 다운로드하여 Applications 폴더로 드래그하면 설치 완료!

## Features

| 기능 | 설명 |
|------|------|
| 자막 추출 | YouTube URL에서 자동으로 자막 추출 (yt-dlp) |
| AI 번역 | Ollama 기반 로컬 AI 번역 (gemma3) |
| 음성 합성 | Edge TTS를 활용한 자연스러운 한국어 음성 |
| 병렬 처리 | 청크 단위 병렬 번역으로 빠른 처리 속도 |
| 작업 관리 | 일시정지, 재개, 재시도 지원 |
| 테마 | 5가지 UI 테마 제공 |

## System Requirements

- macOS 12.0 이상 (Apple Silicon / Intel)
- [Ollama](https://ollama.ai) - 앱 실행 시 자동 설치 안내

## Quick Start

1. [DMG 다운로드](https://github.com/frentis-ai-study/youtube-dubbing-app/releases/latest)
2. Applications 폴더로 앱 드래그
3. 앱 실행 후 Ollama 설치 안내 따르기
4. YouTube URL 입력 → 추가 → 전체 시작
5. 완료 후 재생 버튼으로 결과 확인

## Development

### 개발 환경 설정

```bash
# 저장소 클론
git clone https://github.com/frentis-ai-study/youtube-dubbing-app.git
cd youtube-dubbing-app

# 의존성 설치
uv sync

# 개발 모드 실행
uv run flet run src/dubbing_app/main.py
```

### 빌드

```bash
# macOS 앱 빌드
uv run flet build macos

# DMG 인스톨러 생성
mkdir -p dist/dmg-temp
cp -R "build/macos/YouTube Dubbing.app" dist/dmg-temp/
ln -s /Applications dist/dmg-temp/Applications
hdiutil create -volname "YouTube Dubbing" -srcfolder dist/dmg-temp -ov -format UDZO dist/YouTube-Dubbing.dmg
rm -rf dist/dmg-temp
```

## Architecture

```
youtube-dubbing-app/
├── pyproject.toml
├── README.md
└── src/
    ├── main.py                 # Flet 빌드 엔트리포인트
    └── dubbing_app/
        ├── main.py             # Flet UI
        └── core/
            ├── config.py       # 설정 관리
            ├── downloader.py   # YouTube 자막 추출
            ├── translator.py   # Ollama 번역
            ├── tts.py          # Edge TTS 음성 합성
            ├── setup.py        # Ollama 온보딩
            └── job_manager.py  # 작업 큐 관리
```

### 처리 흐름

```
┌─────────────────────────────────────────┐
│              Flet UI                    │
│  • URL 입력, 작업 관리                   │
│  • 진행 상황 표시, 테마 설정              │
└────────────────┬────────────────────────┘
                 │ 비동기 작업 큐
                 ▼
┌─────────────────────────────────────────┐
│           Core Modules                  │
│  • 자막 추출 (yt-dlp)                   │
│  • 한국어 번역 (Ollama - gemma3)        │
│  • TTS 음성 생성 (edge-tts)             │
└─────────────────────────────────────────┘
```

## Output

```
~/Dubbing/
└── 영상제목/
    ├── segments.json           # 청크 정보 (재개용)
    ├── transcript_original.txt # 원본 자막
    ├── transcript_korean.txt   # 한국어 번역
    └── 영상제목.mp3            # 한국어 음성
```

## Tech Stack

| 분류 | 기술 |
|------|------|
| UI Framework | [Flet](https://flet.dev) (Flutter 기반 Python UI) |
| AI 번역 | [Ollama](https://ollama.ai) (gemma3) |
| 음성 합성 | [Edge TTS](https://github.com/rany2/edge-tts) |
| 자막 추출 | [yt-dlp](https://github.com/yt-dlp/yt-dlp) |
| 패키지 관리 | [uv](https://docs.astral.sh/uv/) |

## Contributing

이슈와 PR은 언제든 환영합니다.

## About

**Frentis Co., Ltd.**
대표: 윤성열
https://frentis.co.kr

## License

[MIT](LICENSE)
