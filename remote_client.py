# -*- coding: utf-8 -*-
"""Remote Screen Companion Client.

Capture screenshots locally and push them to the plugin via WebSocket.

Usage:
    python remote_client.py --server ws://your-server:6315 --token your-token
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import logging
import platform
import os
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Any

pyautogui = None

try:
    import websockets
except ImportError:
    print("ERROR: pip install websockets")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("screen_client")


def get_active_window_title() -> str:
    """Get the active window title when the platform supports it."""
    try:
        if sys.platform == "win32":
            import pygetwindow

            win = pygetwindow.getActiveWindow()
            return str(win.title or "").strip() if win else ""
        if sys.platform == "darwin":
            import subprocess

            script = (
                "tell application \"System Events\" to get name of first application "
                "process whose frontmost is true"
            )
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip()

        import subprocess

        result = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception as e:
        log.debug(f"Failed to get window title: {e}")
        return ""


def get_system_stats() -> dict[str, Any]:
    stats: dict[str, Any] = {}
    try:
        import psutil

        stats["cpu_percent"] = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        stats["memory_percent"] = mem.percent
        stats["memory_used_mb"] = mem.used // (1024 * 1024)
        battery = psutil.sensors_battery()
        if battery:
            stats["battery_percent"] = battery.percent
            stats["battery_plugged"] = battery.power_plugged
    except ImportError:
        pass
    return stats


def capture_screenshot(image_quality: int = 70) -> bytes:
    global pyautogui
    if pyautogui is None:
        try:
            import pyautogui as pyautogui_module
        except ImportError as exc:
            raise RuntimeError("截图模式需要 pyautogui 和 Pillow，请先安装客户端依赖") from exc
        pyautogui = pyautogui_module
    screenshot = pyautogui.screenshot()
    if screenshot.mode != "RGB":
        screenshot = screenshot.convert("RGB")
    buf = io.BytesIO()
    screenshot.save(buf, format="JPEG", quality=image_quality)
    return buf.getvalue()


def capture_video(duration_seconds: int, ffmpeg_path: str = "") -> bytes:
    """Capture a short MP4 clip using the platform's ffmpeg input."""
    duration = max(1, int(duration_seconds or 10))
    ffmpeg = ffmpeg_path.strip() or ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    output_path = os.path.join(tempfile.gettempdir(), f"screen_companion_{uuid.uuid4().hex}.mp4")
    if sys.platform == "win32":
        input_args = ["-f", "gdigrab", "-framerate", "5", "-i", "desktop"]
    elif sys.platform == "darwin":
        input_args = ["-f", "avfoundation", "-framerate", "5", "-i", "1:none"]
    else:
        display = os.environ.get("DISPLAY", ":0")
        input_args = ["-f", "x11grab", "-framerate", "5", "-i", f"{display}.0"]
    command = [ffmpeg, "-y", *input_args, "-t", str(duration), "-pix_fmt", "yuv420p", output_path]
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=duration + 20,
        )
        with open(output_path, "rb") as video_file:
            return video_file.read()
    finally:
        try:
            os.remove(output_path)
        except OSError:
            pass


async def send_video(
    ws,
    video_bytes: bytes,
    *,
    window_title: str,
    client_id: str,
    duration_seconds: int = 0,
) -> None:
    """Upload a video in bounded base64 JSON chunks."""
    upload_id = uuid.uuid4().hex
    chunk_size = 5 * 1024 * 1024
    await ws.send(json.dumps({
        "type": "video_meta",
        "upload_id": upload_id,
        "total_size": len(video_bytes),
        "mime_type": "video/mp4",
        "window_title": window_title,
        "client_id": client_id,
        "duration_seconds": max(0, int(duration_seconds or 0)),
        "timestamp": time.time(),
    }))
    ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=10.0))
    if ready.get("status") != "video_ready":
        raise RuntimeError(f"Video upload rejected: {ready}")
    for index, offset in enumerate(range(0, len(video_bytes), chunk_size)):
        chunk = video_bytes[offset : offset + chunk_size]
        await ws.send(json.dumps({
            "type": "video_chunk",
            "upload_id": upload_id,
            "index": index,
            "data": base64.b64encode(chunk).decode("ascii"),
        }))
        ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=20.0))
        if ack.get("status") != "video_chunk_received":
            raise RuntimeError(f"Video chunk rejected: {ack}")
    await ws.send(json.dumps({"type": "video_complete", "upload_id": upload_id}))
    complete = json.loads(await asyncio.wait_for(ws.recv(), timeout=20.0))
    if complete.get("status") != "video_complete":
        raise RuntimeError(f"Video upload failed: {complete}")


