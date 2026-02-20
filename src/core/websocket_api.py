"""
WebSocket API — real-time OFS bridge.

Mirrors the OFS Lua/WebSocket extension API so that external tools
(TCode firmware, haptics runtimes, custom GUIs) can subscribe to
playback events and send commands.

Protocol: newline-delimited JSON over WebSocket.

Inbound messages (client → server):
  {"type": "seek",    "time": <seconds>}
  {"type": "play"}
  {"type": "pause"}
  {"type": "speed",   "speed": <float>}
  {"type": "add_action",  "at": <ms>, "pos": <0-100>}
  {"type": "remove_action","at": <ms>}
  {"type": "save"}

Outbound messages (server → all clients):
  {"type": "position",  "time": <seconds>, "pos": <0-100|null>}
  {"type": "duration",  "duration": <seconds>}
  {"type": "playing",   "playing": <bool>}
  {"type": "actions",   "script": <name>, "actions": [...]}
  {"type": "error",     "message": <str>}

Usage::

    api = WebSocketAPI(port=8080)
    api.set_callbacks(
        on_seek=player.seek_absolute,
        on_play=player.play,
        on_pause=player.pause,
        on_speed=player.set_speed,
        on_add_action=...,
        on_remove_action=...,
        on_save=...,
    )
    api.start()      # non-blocking (runs in thread)
    api.broadcast_position(t_s, pos_0_100)
    api.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Callable, Dict, Optional, Set

log = logging.getLogger(__name__)

try:
    import websockets
    from websockets.server import WebSocketServerProtocol
    _HAS_WEBSOCKETS = True
except ImportError:
    _HAS_WEBSOCKETS = False


class WebSocketAPI:
    """
    Lightweight WebSocket server that exposes OFS state to external clients.

    Thread-safe: public methods may be called from the Qt main thread;
    the asyncio event loop runs on a dedicated daemon thread.
    """

    def __init__(self, host: str = "localhost", port: int = 8080) -> None:
        self._host = host
        self._port = port
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server = None
        self._thread: Optional[threading.Thread] = None
        self._clients: Set["WebSocketServerProtocol"] = set()
        self._running = False
        self._stop_event: Optional[asyncio.Event] = None

        # Callbacks set by the main window
        self._on_seek:          Optional[Callable[[float], None]] = None
        self._on_play:          Optional[Callable[[], None]] = None
        self._on_pause:         Optional[Callable[[], None]] = None
        self._on_speed:         Optional[Callable[[float], None]] = None
        self._on_add_action:    Optional[Callable[[int, int], None]] = None
        self._on_remove_action: Optional[Callable[[int], None]] = None
        self._on_save:          Optional[Callable[[], None]] = None

    # ------------------------------------------------------------------
    # Public API (called from Qt thread)
    # ------------------------------------------------------------------

    def set_callbacks(self, **kwargs: Callable) -> None:
        """
        Register handler callables.

        Accepted keyword args: on_seek, on_play, on_pause, on_speed,
        on_add_action, on_remove_action, on_save.
        """
        for key, val in kwargs.items():
            attr = f"_{key}"
            if hasattr(self, attr):
                setattr(self, attr, val)
            else:
                log.warning("WebSocketAPI.set_callbacks: unknown key %r", key)

    def start(self) -> bool:
        """Start the WebSocket server in a background thread. Returns True on success."""
        if not _HAS_WEBSOCKETS:
            log.warning("websockets package not installed; WebSocket API disabled.")
            return False
        if self._running:
            return True
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="WebSocketAPI"
        )
        self._thread.start()
        self._running = True
        log.info("WebSocket API started on ws://%s:%d", self._host, self._port)
        return True

    def stop(self) -> None:
        """Gracefully shut down the server."""
        if not self._running or self._loop is None:
            return
        self._running = False
        asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        if self._thread:
            self._thread.join(timeout=3.0)

    def broadcast_position(self, time_s: float, pos: Optional[float] = None) -> None:
        """Send current playhead position (seconds) and script position (0-100)."""
        self._broadcast_nowait({"type": "position", "time": round(time_s, 4),
                                 "pos": round(pos, 1) if pos is not None else None})

    def broadcast_duration(self, duration_s: float) -> None:
        self._broadcast_nowait({"type": "duration", "duration": round(duration_s, 3)})

    def broadcast_playing(self, playing: bool) -> None:
        self._broadcast_nowait({"type": "playing", "playing": playing})

    def broadcast_actions(self, script_name: str, actions: list) -> None:
        """Broadcast full action list for a script (after edits)."""
        payload = [{"at": a.at, "pos": a.pos} for a in actions]
        self._broadcast_nowait({"type": "actions", "script": script_name,
                                 "actions": payload})

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def port(self) -> int:
        return self._port

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self) -> None:
        self._stop_event = asyncio.Event()
        # Try self._port, then self._port+1 … self._port+9
        for attempt in range(10):
            port = self._port + attempt
            try:
                async with websockets.serve(self._handler, self._host, port):
                    if attempt:
                        self._port = port
                        log.info("WebSocket API bound to ws://%s:%d (fallback port)", self._host, port)
                    await self._stop_event.wait()  # run until stop() sets the event
                return
            except OSError:
                if attempt == 9:
                    log.error("WebSocket API: could not bind on ports %d-%d", self._port, port)
                    raise

    async def _shutdown(self) -> None:
        if self._stop_event:
            self._stop_event.set()

    async def _handler(self, ws: "WebSocketServerProtocol", path: str = "/") -> None:
        self._clients.add(ws)
        log.debug("WS client connected: %s", ws.remote_address)
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    await self._dispatch(msg)
                except json.JSONDecodeError:
                    await ws.send(json.dumps({"type": "error",
                                              "message": "invalid JSON"}))
        except Exception:
            pass
        finally:
            self._clients.discard(ws)
            log.debug("WS client disconnected: %s", ws.remote_address)

    async def _dispatch(self, msg: Dict[str, Any]) -> None:
        """Route an inbound message to the appropriate callback."""
        t = msg.get("type")
        try:
            if t == "seek" and self._on_seek:
                self._on_seek(float(msg["time"]))
            elif t == "play" and self._on_play:
                self._on_play()
            elif t == "pause" and self._on_pause:
                self._on_pause()
            elif t == "speed" and self._on_speed:
                self._on_speed(float(msg["speed"]))
            elif t == "add_action" and self._on_add_action:
                self._on_add_action(int(msg["at"]), int(msg["pos"]))
            elif t == "remove_action" and self._on_remove_action:
                self._on_remove_action(int(msg["at"]))
            elif t == "save" and self._on_save:
                self._on_save()
        except (KeyError, ValueError, TypeError) as e:
            log.warning("WS dispatch error for %r: %s", t, e)

    def _broadcast_nowait(self, payload: Dict[str, Any]) -> None:
        """Thread-safe fire-and-forget broadcast."""
        if not self._running or not self._clients or self._loop is None:
            return
        data = json.dumps(payload)
        asyncio.run_coroutine_threadsafe(self._broadcast(data), self._loop)

    async def _broadcast(self, data: str) -> None:
        dead = set()
        for ws in list(self._clients):
            try:
                await ws.send(data)
            except Exception:
                dead.add(ws)
        self._clients -= dead
