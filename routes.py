"""Rocksmith state and song-resolution routes for the Rocksmith Sync plugin."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rocksmith_reader import RocksmithReader

PLUGIN_ID = "rocksmith_sync"
SONG_INDEX_VERSION = 4


def _key(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _clean_stem(stem: str) -> str:
    lower = stem.lower()
    for suffix in ("_p", "_m", "_bass", "_lead", "_rhythm"):
        if lower.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return re.sub(r"(?i)(?:[ _.-]+v(?:ersion)?\d+(?:\.\d+)*)$", "", stem).strip(" _.-")


def _stem_lookup_keys(path: Path) -> list[str]:
    stem = _clean_stem(path.stem)
    candidates = [stem]
    parts = [part.strip(" _.") for part in re.split(r"\s*(?:--|-)\s*", stem) if part.strip(" _.")]
    if len(parts) == 2:
        candidates.append(" ".join(reversed(parts)))

    keys: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _key(candidate)
        if normalized and normalized not in seen:
            seen.add(normalized)
            keys.append(normalized)
    return keys


def _stem_part_lookup_keys(path: Path) -> list[str]:
    stem = _clean_stem(path.stem)
    parts = [part.strip(" _.") for part in re.split(r"\s*(?:--|-)\s*", stem) if part.strip(" _.")]
    if len(parts) != 2:
        return []

    keys: list[str] = []
    seen: set[str] = set()
    for part in parts:
        normalized = _key(part)
        if normalized and _allow_part_lookup(normalized) and normalized not in seen:
            seen.add(normalized)
            keys.append(normalized)
    return keys


def _allow_fuzzy_lookup(lookup: str) -> bool:
    return len(lookup) >= 8 or (len(lookup) >= 4 and any(ch.isdigit() for ch in lookup))


def _allow_part_lookup(lookup: str) -> bool:
    return len(lookup) >= 3


def _psarc_rank(path: Path) -> tuple[int, str]:
    lower = path.name.lower()
    if lower.endswith("_p.psarc"):
        return (0, lower)
    if lower.endswith("_m.psarc"):
        return (2, lower)
    return (1, lower)


@dataclass(frozen=True)
class SongIdentity:
    title: str = ""
    artist: str = ""
    album: str = ""


def _identity_lookup_keys(identity: SongIdentity) -> list[str]:
    title = _key(identity.title)
    artist = _key(identity.artist)
    keys: list[str] = []
    if title and artist:
        keys.extend((title + artist, artist + title))
    if title:
        keys.append(title)

    seen: set[str] = set()
    unique: list[str] = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def _identity_match_keys(identity: SongIdentity) -> list[str]:
    title = _key(identity.title)
    artist = _key(identity.artist)
    keys: list[str] = []
    if title and artist:
        keys.append(f"titleartist:{title}:{artist}")
    if title:
        keys.append(f"title:{title}")
    return keys


def _identity_from_attrs(attrs: dict[str, Any]) -> SongIdentity:
    return SongIdentity(
        title=str(attrs.get("SongName") or attrs.get("Title") or ""),
        artist=str(attrs.get("ArtistName") or attrs.get("Artist") or ""),
        album=str(attrs.get("AlbumName") or attrs.get("Album") or ""),
    )


def _read_psarc_song_metadata(path: Path) -> dict[str, SongIdentity]:
    """Read Rocksmith song keys and display metadata from PSARC manifests."""
    try:
        from psarc import read_psarc_entries

        files = read_psarc_entries(str(path), ["*.json"])
    except Exception:
        return {}

    songs: dict[str, SongIdentity] = {}
    for raw in files.values():
        try:
            entries = (json.loads(raw).get("Entries") or {}).values()
        except (AttributeError, TypeError, ValueError):
            continue
        for entry in entries:
            attrs = entry.get("Attributes") if isinstance(entry, dict) else None
            if not isinstance(attrs, dict):
                continue
            identity = _identity_from_attrs(attrs)
            for value in (attrs.get("DLCKey"), attrs.get("SongKey")):
                normalized = _key(str(value or ""))
                if normalized and (normalized not in songs or not songs[normalized].title):
                    songs[normalized] = identity
    return songs


def _read_psarc_dlc_keys(path: Path) -> set[str]:
    """Read Rocksmith DLC keys using Slopsmith's already-loaded PSARC parser."""
    return set(_read_psarc_song_metadata(path))


def _read_sloppak_identity(path: Path) -> SongIdentity | None:
    try:
        from sloppak import load_manifest

        manifest = load_manifest(path)
    except Exception:
        return None
    if not isinstance(manifest, dict):
        return None
    identity = SongIdentity(
        title=str(manifest.get("title") or ""),
        artist=str(manifest.get("artist") or ""),
        album=str(manifest.get("album") or ""),
    )
    return identity if identity.title or identity.artist else None


