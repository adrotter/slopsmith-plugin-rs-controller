"""Rocksmith state and song-resolution routes for the Rocksmith Sync plugin."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rocksmith_reader import RocksmithReader

PLUGIN_ID = "rocksmith_sync"


def _key(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _stem_key(path: Path) -> str:
    stem = path.stem
    lower = stem.lower()
    for suffix in ("_p", "_m", "_bass", "_lead", "_rhythm"):
        if lower.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return _key(stem)


def _psarc_rank(path: Path) -> tuple[int, str]:
    lower = path.name.lower()
    if lower.endswith("_p.psarc"):
        return (0, lower)
    if lower.endswith("_m.psarc"):
        return (2, lower)
    return (1, lower)


@dataclass
class SongMatch:
    filename: str
    format: str
    automatic: bool


class SongResolver:
    def __init__(self, dlc_dir: Path, config_dir: Path) -> None:
        self.dlc_dir = dlc_dir.resolve()
        self.config_path = config_dir / f"{PLUGIN_ID}.json"
        self._lock = threading.Lock()
        self._files: list[Path] | None = None
        self._mappings = self._read_mappings()

    def _read_mappings(self) -> dict[str, str]:
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            mappings = raw.get("mappings", {}) if isinstance(raw, dict) else {}
            if isinstance(mappings, dict):
                return {str(k): str(v) for k, v in mappings.items()}
        except (OSError, ValueError, TypeError):
            pass
        return {}

    def _write_mappings(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"mappings": self._mappings}
        self.config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def rescan(self) -> int:
        files: list[Path] = []
        if self.dlc_dir.exists():
            for root, _, names in os.walk(self.dlc_dir):
                root_path = Path(root)
                for name in names:
                    path = root_path / name
                    if path.suffix.lower() in {".sloppak", ".psarc"}:
                        files.append(path)
        with self._lock:
            self._files = files
        return len(files)

    def list_mappings(self) -> dict[str, str]:
        with self._lock:
            return dict(self._mappings)

    def set_mapping(self, song_key: str, filename: str | None) -> None:
        map_key = _key(song_key)
        if not map_key:
            raise ValueError("song_key is required")
        with self._lock:
            if filename:
                resolved = (self.dlc_dir / filename).resolve()
                if self.dlc_dir not in resolved.parents and resolved != self.dlc_dir:
                    raise ValueError("mapping must stay inside the Slopsmith DLC directory")
                if not resolved.is_file() or resolved.suffix.lower() not in {".sloppak", ".psarc"}:
                    raise ValueError("mapping target must be an existing .sloppak or .psarc file")
                self._mappings[map_key] = resolved.relative_to(self.dlc_dir).as_posix()
            else:
                self._mappings.pop(map_key, None)
            self._write_mappings()

    def resolve(self, song_key: str) -> SongMatch | None:
        lookup = _key(song_key)
        if not lookup:
            return None
        with self._lock:
            manual = self._mappings.get(lookup)
            files = list(self._files) if self._files is not None else None
        manual_path = (self.dlc_dir / manual).resolve() if manual else None
        if manual_path and manual_path.is_file() and manual_path.suffix.lower() == ".sloppak":
            return SongMatch(manual, "sloppak", False)
        if files is None:
            self.rescan()
            with self._lock:
                files = list(self._files or [])
        matching = [path for path in files if _stem_key(path) == lookup]
        sloppaks = sorted((path for path in matching if path.suffix.lower() == ".sloppak"), key=lambda p: p.name.lower())
        if sloppaks:
            return SongMatch(sloppaks[0].relative_to(self.dlc_dir).as_posix(), "sloppak", True)
        if manual_path and manual_path.is_file() and manual_path.suffix.lower() == ".psarc":
            return SongMatch(manual, "psarc", False)
        psarcs = sorted((path for path in matching if path.suffix.lower() == ".psarc"), key=_psarc_rank)
        if psarcs:
            return SongMatch(psarcs[0].relative_to(self.dlc_dir).as_posix(), "psarc", True)
        return None


def setup(app: Any, context: dict[str, Any]) -> None:
    from fastapi import Body

    config_dir_value = os.environ.get("CONFIG_DIR") or context.get("config_dir")
    get_dlc_dir = context.get("get_dlc_dir")
    context_dlc_dir = get_dlc_dir() if callable(get_dlc_dir) else context.get("dlc_dir")
    dlc_dir_value = os.environ.get("DLC_DIR") or context_dlc_dir
    if not config_dir_value:
        raise RuntimeError("Rocksmith Sync requires Slopsmith CONFIG_DIR")
    config_dir = Path(config_dir_value)
    dlc_dir = Path(dlc_dir_value) if dlc_dir_value else config_dir / "unconfigured-dlc"
    reader = RocksmithReader()
    resolver = SongResolver(dlc_dir, config_dir)
    reader.start()

    @app.get("/api/plugins/rocksmith_sync/state")
    def rocksmith_sync_state() -> dict[str, Any]:
        return reader.snapshot()

    @app.get("/api/plugins/rocksmith_sync/resolve/{song_key}")
    def rocksmith_sync_resolve(song_key: str) -> dict[str, Any]:
        match = resolver.resolve(song_key)
        return {"match": match.__dict__ if match else None}

    @app.post("/api/plugins/rocksmith_sync/rescan")
    def rocksmith_sync_rescan() -> dict[str, int]:
        return {"files": resolver.rescan()}

    @app.get("/api/plugins/rocksmith_sync/mappings")
    def rocksmith_sync_mappings() -> dict[str, dict[str, str]]:
        return {"mappings": resolver.list_mappings()}

    @app.post("/api/plugins/rocksmith_sync/mappings")
    def rocksmith_sync_set_mapping(payload: dict[str, Any] = Body(default={})) -> dict[str, bool]:
        resolver.set_mapping(str(payload.get("songKey", "")), payload.get("filename"))
        return {"ok": True}
