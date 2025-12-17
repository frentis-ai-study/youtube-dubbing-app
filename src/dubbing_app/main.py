"""YouTube Dubbing App - Streamlit UI"""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import streamlit as st

from dubbing_app.runner import (
    DubbingJob,
    check_claude_available,
    generate_job_id,
    run_dubbing,
)

# 페이지 설정
st.set_page_config(
    page_title="YouTube Dubbing",
    page_icon="🎬",
    layout="wide",
)


def init_session_state():
    """세션 상태 초기화"""
    if "jobs" not in st.session_state:
        st.session_state.jobs = []
    if "processing" not in st.session_state:
        st.session_state.processing = False


def process_urls_parallel(urls: list[str], output_dir: Path, max_workers: int) -> list[DubbingJob]:
    """여러 URL 병렬 처리"""
    jobs = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for url in urls:
            future = executor.submit(run_dubbing, url, output_dir)
            futures[future] = url

        for future in as_completed(futures):
            url = futures[future]
            try:
                job = future.result()
                jobs.append(job)
            except Exception as e:
                # 에러 발생 시 실패 작업 생성
                job = DubbingJob(
                    job_id=generate_job_id(),
                    url=url,
                    output_dir=output_dir,
                    status="error",
                    error=str(e),
                )
                jobs.append(job)

    return jobs


def render_job_status(job: DubbingJob):
    """작업 상태 렌더링"""
    status_icons = {
        "pending": "⏳",
        "running": "🔄",
        "completed": "✅",
        "error": "❌",
    }
    icon = status_icons.get(job.status, "❓")

    with st.expander(f"{icon} {job.url[:50]}...", expanded=job.status == "error"):
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**작업 ID:** {job.job_id}")
            st.write(f"**상태:** {job.status}")
        with col2:
            st.write(f"**출력 위치:** {job.output_dir}")
            st.write(f"**시작 시간:** {job.created_at.strftime('%H:%M:%S')}")

        if job.status == "completed" and job.result_files:
            st.write("**생성된 파일:**")
            for file_path in job.result_files:
                file_name = Path(file_path).name
                if Path(file_path).exists():
                    if file_name.endswith(".mp3"):
                        st.audio(file_path)
                    with open(file_path, "rb") as f:
                        st.download_button(
                            label=f"📥 {file_name}",
                            data=f,
                            file_name=file_name,
                            key=f"download_{job.job_id}_{file_name}",
                        )

        if job.status == "error" and job.error:
            st.error(f"오류: {job.error}")

        if job.messages:
            with st.expander("진행 로그"):
                for msg in job.messages[-10:]:  # 최근 10개만
                    st.text(msg[:200])


def main():
    """메인 함수"""
    init_session_state()

    st.title("🎬 YouTube Dubbing")
    st.markdown("YouTube 영상을 한국어 음성으로 변환합니다. (Claude Code 활용)")

    # 사이드바: 설정
    with st.sidebar:
        st.header("⚙️ 설정")

        # 출력 디렉토리
        default_output = os.path.expanduser("~/Dubbing")
        output_dir = st.text_input(
            "출력 디렉토리",
            value=default_output,
            help="더빙 결과물이 저장될 폴더",
        )

        # 병렬 처리 수
        max_workers = st.slider(
            "동시 처리 수",
            min_value=1,
            max_value=5,
            value=2,
            help="동시에 처리할 영상 수",
        )

        st.divider()

        # Claude Code 연결 상태
        st.subheader("🔌 연결 상태")
        available, version = check_claude_available()
        if available:
            st.success(f"Claude Code: {version}")
        else:
            st.error(f"Claude Code 연결 실패: {version}")
            st.info("Claude Code가 설치되어 있는지 확인하세요.")

    # 메인 영역
    col1, col2 = st.columns([3, 2])

    with col1:
        st.subheader("📥 입력")

        # URL 입력
        urls_input = st.text_area(
            "YouTube URL (한 줄에 하나씩)",
            placeholder="https://youtube.com/watch?v=...\nhttps://youtu.be/...",
            height=150,
        )

        # 시작 버튼
        if st.button("🚀 더빙 시작", type="primary", use_container_width=True):
            urls = [u.strip() for u in urls_input.strip().split("\n") if u.strip()]

            if not urls:
                st.error("URL을 입력하세요.")
            elif not available:
                st.error("Claude Code가 연결되어 있지 않습니다.")
            else:
                output_path = Path(output_dir)
                output_path.mkdir(parents=True, exist_ok=True)

                st.session_state.processing = True
                st.session_state.jobs = []

                with st.spinner(f"{len(urls)}개 영상 처리 중... (최대 {max_workers}개 동시)"):
                    jobs = process_urls_parallel(urls, output_path, max_workers)
                    st.session_state.jobs = jobs

                st.session_state.processing = False
                st.rerun()

    with col2:
        st.subheader("📊 처리 현황")

        if not st.session_state.jobs:
            st.info("아직 처리된 작업이 없습니다.")
        else:
            # 요약
            total = len(st.session_state.jobs)
            success = sum(1 for j in st.session_state.jobs if j.status == "completed")
            errors = sum(1 for j in st.session_state.jobs if j.status == "error")

            metrics = st.columns(3)
            metrics[0].metric("전체", total)
            metrics[1].metric("성공", success)
            metrics[2].metric("실패", errors)

            st.divider()

            # 작업 목록
            for job in st.session_state.jobs:
                render_job_status(job)

    # 푸터
    st.divider()
    st.caption("💡 Claude Code headless 모드를 사용하여 자막 추출, 번역, TTS를 자동으로 처리합니다.")


if __name__ == "__main__":
    main()
