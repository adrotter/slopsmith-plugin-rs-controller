"""Read-only Rocksmith 2014 state reader for the Rocksmith Sync plugin."""

from __future__ import annotations

import ctypes
import math
import os
import re
import struct
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROCESS_NAME = "Rocksmith2014.exe"
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_PATH = 260
LIST_MODULES_32BIT = 0x01
MAX_MODULES = 1024
WAIT_OBJECT_0 = 0

MENU_OFFSETS = (0x28, 0x8C, 0x0)
PREVIEW_NAME_OFFSETS = (0xBC, 0x0)
TIMER_OFFSETS = (0xB0, 0x538, 0x8)
TIMER_RARE_OFFSETS = (0x20, 0x28, 0x0, 0x24, 0xC, 0x3B4)

SONG_MENUS = frozenset(
    {
        "LearnASong_Game",
        "NonStopPlay_Game",
        "ScoreAttack_Game",
        "LearnASong_Pause",
        "NonStopPlay_Pause",
        "ScoreAttack_Pause",
        "LearnASong_RiffRepeater",
        "RiffRepeater_AdvancedSettings",
        "SessionMode_Game",
        "SessionMode_PauseGame",
        "Guitarcade_Game",
        "Guitarcade_Pause",
        "HelpList",
        "MixerMenu",
    }
)
SONG_TIMER_MENUS = frozenset(
    {
        "LearnASong_Game",
        "NonStopPlay_Game",
        "ScoreAttack_Game",
        "LearnASong_Pause",
        "NonStopPlay_Pause",
        "ScoreAttack_Pause",
        "RiffRepeater",
        "LearnASong_RiffRepeater",
        "RiffRepeater_AdvancedSettings",
        "RiffRepeater_Pause",
        "Tuner",
        "MixerMenu",
        "HelpList",
        "SideList",
        "CalibrationMeter",
    }
)
PRE_SONG_TUNERS = frozenset(
    {
        "SelectionListDialog",
        "LearnASong_PreSongTuner",
        "LearnASong_PreSongTunerMP",
        "NonStopPlay_PreSongTuner",
        "NonStopPlay_PreSongTunerMP",
        "ScoreAttack_PreSongTuner",
        "SessionMode_PreSMTunerMP",
        "SessionMode_PreSMTuner",
        "Duet_PreSongTuner",
        "H2H_PreSongTuner",
        "PreGame_GETuner",
    }
)
PAUSED_MENUS = frozenset(
    {
        "LearnASong_Pause",
        "NonStopPlay_Pause",
        "ScoreAttack_Pause",
        "SessionMode_PauseGame",
        "Guitarcade_Pause",
        "RiffRepeater_AdvancedSettings",
        "HelpList",
        "MixerMenu",
    }
)


@dataclass(frozen=True)
class OffsetSet:
    name: str
    checksum: int
    current_menu: int
    preview_name: int
    timer: int
    timer_rare: int


OFFSETS_BY_CHECKSUM = {
    0x00B13D7C: OffsetSet(
        "Remastered September 2022",
        0x00B13D7C,
        0x00F5F62C,
        0x00F5F514,
        0x00F5F62C,
        0x00F5F54C,
    ),
    0x0176EC34: OffsetSet(
        "Learn & Play December 2024",
        0x0176EC34,
        0x00F6062C,
        0x00F60514,
        0x00F6062C,
        0x00F6054C,
    ),
}


def extract_song_key(event_name: str) -> str | None:
    if not event_name.startswith("Play_"):
        return None
    for suffix in ("_Preview", "_Invalid"):
        if event_name.endswith(suffix):
            key = event_name[len("Play_") : -len(suffix)]
            return key or None
    return None


def extract_song_key_buffer(data: bytes | None) -> str | None:
    if not data:
        return None
    text = data.decode("ascii", errors="ignore")
    match = re.search(r"(?:Play_|lay_)([^\x00]+?)_(?:Preview|Invalid)", text)
    return match.group(1) if match else None


