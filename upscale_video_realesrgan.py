from __future__ import annotations

import argparse
from pathlib import Path

from video_scale import add_common_scale_args, resolve_paths, upscale_with_realesrgan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upscale video with Real-ESRGAN, then resize/remux with ffmpeg.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", help="Input video path.")
    parser.add_argument("output", help="Output video path.")
    add_common_scale_args(parser)
    parser.add_argument(
        "--realesrgan",
        default="realesrgan-ncnn-vulkan",
        help="Real-ESRGAN executable.",
    )
    parser.add_argument(
        "--realesrgan-model",
        default="realesrgan-x4plus",
        help="Model name passed to Real-ESRGAN.",
    )
    parser.add_argument(
        "--realesrgan-model-folder",
        type=Path,
        help="Folder containing Real-ESRGAN model files; passed as -m.",
    )
    parser.add_argument(
        "--realesrgan-scale",
        type=int,
        choices=(2, 3, 4),
        help="Intermediate Real-ESRGAN scale. Defaults to the smallest supported scale that covers the target.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the temporary frame directories after completion or failure.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    input_path, output_path = resolve_paths(args.input, args.output)
    model_folder = args.realesrgan_model_folder.expanduser() if args.realesrgan_model_folder else None
    upscale_with_realesrgan(
        input_path,
        output_path,
        size=args.size,
        width=args.width,
        height=args.height,
        mode=args.mode,
        realesrgan=args.realesrgan,
        realesrgan_model=args.realesrgan_model,
        realesrgan_model_folder=model_folder,
        realesrgan_scale=args.realesrgan_scale,
        keep_temp=args.keep_temp,
        video_codec=args.video_codec,
        crf=args.crf,
        preset=args.preset,
        audio=args.audio,
        scale_flags=args.scale_flags,
        output_fps=args.output_fps,
        fps_method=args.fps_method,
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
