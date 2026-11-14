from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
from threading import Event

import pytest

from my_video_manager import adapters
from my_video_manager.adapters import FFmpegMediaReader
from my_video_manager.onscreen_subtitles import RegionRect


@pytest.fixture
def reader():
    try:
        return FFmpegMediaReader()
    except RuntimeError as error:
        pytest.skip(str(error))


def encode(reader, path, *, size="320x240", duration=3, box=True):
    command = [reader.ffmpeg, "-v", "error", "-nostdin", "-y", "-f", "lavfi",
               "-i", f"color=black:s={size}:d={duration}:r=30"]
    if box:
        command += ["-vf", "drawbox=x=80:y=60:w=80:h=60:color=white:t=fill:enable='between(t,1,2)'"]
    command += ["-c:v", "libx264", "-preset", "ultrafast", "-threads", "1", str(path)]
    subprocess.run(command, check=True, capture_output=True)
    return path


def frames(reader, path, region, fps=4):
    return list(reader.region_frames(path, region, fps=fps, cancellation=Event()))


def test_crop_timestamps_and_visible_interval(reader, tmp_path):
    path = encode(reader, tmp_path / "boxes.mkv")
    images = frames(reader, path, RegionRect(.25, .25, .25, .25))
    assert len(images) == pytest.approx(3 * 4, abs=1)
    assert [time for time, _ in images] == [index / 4 for index in range(len(images))]
    assert {(image.width, image.height) for _, image in images} == {(80, 60)}
    bright = [time for time, image in images if sum(image.pixels) / len(image.pixels) > 200]
    assert min(bright) == pytest.approx(1, abs=.25)
    assert max(bright) == pytest.approx(2, abs=.25)
    outside = frames(reader, path, RegionRect(.6, .6, .25, .25))
    assert all(max(image.pixels) < 20 for _, image in outside)


@pytest.mark.parametrize("region, size, expected", [
    (RegionRect(.1, .1, .253125, .2541666667), "320x240", (81, 61)),
    (RegionRect(.99, .99, .01, .01), "32x24", (1, 1)),
])
def test_odd_and_minimum_crop_sizes(reader, tmp_path, region, size, expected):
    path = encode(reader, tmp_path / "small.mkv", size=size, duration=1, box=False)
    images = frames(reader, path, region)
    assert images
    assert all((image.width, image.height) == expected for _, image in images)
    assert all(len(image.pixels) == expected[0] * expected[1] for _, image in images)


def test_large_region_is_scaled(reader, tmp_path):
    path = encode(reader, tmp_path / "large.mkv", size="3840x2160", duration=1, box=False)
    images = frames(reader, path, RegionRect(0, 0, 1, 1), fps=1)
    assert len(images) == 1
    assert (images[0][1].width, images[0][1].height) == (2560, 1440)


def test_rotation_uses_display_coordinates(reader, tmp_path):
    original = encode(reader, tmp_path / "original.mp4")
    rotated = tmp_path / "rotated.mp4"
    subprocess.run([reader.ffmpeg, "-v", "error", "-i", str(original), "-c", "copy",
                    "-metadata:s:v:0", "rotate=90", str(rotated)], check=True, capture_output=True)
    info = reader.read(rotated)
    if (info.width, info.height) != (240, 320):
        result = subprocess.run(
            [reader.ffmpeg, "-v", "error", "-y", "-display_rotation:v:0", "90",
             "-i", str(original), "-c", "copy", str(rotated)], capture_output=True,
        )
        if result.returncode:
            pytest.skip("이 ffmpeg는 회전 메타데이터를 기록하지 않습니다.")
        info = reader.read(rotated)
        assert (info.width, info.height) == (240, 320)
    # 90도 반시계 회전: 원본의 (80,60)-(160,120)이 (60,160)-(120,240)이 된다.
    images = frames(reader, rotated, RegionRect(.25, .5, .25, .25))
    assert {(image.width, image.height) for _, image in images} == {(60, 80)}
    assert any(min(image.pixels) > 200 for _, image in images)
    outside = frames(reader, rotated, RegionRect(.5, 0, .25, .25))
    assert all(max(image.pixels) < 20 for _, image in outside)


def track_processes(monkeypatch, reader, *, realtime=False):
    popen = subprocess.Popen
    processes = []
    started = Event()

    def launch(command, *args, **kwargs):
        if command[0] == reader.ffmpeg:
            command = list(command)
            if realtime:
                command.insert(command.index("-i"), "-re")
            process = popen(command, *args, **kwargs)
            processes.append(process)
            started.set()
            return process
        return popen(command, *args, **kwargs)

    monkeypatch.setattr(adapters.subprocess, "Popen", launch)
    return processes, started


def test_cancellation_interrupts_blocked_stdout(reader, tmp_path, monkeypatch):
    path = encode(reader, tmp_path / "cancel.mkv", duration=30, box=False)
    processes, started = track_processes(monkeypatch, reader, realtime=True)
    cancellation = Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(lambda: list(reader.region_frames(
            path, RegionRect(0, 0, 1, 1), fps=.1, cancellation=cancellation)))
        try:
            assert started.wait(5)
            cancellation.set()
            assert result.result(timeout=3) == []
        finally:
            cancellation.set()
    assert processes and all(process.poll() is not None for process in processes)
    assert all(process.stdout.closed and process.stderr.closed for process in processes)