def is_in_song(menu: str) -> bool:
    return menu in SONG_MENUS


def is_playing(menu: str) -> bool:
    return is_in_song(menu) and menu not in PAUSED_MENUS


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


def _kernel32() -> Any:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.ReadProcessMemory.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.LPVOID,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    return kernel32


def _psapi() -> Any:
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.EnumProcessModulesEx.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HMODULE),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.DWORD,
    ]
    psapi.EnumProcessModulesEx.restype = wintypes.BOOL
    psapi.GetModuleFileNameExW.argtypes = [
        wintypes.HANDLE,
        wintypes.HMODULE,
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    psapi.GetModuleFileNameExW.restype = wintypes.DWORD
    return psapi


def calculated_checksum(path: Path) -> int | None:
    if os.name != "nt":
        return None
    try:
        imagehlp = ctypes.WinDLL("imagehlp", use_last_error=True)
        imagehlp.MapFileAndCheckSumW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
        ]
        imagehlp.MapFileAndCheckSumW.restype = wintypes.DWORD
        header_checksum = wintypes.DWORD()
        calculated = wintypes.DWORD()
        if imagehlp.MapFileAndCheckSumW(str(path), ctypes.byref(header_checksum), ctypes.byref(calculated)) == 0:
            return calculated.value
    except OSError:
        pass
    return None


class ProcessMemory:
    def __init__(self, handle: int, base_address: int, offsets: OffsetSet) -> None:
        self.handle = handle
        self.base_address = base_address
        self.offsets = offsets
        self.kernel32 = _kernel32()

    def close(self) -> None:
        if self.handle:
            self.kernel32.CloseHandle(self.handle)
            self.handle = 0

    def exited(self) -> bool:
        return bool(self.handle and self.kernel32.WaitForSingleObject(self.handle, 0) == WAIT_OBJECT_0)

    def read(self, address: int | None, size: int) -> bytes | None:
        if not address or not self.handle:
            return None
        buffer = ctypes.create_string_buffer(size)
        read = ctypes.c_size_t()
        ok = self.kernel32.ReadProcessMemory(
            self.handle,
            ctypes.c_void_p(address),
            buffer,
            size,
            ctypes.byref(read),
        )
        if not ok or read.value != size:
            return None
        return buffer.raw

    def read_u32(self, address: int | None) -> int | None:
        value = self.read(address, 4)
        return struct.unpack("<I", value)[0] if value else None

    def read_float(self, address: int | None) -> float | None:
        value = self.read(address, 4)
        if not value:
            return None
        number = struct.unpack("<f", value)[0]
        return number if math.isfinite(number) else None

    def read_text(self, address: int | None, limit: int = 128) -> str | None:
        value = self.read(address, limit)
        if not value:
            return None
        return value.split(b"\0", 1)[0].decode("ascii", errors="ignore")

    def follow(self, start_address: int, offsets: tuple[int, ...]) -> int | None:
        address = start_address
        for offset in offsets:
            pointer = self.read_u32(address)
            if not pointer:
                return None
            address = pointer + offset
        return address


def _find_process_id(kernel32: Any) -> int | None:
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.szExeFile.lower() == PROCESS_NAME.lower():
                return entry.th32ProcessID
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return None


