from __future__ import annotations

import argparse

from video_scale import add_common_scale_args, resolve_paths, scale_with_ffmpeg


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scale a video with ffmpeg.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", help="Input video path.")
    parser.add_argument("output", help="Output video path.")
    add_common_scale_args(parser)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    input_path, output_path = resolve_paths(args.input, args.output)
    scale_with_ffmpeg(
        input_path,
        output_path,
        size=args.size,
        width=args.width,
        height=args.height,
        mode=args.mode,
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
