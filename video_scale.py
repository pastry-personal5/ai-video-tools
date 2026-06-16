from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: Fraction


DEFAULT_CRF = 16
DEFAULT_PRESET = "slow"
DEFAULT_SCALE_FLAGS = "lanczos+accurate_rnd+full_chroma_int"
DEFAULT_OUTPUT_FPS = Fraction(30, 1)
DEFAULT_FPS_METHOD = "mci"


def require_command(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise SystemExit(f"Required command not found on PATH: {name}")
    return path


def run_command(command: list[str], *, dry_run: bool = False, cwd: Path | None = None) -> None:
    printable = " ".join(command)
    if dry_run:
        print(printable)
        return
    print(printable)
    try:
        subprocess.run(command, check=True, cwd=cwd)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(command_failure_message(command, exc)) from exc


def command_failure_message(command: list[str], exc: subprocess.CalledProcessError) -> str:
    message = f"Command failed with exit code {exc.returncode}: {' '.join(command)}"
    if exc.returncode < 0:
        message = f"Command crashed with signal {-exc.returncode}: {' '.join(command)}"

    if command and Path(command[0]).name == "fx-upscale":
        message += (
            "\nfx-upscale failed before producing an output video. "
            "Use --keep-temp to preserve the temporary input copy for retry/debugging."
        )
    if command and Path(command[0]).name.startswith("realesrgan-ncnn-vulkan"):
        message += (
            "\nReal-ESRGAN failed before producing upscaled frames. "
            "Use --keep-temp to preserve the temporary frames for retry/debugging."
        )
    return message


@contextmanager
def temporary_work_dir(prefix: str, *, keep: bool = False):
    temp_root = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield temp_root
    finally:
        if keep:
            print(f"Keeping temporary directory: {temp_root}")
        else:
            shutil.rmtree(temp_root, ignore_errors=True)


def probe_video(input_path: Path, *, ffprobe: str = "ffprobe") -> VideoInfo:
    require_command(ffprobe)
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate",
        "-of",
        "json",
        str(input_path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    if not streams:
        raise SystemExit(f"No video stream found in {input_path}")

    stream = streams[0]
    fps_text = stream.get("avg_frame_rate") or "0/1"
    fps = Fraction(fps_text)
    if fps <= 0:
        fps = Fraction(30, 1)

    return VideoInfo(
        width=int(stream["width"]),
        height=int(stream["height"]),
        fps=fps,
    )


def even(value: int) -> int:
    return max(2, value - (value % 2))


def parse_size(value: str) -> tuple[int, int]:
    normalized = value.lower().replace(" ", "")
    if "x" not in normalized:
        raise argparse.ArgumentTypeError("size must look like WIDTHxHEIGHT, for example 1920x1080")
    width_text, height_text = normalized.split("x", 1)
    try:
        width = int(width_text)
        height = int(height_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("width and height must be integers") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("width and height must be positive")
    return width, height


def parse_fps(value: str) -> Fraction:
    try:
        fps = Fraction(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("fps must be a positive number or fraction, for example 30 or 30000/1001") from exc
    if fps <= 0:
        raise argparse.ArgumentTypeError("fps must be positive")
    return fps


def format_fps(fps: Fraction) -> str:
    return f"{fps.numerator}/{fps.denominator}"


def ffmpeg_fps_filter(output_fps: Fraction | None, fps_method: str) -> str:
    if output_fps is None:
        return ""
    fps_text = format_fps(output_fps)
    if fps_method == "duplicate":
        return f",fps={fps_text}"
    if fps_method == "mci":
        return f",minterpolate=fps={fps_text}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,fps={fps_text}"
    raise ValueError(f"Unknown fps method: {fps_method}")


def ffmpeg_output_fps_args(output_fps: Fraction | None) -> list[str]:
    if output_fps is None:
        return []
    return ["-r", format_fps(output_fps)]


def fps_matches(actual: Fraction, expected: Fraction, *, tolerance: Fraction = Fraction(1, 1000)) -> bool:
    return abs(actual - expected) <= tolerance


def ensure_output_fps(
    output_path: Path,
    *,
    output_fps: Fraction | None,
    fps_method: str,
    video_codec: str,
    crf: int,
    preset: str,
    audio: str,
    ffmpeg: str,
    ffprobe: str,
) -> None:
    if output_fps is None:
        return

    actual = probe_video(output_path, ffprobe=ffprobe).fps
    if fps_matches(actual, output_fps):
        return

    with tempfile.TemporaryDirectory(prefix="video-fps-fix-") as temp_name:
        corrected = Path(temp_name) / output_path.name
        run_command([
            ffmpeg,
            "-y",
            "-i",
            str(output_path),
            "-vf",
            ffmpeg_fps_filter(output_fps, fps_method).removeprefix(","),
            *ffmpeg_output_fps_args(output_fps),
            "-c:v",
            video_codec,
            "-crf",
            str(crf),
            "-preset",
            preset,
            "-c:a",
            audio,
            str(corrected),
        ])
        corrected.replace(output_path)

    actual = probe_video(output_path, ffprobe=ffprobe).fps
    if not fps_matches(actual, output_fps):
        raise SystemExit(
            f"Output frame rate is {format_fps(actual)}, expected {format_fps(output_fps)}: {output_path}"
        )


def target_from_width(source: VideoInfo, width: int) -> tuple[int, int]:
    if width <= 0:
        raise ValueError("width must be positive")
    height = round(source.height * width / source.width)
    return even(width), even(height)


def target_from_height(source: VideoInfo, height: int) -> tuple[int, int]:
    if height <= 0:
        raise ValueError("height must be positive")
    width = round(source.width * height / source.height)
    return even(width), even(height)


def ffmpeg_scale_filter(
    mode: str,
    target_width: int,
    target_height: int,
    *,
    scale_flags: str = DEFAULT_SCALE_FLAGS,
    output_fps: Fraction | None = DEFAULT_OUTPUT_FPS,
    fps_method: str = DEFAULT_FPS_METHOD,
) -> str:
    scale_suffix = f":flags={scale_flags}" if scale_flags else ""
    fps_filter = ffmpeg_fps_filter(output_fps, fps_method)
    if mode == "exact":
        return f"scale={target_width}:{target_height}{scale_suffix},setsar=1{fps_filter}"
    if mode == "fit":
        return (
            f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease{scale_suffix},"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1{fps_filter}"
        )
    if mode == "fill":
        return (
            f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase{scale_suffix},"
            f"crop={target_width}:{target_height},"
            f"setsar=1{fps_filter}"
        )
    raise ValueError(f"Unknown scale mode: {mode}")


def build_ffmpeg_scale_command(
    input_path: Path,
    output_path: Path,
    *,
    size: tuple[int, int] | None = None,
    width: int | None = None,
    height: int | None = None,
    mode: str = "exact",
    video_codec: str = "libx264",
    crf: int = DEFAULT_CRF,
    preset: str = DEFAULT_PRESET,
    audio: str = "copy",
    scale_flags: str = DEFAULT_SCALE_FLAGS,
    output_fps: Fraction | None = DEFAULT_OUTPUT_FPS,
    fps_method: str = DEFAULT_FPS_METHOD,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> list[str]:
    require_command(ffmpeg)
    source = probe_video(input_path, ffprobe=ffprobe)

    if size is not None:
        target_width, target_height = size
    elif width is not None:
        target_width, target_height = target_from_width(source, width)
    elif height is not None:
        target_width, target_height = target_from_height(source, height)
    else:
        raise ValueError("Provide size, width, or height")

    target_width = even(target_width)
    target_height = even(target_height)
    scale_filter = ffmpeg_scale_filter(
        mode,
        target_width,
        target_height,
        scale_flags=scale_flags,
        output_fps=output_fps,
        fps_method=fps_method,
    )

    return [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-vf",
        scale_filter,
        *ffmpeg_output_fps_args(output_fps),
        "-c:v",
        video_codec,
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-c:a",
        audio,
        str(output_path),
    ]


def scale_with_ffmpeg(
    input_path: Path,
    output_path: Path,
    **kwargs: object,
) -> None:
    dry_run = bool(kwargs.pop("dry_run", False))
    command = build_ffmpeg_scale_command(input_path, output_path, **kwargs)
    run_command(command, dry_run=dry_run)
    if not dry_run:
        ensure_output_fps(
            output_path,
            output_fps=kwargs.get("output_fps", DEFAULT_OUTPUT_FPS),
            fps_method=str(kwargs.get("fps_method", DEFAULT_FPS_METHOD)),
            video_codec=str(kwargs.get("video_codec", "libx264")),
            crf=int(kwargs.get("crf", DEFAULT_CRF)),
            preset=str(kwargs.get("preset", DEFAULT_PRESET)),
            audio=str(kwargs.get("audio", "copy")),
            ffmpeg=str(kwargs.get("ffmpeg", "ffmpeg")),
            ffprobe=str(kwargs.get("ffprobe", "ffprobe")),
        )


def fx_codec_for_video_codec(video_codec: str) -> str:
    normalized = video_codec.lower()
    if normalized in {"h264", "avc1", "libx264"}:
        return "h264"
    if normalized in {"hevc", "h265", "libx265"}:
        return "hevc"
    if normalized in {"prores", "prores_ks", "prores_videotoolbox"}:
        return "prores"
    return "hevc"


def upscale_with_fx(
    input_path: Path,
    output_path: Path,
    *,
    size: tuple[int, int] | None = None,
    width: int | None = None,
    height: int | None = None,
    mode: str = "exact",
    fx_upscale: str = "fx-upscale",
    fx_codec: str | None = None,
    keep_temp: bool = False,
    video_codec: str = "libx264",
    crf: int = DEFAULT_CRF,
    preset: str = DEFAULT_PRESET,
    audio: str = "copy",
    scale_flags: str = DEFAULT_SCALE_FLAGS,
    output_fps: Fraction | None = DEFAULT_OUTPUT_FPS,
    fps_method: str = DEFAULT_FPS_METHOD,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    dry_run: bool = False,
) -> None:
    require_command(ffmpeg)
    require_command(ffprobe)
    require_command(fx_upscale)

    source = probe_video(input_path, ffprobe=ffprobe)
    if size is not None:
        target_width, target_height = size
    elif width is not None:
        target_width, target_height = target_from_width(source, width)
    elif height is not None:
        target_width, target_height = target_from_height(source, height)
    else:
        raise ValueError("Provide size, width, or height")

    target_width = even(target_width)
    target_height = even(target_height)
    fx_codec = fx_codec or fx_codec_for_video_codec(video_codec)
    if fx_codec not in {"hevc", "prores", "h264"}:
        raise ValueError("fx-upscale codec must be hevc, prores, or h264")

    if dry_run:
        temp_root = Path("<temporary-directory>")
        fx_input = temp_root / input_path.name
        fx_output = temp_root / "<fx-upscale-output>"
        _print_fx_plan(
            input_path,
            output_path,
            fx_input,
            fx_output,
            target_width,
            target_height,
            mode,
            fx_upscale,
            fx_codec,
            video_codec,
            crf,
            preset,
            audio,
            scale_flags,
            output_fps,
            fps_method,
            ffmpeg,
        )
        return

    with temporary_work_dir("video-scale-", keep=keep_temp) as temp_root:
        fx_input = temp_root / input_path.name
        shutil.copy2(input_path, fx_input)
        before = video_files(temp_root)
        run_command(
            build_fx_command(
                fx_input,
                target_width=target_width,
                target_height=target_height,
                codec=fx_codec,
                fx_upscale=fx_upscale,
            ),
            cwd=temp_root,
        )
        fx_output = detect_fx_output(temp_root, before, fx_input)
        scale_filter = ffmpeg_scale_filter(
            mode,
            target_width,
            target_height,
            scale_flags=scale_flags,
            output_fps=output_fps,
            fps_method=fps_method,
        )
        run_command([
            ffmpeg,
            "-y",
            "-i",
            str(fx_output),
            "-i",
            str(input_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a?",
            "-vf",
            scale_filter,
            *ffmpeg_output_fps_args(output_fps),
            "-c:v",
            video_codec,
            "-crf",
            str(crf),
            "-preset",
            preset,
            "-c:a",
            audio,
            "-shortest",
            str(output_path),
        ])
        ensure_output_fps(
            output_path,
            output_fps=output_fps,
            fps_method=fps_method,
            video_codec=video_codec,
            crf=crf,
            preset=preset,
            audio=audio,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
        )


def upscale_with_realesrgan(
    input_path: Path,
    output_path: Path,
    *,
    size: tuple[int, int] | None = None,
    width: int | None = None,
    height: int | None = None,
    mode: str = "exact",
    realesrgan: str = "realesrgan-ncnn-vulkan",
    realesrgan_model: str = "realesrgan-x4plus",
    realesrgan_model_folder: Path | None = None,
    realesrgan_scale: int | None = None,
    keep_temp: bool = False,
    video_codec: str = "libx264",
    crf: int = DEFAULT_CRF,
    preset: str = DEFAULT_PRESET,
    audio: str = "copy",
    scale_flags: str = DEFAULT_SCALE_FLAGS,
    output_fps: Fraction | None = DEFAULT_OUTPUT_FPS,
    fps_method: str = DEFAULT_FPS_METHOD,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    dry_run: bool = False,
) -> None:
    require_command(ffmpeg)
    require_command(ffprobe)
    require_command(realesrgan)

    source = probe_video(input_path, ffprobe=ffprobe)
    if size is not None:
        target_width, target_height = size
    elif width is not None:
        target_width, target_height = target_from_width(source, width)
    elif height is not None:
        target_width, target_height = target_from_height(source, height)
    else:
        raise ValueError("Provide size, width, or height")

    target_width = even(target_width)
    target_height = even(target_height)
    real_scale = realesrgan_scale or realesrgan_scale_for_target(source, target_width, target_height)

    if dry_run:
        temp_root = Path("<temporary-directory>")
        frame_dir = temp_root / "frames"
        upscaled_dir = temp_root / "upscaled"
        _print_realesrgan_plan(
            input_path,
            output_path,
            frame_dir,
            upscaled_dir,
            source,
            target_width,
            target_height,
            mode,
            realesrgan,
            realesrgan_model,
            realesrgan_model_folder,
            real_scale,
            video_codec,
            crf,
            preset,
            audio,
            scale_flags,
            output_fps,
            fps_method,
            ffmpeg,
        )
        return

    with temporary_work_dir("video-realesrgan-", keep=keep_temp) as temp_root:
        frame_dir = temp_root / "frames"
        upscaled_dir = temp_root / "upscaled"
        frame_dir.mkdir()
        upscaled_dir.mkdir()

        run_command(build_extract_frames_command(input_path, frame_dir, ffmpeg))
        run_command(
            build_realesrgan_command(
                frame_dir,
                upscaled_dir,
                realesrgan=realesrgan,
                model=realesrgan_model,
                model_folder=realesrgan_model_folder,
                scale=real_scale,
            )
        )
        ensure_frames_exist(upscaled_dir)

        scale_filter = ffmpeg_scale_filter(
            mode,
            target_width,
            target_height,
            scale_flags=scale_flags,
            output_fps=output_fps,
            fps_method=fps_method,
        )
        run_command(build_encode_frames_command(
            input_path,
            output_path,
            upscaled_dir,
            source,
            scale_filter,
            output_fps=output_fps,
            video_codec=video_codec,
            crf=crf,
            preset=preset,
            audio=audio,
            ffmpeg=ffmpeg,
        ))
        ensure_output_fps(
            output_path,
            output_fps=output_fps,
            fps_method=fps_method,
            video_codec=video_codec,
            crf=crf,
            preset=preset,
            audio=audio,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
        )


def realesrgan_scale_for_target(source: VideoInfo, target_width: int, target_height: int) -> int:
    required = max(target_width / source.width, target_height / source.height)
    if required <= 2:
        return 2
    if required <= 3:
        return 3
    if required <= 4:
        return 4
    raise ValueError("Real-ESRGAN scale only supports targets up to 4x the source; pass a smaller target")


def build_extract_frames_command(input_path: Path, frame_dir: Path, ffmpeg: str) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        str(frame_dir / "%08d.png"),
    ]


def build_realesrgan_command(
    input_dir: Path,
    output_dir: Path,
    *,
    realesrgan: str,
    model: str,
    model_folder: Path | None,
    scale: int,
) -> list[str]:
    command = [
        realesrgan,
        "-i",
        str(input_dir),
        "-o",
        str(output_dir),
        "-n",
        model,
        "-s",
        str(scale),
    ]
    if model_folder is not None:
        command.extend(["-m", str(model_folder)])
    return command


def build_encode_frames_command(
    input_path: Path,
    output_path: Path,
    frame_dir: Path,
    source: VideoInfo,
    scale_filter: str,
    *,
    output_fps: Fraction | None,
    video_codec: str,
    crf: int,
    preset: str,
    audio: str,
    ffmpeg: str,
) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-framerate",
        format_fps(source.fps),
        "-i",
        str(frame_dir / "%08d.png"),
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a?",
        "-vf",
        scale_filter,
        *ffmpeg_output_fps_args(output_fps),
        "-c:v",
        video_codec,
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-c:a",
        audio,
        "-shortest",
        str(output_path),
    ]


def ensure_frames_exist(directory: Path) -> None:
    if not any(directory.glob("*.png")):
        raise SystemExit(f"Real-ESRGAN did not produce PNG frames in {directory}")


def build_fx_command(
    input_path: Path,
    *,
    target_width: int,
    target_height: int,
    codec: str,
    fx_upscale: str,
) -> list[str]:
    return [
        fx_upscale,
        str(input_path),
        "--width",
        str(target_width),
        "--height",
        str(target_height),
        "--codec",
        codec,
    ]


def video_files(directory: Path) -> set[Path]:
    return {
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".m4v"}
    }


def detect_fx_output(temp_root: Path, before: set[Path], fx_input: Path) -> Path:
    candidates = sorted(video_files(temp_root) - before, key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        candidates = sorted(
            (path for path in video_files(temp_root) if path != fx_input),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    if not candidates:
        raise SystemExit(f"fx-upscale did not produce an output video in {temp_root}")
    if len(candidates) > 1:
        names = ", ".join(path.name for path in candidates)
        raise SystemExit(f"fx-upscale produced multiple possible output videos in {temp_root}: {names}")
    return candidates[0]


def _print_fx_plan(
    input_path: Path,
    output_path: Path,
    fx_input: Path,
    fx_output: Path,
    target_width: int,
    target_height: int,
    mode: str,
    fx_upscale: str,
    fx_codec: str,
    video_codec: str,
    crf: int,
    preset: str,
    audio: str,
    scale_flags: str,
    output_fps: Fraction | None,
    fps_method: str,
    ffmpeg: str,
) -> None:
    scale_filter = ffmpeg_scale_filter(
        mode,
        target_width,
        target_height,
        scale_flags=scale_flags,
        output_fps=output_fps,
        fps_method=fps_method,
    )
    commands = [
        [
            "cp",
            str(input_path),
            str(fx_input),
        ],
        build_fx_command(
            fx_input,
            target_width=target_width,
            target_height=target_height,
            codec=fx_codec,
            fx_upscale=fx_upscale,
        ),
        [
            ffmpeg,
            "-y",
            "-i",
            str(fx_output),
            "-i",
            str(input_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a?",
            "-vf",
            scale_filter,
            *ffmpeg_output_fps_args(output_fps),
            "-c:v",
            video_codec,
            "-crf",
            str(crf),
            "-preset",
            preset,
            "-c:a",
            audio,
            "-shortest",
            str(output_path),
        ],
    ]
    for command in commands:
        print(" ".join(command))


def _print_realesrgan_plan(
    input_path: Path,
    output_path: Path,
    frame_dir: Path,
    upscaled_dir: Path,
    source: VideoInfo,
    target_width: int,
    target_height: int,
    mode: str,
    realesrgan: str,
    realesrgan_model: str,
    realesrgan_model_folder: Path | None,
    real_scale: int,
    video_codec: str,
    crf: int,
    preset: str,
    audio: str,
    scale_flags: str,
    output_fps: Fraction | None,
    fps_method: str,
    ffmpeg: str,
) -> None:
    scale_filter = ffmpeg_scale_filter(
        mode,
        target_width,
        target_height,
        scale_flags=scale_flags,
        output_fps=output_fps,
        fps_method=fps_method,
    )
    commands = [
        ["mkdir", "-p", str(frame_dir), str(upscaled_dir)],
        build_extract_frames_command(input_path, frame_dir, ffmpeg),
        build_realesrgan_command(
            frame_dir,
            upscaled_dir,
            realesrgan=realesrgan,
            model=realesrgan_model,
            model_folder=realesrgan_model_folder,
            scale=real_scale,
        ),
        build_encode_frames_command(
            input_path,
            output_path,
            upscaled_dir,
            source,
            scale_filter,
            output_fps=output_fps,
            video_codec=video_codec,
            crf=crf,
            preset=preset,
            audio=audio,
            ffmpeg=ffmpeg,
        ),
    ]
    for command in commands:
        print(" ".join(command))


def add_common_scale_args(parser: argparse.ArgumentParser) -> None:
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--size", type=parse_size, help="Exact WIDTHxHEIGHT target, for example 1920x1080.")
    target.add_argument("--width", type=int, help="Target width; height is calculated from the source aspect ratio.")
    target.add_argument("--height", type=int, help="Target height; width is calculated from the source aspect ratio.")
    parser.add_argument(
        "--mode",
        choices=("exact", "fit", "fill"),
        default="exact",
        help="exact stretches to target, fit pads, fill crops.",
    )
    parser.add_argument("--video-codec", default="libx264")
    parser.add_argument("--crf", type=int, default=DEFAULT_CRF)
    parser.add_argument("--preset", default=DEFAULT_PRESET)
    parser.add_argument("--audio", default="copy", help="Audio codec setting passed to ffmpeg, usually copy or aac.")
    parser.add_argument(
        "--scale-flags",
        default=DEFAULT_SCALE_FLAGS,
        help="FFmpeg swscale flags. Use an empty string for ffmpeg defaults.",
    )
    parser.add_argument(
        "--fps",
        dest="output_fps",
        type=parse_fps,
        default=DEFAULT_OUTPUT_FPS,
        help="Output frame rate. Use 30 to convert 16fps inputs to 30fps outputs.",
    )
    parser.add_argument(
        "--fps-method",
        choices=("mci", "duplicate"),
        default=DEFAULT_FPS_METHOD,
        help="Frame-rate conversion method. mci uses motion interpolation; duplicate repeats/drops frames.",
    )
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")


def resolve_paths(input_value: str, output_value: str) -> tuple[Path, Path]:
    input_path = Path(input_value).expanduser()
    output_path = Path(output_value).expanduser()
    if not input_path.exists():
        raise SystemExit(f"Input file does not exist: {input_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return input_path, output_path
