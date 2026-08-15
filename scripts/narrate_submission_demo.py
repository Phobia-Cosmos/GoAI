#!/usr/bin/env python3
"""Generate synchronized Mandarin narration and mux it into the demo WebM."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
from pathlib import Path

import edge_tts
import imageio_ffmpeg


DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"


def ffmpeg_executable() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def media_duration(path: Path) -> float:
    result = subprocess.run(
        [ffmpeg_executable(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        raise RuntimeError(f"无法读取媒体时长：{path}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


async def prepare(output: Path, voice: str, rate: str) -> None:
    scenes_path = output / "scenes.json"
    payload = json.loads(scenes_path.read_text(encoding="utf-8"))
    voice_dir = output / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, scene in enumerate(payload["scenes"], 1):
        target = voice_dir / f"{index:02d}.mp3"
        communicate = edge_tts.Communicate(scene["caption"], voice=voice, rate=rate, volume="+0%")
        await communicate.save(str(target))
        rows.append({
            "index": index,
            "caption": scene["caption"],
            "voice": voice,
            "rate": rate,
            "file": target.name,
            "duration_seconds": round(media_duration(target), 3),
        })
    manifest = {"voice": voice, "rate": rate, "segments": rows}
    (output / "voice_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"segments": len(rows), "voice": voice, "speech_seconds": round(sum(row["duration_seconds"] for row in rows), 2)}, ensure_ascii=False))


def mix(output: Path) -> None:
    scenes = json.loads((output / "scenes.json").read_text(encoding="utf-8"))["scenes"]
    manifest = json.loads((output / "voice_manifest.json").read_text(encoding="utf-8"))
    silent_video = output / "StratPilot_Interactive_Demo_Silent.webm"
    narrated_video = output / "StratPilot_Interactive_Demo.webm"
    video_duration = media_duration(silent_video)
    if len(scenes) != len(manifest["segments"]):
        raise RuntimeError("场景数量和旁白数量不一致，请重新执行 prepare")
    command = [ffmpeg_executable(), "-y", "-i", str(silent_video)]
    for row in manifest["segments"]:
        command.extend(["-i", str(output / "voice" / row["file"])])
    filters = []
    labels = []
    for index, scene in enumerate(scenes, 1):
        delay_ms = max(0, round(float(scene.get("at_seconds") or 0) * 1000))
        label = f"voice{index}"
        filters.append(f"[{index}:a]adelay={delay_ms}|{delay_ms}[{label}]")
        labels.append(f"[{label}]")
    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0,apad=whole_dur={video_duration:.3f}[aout]")
    command.extend([
        "-filter_complex", ";".join(filters),
        "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "libopus", "-b:a", "96k", "-t", f"{video_duration:.3f}",
        str(narrated_video),
    ])
    subprocess.run(command, check=True)
    print(json.dumps({
        "output": str(narrated_video),
        "duration_seconds": round(media_duration(narrated_video), 3),
        "voice": manifest["voice"],
        "audio_codec": "Opus",
    }, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "mix"))
    parser.add_argument("--output", type=Path, default=Path("artifact/submission/demo"))
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--rate", default="+12%")
    args = parser.parse_args()
    if args.mode == "prepare":
        asyncio.run(prepare(args.output, args.voice, args.rate))
    else:
        mix(args.output)


if __name__ == "__main__":
    main()