async def run_client(
    server_url: str,
    token: str,
    interval: float,
    image_quality: int,
    client_id: str,
    binary: bool = False,
    video_enabled: bool = False,
    screenshot_only: bool = False,
    video_only: bool = False,
    video_duration: int = 10,
    ffmpeg_path: str = "",
    heartbeat_interval: float = 30.0,
) -> None:
    last_heartbeat = 0.0
    while True:
        try:
            log.info(f"Connecting to {server_url} ...")
            async with websockets.connect(server_url) as ws:
                if token:
                    await ws.send(json.dumps({"token": token}))
                    resp = json.loads(await ws.recv())
                    if resp.get("status") not in {"authenticated", "ready"}:
                        log.error(f"Auth failed: {resp}")
                        await asyncio.sleep(5)
                        continue
                    log.info(f"Server status: {resp.get('status')}")
                else:
                    resp = json.loads(await ws.recv())
                    log.info(f"Server status: {resp.get('status')}")

                while True:
                    try:
                        now = time.monotonic()
                        if heartbeat_interval > 0 and now - last_heartbeat >= heartbeat_interval:
                            await ws.send(json.dumps({"type": "ping"}))
                            pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=10.0))
                            if pong.get("type") != "pong":
                                raise RuntimeError(f"Heartbeat failed: {pong}")
                            last_heartbeat = now

                        jpeg_bytes = b""
                        if not video_only:
                            jpeg_bytes = await asyncio.to_thread(
                                capture_screenshot,
                                image_quality,
                            )
                        window_title = await asyncio.to_thread(get_active_window_title)
                        system_stats = await asyncio.to_thread(get_system_stats)

                        if not video_only:
                            if binary:
                                await ws.send(json.dumps({
                                    "type": "screenshot_meta",
                                    "window_title": window_title,
                                    "system_stats": system_stats,
                                    "timestamp": time.time(),
                                    "client_id": client_id,
                                }))
                                meta_ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=10.0))
                                if meta_ack.get("status") != "meta_received":
                                    raise RuntimeError(f"Screenshot metadata rejected: {meta_ack}")
                                await ws.send(jpeg_bytes)
                            else:
                                await ws.send(json.dumps({
                                    "type": "screenshot_bundle",
                                    "image": base64.b64encode(jpeg_bytes).decode("ascii"),
                                    "window_title": window_title,
                                    "system_stats": system_stats,
                                    "timestamp": time.time(),
                                    "client_id": client_id,
                                }))

                            ack = await asyncio.wait_for(ws.recv(), timeout=10.0)
                            ack_data = json.loads(ack)
                            log.debug(f"Ack: {ack_data.get('status')}")
                        if video_enabled and not screenshot_only:
                            video_bytes = await asyncio.to_thread(capture_video, video_duration, ffmpeg_path)
                            await send_video(
                                ws,
                                video_bytes,
                                window_title=window_title,
                                client_id=client_id,
                                duration_seconds=video_duration,
                            )
                        material = f"screenshot: {len(jpeg_bytes)} bytes" if not video_only else "video"
                        log.info(f"Sent {material}, window='{window_title}'")
                    except asyncio.TimeoutError:
                        log.warning("Ack timeout, continuing...")
                    except Exception as e:
                        log.error(f"Send error: {e}")
                        break

                    await asyncio.sleep(interval)

        except websockets.exceptions.ConnectionClosed as e:
            log.warning(f"Connection closed: {e}, reconnecting in 5s...")
            await asyncio.sleep(5)
        except ConnectionRefusedError:
            log.warning("Connection refused, retrying in 10s...")
            await asyncio.sleep(10)
        except Exception as e:
            log.error(f"Unexpected error: {e}, reconnecting in 10s...")
            await asyncio.sleep(10)


def main():
    parser = argparse.ArgumentParser(description="Remote Screen Companion Client")
    parser.add_argument(
        "--server",
        "-s",
        required=True,
        help="WebSocket server URL, e.g. ws://your-server:6315",
    )
    parser.add_argument(
        "--token",
        "-t",
        default="",
        help="Authentication token. Leave empty only if the server also allows no auth.",
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=float,
        default=10.0,
        help="Screenshot interval in seconds (default: 10)",
    )
    parser.add_argument(
        "--quality",
        "-q",
        type=int,
        default=70,
        help="JPEG quality 1-100 (default: 70)",
    )
    parser.add_argument(
        "--client-id",
        default=f"client_{platform.node()}",
        help="Client identifier",
    )
    parser.add_argument("--binary", action="store_true", help="Use metadata plus raw JPEG bytes")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--screenshot-only", action="store_true", help="Only send screenshots")
    mode_group.add_argument("--video-only", action="store_true", help="Only send video clips")
    parser.add_argument("--video", action="store_true", help="Also upload a short video after each screenshot")
    parser.add_argument("--video-duration", type=int, default=10, help="Video duration in seconds")
    parser.add_argument("--ffmpeg", dest="ffmpeg_path", default="", help="ffmpeg executable path")
    parser.add_argument("--heartbeat", type=float, default=30.0, help="Heartbeat interval in seconds")
    args = parser.parse_args()

    log.info("Starting remote screen client")
    log.info(f"  Server: {args.server}")
    log.info(f"  Interval: {args.interval}s")
    log.info(f"  Quality: {args.quality}")
    log.info(f"  Client ID: {args.client_id}")

    try:
        asyncio.run(
            run_client(
                server_url=args.server,
                token=args.token,
                interval=args.interval,
                image_quality=args.quality,
                client_id=args.client_id,
                binary=args.binary,
                video_enabled=args.video or args.video_only,
                screenshot_only=args.screenshot_only,
                video_only=args.video_only,
                video_duration=args.video_duration,
                ffmpeg_path=args.ffmpeg_path,
                heartbeat_interval=args.heartbeat,
            )
        )
    except KeyboardInterrupt:
        log.info("Client stopped")


if __name__ == "__main__":
    main()
