"""
WaveformData  --  background audio waveform extraction for the script timeline.

Uses ffmpeg (subprocess) to decode the video's audio track to raw s16le mono
at a low sample rate (SAMPLE_RATE Hz).  Samples are normalised to 0-1 and
stored for quick lookup during timeline rendering.

No external pip packages needed  --  only stdlib struct + subprocess.
"""

from __future__ import annotations

import logging
import os
import shutil
import struct
import subprocess
import threading
from typing import List, Optional

log = logging.getLogger(__name__)

# Low enough to be fast; high enough for waveform detail at any reasonable zoom.
SAMPLE_RATE = 200  # Hz


class WaveformData:
    """Async audio waveform loader.  Thread-safe for read access once ready."""

    def __init__(self) -> None:
        self._samples: List[float] = []
        self._video_path: str = ""
        self._ready: bool = False
        self._loading: bool = False
        self._duration: float = 0.0

    # ----------------------------------------------------------------------
    # Properties
    # ----------------------------------------------------------------------

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def loading(self) -> bool:
        return self._loading

    @property
    def duration(self) -> float:
        return self._duration

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------

    def clear(self) -> None:
        self._samples = []
        self._ready = False
        self._loading = False
        self._video_path = ""
        self._duration = 0.0

    def load_async(self, video_path: str) -> None:
        """Start waveform extraction in a background thread.
        Safe to call multiple times  --  ignores if already loaded for same path."""
        if not video_path:
            return
        if video_path == self._video_path and self._ready:
            return
        if self._loading:
            return
        self._video_path = video_path
        self._ready = False
        self._loading = True
        t = threading.Thread(
            target=self._load_thread,
            args=(video_path,),
            daemon=True,
            name="WaveformLoader",
        )
        t.start()

    def get_max_in_range(self, t_start: float, t_end: float) -> float:
        """Return the max amplitude (0-1) in the time window [t_start, t_end].

        Returns 0.0 if waveform not ready or no samples in range.
        """
        if not self._ready or not self._samples:
            return 0.0
        i0 = max(0, int(t_start * SAMPLE_RATE))
        i1 = min(len(self._samples), int(t_end * SAMPLE_RATE) + 1)
        if i0 >= i1:
            return 0.0
        return max(self._samples[i0:i1])

    # ----------------------------------------------------------------------
    # Background loader thread
    # ----------------------------------------------------------------------

    def _load_thread(self, video_path: str) -> None:
        try:
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                log.warning("Waveform: ffmpeg not found in PATH - waveform unavailable")
                return

            # Decode audio to raw signed 16-bit mono at SAMPLE_RATE Hz.
            # We pipe directly to stdout to avoid temp files.
            cmd = [
                ffmpeg,
                "-y",
                "-loglevel", "quiet",
                "-i", video_path,
                "-vn",                      # skip video
                "-ac", "1",                 # mono
                "-ar", str(SAMPLE_RATE),    # resample to low rate
                "-f", "s16le",              # raw s16 little-endian
                "-",                        # output to stdout
            ]
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=120,
            )
            raw = result.stdout
            n = len(raw) // 2
            if n == 0:
                log.warning("Waveform: no audio data extracted from %s", video_path)
                return

            # Unpack samples
            samples_raw: tuple = struct.unpack(f"<{n}h", raw)

            # Normalise to 0-1 using absolute values
            max_val = max(abs(s) for s in samples_raw)
            if max_val == 0:
                max_val = 1
            self._samples = [abs(s) / max_val for s in samples_raw]
            self._duration = n / SAMPLE_RATE
            self._ready = True
            log.info(
                "Waveform loaded: %d samples, %.1fs - %s",
                n,
                self._duration,
                os.path.basename(video_path),
            )
        except subprocess.TimeoutExpired:
            log.warning("Waveform: ffmpeg timed out for %s", video_path)
        except Exception as exc:
            log.error("Waveform load failed: %s", exc)
        finally:
            self._loading = False
