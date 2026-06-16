from __future__ import annotations

import argparse

from video_concat import add_concat_args, concat_videos, resolve_concat_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Concatenate multiple videos into one output file.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_concat_args(parser)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    input_paths, output_path = resolve_concat_paths(args.inputs, args.output, inputs_file=args.inputs_file)
    concat_videos(
        input_paths,
        output_path,
        method=args.method,
        reverse=args.reverse,
        video_codec=args.video_codec,
        crf=args.crf,
        preset=args.preset,
        audio_codec=args.audio_codec,
        include_audio=not args.no_audio,
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
