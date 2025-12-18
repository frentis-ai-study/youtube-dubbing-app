"""YouTube Dubbing App - FluentFlet UI with Async Job Queue"""

import asyncio
import json
import subprocess
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import flet as ft
import flet_audio

from dubbing_app.core.config import Config, load_config, save_config
from dubbing_app.core.theme import THEMES, get_theme, apply_theme, get_status_color, AppTheme
from dubbing_app.core.tts import KOREAN_VOICES
from dubbing_app.core.transcript import get_video_info
from dubbing_app.runner import DubbingJob, generate_job_id, run_dubbing, PauseController


# Toast severity
class ToastSeverity:
    INFORMATIONAL = "info"
    SUCCESS = "success"
    WARNING = "warning"
    CRITICAL = "error"


def styled_button(
    text: str,
    on_click=None,
    primary: bool = False,
    theme: AppTheme = None,
    icon: str = None,
) -> ft.ElevatedButton:
    """테마 적용된 스타일 버튼"""
    if theme and primary:
        return ft.ElevatedButton(
            text=text,
            icon=icon,
            on_click=on_click,
            bgcolor=theme.accent,
            color=theme.text_primary,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.padding.symmetric(horizontal=20, vertical=12),
            ),
        )
    elif theme:
        return ft.ElevatedButton(
            text=text,
            icon=icon,
            on_click=on_click,
            bgcolor=theme.surface,
            color=theme.text_primary,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.padding.symmetric(horizontal=16, vertical=10),
                side=ft.BorderSide(1, theme.border),
            ),
        )
    return ft.ElevatedButton(text=text, icon=icon, on_click=on_click)


def styled_textfield(
    placeholder: str = "",
    width: int = None,
    theme: AppTheme = None,
    on_submit=None,
    **kwargs,
) -> ft.TextField:
    """테마 적용된 스타일 텍스트필드"""
    return ft.TextField(
        hint_text=placeholder,
        width=width,
        border_color=theme.border if theme else None,
        focused_border_color=theme.accent if theme else None,
        cursor_color=theme.accent if theme else None,
        text_style=ft.TextStyle(color=theme.text_primary if theme else None),
        hint_style=ft.TextStyle(color=theme.text_muted if theme else None),
        bgcolor=theme.surface if theme else None,
        border_radius=8,
        content_padding=ft.padding.symmetric(horizontal=16, vertical=12),
        on_submit=on_submit,
        **kwargs,
    )


# 상수
JOBS_FILE = Path.home() / ".dubbing_app" / "jobs.json"
PRESETS = {
    "z.ai": {
        "base_url": "https://api.z.ai/api/coding/paas/v4",
        "models": ["GLM-4.6", "GLM-4.5", "GLM-4.5-air"],
        "default_model": "GLM-4.6",
    },
    "Ollama": {
        "base_url": "http://localhost:11434/v1",
        "models": [],
        "default_model": "gemma3:latest",
    },
}


def get_ollama_models() -> list[str]:
    """Ollama 설치된 모델 목록 가져오기"""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")[1:]
            return [line.split()[0] for line in lines if line.strip()]
    except Exception:
        pass
    return []


def check_ollama_running() -> tuple[bool, str]:
    """Ollama 실행 상태 확인"""
    import httpx
    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=3)
        if response.status_code == 200:
            return True, "Ollama 연결됨"
        return False, f"Ollama 응답 오류: {response.status_code}"
    except httpx.ConnectError:
        return False, "Ollama가 실행되지 않았습니다. 'ollama serve'를 실행하세요."
    except Exception as e:
        return False, f"Ollama 연결 실패: {str(e)}"


def check_ai_config(config: Config) -> tuple[bool, str]:
    """AI 설정 상태 확인"""
    is_ollama = "localhost:11434" in config.zai_base_url

    if is_ollama:
        # Ollama 모드
        ok, msg = check_ollama_running()
        if not ok:
            return False, msg

        models = get_ollama_models()
        if not models:
            return False, "Ollama에 설치된 모델이 없습니다. 'ollama pull gemma3'을 실행하세요."

        if config.zai_model and config.zai_model not in models:
            return False, f"모델 '{config.zai_model}'이 설치되지 않았습니다."

        return True, f"Ollama 준비됨 ({len(models)}개 모델)"
    else:
        # z.ai 또는 외부 API 모드
        if not config.zai_api_key or config.zai_api_key == "ollama":
            return False, "API 키가 설정되지 않았습니다."

        if not config.zai_model:
            return False, "모델이 설정되지 않았습니다."

        return True, f"API 준비됨 ({config.zai_model})"


def load_jobs() -> list[dict]:
    """저장된 작업 목록 로드 (중단된 작업 복구 포함)"""
    try:
        if JOBS_FILE.exists():
            jobs = json.loads(JOBS_FILE.read_text())
            for job in jobs:
                if job.get("status") == "running":
                    job["status"] = "pending"
                    job["current_step"] = "중단됨 - 재시작 대기"
                    job["progress"] = 0
            return jobs
    except Exception:
        pass
    return []