def test_closing_generator_reaps_process(reader, tmp_path, monkeypatch):
    path = encode(reader, tmp_path / "close.mkv", duration=3, box=False)
    processes, _ = track_processes(monkeypatch, reader)
    stream = reader.region_frames(path, RegionRect(0, 0, 1, 1), fps=30, cancellation=Event())
    next(stream)
    stream.close()
    assert processes and all(process.poll() is not None for process in processes)
    assert all(process.stdout.closed and process.stderr.closed for process in processes)


def test_cancellation_during_probe_stops_without_frames_or_error(reader, tmp_path, monkeypatch):
    """크기를 읽는 ffprobe 단계에서도 취소를 받는다(대기열 빼기·앱 종료가 기다리지 않는다)."""
    path = encode(reader, tmp_path / "probe.mkv", duration=1, box=False)
    popen = subprocess.Popen
    probes, started = [], Event()

    def launch(command, *args, **kwargs):
        if command[0] == reader.ffprobe:
            # 응답하지 않는 ffprobe 대신 오래 자는 프로세스를 띄운다.
            process = popen([sys.executable, "-c", "import time; time.sleep(60)"], *args, **kwargs)
            probes.append(process)
            started.set()
            return process
        return popen(command, *args, **kwargs)

    monkeypatch.setattr(adapters.subprocess, "Popen", launch)
    cancellation = Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(lambda: list(reader.region_frames(
            path, RegionRect(0, 0, 1, 1), fps=4, cancellation=cancellation)))
        try:
            assert started.wait(5)
            cancellation.set()
            assert result.result(timeout=3) == []
        finally:
            cancellation.set()
            for process in probes:
                process.kill()
    assert probes and all(process.poll() is not None for process in probes)


def test_probe_timeout_fails_onscreen_job_with_retry_guidance_and_retry_requeues(reader, tmp_path, monkeypatch):
    """크기 조사 시간 초과는 화면 자막 실패로 남고, 안내는 실제 복구 방법(재시도)을 말한다."""
    from datetime import datetime, timezone
    from my_video_manager.core import AppCore
    from my_video_manager.subtitle_queue_kind import ONSCREEN_SUBTITLE
    from test_onscreen_subtitles import FakeOcr
    core = AppCore(media=reader, clock=lambda: datetime.now(timezone.utc), ocr_engine=FakeOcr(),
                   database=tmp_path / "data/library.sqlite3")
    core.set_minimum_duration(0)
    core.add_file(encode(reader, tmp_path / "slow.mkv", duration=1, box=False))
    video, = core.videos()
    core.set_onscreen_subtitle_regions(video.id, [(RegionRect(0, .8, 1, .2), "en")])
    popen = subprocess.Popen

    def launch(command, *args, **kwargs):
        if command[0] == reader.ffprobe:
            command = [sys.executable, "-c", "import time; time.sleep(60)"]
        return popen(command, *args, **kwargs)

    monkeypatch.setattr(adapters.subprocess, "Popen", launch)
    monkeypatch.setattr(adapters, "REGION_PROBE_TIMEOUT_SECONDS", 0.5, raising=False)
    assert core.process_next_onscreen_subtitle().state == "failed"
    item, = core.subtitle_queue_items()
    assert item.state == "failed"
    assert "실패 항목 모두 재시도" in item.error and "다시 검사" not in item.error
    assert "영상 크기" in item.error
    assert core.retry_failed_subtitles(kind=ONSCREEN_SUBTITLE).retried == 1
    assert [entry.state for entry in core.subtitle_queue(kind=ONSCREEN_SUBTITLE)] == ["queued"]



def test_missing_file_raises_runtime_error(reader, tmp_path):
    with pytest.raises(RuntimeError):
        frames(reader, tmp_path / "missing.mkv", RegionRect(0, 0, 1, 1))


def test_decoder_failure_raises_runtime_error(reader, tmp_path, monkeypatch):
    path = encode(reader, tmp_path / "removed.mkv", duration=1, box=False)
    read = reader.read_resolution

    def read_then_remove(path, **options):
        info = read(path, **options)
        path.unlink()
        return info

    monkeypatch.setattr(reader, "read_resolution", read_then_remove)
    with pytest.raises(RuntimeError):
        frames(reader, path, RegionRect(0, 0, 1, 1))


def test_range_reads_only_that_interval_with_video_times(reader, tmp_path):
    path = encode(reader, tmp_path / "range.mkv")  # 1–2초에 흰 상자
    images = list(reader.region_frames(path, RegionRect(.25, .25, .25, .25), fps=4, cancellation=Event(),
                                       start=1.5, end=2.5))
    times = [time for time, _ in images]
    assert times[0] == 1.5 and times == [1.5 + index / 4 for index in range(len(images))]
    assert len(images) == pytest.approx(4, abs=1) and times[-1] < 2.5
    bright = {time: sum(image.pixels) / len(image.pixels) > 200 for time, image in images}
    assert bright[1.5] and bright[1.75]
    assert not any(value for time, value in bright.items() if time > 2.1)
