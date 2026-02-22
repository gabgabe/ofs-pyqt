"""
WebSocket API — real-time OFS bridge.

Implements the OFS WebSocket extension protocol so that external tools
(TCode firmware, haptics runtimes, custom GUIs) can subscribe to
playback events and send commands.

Protocol: JSON over WebSocket, path: ws://host:port/ofs

Outbound events (server → all clients):
  {"type":"event","name":"time_change",         "data":{"time":<s>}}
  {"type":"event","name":"play_change",          "data":{"playing":<bool>}}
  {"type":"event","name":"duration_change",      "data":{"duration":<s>}}
  {"type":"event","name":"media_change",         "data":{"path":<str>}}
  {"type":"event","name":"playbackspeed_change", "data":{"speed":<float>}}
  {"type":"event","name":"project_change",       "data":{}}
  {"type":"event","name":"funscript_change",     "data":{"name":<str>,"actions":[...]}}
  {"type":"event","name":"funscript_remove",     "data":{"name":<str>}}

Inbound commands (client → server):
  {"type":"command","name":"change_time",           "data":{"time":<s>}}
  {"type":"command","name":"change_play",           "data":{"playing":<bool>}}
  {"type":"command","name":"change_playbackspeed",  "data":{"speed":<float>}}

On connect: {"connected":"OFS 3.0.0"} followed by full state dump (UpdateAll).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Set

log = logging.getLogger(__name__)

OFS_VERSION = "3.0.0"
WS_PATH = "/ofs"
FUNSCRIPT_DEBOUNCE_S = 0.200   # 200 ms debounce per script

try:
    import websockets
    from websockets.server import WebSocketServerProtocol
    _HAS_WEBSOCKETS = True
except ImportError:
    _HAS_WEBSOCKETS = False


def _event(name: str, data: Dict[str, Any]) -> str:
    """Serialize an outbound event envelope to JSON."""
    return json.dumps({"type": "event", "name": name, "data": data})


class WebSocketAPI:
    """
    Lightweight WebSocket server that exposes OFS state to external clients.

    Thread-safe: public methods may be called from the main thread;
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

        # State getters (registered by app via set_state_getters)
        self._get_time:       Optional[Callable[[], float]] = None
        self._get_duration:   Optional[Callable[[], float]] = None
        self._get_playing:    Optional[Callable[[], bool]]  = None
        self._get_speed:      Optional[Callable[[], float]] = None
        self._get_media:      Optional[Callable[[], str]]   = None
        self._get_funscripts: Optional[Callable[[], List]]  = None

        # Command callbacks (registered by app via set_callbacks)
        self._on_change_time:          Optional[Callable[[float], None]] = None
        self._on_change_play:          Optional[Callable[[bool], None]]  = None
        self._on_change_playbackspeed: Optional[Callable[[float], None]] = None

        # Per-script debounce state for funscript_change
        self._pending_handles: Dict[str, asyncio.TimerHandle] = {}
        self._pending_data:    Dict[str, str]                 = {}

    # ------------------------------------------------------------------
    # Public configuration  (called from main thread before/after start)
    # ------------------------------------------------------------------

    def set_state_getters(self, **kwargs: Callable) -> None:
        """
        Register getter callables for the on-connect UpdateAll dump.

        Accepted keys: get_time, get_duration, get_playing, get_speed,
        get_media, get_funscripts.
        """
        for key, val in kwargs.items():
            attr = f"_{key}"
            if hasattr(self, attr):
                setattr(self, attr, val)
            else:
                log.warning("WebSocketAPI.set_state_getters: unknown key %r", key)

    def set_callbacks(self, **kwargs: Callable) -> None:
        """
        Register command handler callables.

        Accepted keys: on_change_time, on_change_play, on_change_playbackspeed.
        """
        for key, val in kwargs.items():
            attr = f"_{key}"
            if hasattr(self, attr):
                setattr(self, attr, val)
            else:
                log.warning("WebSocketAPI.set_callbacks: unknown key %r", key)

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

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
        log.info("WebSocket API started on ws://%s:%d%s",
                 self._host, self._port, WS_PATH)
        return True

    def stop(self) -> None:
        """Gracefully shut down the server."""
        if not self._running or self._loop is None:
            return
        self._running = False
        asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        if self._thread:
            self._thread.join(timeout=3.0)

    # ------------------------------------------------------------------
    # Outbound broadcasts  (called from main thread)
    # ------------------------------------------------------------------

    def broadcast_time_change(self, time_s: float) -> None:
        self._broadcast_nowait(_event("time_change", {"time": round(time_s, 4)}))

    def broadcast_play_change(self, playing: bool) -> None:
        self._broadcast_nowait(_event("play_change", {"playing": bool(playing)}))

    def broadcast_duration_change(self, duration_s: float) -> None:
        self._broadcast_nowait(_event("duration_change",
                                      {"duration": round(duration_s, 3)}))

    def broadcast_media_change(self, path: str) -> None:
        self._broadcast_nowait(_event("media_change", {"path": path}))

    def broadcast_playbackspeed_change(self, speed: float) -> None:
        self._broadcast_nowait(_event("playbackspeed_change",
                                      {"speed": round(speed, 4)}))

    def broadcast_project_change(self) -> None:
        self._broadcast_nowait(_event("project_change", {}))

    def broadcast_funscript_change(self, name: str, actions) -> None:
        """
        Broadcast a full funscript with a 200 ms debounce per script name.
        Rapid successive calls for the same name are coalesced into one send.
        """
        if not self._running or self._loop is None:
            return
        payload = _event("funscript_change", {
            "name": name,
            "actions": [{"at": a.at, "pos": a.pos} for a in actions],
        })
        self._pending_data[name] = payload
        asyncio.run_coroutine_threadsafe(
            self._schedule_funscript(name), self._loop
        )

    def broadcast_funscript_remove(self, name: str) -> None:
        self._broadcast_nowait(_event("funscript_remove", {"name": name}))

    # --- Backward-compat aliases so existing call-sites keep working ---

    def broadcast_position(self, time_s: float,
                           pos: Optional[float] = None) -> None:
        self.broadcast_time_change(time_s)

    def broadcast_duration(self, duration_s: float) -> None:
        self.broadcast_duration_change(duration_s)

    def broadcast_playing(self, playing: bool) -> None:
        self.broadcast_play_change(playing)

    def broadcast_actions(self, script_name: str, actions: list) -> None:
        self.broadcast_funscript_change(script_name, actions)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def port(self) -> int:
        return self._port

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # ------------------------------------------------------------------
    # Internal — loop management
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
                        log.info(
                            "WebSocket API bound to ws://%s:%d (fallback port)",
                            self._host, port)
                    await self._stop_event.wait()
                return
            except OSError:
                if attempt == 9:
                    log.error("WebSocket API: could not bind on ports %d-%d",
                              self._port, port)
                    raise

    async def _shutdown(self) -> None:
        if self._stop_event:
            self._stop_event.set()

    # ------------------------------------------------------------------
    # Internal — connection handler
    # ------------------------------------------------------------------

    async def _handler(self, ws: "WebSocketServerProtocol",
                       path: str = "/") -> None:
        # Only accept connections on /ofs; reject anything else.
        norm = (path or "/").rstrip("/") or "/"
        if norm != WS_PATH:
            await ws.close(1008, f"Expected path {WS_PATH}")
            return

        self._clients.add(ws)
        log.debug("WS client connected: %s  path=%s", ws.remote_address, path)

        # Send welcome + full state dump to the new client
        try:
            await ws.send(json.dumps({"connected": f"OFS {OFS_VERSION}"}))
            await self._send_update_all(ws)
        except Exception:
            pass

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

    async def _send_update_all(self, ws: "WebSocketServerProtocol") -> None:
        """Send the full current state to a newly-connected client."""
        try:
            if self._get_duration:
                await ws.send(_event("duration_change",
                                     {"duration": round(self._get_duration(), 3)}))
            if self._get_playing:
                await ws.send(_event("play_change",
                                     {"playing": bool(self._get_playing())}))
            if self._get_speed:
                await ws.send(_event("playbackspeed_change",
                                     {"speed": round(self._get_speed(), 4)}))
            if self._get_time:
                await ws.send(_event("time_change",
                                     {"time": round(self._get_time(), 4)}))
            if self._get_media:
                media = self._get_media()
                if media:
                    await ws.send(_event("media_change", {"path": media}))
            await ws.send(_event("project_change", {}))
            if self._get_funscripts:
                for fs in self._get_funscripts():
                    payload = _event("funscript_change", {
                        "name": fs.title,
                        "actions": [{"at": a.at, "pos": a.pos}
                                    for a in fs.actions],
                    })
                    await ws.send(payload)
        except Exception as exc:
            log.debug("_send_update_all error: %s", exc)

    # ------------------------------------------------------------------
    # Internal — command dispatch
    # ------------------------------------------------------------------

    async def _dispatch(self, msg: Dict[str, Any]) -> None:
        """Route an inbound command message to the appropriate callback."""
        if msg.get("type") != "command":
            return
        name = msg.get("name", "")
        data = msg.get("data") or {}
        try:
            if name == "change_time" and self._on_change_time:
                self._on_change_time(float(data["time"]))
            elif name == "change_play" and self._on_change_play:
                self._on_change_play(bool(data["playing"]))
            elif name == "change_playbackspeed" and self._on_change_playbackspeed:
                self._on_change_playbackspeed(float(data["speed"]))
        except (KeyError, ValueError, TypeError) as e:
            log.warning("WS dispatch error for command %r: %s", name, e)

    # ------------------------------------------------------------------
    # Internal — per-script debounced funscript broadcast
    # ------------------------------------------------------------------

    async def _schedule_funscript(self, name: str) -> None:
        """Cancel any pending timer for *name* and arm a fresh 200 ms one."""
        old = self._pending_handles.pop(name, None)
        if old is not None:
            old.cancel()
        handle = self._loop.call_later(
            FUNSCRIPT_DEBOUNCE_S, self._fire_funscript, name
        )
        self._pending_handles[name] = handle

    def _fire_funscript(self, name: str) -> None:
        """Called by call_later inside the event loop — send the queued payload."""
        self._pending_handles.pop(name, None)
        payload = self._pending_data.pop(name, None)
        if payload and self._clients:
            asyncio.ensure_future(self._broadcast(payload))

    # ------------------------------------------------------------------
    # Internal — low-level send helpers
    # ------------------------------------------------------------------

    def _broadcast_nowait(self, data: str) -> None:
        """Thread-safe fire-and-forget broadcast to all connected clients."""
        if not self._running or not self._clients or self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(data), self._loop)

    async def _broadcast(self, data: str) -> None:
        dead = set()
        for ws in list(self._clients):
            try:
                await ws.send(data)
            except Exception:
                dead.add(ws)
        self._clients -= dead