def save_jobs(jobs: list[dict]):
    """작업 목록 저장"""
    try:
        JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        JOBS_FILE.write_text(json.dumps(jobs, ensure_ascii=False, indent=2, default=str))
    except Exception:
        pass


class JobCard(ft.Container):
    """개별 작업 카드 컴포넌트 (FluentFlet 스타일)"""

    def __init__(
        self,
        job: dict,
        theme: AppTheme,
        on_delete,
        on_retry,
        on_start_single=None,
        page=None,
        on_play=None,
        on_pause=None,
        on_resume=None,
        on_cancel=None,
        playing_audio_path: str | None = None,
        is_audio_playing: bool = False,
    ):
        self.job = job
        self.theme = theme
        self.on_delete = on_delete
        self.on_retry = on_retry
        self.on_start_single = on_start_single
        self.on_play = on_play
        self.on_pause = on_pause
        self.on_resume = on_resume
        self.on_cancel = on_cancel
        self.page = page
        self.playing_audio_path = playing_audio_path
        self.is_audio_playing = is_audio_playing

        status = job["status"]
        status_color = get_status_color(theme, status)

        # 상태 아이콘
        status_icons = {
            "pending": ft.Icons.HOURGLASS_EMPTY,
            "running": ft.Icons.SYNC,
            "paused": ft.Icons.PAUSE_CIRCLE,
            "completed": ft.Icons.CHECK_CIRCLE,
            "error": ft.Icons.ERROR,
            "cancelled": ft.Icons.CANCEL,
        }
        status_icon = status_icons.get(status, ft.Icons.HELP)

        # 영상 정보
        video_info = job.get("video_info", {})
        title = video_info.get("title", "제목 로딩 중...")
        uploader = video_info.get("uploader", "")
        thumbnail = video_info.get("thumbnail", "")
        duration = video_info.get("duration", 0)
        description = video_info.get("description", "")
        url = job.get("url", "")

        # 재생시간 포맷
        duration_str = ""
        if duration:
            mins, secs = divmod(duration, 60)
            hours, mins = divmod(mins, 60)
            if hours:
                duration_str = f"{hours}:{mins:02d}:{secs:02d}"
            else:
                duration_str = f"{mins}:{secs:02d}"

        # 진행률 바
        progress_bar = ft.ProgressBar(
            value=job.get("progress", 0) / 100,
            expand=True,
            color=theme.accent if status == "running" else status_color,
            bgcolor=theme.border,
        )

        current_step = job.get("current_step", "")

        # 액션 버튼들
        actions = []

        if job["status"] == "pending":
            actions.append(
                ft.IconButton(
                    icon=ft.Icons.PLAY_ARROW_ROUNDED,
                    tooltip="시작",
                    icon_color=theme.success,
                    icon_size=20,
                    on_click=lambda e: on_start_single(job) if on_start_single else None,
                )
            )
        elif job["status"] == "running":
            # 실행 중: 일시 정지 버튼
            actions.append(
                ft.IconButton(
                    icon=ft.Icons.PAUSE_ROUNDED,
                    tooltip="일시 정지",
                    icon_color=theme.warning,
                    icon_size=20,
                    on_click=lambda e: on_pause(job) if on_pause else None,
                )
            )
        elif job["status"] == "paused":
            # 일시 정지 중: 재개, 취소 버튼
            actions.append(
                ft.IconButton(
                    icon=ft.Icons.PLAY_ARROW_ROUNDED,
                    tooltip="재개",
                    icon_color=theme.success,
                    icon_size=20,
                    on_click=lambda e: on_resume(job) if on_resume else None,
                )
            )
            actions.append(
                ft.IconButton(
                    icon=ft.Icons.STOP_ROUNDED,
                    tooltip="취소",
                    icon_color=theme.error,
                    icon_size=20,
                    on_click=lambda e: on_cancel(job) if on_cancel else None,
                )
            )
        elif job["status"] == "completed":
            result_files = job.get("result_files", [])
            audio_file = next((f for f in result_files if f.endswith(".mp3")), None)

            if audio_file and on_play:
                # 현재 이 파일이 재생 중인지 확인
                is_this_playing = (
                    self.playing_audio_path == audio_file and self.is_audio_playing
                )
                actions.append(
                    ft.IconButton(
                        icon=ft.Icons.PAUSE_CIRCLE_FILLED if is_this_playing else ft.Icons.PLAY_CIRCLE_FILLED,
                        tooltip="일시정지" if is_this_playing else "재생",
                        icon_color=theme.accent,
                        icon_size=22,
                        on_click=lambda e, f=audio_file: on_play(f),
                    )
                )

            output_dir = job.get("output_dir", "")
            if output_dir:
                actions.append(
                    ft.IconButton(
                        icon=ft.Icons.FOLDER_OPEN_ROUNDED,
                        tooltip="폴더 열기",
                        icon_color=theme.text_secondary,
                        icon_size=20,
                        on_click=lambda e, d=output_dir: self.open_folder(d),
                    )
                )
        elif job["status"] == "error":
            actions.append(
                ft.IconButton(
                    icon=ft.Icons.REFRESH_ROUNDED,
                    tooltip="재시도",
                    icon_color=theme.warning,
                    icon_size=20,
                    on_click=lambda e: on_retry(job),
                )
            )

        actions.append(
            ft.IconButton(
                icon=ft.Icons.CLOSE_ROUNDED,
                tooltip="삭제",
                icon_color=theme.text_muted,
                icon_size=18,
                on_click=lambda e: on_delete(job),
            )
        )

        # 썸네일 (클릭 시 YouTube로 이동)
        thumbnail_widget = ft.Container(
            content=ft.Image(
                src=thumbnail,
                width=140,
                height=79,
                fit=ft.ImageFit.COVER,
                border_radius=ft.border_radius.all(8),
            )
            if thumbnail
            else ft.Container(
                width=140,
                height=79,
                bgcolor=theme.surface,
                border_radius=8,
                content=ft.Icon(ft.Icons.VIDEO_LIBRARY, color=theme.text_muted, size=32),
                alignment=ft.alignment.center,
            ),
            on_click=lambda e: self.open_url(url),
            tooltip="YouTube에서 보기",
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )

        # 제목 텍스트
        title_text = ft.Text(
            title[:50] + "..." if len(title) > 50 else title,
            size=14,
            weight=ft.FontWeight.W_600,
            color=theme.text_primary,
            overflow=ft.TextOverflow.ELLIPSIS,
            max_lines=1,
        )

        super().__init__(
            content=ft.Row(
                [
                    # 썸네일
                    thumbnail_widget,
                    # 영상 정보 + 진행 상태
                    ft.Column(
                        [
                            # 제목 + 상태 아이콘 + 액션
                            ft.Row(
                                [
                                    ft.Icon(status_icon, size=16, color=status_color),
                                    ft.Container(
                                        content=title_text,
                                        expand=True,
                                        on_click=lambda e: self.open_url(url),
                                        tooltip=title,
                                    ),
                                    ft.Row(actions, spacing=0),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            # 채널 + 재생시간
                            ft.Row(
                                [
                                    ft.Text(
                                        uploader,
                                        size=11,
                                        color=theme.text_secondary,
                                    )
                                    if uploader
                                    else ft.Container(),
                                    ft.Container(
                                        content=ft.Text(
                                            duration_str,
                                            size=10,
                                            color=theme.text_muted,
                                        ),
                                        bgcolor=theme.surface,
                                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                        border_radius=4,
                                    )
                                    if duration_str
                                    else ft.Container(),
                                ],
                                spacing=10,
                            ),
                            # 설명 (1줄)
                            ft.Text(
                                description[:100] + "..." if len(description) > 100 else description,
                                size=11,
                                color=theme.text_muted,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            )
                            if description
                            else ft.Container(),
                            # 진행률
                            ft.Row(
                                [
                                    progress_bar,
                                    ft.Text(
                                        f"{job.get('progress', 0)}%",
                                        size=11,
                                        color=theme.text_secondary,
                                        width=35,
                                    ),
                                ],
                                spacing=8,
                            ),
                            # 현재 단계
                            ft.Text(
                                current_step or status,
                                size=11,
                                color=theme.text_muted,
                                max_lines=1,
                            ),
                        ],
                        spacing=4,
                        expand=True,
                    ),
                ],
                spacing=16,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            padding=16,
            border_radius=12,
            bgcolor=theme.card_bg,
            border=ft.border.all(1, theme.border),
            margin=ft.margin.only(bottom=10),
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
            on_hover=lambda e: self._on_hover(e),
        )

    def _on_hover(self, e):
        """호버 효과"""
        if not self.theme:
            return
        try:
            if e.data == "true":
                self.border = ft.border.all(1, self.theme.accent)
            else:
                self.border = ft.border.all(1, self.theme.border)
            self.update()
        except Exception:
            pass

    def open_folder(self, path: str):
        try:
            subprocess.run(["open", path])
        except Exception:
            pass

    def open_url(self, url: str):
        try:
            subprocess.run(["open", url])
        except Exception:
            pass


class DubbingApp:
    """메인 앱 클래스"""

    def __init__(self, page: ft.Page):
        self.page = page
        self.config = load_config()
        self.theme = get_theme(self.config.theme)
        self.jobs: list[dict] = load_jobs()
        self.ollama_models: list[str] = []
        self.job_queue: asyncio.Queue = asyncio.Queue()
        self.worker_running = False
        self.current_audio = None
        self.current_audio_path: str | None = None
        self.is_playing = False
        self.pause_controllers: dict[str, PauseController] = {}  # job_id -> PauseController

        self.setup_page()
        self.build_ui()
        self.check_ai_on_startup()

    def check_ai_on_startup(self):
        """앱 시작 시 AI 설정 상태 확인"""
        ok, msg = check_ai_config(self.config)
        if not ok:
            # 문제가 있으면 경고 + 설정 다이얼로그 표시
            self.show_config_warning(msg)

    def show_config_warning(self, message: str):
        """설정 경고 다이얼로그"""
        theme = self.theme

        def open_settings(e):
            self.page.close(dlg)
            self.show_settings(None)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=theme.warning, size=28),
                    ft.Text("AI 엔진 설정 필요", color=theme.text_primary, weight=ft.FontWeight.BOLD),
                ],
                spacing=10,
            ),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            message,
                            color=theme.text_secondary,
                            size=14,
                        ),
                        ft.Container(height=16),
                        ft.Text(
                            "번역 기능을 사용하려면 AI 엔진을 설정해주세요.",
                            color=theme.text_muted,
                            size=12,
                        ),
                    ],
                    spacing=8,
                ),
                width=350,
                padding=8,
            ),
            bgcolor=theme.card_bg,
            actions=[
                ft.TextButton("나중에", on_click=lambda e: self.page.close(dlg)),
                styled_button("설정 열기", primary=True, theme=theme, on_click=open_settings),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self.page.open(dlg)

    def setup_page(self):
        """페이지 기본 설정"""
        self.page.title = "YouTube Dubbing"
        self.page.window.width = 750
        self.page.window.height = 850
        self.page.padding = 0

        apply_theme(self.page, self.theme)

    def play_audio(self, audio_path: str):
        """MP3 파일 재생/일시정지"""
        if not audio_path or not Path(audio_path).exists():
            self.show_toast("오디오 파일을 찾을 수 없습니다", severity=ToastSeverity.CRITICAL)
            return

        if self.current_audio and self.current_audio_path == audio_path:
            if self.is_playing:
                self.current_audio.pause()
                self.is_playing = False
                self.show_toast("일시정지", severity=ToastSeverity.INFORMATIONAL)
            else:
                self.current_audio.resume()
                self.is_playing = True
                self.show_toast("재생 중...", severity=ToastSeverity.INFORMATIONAL)
            self.refresh_jobs_list()
            return

        if self.current_audio:
            self.current_audio.pause()
            self.page.overlay.remove(self.current_audio)

        self.current_audio_path = audio_path
        self.current_audio = flet_audio.Audio(
            src=audio_path,
            autoplay=True,
            on_state_changed=lambda e: self._on_audio_state_changed(e),
        )
        self.page.overlay.append(self.current_audio)
        self.page.update()
        self.is_playing = True

        filename = Path(audio_path).stem
        self.show_toast(f"재생: {filename[:30]}...", severity=ToastSeverity.SUCCESS)
        self.refresh_jobs_list()

    def _on_audio_state_changed(self, e):
        if e.data == "completed":
            self.is_playing = False
            self.current_audio_path = None
            self.show_toast("재생 완료", severity=ToastSeverity.SUCCESS)
            self.refresh_jobs_list()

    def on_start_all_click(self, e):
        self.page.run_task(self.start_all_jobs)

    def build_ui(self):
        """UI 구성"""
        theme = self.theme

        # URL 입력
        self.url_input = styled_textfield(
            placeholder="YouTube URL을 입력하세요...",
            width=500,
            theme=theme,
            on_submit=lambda e: self.add_job(e),
        )

        # 진행중 탭 - 작업 목록
        self.pending_list = ft.Column(
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        # 완료됨 탭 - 재생 목록
        self.completed_list = ft.Column(
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        # 상태 표시
        is_ollama = "localhost:11434" in self.config.zai_base_url
        mode_icon = "assets/ollama.png" if is_ollama else "assets/zai.png"
        mode_text = f"Ollama ({self.config.zai_model})" if is_ollama else f"z.ai ({self.config.zai_model})"

        self.status_text = ft.Text(mode_text, size=12, color=theme.text_muted)

        # 탭 구성
        self.tabs = ft.Tabs(
            selected_index=0,
            animation_duration=200,
            expand=True,
            label_color=theme.primary,
            unselected_label_color=theme.text_muted,
            indicator_color=theme.accent,
            indicator_border_radius=4,
            divider_color=theme.divider,
            tabs=[
                ft.Tab(
                    text="진행중",
                    icon=ft.Icons.HOURGLASS_EMPTY_ROUNDED,
                    content=ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        styled_button(
                                            "전체 시작",
                                            primary=True,
                                            theme=theme,
                                            on_click=self.on_start_all_click,
                                        ),
                                    ],
                                    alignment=ft.MainAxisAlignment.END,
                                ),
                                ft.Container(height=8),
                                ft.Container(
                                    content=self.pending_list,
                                    expand=True,
                                    border_radius=12,
                                    padding=12,
                                    bgcolor=theme.surface,
                                ),
                            ],
                            expand=True,
                        ),
                        padding=16,
                        expand=True,
                    ),
                ),
                ft.Tab(
                    text="완료됨",
                    icon=ft.Icons.CHECK_CIRCLE_ROUNDED,
                    content=ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        styled_button(
                                            "전체 삭제",
                                            theme=theme,
                                            on_click=self.clear_completed,
                                        ),
                                    ],
                                    alignment=ft.MainAxisAlignment.END,
                                ),
                                ft.Container(height=8),
                                ft.Container(
                                    content=self.completed_list,
                                    expand=True,
                                    border_radius=12,
                                    padding=12,
                                    bgcolor=theme.surface,
                                ),
                            ],
                            expand=True,
                        ),
                        padding=16,
                        expand=True,
                    ),
                ),
            ],
        )

        # 헤더
        header = ft.Container(
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.MOVIE_FILTER_ROUNDED, size=28, color=theme.primary),
                            ft.Text(
                                "YouTube Dubbing",
                                size=22,
                                weight=ft.FontWeight.BOLD,
                                color=theme.text_primary,
                            ),
                        ],
                        spacing=10,
                    ),
                    ft.Row(
                        [
                            self.status_text,
                            ft.IconButton(
                                icon=ft.Icons.PALETTE_ROUNDED,
                                tooltip="테마",
                                icon_color=theme.text_secondary,
                                on_click=self.show_theme_picker,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.SETTINGS_ROUNDED,
                                tooltip="설정",
                                icon_color=theme.text_secondary,
                                on_click=self.show_settings,
                            ),
                        ],
                        spacing=4,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=ft.padding.symmetric(horizontal=24, vertical=16),
            bgcolor=theme.surface,
            border=ft.border.only(bottom=ft.BorderSide(1, theme.divider)),
        )

        # 입력 영역
        input_area = ft.Container(
            content=ft.Row(
                [
                    self.url_input,
                    styled_button(
                        "추가",
                        primary=True,
                        theme=theme,
                        on_click=self.add_job,
                    ),
                ],
                spacing=12,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=24, vertical=16),
            bgcolor=theme.background,
        )

        # 메인 레이아웃
        self.page.add(
            ft.Column(
                [
                    header,
                    input_area,
                    ft.Container(
                        content=self.tabs,
                        expand=True,
                        padding=ft.padding.only(left=8, right=8),
                    ),
                ],
                expand=True,
                spacing=0,
            )
        )

        self.refresh_jobs_list()

    def refresh_jobs_list(self):
        """작업 목록 UI 갱신"""
        self.pending_list.controls.clear()
        self.completed_list.controls.clear()

        pending_jobs = [j for j in self.jobs if j["status"] in ("pending", "running", "error")]
        completed_jobs = [j for j in self.jobs if j["status"] == "completed"]

        if self.tabs.tabs:
            self.tabs.tabs[0].text = f"진행중 ({len(pending_jobs)})"
            self.tabs.tabs[1].text = f"완료됨 ({len(completed_jobs)})"

        # 진행중 탭
        if not pending_jobs:
            self.pending_list.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE_ROUNDED, size=48, color=self.theme.text_muted),
                            ft.Text(
                                "진행 중인 작업이 없습니다",
                                color=self.theme.text_muted,
                                size=14,
                            ),
                            ft.Text(
                                "YouTube URL을 입력하고 추가하세요",
                                color=self.theme.text_muted,
                                size=12,
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                    ),
                    alignment=ft.alignment.center,
                    padding=60,
                )
            )
        else:
            for job in reversed(pending_jobs):
                self.pending_list.controls.append(
                    JobCard(
                        job,
                        self.theme,
                        self.delete_job,
                        self.retry_job,
                        self.start_single_job,
                        self.page,
                        self.play_audio,
                        self.pause_job,
                        self.resume_job,
                        self.cancel_job,
                        self.current_audio_path,
                        self.is_playing,
                    )
                )

        # 완료됨 탭
        if not completed_jobs:
            self.completed_list.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.HEADPHONES_ROUNDED, size=48, color=self.theme.text_muted),
                            ft.Text(
                                "완료된 작업이 없습니다",
                                color=self.theme.text_muted,
                                size=14,
                            ),
                            ft.Text(
                                "더빙이 완료되면 여기서 재생할 수 있습니다",
                                color=self.theme.text_muted,
                                size=12,
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                    ),
                    alignment=ft.alignment.center,
                    padding=60,
                )
            )
        else:
            for job in reversed(completed_jobs):
                self.completed_list.controls.append(
                    JobCard(
                        job,
                        self.theme,
                        self.delete_job,
                        self.retry_job,
                        self.start_single_job,
                        self.page,
                        self.play_audio,
                        self.pause_job,
                        self.resume_job,
                        self.cancel_job,
                        self.current_audio_path,
                        self.is_playing,
                    )
                )

        self.page.update()

    def add_job(self, e):
        """새 작업 추가"""
        url = self.url_input.value.strip() if hasattr(self.url_input, "value") else ""
        if not url:
            self.show_toast("URL을 입력하세요", severity=ToastSeverity.WARNING)
            return

        if any(j["url"] == url and j["status"] in ("pending", "running") for j in self.jobs):
            self.show_toast("이미 대기 중인 작업입니다", severity=ToastSeverity.WARNING)
            return

        self.url_input.value = ""
        self.page.update()

        async def _add_with_info():
            try:
                self.show_toast("영상 정보 가져오는 중...", severity=ToastSeverity.INFORMATIONAL)
                video_info = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: get_video_info(url)
                )
            except Exception:
                video_info = {"title": "정보 로드 실패", "url": url}

            job = {
                "job_id": generate_job_id(),
                "url": url,
                "output_dir": self.config.output_dir,
                "status": "pending",
                "progress": 0,
                "current_step": "대기 중",
                "messages": [],
                "error": None,
                "result_files": [],
                "created_at": datetime.now().isoformat(),
                "video_info": video_info,
            }

            self.jobs.append(job)
            save_jobs(self.jobs)
            self.refresh_jobs_list()
            self.show_toast("작업이 추가되었습니다", severity=ToastSeverity.SUCCESS)

        self.page.run_task(_add_with_info)

    def delete_job(self, job: dict):
        self.jobs = [j for j in self.jobs if j["job_id"] != job["job_id"]]
        save_jobs(self.jobs)
        self.refresh_jobs_list()

    def retry_job(self, job: dict):
        job["status"] = "pending"
        job["progress"] = 0
        job["current_step"] = "대기 중"
        job["error"] = None
        save_jobs(self.jobs)
        self.refresh_jobs_list()

    def pause_job(self, job: dict):
        """작업 일시 정지"""
        job_id = job.get("job_id")
        if job_id and job_id in self.pause_controllers:
            self.pause_controllers[job_id].pause()
            job["status"] = "paused"
            job["current_step"] = "일시 정지됨"
            save_jobs(self.jobs)
            self.refresh_jobs_list()
            self.show_toast("작업 일시 정지됨", severity=ToastSeverity.WARNING)

    def resume_job(self, job: dict):
        """작업 재개"""
        job_id = job.get("job_id")
        if job_id and job_id in self.pause_controllers:
            self.pause_controllers[job_id].resume()
            job["status"] = "running"
            job["current_step"] = "재개됨..."
            save_jobs(self.jobs)
            self.refresh_jobs_list()
            self.show_toast("작업 재개됨", severity=ToastSeverity.SUCCESS)

    def cancel_job(self, job: dict):
        """작업 취소"""
        job_id = job.get("job_id")
        if job_id and job_id in self.pause_controllers:
            self.pause_controllers[job_id].cancel()
            job["status"] = "cancelled"
            job["current_step"] = "취소됨"
            save_jobs(self.jobs)
            self.refresh_jobs_list()
            self.show_toast("작업 취소됨", severity=ToastSeverity.WARNING)
            # 컨트롤러 정리
            del self.pause_controllers[job_id]

    def clear_completed(self, e):
        self.jobs = [j for j in self.jobs if j["status"] not in ("completed", "error")]
        save_jobs(self.jobs)
        self.refresh_jobs_list()

    def start_single_job(self, job: dict):
        if job["status"] != "pending":
            return

        async def _start():
            if not self.worker_running:
                self.page.run_task(self.job_worker)
            await self.job_queue.put(job)
            self.show_toast("작업 시작", severity=ToastSeverity.INFORMATIONAL)

        self.page.run_task(_start)

    async def start_all_jobs(self):
        pending_jobs = [j for j in self.jobs if j["status"] == "pending"]
        if not pending_jobs:
            self.show_toast("대기 중인 작업이 없습니다", severity=ToastSeverity.WARNING)
            return

        self.show_toast(f"{len(pending_jobs)}개 작업 시작", severity=ToastSeverity.INFORMATIONAL)

        if not self.worker_running:
            self.page.run_task(self.job_worker)

        for job in pending_jobs:
            await self.job_queue.put(job)

    async def job_worker(self):
        self.worker_running = True

        while True:
            try:
                job = await asyncio.wait_for(self.job_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if not any(j["status"] == "pending" for j in self.jobs):
                    break
                continue

            await self.run_job(job)

        self.worker_running = False

    async def run_job(self, job: dict):
        job["status"] = "running"
        job["current_step"] = "시작 중..."
        save_jobs(self.jobs)
        self.refresh_jobs_list()

        # PauseController 생성 및 저장
        job_id = job.get("job_id")
        pause_controller = PauseController()
        self.pause_controllers[job_id] = pause_controller

        def on_progress(msg: str, progress: int):
            job["current_step"] = msg
            job["progress"] = progress
            job["messages"].append(msg)
            self.page.run_task(self._update_job_ui)

        try:
            output_dir = Path(self.config.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: run_dubbing(
                    url=job["url"],
                    output_dir=output_dir,
                    config=self.config,
                    on_progress=on_progress,
                    pause_controller=pause_controller,
                ),
            )

            job["status"] = result.status
            job["progress"] = result.progress
            job["error"] = result.error
            job["result_files"] = result.result_files
            job["output_dir"] = str(result.output_dir)

            if result.status == "completed":
                if result.result_files:
                    job["output_dir"] = str(Path(result.result_files[0]).parent)
                self.show_toast("더빙 완료!", severity=ToastSeverity.SUCCESS)
            elif result.status == "cancelled":
                self.show_toast("작업 취소됨", severity=ToastSeverity.WARNING)

        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
            self.show_toast(f"오류: {str(e)[:50]}", severity=ToastSeverity.CRITICAL)

        # PauseController 정리
        if job_id in self.pause_controllers:
            del self.pause_controllers[job_id]

        save_jobs(self.jobs)
        self.refresh_jobs_list()

    async def _update_job_ui(self):
        save_jobs(self.jobs)
        self.refresh_jobs_list()

    def show_theme_picker(self, e):
        """테마 선택 다이얼로그"""
        theme = self.theme

        theme_options = []
        for name, t in THEMES.items():
            is_current = name == self.config.theme
            theme_options.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(
                                width=24,
                                height=24,
                                bgcolor=t.primary,
                                border_radius=12,
                            ),
                            ft.Text(
                                t.display_name,
                                color=theme.text_primary,
                                weight=ft.FontWeight.W_600 if is_current else ft.FontWeight.NORMAL,
                            ),
                            ft.Icon(
                                ft.Icons.CHECK,
                                color=theme.accent,
                                size=16,
                            )
                            if is_current
                            else ft.Container(),
                        ],
                        spacing=12,
                    ),
                    padding=ft.padding.symmetric(horizontal=12, vertical=10),
                    border_radius=8,
                    bgcolor=theme.surface if is_current else None,
                    on_click=lambda e, n=name: self._apply_theme(n),
                    on_hover=lambda e: self._theme_item_hover(e),
                )
            )

        dlg = ft.AlertDialog(
            title=ft.Text("테마 선택", color=theme.text_primary, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column(theme_options, spacing=4),
                width=280,
                padding=8,
            ),
            bgcolor=theme.card_bg,
            actions=[
                ft.TextButton("닫기", on_click=lambda e: self.page.close(dlg)),
            ],
        )

        self.page.open(dlg)

    def _theme_item_hover(self, e):
        if e.data == "true":
            e.control.bgcolor = self.theme.surface
        else:
            if self.config.theme not in str(e.control.content):
                e.control.bgcolor = None
        e.control.update()

    def _apply_theme(self, theme_name: str):
        """테마 적용"""
        self.config.theme = theme_name
        save_config(self.config)
        self.theme = get_theme(theme_name)
        apply_theme(self.page, self.theme)

        # UI 다시 빌드
        self.page.controls.clear()
        self.build_ui()
        self.show_toast(f"테마: {self.theme.display_name}", severity=ToastSeverity.SUCCESS)

    def show_settings(self, e):
        """설정 다이얼로그"""
        theme = self.theme
        is_ollama = "localhost:11434" in self.config.zai_base_url

        if is_ollama and not self.ollama_models:
            self.ollama_models = get_ollama_models()

        api_key_field = ft.TextField(
            label="API 키",
            value=self.config.zai_api_key,
            password=not is_ollama,
            width=380,
            border_color=theme.border,
            focused_border_color=theme.accent,
            label_style=ft.TextStyle(color=theme.text_secondary),
            text_style=ft.TextStyle(color=theme.text_primary),
            cursor_color=theme.accent,
        )

        base_url_field = ft.TextField(
            label="API URL",
            value=self.config.zai_base_url,
            width=380,
            border_color=theme.border,
            focused_border_color=theme.accent,
            label_style=ft.TextStyle(color=theme.text_secondary),
            text_style=ft.TextStyle(color=theme.text_primary),
            cursor_color=theme.accent,
        )

        if is_ollama and self.ollama_models:
            model_field = ft.Dropdown(
                label="모델",
                value=self.config.zai_model
                if self.config.zai_model in self.ollama_models
                else self.ollama_models[0],
                options=[ft.dropdown.Option(m) for m in self.ollama_models],
                width=380,
                border_color=theme.border,
                focused_border_color=theme.accent,
                label_style=ft.TextStyle(color=theme.text_secondary),
                text_style=ft.TextStyle(color=theme.text_primary),
            )
        else:
            model_field = ft.TextField(
                label="모델",
                value=self.config.zai_model,
                width=380,
                border_color=theme.border,
                focused_border_color=theme.accent,
                label_style=ft.TextStyle(color=theme.text_secondary),
                text_style=ft.TextStyle(color=theme.text_primary),
                cursor_color=theme.accent,
            )

        output_dir_field = ft.TextField(
            label="출력 디렉토리",
            value=self.config.output_dir,
            width=380,
            border_color=theme.border,
            focused_border_color=theme.accent,
            label_style=ft.TextStyle(color=theme.text_secondary),
            text_style=ft.TextStyle(color=theme.text_primary),
            cursor_color=theme.accent,
        )

        voice_options = list(KOREAN_VOICES.keys())
        voice_field = ft.Dropdown(
            label="TTS 음성",
            value=self.config.tts_voice if self.config.tts_voice in voice_options else voice_options[0],
            options=[ft.dropdown.Option(v, f"{v} ({KOREAN_VOICES[v]['gender']})") for v in voice_options],
            width=380,
            border_color=theme.border,
            focused_border_color=theme.accent,
            label_style=ft.TextStyle(color=theme.text_secondary),
            text_style=ft.TextStyle(color=theme.text_primary),
        )

        def use_zai(e):
            base_url_field.value = PRESETS["z.ai"]["base_url"]
            model_field.value = PRESETS["z.ai"]["default_model"]
            api_key_field.password = True
            self.page.update()

        def use_ollama(e):
            base_url_field.value = PRESETS["Ollama"]["base_url"]
            api_key_field.value = "ollama"
            api_key_field.password = False
            self.ollama_models = get_ollama_models()
            if self.ollama_models:
                model_field.value = self.ollama_models[0]
            self.page.update()

        def save_settings(e):
            self.config = Config(
                zai_api_key=api_key_field.value,
                zai_base_url=base_url_field.value,
                zai_model=model_field.value if hasattr(model_field, "value") else model_field.value,
                output_dir=output_dir_field.value,
                tts_voice=voice_field.value,
                tts_rate=self.config.tts_rate,
                max_workers=self.config.max_workers,
                theme=self.config.theme,
            )
            save_config(self.config)

            is_ollama = "localhost:11434" in self.config.zai_base_url
            mode_text = f"Ollama ({self.config.zai_model})" if is_ollama else f"z.ai ({self.config.zai_model})"
            self.status_text.value = mode_text

            self.page.close(dlg)
            self.show_toast("설정이 저장되었습니다", severity=ToastSeverity.SUCCESS)

        dlg = ft.AlertDialog(
            title=ft.Text("설정", color=theme.text_primary, weight=ft.FontWeight.BOLD, size=18),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text("빠른 설정", weight=ft.FontWeight.W_600, color=theme.text_secondary, size=12),
                        ft.Row(
                            [
                                styled_button("z.ai 사용", theme=theme, on_click=use_zai),
                                styled_button("Ollama 사용", theme=theme, on_click=use_ollama),
                            ],
                            spacing=10,
                        ),
                        ft.Divider(color=theme.divider),
                        api_key_field,
                        base_url_field,
                        model_field,
                        ft.Divider(color=theme.divider),
                        output_dir_field,
                        voice_field,
                    ],
                    spacing=12,
                    tight=True,
                ),
                width=420,
                padding=12,
            ),
            bgcolor=theme.card_bg,
            actions=[
                ft.TextButton("취소", on_click=lambda e: self.page.close(dlg)),
                styled_button("저장", primary=True, theme=theme, on_click=save_settings),
            ],
        )

        self.page.open(dlg)

    def show_toast(self, message: str, severity: str = ToastSeverity.INFORMATIONAL):
        """Toast 알림 표시 (SnackBar 사용)"""
        colors = {
            ToastSeverity.INFORMATIONAL: self.theme.info,
            ToastSeverity.SUCCESS: self.theme.success,
            ToastSeverity.WARNING: self.theme.warning,
            ToastSeverity.CRITICAL: self.theme.error,
        }
        bgcolor = colors.get(severity, self.theme.info)

        self.page.open(
            ft.SnackBar(
                content=ft.Text(message, color="#FFFFFF"),
                bgcolor=bgcolor,
                duration=3000,
            )
        )


async def main(page: ft.Page):
    """메인 함수"""
    DubbingApp(page)


if __name__ == "__main__":
    ft.app(target=main)
