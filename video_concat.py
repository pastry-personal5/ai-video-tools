from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from video_scale import DEFAULT_CRF, DEFAULT_PRESET, require_command, run_command


@dataclass(frozen=True)
class StreamInfo:
    video_codec: str | None
    has_audio: bool


def probe_streams(input_path: Path, *, ffprobe: str = "ffprobe") -> StreamInfo:
    require_command(ffprobe)
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,codec_name",
        "-of",
        "json",
        str(input_path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    video_codec = video_stream.get("codec_name") if video_stream else None
    return StreamInfo(
        video_codec=video_codec,
        has_audio=any(stream.get("codec_type") == "audio" for stream in streams),
    )


def validate_copy_container(input_paths: list[Path], output_path: Path, *, ffprobe: str = "ffprobe") -> None:
    output_suffix = output_path.suffix.lower()
    if output_suffix not in {".mp4", ".m4v"}:
        return

    first_stream = probe_streams(input_paths[0], ffprobe=ffprobe)
    if first_stream.video_codec == "prores":
        mov_output = output_path.with_suffix(".mov")
        raise SystemExit(
            "Cannot stream-copy ProRes video into an MP4 container. "
            f"Use a .mov output to preserve ProRes quality, for example: --output {mov_output} "
            "Or use --method reencode for an H.264 MP4 output."
        )


def concat_file_line(path: Path) -> str:
    escaped = str(path.resolve()).replace("'", "'\\''")
    return f"file '{escaped}'"


def write_concat_list(input_paths: list[Path], list_path: Path) -> None:
    list_path.write_text("\n".join(concat_file_line(path) for path in input_paths) + "\n", encoding="utf-8")


def build_concat_copy_command(
    list_path: Path,
    output_path: Path,
    *,
    ffmpeg: str = "ffmpeg",
) -> list[str]:
    require_command(ffmpeg)
    return [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c",
        "copy",
        str(output_path),
    ]


def build_concat_reencode_command(
    input_paths: list[Path],
    output_path: Path,
    *,
    video_codec: str = "libx264",
    crf: int = DEFAULT_CRF,
    preset: str = DEFAULT_PRESET,
    audio_codec: str = "aac",
    include_audio: bool = True,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> list[str]:
    require_command(ffmpeg)
    stream_info = [probe_streams(path, ffprobe=ffprobe) for path in input_paths]
    can_concat_audio = include_audio and all(info.has_audio for info in stream_info)

    command = [ffmpeg, "-y"]
    for path in input_paths:
        command.extend(["-i", str(path)])

    if can_concat_audio:
        segments = "".join(f"[{index}:v:0][{index}:a:0]" for index in range(len(input_paths)))
        filter_complex = f"{segments}concat=n={len(input_paths)}:v=1:a=1[v][a]"
        maps = ["-map", "[v]", "-map", "[a]"]
        audio_args = ["-c:a", audio_codec]
    else:
        segments = "".join(f"[{index}:v:0]" for index in range(len(input_paths)))
        filter_complex = f"{segments}concat=n={len(input_paths)}:v=1:a=0[v]"
        maps = ["-map", "[v]"]
        audio_args = ["-an"]

    command.extend([
        "-filter_complex",
        filter_complex,
        *maps,
        "-c:v",
        video_codec,
        "-crf",
        str(crf),
        "-preset",
        preset,
        *audio_args,
        str(output_path),
    ])
    return command


def concat_videos(
    input_paths: list[Path],
    output_path: Path,
    *,
    method: str = "copy",
    reverse: bool = False,
    video_codec: str = "libx264",
    crf: int = DEFAULT_CRF,
    preset: str = DEFAULT_PRESET,
    audio_codec: str = "aac",
    include_audio: bool = True,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    dry_run: bool = False,
) -> None:
    if len(input_paths) < 2:
        raise SystemExit("Provide at least two input videos.")
    if reverse:
        input_paths = list(reversed(input_paths))

    if method == "copy":
        validate_copy_container(input_paths, output_path, ffprobe=ffprobe)
        with tempfile.TemporaryDirectory(prefix="video-concat-") as temp_name:
            list_path = Path(temp_name) / "inputs.txt"
            write_concat_list(input_paths, list_path)
            command = build_concat_copy_command(list_path, output_path, ffmpeg=ffmpeg)
            if dry_run:
                print(list_path.read_text(encoding="utf-8"), end="")
            run_command(command, dry_run=dry_run)
        return

    if method == "reencode":
        command = build_concat_reencode_command(
            input_paths,
            output_path,
            video_codec=video_codec,
            crf=crf,
            preset=preset,
            audio_codec=audio_codec,
            include_audio=include_audio,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
        )
        run_command(command, dry_run=dry_run)
        return

    raise ValueError(f"Unknown concat method: {method}")


def read_input_list(list_path: Path) -> list[str]:
    values: list[str] = []
    for raw_line in list_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("file "):
            line = line[5:].strip()
        if len(line) >= 2 and line[0] == "'" and line[-1] == "'":
            line = line[1:-1].replace("'\\''", "'")
        values.append(line)
    return values


def resolve_concat_paths(
    input_values: list[str],
    output_value: str,
    *,
    inputs_file: str | None = None,
) -> tuple[list[Path], Path]:
    if inputs_file:
        input_values = [*input_values, *read_input_list(Path(inputs_file).expanduser())]
    input_paths = [Path(value).expanduser() for value in input_values]
    missing = [str(path) for path in input_paths if not path.exists()]
    if missing:
        raise SystemExit("Input file does not exist: " + ", ".join(missing))
    output_path = Path(output_value).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return input_paths, output_path


def add_concat_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("inputs", nargs="*", help="Input videos in concatenation order.")
    parser.add_argument("-o", "--output", required=True, help="Output video path.")
    parser.add_argument(
        "--inputs-file",
        help="Text file containing one input video path per line. ffmpeg concat list files are also accepted.",
    )
    parser.add_argument(
        "--method",
        choices=("copy", "reencode"),
        default="copy",
        help="copy preserves original encoded streams; reencode handles mismatched inputs.",
    )
    parser.add_argument("--video-codec", default="libx264")
    parser.add_argument("--crf", type=int, default=DEFAULT_CRF)
    parser.add_argument("--preset", default=DEFAULT_PRESET)
    parser.add_argument("--audio-codec", default="aac")
    parser.add_argument("--no-audio", action="store_true", help="Drop audio in reencode mode.")
    parser.add_argument("--reverse", action="store_true", help="Concatenate the input file paths in reverse order.")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