def _find_module(handle: int) -> tuple[int, Path] | None:
    psapi = _psapi()
    modules = (wintypes.HMODULE * MAX_MODULES)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcessModulesEx(
        handle,
        modules,
        ctypes.sizeof(modules),
        ctypes.byref(needed),
        LIST_MODULES_32BIT,
    ):
        return None
    count = min(needed.value // ctypes.sizeof(wintypes.HMODULE), MAX_MODULES)
    for module in modules[:count]:
        path_buffer = ctypes.create_unicode_buffer(MAX_PATH)
        if not psapi.GetModuleFileNameExW(handle, module, path_buffer, MAX_PATH):
            continue
        path = Path(path_buffer.value)
        if path.name.lower() == PROCESS_NAME.lower():
            base_address = ctypes.cast(module, ctypes.c_void_p).value
            if base_address:
                return base_address, path
    return None


def attach_to_rocksmith() -> tuple[ProcessMemory | None, str]:
    if os.name != "nt":
        return None, "Rocksmith reading is supported only on Windows"
    kernel32 = _kernel32()
    pid = _find_process_id(kernel32)
    if not pid:
        return None, "Start Rocksmith 2014"
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return None, "Rocksmith is running, but memory access was denied"
    module = _find_module(handle)
    if not module:
        kernel32.CloseHandle(handle)
        return None, "Rocksmith is running, but its module could not be read"
    base_address, path = module
    checksum = calculated_checksum(path)
    offsets = OFFSETS_BY_CHECKSUM.get(checksum)
    if not offsets:
        kernel32.CloseHandle(handle)
        detail = f"0x{checksum:08X}" if checksum is not None else "unknown checksum"
        return None, f"Unsupported Rocksmith build ({detail})"
    return ProcessMemory(handle, base_address, offsets), f"Connected ({offsets.name})"


class RocksmithReader:
    def __init__(self, poll_seconds: float = 0.04) -> None:
        self.poll_seconds = poll_seconds
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._session: ProcessMemory | None = None
        self._song_key = ""
        self._received_at: float | None = None
        self._snapshot: dict[str, Any] = {
            "connected": False,
            "status": "Start Rocksmith 2014",
            "ageMs": None,
            "state": None,
        }

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="rocksmith-memory-reader", daemon=True)
        self._thread.start()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            response = dict(self._snapshot)
            state = response.get("state")
            if isinstance(state, dict):
                response["state"] = dict(state)
            received_at = self._received_at
        if received_at is not None:
            response["ageMs"] = round((time.monotonic() - received_at) * 1000)
        return response

    def _publish(self, connected: bool, status: str, state: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._snapshot = {
                "connected": connected,
                "status": status,
                "ageMs": 0 if state is not None else None,
                "state": state,
            }
            self._received_at = time.monotonic() if state is not None else None

    def _run(self) -> None:
        while True:
            if not self._session:
                self._session, status = attach_to_rocksmith()
                if not self._session:
                    self._publish(False, status)
                    time.sleep(1.0)
                    continue
            try:
                if self._session.exited():
                    raise OSError("Rocksmith process exited")
                state = self._read_state(self._session)
                status = f"Connected ({self._session.offsets.name})"
                self._publish(True, status, state)
            except OSError:
                self._session.close()
                self._session = None
                self._publish(False, "Rocksmith disconnected")
                time.sleep(0.5)
            time.sleep(self.poll_seconds)

    def _read_state(self, session: ProcessMemory) -> dict[str, Any]:
        base = session.base_address
        menu_address = session.follow(base + session.offsets.current_menu, MENU_OFFSETS)
        menu = session.read_text(menu_address) or ""
        preview_address = session.follow(base + session.offsets.preview_name, PREVIEW_NAME_OFFSETS)
        song_key = extract_song_key_buffer(session.read(preview_address, 96))
        if song_key:
            self._song_key = song_key
        position = self._read_position(session, menu)
        return {
            "songKey": self._song_key,
            "positionSeconds": position,
            "inSong": is_in_song(menu),
            "playing": is_playing(menu),
            "menu": menu,
            "build": session.offsets.name,
        }

    def _read_position(self, session: ProcessMemory, menu: str) -> float:
        if menu in PRE_SONG_TUNERS:
            return 0.0
        base = session.base_address
        timer_address = session.follow(base + session.offsets.timer, TIMER_OFFSETS)
        position = session.read_float(timer_address) or 0.0
        rare_address = session.follow(base + session.offsets.timer_rare, TIMER_RARE_OFFSETS)
        rare_position = session.read_float(rare_address) or 0.0
        if menu in SONG_TIMER_MENUS and position == 0.0 and rare_position != 0.0:
            position = rare_position
        return max(0.0, position)
