from __future__ import annotations

import argparse

from video_scale import add_common_scale_args, resolve_paths, upscale_with_fx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upscale video with fx-upscale, then resize/remux with ffmpeg.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", help="Input video path.")
    parser.add_argument("output", help="Output video path.")
    add_common_scale_args(parser)
    parser.add_argument("--fx-upscale", default="fx-upscale", help="fx-upscale executable.")
    parser.add_argument(
        "--fx-codec",
        choices=("hevc", "prores", "h264"),
        help="Intermediate codec passed to fx-upscale. Defaults from --video-codec when possible.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the temporary fx-upscale working directory after completion or failure.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    input_path, output_path = resolve_paths(args.input, args.output)
    upscale_with_fx(
        input_path,
        output_path,
        size=args.size,
        width=args.width,
        height=args.height,
        mode=args.mode,
        fx_upscale=args.fx_upscale,
        fx_codec=args.fx_codec,
        keep_temp=args.keep_temp,
        video_codec=args.video_codec,
        crf=args.crf,
        preset=args.preset,
        pixel_format=args.pixel_format or None,
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