@dataclass
class SongMatch:
    filename: str
    format: str
    automatic: bool


class SongResolver:
    def __init__(
        self,
        dlc_dir: Path,
        config_dir: Path,
        dlc_key_reader: Callable[[Path], set[str]] | None = None,
        psarc_metadata_reader: Callable[[Path], dict[str, SongIdentity]] | None = None,
        sloppak_identity_reader: Callable[[Path], SongIdentity | None] | None = None,
    ) -> None:
        self.dlc_dir = dlc_dir.resolve()
        self.config_path = config_dir / f"{PLUGIN_ID}.json"
        self.song_index_path = config_dir / f"{PLUGIN_ID}_song_index.json"
        self.converter_jobs_path = config_dir / "sloppak_converter_jobs.json"
        if psarc_metadata_reader:
            self._psarc_metadata_reader = psarc_metadata_reader
        elif dlc_key_reader:
            self._psarc_metadata_reader = lambda path: {
                _key(value): SongIdentity()
                for value in dlc_key_reader(path)
                if _key(value)
            }
        else:
            self._psarc_metadata_reader = _read_psarc_song_metadata
        self._sloppak_identity_reader = sloppak_identity_reader or _read_sloppak_identity
        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._song_index: dict[str, SongMatch] | None = None
        self._library_fingerprint: str | None = None
        self._file_count = 0
        self._mappings = self._read_mappings()

    def _relative_dlc_filename(self, path: Path) -> str | None:
        try:
            return path.relative_to(self.dlc_dir).as_posix()
        except ValueError:
            return None

    def _package_sort_key(self, path: Path) -> str:
        return self._relative_dlc_filename(path) or path.as_posix()

    def _metadata_psarcs(self) -> list[Path]:
        candidates: list[Path] = []
        if self.dlc_dir.name.lower() == "dlc":
            songs_psarc = self.dlc_dir.parent / "songs.psarc"
            if songs_psarc.is_file():
                candidates.append(songs_psarc)
        return candidates

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

    def _path_in_dlc(self, value: str) -> Path | None:
        try:
            candidate = Path(value)
            resolved = (candidate if candidate.is_absolute() else self.dlc_dir / candidate).resolve()
        except (OSError, RuntimeError, ValueError):
            return None
        if resolved == self.dlc_dir or self.dlc_dir in resolved.parents:
            return resolved
        return None

    def _read_converted_sloppaks(self, read_keys: Callable[[Path], set[str]]) -> dict[str, str]:
        try:
            raw = json.loads(self.converter_jobs_path.read_text(encoding="utf-8"))
            jobs = raw.get("jobs", []) if isinstance(raw, dict) else []
        except (OSError, ValueError, TypeError):
            return {}

        matches: dict[str, str] = {}
        for job in jobs:
            if not isinstance(job, dict) or job.get("state") != "done":
                continue
            source = self._path_in_dlc(str(job.get("filename") or ""))
            output = self._path_in_dlc(str(job.get("output_path") or ""))
            if (
                not source
                or not output
                or source.suffix.lower() != ".psarc"
                or output.suffix.lower() != ".sloppak"
                or not source.is_file()
                or not output.is_file()
            ):
                continue
            relative_output = output.relative_to(self.dlc_dir).as_posix()
            for dlc_key in read_keys(source):
                matches.setdefault(dlc_key, relative_output)
        return matches

    def _library_snapshot(self) -> tuple[list[Path], str]:
        files: list[Path] = []
        inventory: list[dict[str, Any]] = []
        if self.dlc_dir.exists():
            for root, dirs, names in os.walk(self.dlc_dir):
                dirs.sort()
                root_path = Path(root)
                for name in sorted(names):
                    path = root_path / name
                    if path.suffix.lower() not in {".sloppak", ".psarc"}:
                        continue
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    files.append(path)
                    inventory.append(
                        {
                            "path": path.relative_to(self.dlc_dir).as_posix(),
                            "size": stat.st_size,
                            "mtimeNs": stat.st_mtime_ns,
                        }
                    )
        for path in self._metadata_psarcs():
            try:
                stat = path.stat()
            except OSError:
                continue
            files.append(path)
            inventory.append(
                {
                    "path": f"metadata:{path.name}",
                    "size": stat.st_size,
                    "mtimeNs": stat.st_mtime_ns,
                }
            )
        try:
            converter_jobs_hash = hashlib.sha256(self.converter_jobs_path.read_bytes()).hexdigest()
        except OSError:
            converter_jobs_hash = None
        payload = {
            "version": SONG_INDEX_VERSION,
            "files": inventory,
            "converterJobs": converter_jobs_hash,
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return files, hashlib.sha256(encoded).hexdigest()

    def _read_song_index(self, fingerprint: str) -> dict[str, SongMatch] | None:
        try:
            raw = json.loads(self.song_index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        if (
            not isinstance(raw, dict)
            or raw.get("version") != SONG_INDEX_VERSION
            or raw.get("libraryFingerprint") != fingerprint
            or not isinstance(raw.get("songs"), dict)
        ):
            return None

        index: dict[str, SongMatch] = {}
        for lookup, value in raw["songs"].items():
            if not isinstance(lookup, str) or _key(lookup) != lookup or not isinstance(value, dict):
                return None
            filename = value.get("filename")
            package_format = value.get("format")
            path = self._path_in_dlc(filename) if isinstance(filename, str) else None
            if (
                not path
                or package_format not in {"sloppak", "psarc"}
                or path.suffix.lower() != f".{package_format}"
                or not path.is_file()
            ):
                return None
            index[lookup] = SongMatch(filename, package_format, True)
        return index

    def _write_song_index(self, fingerprint: str, index: dict[str, SongMatch]) -> None:
        self.song_index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": SONG_INDEX_VERSION,
            "libraryFingerprint": fingerprint,
            "songs": {
                lookup: {"filename": match.filename, "format": match.format}
                for lookup, match in sorted(index.items())
            },
        }
        temporary_path = self.song_index_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary_path, self.song_index_path)

    def _build_song_index(self, files: list[Path]) -> dict[str, SongMatch]:
        index: dict[str, SongMatch] = {}
        weak_aliases: dict[str, SongMatch | None] = {}
        sloppak_identities: dict[str, SongMatch | None] = {}
        psarc_metadata: dict[Path, dict[str, SongIdentity]] = {}

        def read_psarc_metadata(path: Path) -> dict[str, SongIdentity]:
            resolved = path.resolve()
            if resolved not in psarc_metadata:
                psarc_metadata[resolved] = {
                    lookup: identity
                    for lookup, identity in self._psarc_metadata_reader(resolved).items()
                    if _key(lookup)
                }
            return psarc_metadata[resolved]

        def read_keys(path: Path) -> set[str]:
            return set(read_psarc_metadata(path))

        def add(lookup: str, filename: str, package_format: str) -> None:
            normalized = _key(lookup)
            if normalized:
                index.setdefault(normalized, SongMatch(filename, package_format, True))

        def add_weak(lookup: str, filename: str, package_format: str) -> None:
            normalized = _key(lookup)
            if not normalized or normalized in index:
                return
            match = SongMatch(filename, package_format, True)
            if normalized not in weak_aliases:
                weak_aliases[normalized] = match
                return
            existing = weak_aliases[normalized]
            if existing and existing.filename == match.filename and existing.format == match.format:
                return
            weak_aliases[normalized] = None

        def add_identity_alias(identity: SongIdentity | None, filename: str, package_format: str) -> None:
            if not identity:
                return
            match = SongMatch(filename, package_format, True)
            for alias in _identity_match_keys(identity):
                if alias not in sloppak_identities:
                    sloppak_identities[alias] = match
                    continue
                existing = sloppak_identities[alias]
                if existing and existing.filename == match.filename and existing.format == match.format:
                    continue
                sloppak_identities[alias] = None

        def find_identity_sloppak(identity: SongIdentity) -> SongMatch | None:
            for alias in _identity_match_keys(identity):
                match = sloppak_identities.get(alias)
                if match:
                    return match
            return None

        converted_sloppaks = self._read_converted_sloppaks(read_keys)
        for lookup, filename in sorted(converted_sloppaks.items()):
            add(lookup, filename, "sloppak")

        sloppaks = sorted(
            (path for path in files if path.suffix.lower() == ".sloppak"),
            key=lambda path: self._package_sort_key(path).lower(),
        )
        for path in sloppaks:
            filename = self._relative_dlc_filename(path)
            if not filename:
                continue
            for lookup in _stem_lookup_keys(path):
                add(lookup, filename, "sloppak")
            for lookup in _stem_part_lookup_keys(path):
                add_weak(lookup, filename, "sloppak")
            identity = self._sloppak_identity_reader(path)
            for lookup in _identity_lookup_keys(identity or SongIdentity()):
                add_weak(lookup, filename, "sloppak")
            add_identity_alias(identity, filename, "sloppak")

        psarcs = sorted(
            (path for path in files if path.suffix.lower() == ".psarc"),
            key=lambda path: (_psarc_rank(path), self._package_sort_key(path).lower()),
        )
        for path in psarcs:
            filename = self._relative_dlc_filename(path)
            for lookup, identity in sorted(read_psarc_metadata(path).items()):
                sloppak_match = find_identity_sloppak(identity)
                if sloppak_match:
                    add(lookup, sloppak_match.filename, "sloppak")
                if filename:
                    add(lookup, filename, "psarc")
                    for alias in _identity_lookup_keys(identity):
                        add_weak(alias, filename, "psarc")
            if not filename:
                continue
            for lookup in _stem_lookup_keys(path):
                add(lookup, filename, "psarc")
            for lookup in _stem_part_lookup_keys(path):
                add_weak(lookup, filename, "psarc")

        for lookup, match in sorted(weak_aliases.items()):
            if match and lookup not in index:
                index[lookup] = match
        return index

    def _refresh_song_index(self, force: bool = False) -> int:
        with self._refresh_lock:
            files, fingerprint = self._library_snapshot()
            with self._lock:
                if not force and self._song_index is not None and self._library_fingerprint == fingerprint:
                    return self._file_count
            index = None if force else self._read_song_index(fingerprint)
            if index is None:
                index = self._build_song_index(files)
                try:
                    self._write_song_index(fingerprint, index)
                except OSError:
                    pass
            with self._lock:
                self._song_index = index
                self._library_fingerprint = fingerprint
                self._file_count = len(files)
            return len(files)

    def rescan(self) -> int:
        return self._refresh_song_index(force=True)

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

    def _manual_match(self, manual: str | None, package_format: str) -> SongMatch | None:
        manual_path = self._path_in_dlc(manual) if manual else None
        if manual_path and manual_path.is_file() and manual_path.suffix.lower() == f".{package_format}":
            return SongMatch(manual, package_format, False)
        return None

    def _fuzzy_match_locked(self, lookup: str, package_format: str | None = None) -> SongMatch | None:
        if not _allow_fuzzy_lookup(lookup) or not self._song_index:
            return None

        candidates: list[tuple[tuple[int, int, str], SongMatch]] = []
        for indexed, match in self._song_index.items():
            if indexed == lookup or not _allow_fuzzy_lookup(indexed):
                continue
            if package_format and match.format != package_format:
                continue
            if lookup in indexed or indexed in lookup:
                candidates.append(((abs(len(indexed) - len(lookup)), len(indexed), indexed), match))
        if not candidates:
            return None

        if len({match.filename for _, match in candidates}) > 1:
            return None
        candidates.sort(key=lambda candidate: candidate[0])
        return candidates[0][1]

    def _automatic_matches_locked(self, lookup: str) -> tuple[SongMatch | None, SongMatch | None, SongMatch | None]:
        automatic = self._song_index.get(lookup) if self._song_index else None
        fuzzy_sloppak = None
        if not (automatic and automatic.format == "sloppak"):
            fuzzy_sloppak = self._fuzzy_match_locked(lookup, "sloppak")
        fuzzy_automatic = None if automatic else self._fuzzy_match_locked(lookup)
        return automatic, fuzzy_sloppak, fuzzy_automatic

    def _choose_match(
        self,
        manual: str | None,
        automatic: SongMatch | None,
        fuzzy_sloppak: SongMatch | None,
        fuzzy_automatic: SongMatch | None,
    ) -> SongMatch | None:
        manual_sloppak = self._manual_match(manual, "sloppak")
        if manual_sloppak:
            return manual_sloppak
        if automatic and automatic.format == "sloppak":
            return automatic
        if fuzzy_sloppak:
            return fuzzy_sloppak
        manual_psarc = self._manual_match(manual, "psarc")
        if manual_psarc:
            return manual_psarc
        return automatic or fuzzy_automatic

    def resolve(self, song_key: str) -> SongMatch | None:
        lookup = _key(song_key)
        if not lookup:
            return None
        self._refresh_song_index()
        with self._lock:
            manual = self._mappings.get(lookup)
            automatic, fuzzy_sloppak, fuzzy_automatic = self._automatic_matches_locked(lookup)

        match = self._choose_match(manual, automatic, fuzzy_sloppak, fuzzy_automatic)
        if match:
            return match

        # Force one rebuild on a miss in case a package changed while its
        # inventory snapshot was being collected.
        self._refresh_song_index(force=True)
        with self._lock:
            manual = self._mappings.get(lookup)
            automatic, fuzzy_sloppak, fuzzy_automatic = self._automatic_matches_locked(lookup)
        return self._choose_match(manual, automatic, fuzzy_sloppak, fuzzy_automatic)


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
