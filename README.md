# YouTube Dubbing App

YouTube 영상을 한국어 음성으로 더빙하는 macOS 앱입니다.

## 다운로드

**[최신 릴리즈 다운로드](https://github.com/frentis-ai-study/youtube-dubbing-app/releases/latest)**

DMG 파일을 다운로드하여 Applications 폴더로 드래그하면 설치 완료!

## 주요 기능

- YouTube URL에서 자막 자동 추출
- Ollama (로컬 AI)를 활용한 한국어 번역
- Edge TTS로 자연스러운 음성 합성
- 청크별 병렬 처리로 빠른 변환
- 일시정지/재개 지원
- 5가지 테마 지원

## 요구사항

- macOS (Apple Silicon / Intel)
- [Ollama](https://ollama.ai) - 앱 실행 시 자동 설치 안내

## 개발 환경 설정

```bash
# 저장소 클론
git clone https://github.com/frentis-ai-study/youtube-dubbing-app.git
cd youtube-dubbing-app

# 의존성 설치
uv sync

# 개발 모드 실행
uv run flet run src/dubbing_app/main.py
```

## 빌드

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

## 사용법

1. 앱 실행
2. YouTube URL 입력 (여러 개 가능)
3. "추가" 버튼 클릭
4. "전체 시작" 버튼으로 더빙 시작
5. 완료 후 재생 버튼으로 결과 확인

## 구조

```
youtube-dubbing-app/
├── pyproject.toml
├── README.md
└── src/
    ├── main.py                 # Flet 빌드 엔트리포인트
    └── dubbing_app/
        ├── __init__.py
        ├── main.py             # Flet UI
        └── core/
            ├── config.py       # 설정 관리
            ├── downloader.py   # YouTube 자막 추출
            ├── translator.py   # Ollama 번역
            ├── tts.py          # Edge TTS 음성 합성
            ├── setup.py        # Ollama 온보딩
            └── job_manager.py  # 작업 큐 관리
```

## 동작 방식

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

## 출력 형식

```
~/Dubbing/
└── 영상제목/
    ├── segments.json           # 청크 정보 (재개용)
    ├── transcript_original.txt # 원본 자막
    ├── transcript_korean.txt   # 한국어 번역
    └── 영상제목.mp3            # 한국어 음성
```

## 라이선스

MIT
