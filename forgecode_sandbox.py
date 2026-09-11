#!/usr/bin/env python3
"""ForgeCode sandbox — isolation leaves. Depends on base/config/stores."""

from __future__ import annotations

import argparse
import atexit
import base64
import builtins
import codecs
import collections
import concurrent.futures
import contextlib
import copy
import ctypes
import datetime as dt
import difflib
import email.utils
import fnmatch
import getpass
import hashlib
import html.parser
import importlib.metadata
import importlib.util
import json
import locale
import os
import pathlib
import platform
import random
import re
import shlex
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from forgecode_base import atomic_json, decode_subprocess_output, load_json, redact_sensitive, windows_shell_command, powershell_literal_path
from forgecode_config import Config

def _fc(name):
    import forgecode as _m
    return getattr(_m, name)

def interactive(*a, **k):
    import forgecode as _m
    return _m.interactive(*a, **k)


IGNORE_DIRS = {
    ".git", ".forgecode", ".force", ".code-review-graph", "node_modules",
    ".venv", "venv", "__pycache__", "dist", "build", ".ssh", ".aws",
    ".azure", ".gnupg", ".kube", ".forceclient-check",
}


BINARY_ARTIFACT_SUFFIXES = {
    ".class", ".jar", ".war", ".exe", ".dll", ".so", ".dylib", ".o", ".obj",
    ".a", ".lib", ".pdb", ".pyc", ".wasm", ".zip", ".gz", ".7z", ".tar",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".db", ".sqlite",
    ".woff", ".woff2", ".ttf", ".otf", ".mp3", ".mp4", ".wav",
}


SANDBOX_SECRET_NAMES = {
    ".env", ".npmrc", ".pypirc", "credentials.json", "service-account.json",
    ".envrc", ".git-credentials", ".netrc", "auth.json", "secrets.json",
    "id_rsa", "id_ed25519", "known_hosts", "authorized_keys",
}


SANDBOX_SECRET_SUFFIXES = {".pem", ".p12", ".pfx", ".key", ".kdbx", ".keystore"}


@dataclass
class SandboxTransferResult:
    status: str
    changed: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    snapshot: str = ""
    message: str = ""


class NativeSandboxProcess:
    """Small Popen-compatible wrapper around a Windows AppContainer process."""

    def __init__(
        self, runner: "WindowsAppContainerRunner", process_handle: int, job_handle: int,
        process_id: int, stdin_handle: int, stdout_handle: int, args: list[str],
    ):
        import msvcrt

        self._runner = runner
        self._process_handle = process_handle
        self._job_handle = job_handle
        self.pid = process_id
        self.args = args
        self.returncode: int | None = None
        self._completed = False
        stdin_fd = msvcrt.open_osfhandle(stdin_handle, os.O_WRONLY | getattr(os, "O_BINARY", 0))
        stdout_fd = msvcrt.open_osfhandle(stdout_handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        self.stdin = os.fdopen(stdin_fd, "wb", buffering=0)
        self.stdout = os.fdopen(stdout_fd, "rb", buffering=0)

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        code = ctypes.wintypes.DWORD()
        if not self._runner.kernel32.GetExitCodeProcess(self._process_handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        if code.value == 259:  # STILL_ACTIVE
            return None
        self.returncode = int(code.value)
        if not self._completed:
            # PowerShell may start detached descendants. End the entire job
            # before copying results back so no process can mutate files after
            # verification begins.
            if self._job_handle:
                self._runner.kernel32.TerminateJobObject(self._job_handle, 1)
            self._completed = True
            self._runner.complete_command()
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        milliseconds = 0xFFFFFFFF if timeout is None else max(0, min(0xFFFFFFFE, int(timeout * 1000)))
        result = self._runner.kernel32.WaitForSingleObject(self._process_handle, milliseconds)
        if result == 258:  # WAIT_TIMEOUT
            raise subprocess.TimeoutExpired(self.args, timeout)
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        return int(self.poll() or 0)

    def terminate(self) -> None:
        if self.poll() is not None:
            return
        if self._job_handle:
            if not self._runner.kernel32.TerminateJobObject(self._job_handle, 1):
                raise ctypes.WinError(ctypes.get_last_error())
        elif not self._runner.kernel32.TerminateProcess(self._process_handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    kill = terminate

    def communicate(self, input: bytes | None = None, timeout: float | None = None) -> tuple[bytes, bytes]:
        chunks: list[bytes] = []
        read_error: list[BaseException] = []

        def reader() -> None:
            try:
                while True:
                    chunk = self.stdout.read(64 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
            except (OSError, ValueError) as exc:
                read_error.append(exc)

        thread = threading.Thread(target=reader, name="forgecode-native-sandbox-output", daemon=True)
        thread.start()
        try:
            if input:
                self.stdin.write(input)
                self.stdin.flush()
            self.stdin.close()
            self.wait(timeout)
        except subprocess.TimeoutExpired as exc:
            self.terminate()
            try:
                self.wait(2)
            except (OSError, subprocess.TimeoutExpired):
                pass
            thread.join(timeout=2)
            exc.stdout = b"".join(chunks)
            exc.stderr = b""
            raise
        thread.join(timeout=2)
        if read_error and not chunks:
            raise OSError(f"ForceSandbox çıktı kanalı okunamadı: {read_error[-1]}")
        return b"".join(chunks), b""

    def close(self) -> None:
        for stream in (getattr(self, "stdin", None), getattr(self, "stdout", None)):
            try:
                if stream is not None and not stream.closed:
                    stream.close()
            except OSError:
                pass
        for handle_name in ("_process_handle", "_job_handle"):
            handle = int(getattr(self, handle_name, 0) or 0)
            if handle:
                self._runner.kernel32.CloseHandle(handle)
                setattr(self, handle_name, 0)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class WindowsAppContainerRunner:
    """Dependency-free Windows kernel sandbox with a project-only writable root."""

    SE_GROUP_ENABLED = 0x00000004
    PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
    PROC_THREAD_ATTRIBUTE_DESKTOP_APP_POLICY = 0x00020012
    PROCESS_CREATION_DESKTOP_APP_BREAKAWAY_DISABLE_PROCESS_TREE = 0x02
    EXTENDED_STARTUPINFO_PRESENT = 0x00080000
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    CREATE_NO_WINDOW = 0x08000000
    CREATE_SUSPENDED = 0x00000004
    STARTF_USESTDHANDLES = 0x00000100
    HANDLE_FLAG_INHERIT = 0x00000001
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    WIN_CAPABILITY_INTERNET_CLIENT_SID = 85
    WIN_BUILTIN_ANY_PACKAGE_SID = 84

    def __init__(self, workspace: pathlib.Path, identity: str, network_enabled: bool = True):
        if sys.platform != "win32":
            raise OSError("Yerel ForceSandbox AppContainer motoru yalnızca Windows 10/11'de kullanılabilir")
        self.workspace = workspace.resolve()
        self.execution_workspace = self.workspace
        self.identity = re.sub(r"[^A-Za-z0-9._-]", "_", identity)[:64]
        self.network_enabled = bool(network_enabled)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self.userenv = ctypes.WinDLL("userenv", use_last_error=True)
        self._sid_buffer: ctypes.Array[Any] | None = None
        self._sid_pointer = ctypes.wintypes.LPVOID()
        self._sid_text = ""
        self._all_packages_sid_buffer: ctypes.Array[Any] | None = None
        self._all_packages_sid_pointer = ctypes.wintypes.LPVOID()
        self._acl_roots: set[str] = set()
        self._verified = False
        self._command_lock = threading.Lock()
        self._command_active = False
        self._define_types()
        self._configure_api()

    def _define_types(self) -> None:
        wt = ctypes.wintypes

        class SID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Sid", wt.LPVOID), ("Attributes", wt.DWORD)]

        class SECURITY_CAPABILITIES(ctypes.Structure):
            _fields_ = [
                ("AppContainerSid", wt.LPVOID),
                ("Capabilities", ctypes.POINTER(SID_AND_ATTRIBUTES)),
                ("CapabilityCount", wt.DWORD),
                ("Reserved", wt.DWORD),
            ]

        class SECURITY_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("nLength", wt.DWORD), ("lpSecurityDescriptor", wt.LPVOID), ("bInheritHandle", wt.BOOL)]

        class TRUSTEE_W(ctypes.Structure):
            _fields_ = [
                ("pMultipleTrustee", wt.LPVOID), ("MultipleTrusteeOperation", ctypes.c_int),
                ("TrusteeForm", ctypes.c_int), ("TrusteeType", ctypes.c_int), ("ptstrName", wt.LPWSTR),
            ]

        class EXPLICIT_ACCESS_W(ctypes.Structure):
            _fields_ = [
                ("grfAccessPermissions", wt.DWORD), ("grfAccessMode", ctypes.c_int),
                ("grfInheritance", wt.DWORD), ("Trustee", TRUSTEE_W),
            ]

        class STARTUPINFOW(ctypes.Structure):
            _fields_ = [
                ("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
                ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.POINTER(wt.BYTE)), ("hStdInput", wt.HANDLE),
                ("hStdOutput", wt.HANDLE), ("hStdError", wt.HANDLE),
            ]

        class STARTUPINFOEXW(ctypes.Structure):
            _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", wt.LPVOID)]

        class PROCESS_INFORMATION(ctypes.Structure):
            _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE), ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong), ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong), ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong), ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self.SID_AND_ATTRIBUTES = SID_AND_ATTRIBUTES
        self.SECURITY_CAPABILITIES = SECURITY_CAPABILITIES
        self.SECURITY_ATTRIBUTES = SECURITY_ATTRIBUTES
        self.TRUSTEE_W = TRUSTEE_W
        self.EXPLICIT_ACCESS_W = EXPLICIT_ACCESS_W
        self.STARTUPINFOW = STARTUPINFOW
        self.STARTUPINFOEXW = STARTUPINFOEXW
        self.PROCESS_INFORMATION = PROCESS_INFORMATION
        self.JOBOBJECT_EXTENDED_LIMIT_INFORMATION = JOBOBJECT_EXTENDED_LIMIT_INFORMATION

    def _configure_api(self) -> None:
        wt = ctypes.wintypes
        self.kernel32.InitializeProcThreadAttributeList.argtypes = [wt.LPVOID, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.c_size_t)]
        self.kernel32.InitializeProcThreadAttributeList.restype = wt.BOOL
        self.kernel32.UpdateProcThreadAttribute.argtypes = [wt.LPVOID, wt.DWORD, ctypes.c_size_t, wt.LPVOID, ctypes.c_size_t, wt.LPVOID, wt.LPVOID]
        self.kernel32.UpdateProcThreadAttribute.restype = wt.BOOL
        self.kernel32.DeleteProcThreadAttributeList.argtypes = [wt.LPVOID]
        self.kernel32.CreatePipe.argtypes = [ctypes.POINTER(wt.HANDLE), ctypes.POINTER(wt.HANDLE), ctypes.POINTER(self.SECURITY_ATTRIBUTES), wt.DWORD]
        self.kernel32.CreatePipe.restype = wt.BOOL
        self.kernel32.CreateFileW.argtypes = [
            wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE,
        ]
        self.kernel32.CreateFileW.restype = wt.HANDLE
        self.kernel32.SetHandleInformation.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD]
        self.kernel32.SetHandleInformation.restype = wt.BOOL
        self.kernel32.CreateProcessW.argtypes = [
            wt.LPCWSTR, wt.LPWSTR, wt.LPVOID, wt.LPVOID, wt.BOOL, wt.DWORD, wt.LPVOID,
            wt.LPCWSTR, ctypes.POINTER(self.STARTUPINFOW), ctypes.POINTER(self.PROCESS_INFORMATION),
        ]
        self.kernel32.CreateProcessW.restype = wt.BOOL
        self.kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
        self.kernel32.GetExitCodeProcess.restype = wt.BOOL
        self.kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
        self.kernel32.WaitForSingleObject.restype = wt.DWORD
        self.kernel32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
        self.kernel32.TerminateProcess.restype = wt.BOOL
        self.kernel32.CloseHandle.argtypes = [wt.HANDLE]
        self.kernel32.CloseHandle.restype = wt.BOOL
        self.kernel32.ResumeThread.argtypes = [wt.HANDLE]
        self.kernel32.ResumeThread.restype = wt.DWORD
        self.kernel32.CreateJobObjectW.argtypes = [wt.LPVOID, wt.LPCWSTR]
        self.kernel32.CreateJobObjectW.restype = wt.HANDLE
        self.kernel32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, wt.LPVOID, wt.DWORD]
        self.kernel32.SetInformationJobObject.restype = wt.BOOL
        self.kernel32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
        self.kernel32.AssignProcessToJobObject.restype = wt.BOOL
        self.kernel32.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]
        self.kernel32.TerminateJobObject.restype = wt.BOOL
        self.advapi32.CreateWellKnownSid.argtypes = [ctypes.c_int, wt.LPVOID, wt.LPVOID, ctypes.POINTER(wt.DWORD)]
        self.advapi32.CreateWellKnownSid.restype = wt.BOOL
        self.advapi32.GetLengthSid.argtypes = [wt.LPVOID]
        self.advapi32.GetLengthSid.restype = wt.DWORD
        self.advapi32.ConvertSidToStringSidW.argtypes = [wt.LPVOID, ctypes.POINTER(wt.LPWSTR)]
        self.advapi32.ConvertSidToStringSidW.restype = wt.BOOL
        self.advapi32.FreeSid.argtypes = [wt.LPVOID]
        self.advapi32.GetNamedSecurityInfoW.argtypes = [
            wt.LPWSTR, ctypes.c_int, wt.DWORD, ctypes.POINTER(wt.LPVOID), ctypes.POINTER(wt.LPVOID),
            ctypes.POINTER(wt.LPVOID), ctypes.POINTER(wt.LPVOID), ctypes.POINTER(wt.LPVOID),
        ]
        self.advapi32.GetNamedSecurityInfoW.restype = wt.DWORD
        self.advapi32.SetEntriesInAclW.argtypes = [
            wt.ULONG, ctypes.POINTER(self.EXPLICIT_ACCESS_W), wt.LPVOID, ctypes.POINTER(wt.LPVOID),
        ]
        self.advapi32.SetEntriesInAclW.restype = wt.DWORD
        self.advapi32.SetNamedSecurityInfoW.argtypes = [
            wt.LPWSTR, ctypes.c_int, wt.DWORD, wt.LPVOID, wt.LPVOID, wt.LPVOID, wt.LPVOID,
        ]
        self.advapi32.SetNamedSecurityInfoW.restype = wt.DWORD
        self.advapi32.GetSecurityInfo.argtypes = [
            wt.HANDLE, ctypes.c_int, wt.DWORD, ctypes.POINTER(wt.LPVOID), ctypes.POINTER(wt.LPVOID),
            ctypes.POINTER(wt.LPVOID), ctypes.POINTER(wt.LPVOID), ctypes.POINTER(wt.LPVOID),
        ]
        self.advapi32.GetSecurityInfo.restype = wt.DWORD
        self.advapi32.SetSecurityInfo.argtypes = [
            wt.HANDLE, ctypes.c_int, wt.DWORD, wt.LPVOID, wt.LPVOID, wt.LPVOID, wt.LPVOID,
        ]
        self.advapi32.SetSecurityInfo.restype = wt.DWORD
        self.userenv.CreateAppContainerProfile.argtypes = [
            wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, ctypes.POINTER(self.SID_AND_ATTRIBUTES), wt.DWORD,
            ctypes.POINTER(wt.LPVOID),
        ]
        self.userenv.CreateAppContainerProfile.restype = ctypes.c_long
        self.userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [wt.LPCWSTR, ctypes.POINTER(wt.LPVOID)]
        self.userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
        self.userenv.GetAppContainerFolderPath.argtypes = [wt.LPCWSTR, ctypes.POINTER(wt.LPWSTR)]
        self.userenv.GetAppContainerFolderPath.restype = ctypes.c_long

    def _internet_capabilities(self) -> tuple[Any, list[Any]]:
        if not self.network_enabled:
            return None, []
        size = ctypes.wintypes.DWORD(68)
        sid_buffer = ctypes.create_string_buffer(size.value)
        if not self.advapi32.CreateWellKnownSid(
            self.WIN_CAPABILITY_INTERNET_CLIENT_SID, None, sid_buffer, ctypes.byref(size)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        capabilities = (self.SID_AND_ATTRIBUTES * 1)()
        capabilities[0].Sid = ctypes.cast(sid_buffer, ctypes.wintypes.LPVOID)
        capabilities[0].Attributes = self.SE_GROUP_ENABLED
        return capabilities, [sid_buffer, capabilities]

    def _all_packages_sid(self) -> ctypes.wintypes.LPVOID:
        if self._all_packages_sid_pointer:
            return self._all_packages_sid_pointer
        size = ctypes.wintypes.DWORD(68)
        sid_buffer = ctypes.create_string_buffer(size.value)
        if not self.advapi32.CreateWellKnownSid(
            self.WIN_BUILTIN_ANY_PACKAGE_SID, None, sid_buffer, ctypes.byref(size)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        self._all_packages_sid_buffer = sid_buffer
        self._all_packages_sid_pointer = ctypes.cast(sid_buffer, ctypes.wintypes.LPVOID)
        return self._all_packages_sid_pointer

    def _ensure_profile(self) -> None:
        if self._sid_pointer:
            return
        capabilities, keepalive = self._internet_capabilities()
        sid = ctypes.wintypes.LPVOID()
        count = 1 if capabilities is not None else 0
        hr = self.userenv.CreateAppContainerProfile(
            self.identity, "ForceCode Native Sandbox", "ForceCode project command isolation",
            capabilities, count, ctypes.byref(sid),
        )
        unsigned_hr = int(hr) & 0xFFFFFFFF
        if unsigned_hr == 0x800700B7:  # HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS)
            hr = self.userenv.DeriveAppContainerSidFromAppContainerName(self.identity, ctypes.byref(sid))
            unsigned_hr = int(hr) & 0xFFFFFFFF
        if unsigned_hr != 0 or not sid:
            raise OSError(f"Windows AppContainer profili oluşturulamadı: HRESULT 0x{unsigned_hr:08X}")
        length = int(self.advapi32.GetLengthSid(sid))
        if length <= 0:
            self.advapi32.FreeSid(sid)
            raise ctypes.WinError(ctypes.get_last_error())
        self._sid_buffer = ctypes.create_string_buffer(length)
        ctypes.memmove(self._sid_buffer, sid, length)
        self._sid_pointer = ctypes.cast(self._sid_buffer, ctypes.wintypes.LPVOID)
        self.advapi32.FreeSid(sid)
        text_pointer = ctypes.wintypes.LPWSTR()
        if not self.advapi32.ConvertSidToStringSidW(self._sid_pointer, ctypes.byref(text_pointer)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            self._sid_text = str(text_pointer.value)
        finally:
            self.kernel32.LocalFree(text_pointer)
        system_drive = pathlib.Path(os.environ.get("SystemDrive", "C:") + os.sep)
        native_root = pathlib.Path(os.environ.get("FORGECODE_NATIVE_SANDBOX_ROOT", str(system_drive / "ForceCodeSandbox")))
        self.execution_workspace = native_root.resolve() / self.identity
        self.execution_workspace.mkdir(parents=True, exist_ok=True)
        del keepalive

    def _grant_native_acl(
        self,
        path: pathlib.Path,
        access_mask: int,
        inheritance: int,
        label: str,
        sid_pointer: ctypes.wintypes.LPVOID | None = None,
        sid_label: str | None = None,
    ) -> None:
        resolved = path.resolve()
        selected_sid = sid_pointer or self._sid_pointer
        cache_key = f"{label}|{resolved}|{sid_label or self._sid_text}"
        if cache_key in self._acl_roots:
            return
        owner = ctypes.wintypes.LPVOID()
        group = ctypes.wintypes.LPVOID()
        old_dacl = ctypes.wintypes.LPVOID()
        sacl = ctypes.wintypes.LPVOID()
        descriptor = ctypes.wintypes.LPVOID()
        DACL_SECURITY_INFORMATION = 0x00000004
        SE_FILE_OBJECT = 1
        directory_handle = int(self.kernel32.CreateFileW(
            str(resolved), 0x02000000, 0x7, None, 3, 0x02000000, None,
        ) or 0)
        if directory_handle in {0, -1, 0xFFFFFFFFFFFFFFFF}:
            raise ctypes.WinError(ctypes.get_last_error())
        result = self.advapi32.GetSecurityInfo(
            directory_handle, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
            ctypes.byref(owner), ctypes.byref(group), ctypes.byref(old_dacl), ctypes.byref(sacl),
            ctypes.byref(descriptor),
        )
        if result != 0:
            self.kernel32.CloseHandle(directory_handle)
            raise ctypes.WinError(result)
        new_dacl = ctypes.wintypes.LPVOID()
        try:
            access = self.EXPLICIT_ACCESS_W()
            access.grfAccessPermissions = access_mask
            access.grfAccessMode = 1  # GRANT_ACCESS
            access.grfInheritance = inheritance
            access.Trustee.pMultipleTrustee = None
            access.Trustee.MultipleTrusteeOperation = 0
            access.Trustee.TrusteeForm = 0  # TRUSTEE_IS_SID
            access.Trustee.TrusteeType = 0  # TRUSTEE_IS_UNKNOWN
            access.Trustee.ptstrName = ctypes.cast(selected_sid, ctypes.wintypes.LPWSTR)
            result = self.advapi32.SetEntriesInAclW(1, ctypes.byref(access), old_dacl, ctypes.byref(new_dacl))
            if result != 0:
                raise ctypes.WinError(result)
            # MAXIMUM_ALLOWED on the directory handle intentionally prevents
            # SetSecurityInfo from propagating unrelated inherited ACEs into
            # the child tree.
            result = self.advapi32.SetSecurityInfo(
                directory_handle, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
                None, None, new_dacl, None,
            )
            if result != 0:
                raise ctypes.WinError(result)
        finally:
            if new_dacl:
                self.kernel32.LocalFree(new_dacl)
            if descriptor:
                self.kernel32.LocalFree(descriptor)
            self.kernel32.CloseHandle(directory_handle)
        self._acl_roots.add(cache_key)

    def _grant_traverse(self, path: pathlib.Path) -> None:
        # FILE_LIST_DIRECTORY | FILE_TRAVERSE | FILE_READ_ATTRIBUTES |
        # SYNCHRONIZE. No file data read right and no inheritance.
        self._grant_native_acl(path, 0x001000A1, 0, "traverse")

    def _grant_workspace_access(self) -> None:
        # FILE_ALL_ACCESS, inherited only by this AppContainer workspace's
        # children. This never touches the host-side project copy.
        self._grant_native_acl(self.execution_workspace, 0x001F01FF, 0x3, "workspace-full")

    @property
    def python_runtime(self) -> pathlib.Path:
        source = str(pathlib.Path(sys.base_prefix).resolve()).casefold().encode("utf-8")
        source_id = hashlib.sha256(source).hexdigest()[:8]
        version = f"{sys.version_info.major}{sys.version_info.minor}{sys.version_info.micro}"
        return self.execution_workspace.parent / "Runtimes" / f"Python{version}-{source_id}"

    @staticmethod
    def _python_copy_ignore(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            lowered = name.casefold()
            if lowered in {"site-packages", "__pycache__"} or lowered.endswith((".pyc", ".pyo")):
                ignored.add(name)
        return ignored

    def _ensure_python_runtime(self) -> pathlib.Path:
        target = self.python_runtime
        receipt = target / ".force-runtime.json"
        expected = {
            "schema": 1,
            "python": platform.python_version(),
            "source": str(pathlib.Path(sys.base_prefix).resolve()),
        }
        if target.joinpath("python.exe").is_file() and load_json(receipt, {}) == expected:
            return target

        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        # Grant the built-in All Application Packages group read/execute on an
        # empty parent before copying. New runtime files inherit the ACE; no
        # host Python directory or user data ACL is ever changed.
        self._grant_native_acl(
            parent, 0x001200A9, 0x3, "shared-runtime-read",
            sid_pointer=self._all_packages_sid(), sid_label="all-packages",
        )
        staging = parent / f".{target.name}-{uuid.uuid4().hex}.tmp"
        source = pathlib.Path(sys.base_prefix).resolve()
        try:
            staging.mkdir(parents=False, exist_ok=False)
            for pattern in ("python*.exe", "python*.dll", "vcruntime*.dll", "LICENSE.txt"):
                for item in source.glob(pattern):
                    if item.is_file():
                        shutil.copy2(item, staging / item.name)
            for folder_name in ("DLLs", "Lib"):
                source_folder = source / folder_name
                if source_folder.is_dir():
                    shutil.copytree(
                        source_folder, staging / folder_name,
                        ignore=self._python_copy_ignore, dirs_exist_ok=True,
                    )
            (staging / "py.cmd").write_text('@"%~dp0python.exe" %*\r\n', encoding="utf-8", newline="")
            atomic_json(staging / receipt.name, expected)
            if not (staging / "python.exe").is_file():
                raise OSError("YalÄ±tÄ±lmÄ±ÅŸ Python Ã§alÄ±ÅŸma zamanÄ± hazÄ±rlanamadÄ±")
            try:
                os.replace(staging, target)
            except OSError:
                # Another ForceCode window may have completed the same atomic
                # runtime installation while this process was copying.
                if target.joinpath("python.exe").is_file() and load_json(receipt, {}) == expected:
                    return target
                raise
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        return target

    def _grant_command_runtimes(self, command: str) -> None:
        lowered = str(command).casefold()
        if any(marker in lowered for marker in ("python", "pytest", "pip", "py ", "py.exe")):
            self._ensure_python_runtime()

    def _ensure_project_python_launcher(self, command: str) -> None:
        lowered = str(command).casefold()
        if not any(marker in lowered for marker in ("python", "pytest", "pip", "py ", "py.exe")):
            return
        runtime = self.python_runtime
        if not runtime.joinpath("python.exe").is_file():
            return
        launcher = self.execution_workspace / ".forcesandbox-bin"
        launcher.mkdir(parents=True, exist_ok=True)
        shutil.copy2(runtime / "python.exe", launcher / "python.exe")
        (launcher / "py.cmd").write_text('@"%~dp0python.exe" %*\r\n', encoding="utf-8", newline="")

    def _tool_roots(self) -> tuple[list[pathlib.Path], list[pathlib.Path]]:
        paths: list[pathlib.Path] = []
        roots: list[pathlib.Path] = []
        system_root = pathlib.Path(os.environ.get("SystemRoot", r"C:\Windows"))
        paths.extend([system_root / "System32", system_root, system_root / "System32" / "WindowsPowerShell" / "v1.0"])
        private_bin = self.execution_workspace / ".forcesandbox-bin"
        if private_bin.is_dir():
            paths.append(private_bin)
        if self.python_runtime.is_dir():
            paths.extend([self.python_runtime, self.python_runtime / "Scripts"])
            roots.append(self.python_runtime)
        for name in ("git", "node", "npm", "npx", "dotnet", "go", "cargo", "rustc", "java", "javac"):
            executable = shutil.which(name)
            if not executable:
                continue
            executable_path = pathlib.Path(executable).resolve()
            try:
                executable_path.relative_to(HOST_PATH_TYPE.home().resolve())
                continue
            except ValueError:
                pass
            paths.append(executable_path.parent)
            parts = [part.casefold() for part in executable_path.parts]
            if "git" in parts:
                index = parts.index("git")
                roots.append(pathlib.Path(*executable_path.parts[:index + 1]))
            else:
                roots.append(executable_path.parent)
        unique_paths = list(dict.fromkeys(path.resolve() for path in paths if path.exists()))
        unique_roots = list(dict.fromkeys(path.resolve() for path in roots if path.exists()))
        return unique_paths, unique_roots

    def _environment(self) -> ctypes.Array[Any]:
        tool_paths, _ = self._tool_roots()
        private_home = self.execution_workspace / ".forcesandbox-home"
        private_temp = self.execution_workspace / ".forcesandbox-tmp"
        private_home.mkdir(parents=True, exist_ok=True)
        private_temp.mkdir(parents=True, exist_ok=True)
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        user_profile = str(HOST_PATH_TYPE.home())
        values = {
            "SystemRoot": system_root,
            "WINDIR": system_root,
            "ComSpec": str(pathlib.Path(system_root) / "System32" / "cmd.exe"),
            "PATH": os.pathsep.join(str(path) for path in tool_paths),
            "PATHEXT": ".COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC",
            # Windows rewrites these host locations into the AppContainer's
            # package profile. The PowerShell bootstrap below then narrows
            # HOME/TEMP to private directories inside that redirected root.
            "USERPROFILE": user_profile,
            "APPDATA": os.environ.get("APPDATA", str(pathlib.Path(user_profile) / "AppData" / "Roaming")),
            "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", str(pathlib.Path(user_profile) / "AppData" / "Local")),
            "TEMP": os.environ.get("TEMP", str(pathlib.Path(user_profile) / "AppData" / "Local" / "Temp")),
            "TMP": os.environ.get("TMP", str(pathlib.Path(user_profile) / "AppData" / "Local" / "Temp")),
            "CI": "1",
            "FORGECODE_SANDBOX": "1",
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        if self.python_runtime.is_dir():
            values["PYTHONHOME"] = str(self.python_runtime)
            values["PYTHONNOUSERSITE"] = "1"
        block = "\0".join(f"{key}={value}" for key, value in sorted(values.items(), key=lambda row: row[0].casefold())) + "\0\0"
        return ctypes.create_unicode_buffer(block)

    @staticmethod
    def _mirror_link(path: pathlib.Path) -> bool:
        try:
            if path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)()):
                return True
            return bool(int(getattr(path.lstat(), "st_file_attributes", 0) or 0) & 0x400)
        except OSError:
            return True

    @staticmethod
    def _mirror_files(root: pathlib.Path) -> dict[str, pathlib.Path]:
        result: dict[str, pathlib.Path] = {}
        if not root.exists():
            return result
        for directory, names, files in os.walk(root, topdown=True, followlinks=False):
            directory_path = pathlib.Path(directory)
            names[:] = [
                name for name in names
                if name not in {".forcesandbox-home", ".forcesandbox-tmp", ".forcesandbox-bin"}
                and not WindowsAppContainerRunner._mirror_link(directory_path / name)
            ]
            for name in files:
                path = directory_path / name
                if WindowsAppContainerRunner._mirror_link(path):
                    continue
                try:
                    relative = path.relative_to(root).as_posix()
                    if path.is_file():
                        result[relative] = path
                except (OSError, ValueError):
                    continue
        return result

    @staticmethod
    def _mirror(source: pathlib.Path, destination: pathlib.Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        source_files = WindowsAppContainerRunner._mirror_files(source)
        destination_files = WindowsAppContainerRunner._mirror_files(destination)
        for relative, source_file in source_files.items():
            target = destination / pathlib.Path(*pathlib.PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                source_stat = source_file.stat()
                target_stat = target.stat() if target.exists() else None
                unchanged = (
                    target_stat is not None and source_stat.st_size == target_stat.st_size
                    and source_stat.st_mtime_ns == target_stat.st_mtime_ns
                )
            except OSError:
                unchanged = False
            if not unchanged:
                shutil.copy2(source_file, target)
        for relative, target in destination_files.items():
            if relative not in source_files:
                try:
                    target.unlink()
                except OSError:
                    pass
        for directory, _, _ in os.walk(destination, topdown=False):
            path = pathlib.Path(directory)
            if path != destination and path.name not in {".forcesandbox-home", ".forcesandbox-tmp", ".forcesandbox-bin"}:
                try:
                    path.rmdir()
                except OSError:
                    pass

    def complete_command(self) -> None:
        if not self._command_active:
            return
        try:
            self._mirror(self.execution_workspace, self.workspace)
        finally:
            self._command_active = False
            if self._command_lock.locked():
                self._command_lock.release()

    def prepare(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._ensure_profile()
        self._grant_traverse(self.execution_workspace.parent)
        self._grant_native_acl(
            self.execution_workspace.parent, 0x001000A1, 0, "all-packages-traverse",
            sid_pointer=self._all_packages_sid(), sid_label="all-packages",
        )
        # The profile root carries Windows' package-specific conditional ACE.
        # Add an explicit full ACE only to the command workspace so desktop
        # runtimes such as PowerShell can enumerate it reliably.
        self._grant_workspace_access()

    def verify(self) -> bool:
        if self._verified:
            return True
        self.prepare()
        process = self.spawn("Write-Output 'FORGECODE_NATIVE_SANDBOX_OK'")
        output, _ = process.communicate(timeout=10)
        process.close()
        self._verified = b"FORGECODE_NATIVE_SANDBOX_OK" in output
        return self._verified

    def _create_job(self) -> int:
        handle = int(self.kernel32.CreateJobObjectW(None, None) or 0)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = self.JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = (
            self.JOB_OBJECT_LIMIT_ACTIVE_PROCESS | self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE |
            self.JOB_OBJECT_LIMIT_PROCESS_MEMORY
        )
        limits.BasicLimitInformation.ActiveProcessLimit = 128
        limits.ProcessMemoryLimit = 2 * 1024 * 1024 * 1024
        if not self.kernel32.SetInformationJobObject(
            handle, self.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            error = ctypes.get_last_error()
            self.kernel32.CloseHandle(handle)
            raise ctypes.WinError(error)
        return handle

    def spawn(self, command: str) -> NativeSandboxProcess:
        self.prepare()
        self._grant_command_runtimes(command)
        self._command_lock.acquire()
        self._command_active = True
        self._mirror(self.workspace, self.execution_workspace)
        self._ensure_project_python_launcher(command)
        wt = ctypes.wintypes
        security = self.SECURITY_ATTRIBUTES(ctypes.sizeof(self.SECURITY_ATTRIBUTES), None, True)
        stdin_read, stdin_write = wt.HANDLE(), wt.HANDLE()
        stdout_read, stdout_write = wt.HANDLE(), wt.HANDLE()
        handles: list[int] = []
        attribute_list = None
        process_info = self.PROCESS_INFORMATION()
        job_handle = 0
        try:
            if not self.kernel32.CreatePipe(ctypes.byref(stdin_read), ctypes.byref(stdin_write), ctypes.byref(security), 0):
                raise ctypes.WinError(ctypes.get_last_error())
            handles.extend([int(stdin_read.value), int(stdin_write.value)])
            if not self.kernel32.CreatePipe(ctypes.byref(stdout_read), ctypes.byref(stdout_write), ctypes.byref(security), 0):
                raise ctypes.WinError(ctypes.get_last_error())
            handles.extend([int(stdout_read.value), int(stdout_write.value)])
            if not self.kernel32.SetHandleInformation(stdin_write, self.HANDLE_FLAG_INHERIT, 0):
                raise ctypes.WinError(ctypes.get_last_error())
            if not self.kernel32.SetHandleInformation(stdout_read, self.HANDLE_FLAG_INHERIT, 0):
                raise ctypes.WinError(ctypes.get_last_error())

            size = ctypes.c_size_t()
            self.kernel32.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
            attribute_buffer = ctypes.create_string_buffer(size.value)
            attribute_list = ctypes.cast(attribute_buffer, wt.LPVOID)
            if not self.kernel32.InitializeProcThreadAttributeList(attribute_list, 2, 0, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            capabilities, capability_keepalive = self._internet_capabilities()
            security_capabilities = self.SECURITY_CAPABILITIES(
                self._sid_pointer,
                ctypes.cast(capabilities, ctypes.POINTER(self.SID_AND_ATTRIBUTES)) if capabilities is not None else None,
                1 if capabilities is not None else 0,
                0,
            )
            if not self.kernel32.UpdateProcThreadAttribute(
                attribute_list, 0, self.PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                ctypes.byref(security_capabilities), ctypes.sizeof(security_capabilities), None, None,
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            desktop_policy = wt.DWORD(self.PROCESS_CREATION_DESKTOP_APP_BREAKAWAY_DISABLE_PROCESS_TREE)
            if not self.kernel32.UpdateProcThreadAttribute(
                attribute_list, 0, self.PROC_THREAD_ATTRIBUTE_DESKTOP_APP_POLICY,
                ctypes.byref(desktop_policy), ctypes.sizeof(desktop_policy), None, None,
            ):
                raise ctypes.WinError(ctypes.get_last_error())

            startup = self.STARTUPINFOEXW()
            startup.StartupInfo.cb = ctypes.sizeof(self.STARTUPINFOEXW)
            startup.StartupInfo.dwFlags = self.STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput = stdin_read
            startup.StartupInfo.hStdOutput = stdout_write
            startup.StartupInfo.hStdError = stdout_write
            startup.lpAttributeList = attribute_list
            powershell = pathlib.Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
            argv = [
                str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                f"$forceWorkspace = {powershell_literal_path(str(self.execution_workspace))}; "
                "$env:HOME = Join-Path $forceWorkspace '.forcesandbox-home'; "
                "$env:USERPROFILE = $env:HOME; "
                "$env:APPDATA = Join-Path $env:HOME 'AppData\\Roaming'; "
                "$env:TEMP = Join-Path $forceWorkspace '.forcesandbox-tmp'; $env:TMP = $env:TEMP; "
                "Set-Location -LiteralPath $forceWorkspace; " + windows_shell_command(str(command)),
            ]
            command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
            environment = self._environment()
            flags = self.EXTENDED_STARTUPINFO_PRESENT | self.CREATE_UNICODE_ENVIRONMENT | self.CREATE_NO_WINDOW | self.CREATE_SUSPENDED
            if not self.kernel32.CreateProcessW(
                str(powershell), command_line, None, None, True, flags,
                environment, str(pathlib.Path(os.environ.get("SystemRoot", r"C:\Windows"))),
                ctypes.byref(startup.StartupInfo), ctypes.byref(process_info),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            job_handle = self._create_job()
            if not self.kernel32.AssignProcessToJobObject(job_handle, process_info.hProcess):
                raise ctypes.WinError(ctypes.get_last_error())
            if self.kernel32.ResumeThread(process_info.hThread) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
            self.kernel32.CloseHandle(process_info.hThread)
            process_info.hThread = None
            self.kernel32.CloseHandle(stdin_read)
            handles.remove(int(stdin_read.value))
            self.kernel32.CloseHandle(stdout_write)
            handles.remove(int(stdout_write.value))
            process = NativeSandboxProcess(
                self, int(process_info.hProcess), job_handle, int(process_info.dwProcessId),
                int(stdin_write.value), int(stdout_read.value), argv,
            )
            handles.remove(int(stdin_write.value))
            handles.remove(int(stdout_read.value))
            process_info.hProcess = None
            job_handle = 0
            del capability_keepalive, security_capabilities, desktop_policy, attribute_buffer, environment
            return process
        except Exception:
            if process_info.hProcess:
                self.kernel32.TerminateProcess(process_info.hProcess, 1)
            if self._command_active:
                self._command_active = False
                if self._command_lock.locked():
                    self._command_lock.release()
            raise
        finally:
            if attribute_list:
                self.kernel32.DeleteProcThreadAttributeList(attribute_list)
            for raw_handle in handles:
                if raw_handle:
                    self.kernel32.CloseHandle(raw_handle)
            if process_info.hThread:
                self.kernel32.CloseHandle(process_info.hThread)
            if process_info.hProcess:
                self.kernel32.CloseHandle(process_info.hProcess)
            if job_handle:
                self.kernel32.CloseHandle(job_handle)

    def run(self, command: str, input: bytes | None, timeout: float) -> subprocess.CompletedProcess[bytes]:
        process = self.spawn(command)
        try:
            stdout, stderr = process.communicate(input=input, timeout=timeout)
            return subprocess.CompletedProcess(process.args, int(process.returncode or 0), stdout, stderr)
        finally:
            process.close()


class ForceSandboxManager:
    """Stage project work privately and transfer only verified, conflict-free changes."""

    def __init__(self, project_root: pathlib.Path, cfg: Config):
        self.project_root = project_root.resolve()
        self.cfg = cfg
        identity = hashlib.sha256(str(self.project_root).casefold().encode("utf-8")).hexdigest()[:16]
        self.base = (cfg.home / "sandboxes" / identity).resolve()
        self.workspace = self.base / "workspace"
        self.snapshots = self.base / "snapshots"
        self.state_path = self.base / "state.json"
        self.log_path = self.base / "sandbox.jsonl"
        self._lock = threading.RLock()
        self._engine_cache: tuple[str, bool] | None = None
        self._native_runner: WindowsAppContainerRunner | None = None
        self._session_enforced = bool(cfg.data.get("sandbox_enabled", True) and cfg.data.get("_runtime_enable_sandbox", False))

    def active(self) -> bool:
        return self._session_enforced

    @staticmethod
    def _is_link(path: pathlib.Path) -> bool:
        try:
            if path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)()):
                return True
            # OneDrive placeholders and other Windows reparse points are not
            # always reported as symlinks/junctions by pathlib. Never stage
            # them because their real target may live outside the project.
            attributes = int(getattr(path.lstat(), "st_file_attributes", 0) or 0)
            return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
        except OSError:
            return True

    @staticmethod
    def _safe_relative(raw: str) -> pathlib.PurePosixPath:
        normalized = str(raw).replace("\\", "/").strip("/")
        relative = pathlib.PurePosixPath(normalized)
        if not normalized or relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError(f"Güvensiz sandbox yolu: {raw}")
        return relative

    def _safe_target(self, root: pathlib.Path, relative: str) -> pathlib.Path:
        rel = self._safe_relative(relative)
        target = (root / pathlib.Path(*rel.parts)).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"Sandbox yolu çalışma alanının dışına çıkıyor: {relative}") from exc
        current = root.resolve()
        for part in rel.parts:
            current = current / part
            if current.exists() and self._is_link(current):
                raise ValueError(f"Sandbox aktarımında bağlantı/reparse noktası engellendi: {relative}")
        return target

    @staticmethod
    def _digest(path: pathlib.Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(128 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def _ignored(self, relative: pathlib.PurePosixPath) -> bool:
        if any(part in IGNORE_DIRS for part in relative.parts):
            return True
        name = relative.name.casefold()
        if ".docker" in {part.casefold() for part in relative.parts[:-1]} and name == "config.json":
            return True
        if name in SANDBOX_SECRET_NAMES or pathlib.PurePosixPath(name).suffix in SANDBOX_SECRET_SUFFIXES:
            return True
        if name.startswith(".env.") and not name.endswith((".example", ".sample", ".template")):
            return True
        return False

    def manifest(self, root: pathlib.Path) -> dict[str, dict[str, Any]]:
        root = root.resolve()
        if not root.exists():
            return {}
        maximum_file = max(1, int(self.cfg.data.get("sandbox_max_file_mb", 20))) * 1024 * 1024
        configured_total_mb = int(self.cfg.data.get("sandbox_max_transfer_mb", 0))
        maximum_total = configured_total_mb * 1024 * 1024 if configured_total_mb > 0 else None
        total = 0
        result: dict[str, dict[str, Any]] = {}
        for directory, names, files in os.walk(root, topdown=True, followlinks=False):
            directory_path = pathlib.Path(directory)
            kept: list[str] = []
            for name in names:
                candidate = directory_path / name
                relative = pathlib.PurePosixPath(candidate.relative_to(root).as_posix())
                if not self._ignored(relative) and not self._is_link(candidate):
                    kept.append(name)
            names[:] = kept
            for name in files:
                path = directory_path / name
                relative = pathlib.PurePosixPath(path.relative_to(root).as_posix())
                if self._ignored(relative) or self._is_link(path):
                    continue
                try:
                    size = path.stat().st_size
                    if size > maximum_file:
                        continue
                    total += size
                    if maximum_total is not None and total > maximum_total:
                        raise ValueError(
                            f"ForceSandbox proje sınırı aşıldı: en fazla {maximum_total // (1024 * 1024)} MB. "
                            "sandbox_max_transfer_mb ayarını yükseltin veya sınırsız kullanım için 0 yapın."
                        )
                    result[relative.as_posix()] = {"sha256": self._digest(path), "size": size}
                except OSError:
                    continue
        return result

    @staticmethod
    def _atomic_copy(source: pathlib.Path, target: pathlib.Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.forcesandbox-{uuid.uuid4().hex}.tmp")
        try:
            with source.open("rb") as reader, temporary.open("wb") as writer:
                shutil.copyfileobj(reader, writer, length=128 * 1024)
                writer.flush()
                os.fsync(writer.fileno())
            os.replace(temporary, target)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _log(self, event: str, details: dict[str, Any] | None = None) -> None:
        self.base.mkdir(parents=True, exist_ok=True)

        def sanitize(value: Any) -> Any:
            if isinstance(value, dict):
                return {redact_sensitive(str(key))[:100]: sanitize(item) for key, item in value.items()}
            if isinstance(value, (list, tuple, set)):
                return [sanitize(item) for item in value]
            if isinstance(value, str):
                return redact_sensitive(value)
            if value is None or isinstance(value, (bool, int, float)):
                return value
            return redact_sensitive(str(value))

        row = {
            "time": dt.datetime.now().isoformat(timespec="seconds"),
            "event": redact_sensitive(str(event))[:100],
            "details": sanitize(details or {}),
        }
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _load_state(self) -> dict[str, Any]:
        state = load_json(self.state_path, {})
        return state if isinstance(state, dict) else {}

    def _save_state(self, state: dict[str, Any]) -> None:
        state.update({
            "version": 1,
            "project_fingerprint": hashlib.sha256(str(self.project_root).casefold().encode("utf-8")).hexdigest(),
            "workspace": str(self.workspace),
            "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        })
        atomic_json(self.state_path, state)

    def pending_changes(self) -> list[str]:
        state = self._load_state()
        base = state.get("base_manifest", {})
        if not isinstance(base, dict):
            base = {}
        current = self.manifest(self.workspace)
        return sorted(name for name in set(base) | set(current) if base.get(name) != current.get(name))

    def _sync_project_to_workspace(self, project_manifest: dict[str, dict[str, Any]]) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        current = self.manifest(self.workspace)
        for relative, signature in project_manifest.items():
            if current.get(relative) == signature:
                continue
            self._atomic_copy(self._safe_target(self.project_root, relative), self._safe_target(self.workspace, relative))
        for relative in sorted(set(current) - set(project_manifest), reverse=True):
            target = self._safe_target(self.workspace, relative)
            if target.is_file():
                target.unlink()
        for directory, _, _ in os.walk(self.workspace, topdown=False):
            path = pathlib.Path(directory)
            if path != self.workspace:
                try:
                    path.rmdir()
                except OSError:
                    pass

    def prepare(self) -> pathlib.Path:
        if not self.active():
            return self.project_root
        with self._lock:
            self.base.mkdir(parents=True, exist_ok=True)
            self.snapshots.mkdir(parents=True, exist_ok=True)
            state = self._load_state()
            base = state.get("base_manifest", {}) if isinstance(state.get("base_manifest", {}), dict) else {}
            current = self.manifest(self.workspace)
            pending = bool(base and any(base.get(name) != current.get(name) for name in set(base) | set(current)))
            if pending:
                self._log("prepare_preserved_pending", {"count": len(self.pending_changes())})
                return self.workspace
            self._sync_project_to_workspace(self.manifest(self.project_root))
            synchronized = self.manifest(self.workspace)
            state["base_manifest"] = synchronized
            state["prepared_at"] = dt.datetime.now().isoformat(timespec="seconds")
            self._save_state(state)
            self._log("prepared", {"files": len(synchronized)})
            return self.workspace


    def _engine_candidate(self) -> str:
        selected = str(self.cfg.data.get("sandbox_engine", "auto")).lower()
        if selected == "auto":
            # Windows receives a dependency-free kernel AppContainer. Other
            # platforms retain the existing container options and fail closed
            # when neither is available.
            candidates = ["native"] if sys.platform == "win32" else ["docker", "podman"]
        else:
            candidates = [selected]
        for candidate in candidates:
            if candidate == "native":
                if sys.platform == "win32":
                    return "native"
                continue
            executable = shutil.which(candidate)
            if executable:
                return executable
        return ""

    def _get_native_runner(self) -> WindowsAppContainerRunner:
        network = bool(self.cfg.data.get("sandbox_network_enabled", True))
        if self._native_runner is None or self._native_runner.network_enabled != network:
            capability_suffix = ".Internet" if network else ".Offline"
            identity = "ForceCode.Sandbox." + self.base.name + capability_suffix
            self._native_runner = WindowsAppContainerRunner(self.workspace, identity, network)
        return self._native_runner

    def engine_status(self, verify: bool = False) -> tuple[str, bool]:
        if self._engine_cache is not None and (self._engine_cache[1] or not verify):
            return self._engine_cache
        executable = self._engine_candidate()
        if not executable:
            self._engine_cache = ("bulunamadı", False)
            return self._engine_cache
        name = "native-appcontainer" if executable == "native" else pathlib.Path(executable).stem.lower()
        if not verify:
            self._engine_cache = (name, False)
            return self._engine_cache
        try:
            if executable == "native":
                available = self._get_native_runner().verify()
            else:
                completed = subprocess.run(
                    [executable, "info"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=5, shell=False,
                )
                available = completed.returncode == 0
        except (OSError, subprocess.TimeoutExpired, ValueError):
            available = False
        self._engine_cache = (name, available)
        return self._engine_cache

    def run_command(self, command: str, input: bytes | None, timeout: float) -> subprocess.CompletedProcess[bytes]:
        engine, available = self.engine_status(verify=True)
        if not available:
            raise ValueError(
                "ForceSandbox güvenli izolasyon motorunu başlatamadı. Güvenlik için komut bilgisayarda "
                "normal kullanıcı yetkisiyle çalıştırılmadı; dosya araçları özel sandbox kopyasında çalışmaya devam eder."
            )
        self._log("command", {
            "engine": engine,
            "network": bool(self.cfg.data.get("sandbox_network_enabled", True)),
            "command": str(command)[:1000],
        })
        if engine == "native-appcontainer":
            return self._get_native_runner().run(command, input=input, timeout=timeout)
        options: dict[str, Any] = {
            "cwd": self.workspace,
            "text": False,
            "capture_output": True,
            "timeout": timeout,
            "shell": False,
        }
        if input is None:
            options["stdin"] = subprocess.DEVNULL
        else:
            options["input"] = input
        return subprocess.run(self.command_argv(command, interactive=input is not None), **options)

    def start_command(self, command: str) -> Any:
        engine, available = self.engine_status(verify=True)
        if not available:
            raise ValueError(
                "ForceSandbox güvenli izolasyon motorunu başlatamadı; etkileşimli komut ana bilgisayarda çalıştırılmadı."
            )
        self._log("interactive_command", {
            "engine": engine,
            "network": bool(self.cfg.data.get("sandbox_network_enabled", True)),
            "command": str(command)[:1000],
        })
        if engine == "native-appcontainer":
            return self._get_native_runner().spawn(command)
        return subprocess.Popen(
            self.command_argv(command, interactive=True), cwd=self.workspace, shell=False,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=False, bufsize=0,
        )

    def _container_image(self) -> str:
        if any(self.workspace.glob("*.csproj")) or any(self.workspace.glob("*.sln")):
            return "mcr.microsoft.com/dotnet/sdk:9.0"
        if (self.workspace / "package.json").is_file():
            return "node:22-bookworm"
        if (self.workspace / "go.mod").is_file():
            return "golang:1.24-bookworm"
        if (self.workspace / "Cargo.toml").is_file():
            return "rust:1.87-bookworm"
        if (self.workspace / "pyproject.toml").is_file() or (self.workspace / "requirements.txt").is_file() or any(self.workspace.glob("*.py")):
            return "python:3.13-slim"
        return "ubuntu:24.04"

    def command_argv(self, command: str, interactive: bool = False) -> list[str]:
        engine, available = self.engine_status(verify=True)
        if not available:
            raise ValueError(
                "ForceSandbox gerçek izolasyon motoru bulamadı veya motor çalışmıyor. "
                "Güvenlik için yerel kabuk komutu engellendi. "
                "Dosya araçları özel sandbox klasöründe güvenle çalışmaya devam eder."
            )
        if engine == "native-appcontainer":
            raise ValueError("Yerel AppContainer motoru command_argv yerine güvenli süreç köprüsüyle çalıştırılmalıdır")
        executable = self._engine_candidate()
        mount = f"type=bind,source={self.workspace},target=/workspace"
        arguments = [
            executable, "run", "--rm", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--pids-limit=512", "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=268435456",
            "--mount", mount, "--workdir", "/workspace",
            "--env", "HOME=/tmp/forge-home", "--env", "CI=1", "--env", "FORGECODE_SANDBOX=1",
        ]
        if interactive:
            arguments.append("-i")
        if not self.cfg.data.get("sandbox_network_enabled", True):
            arguments.extend(["--network", "none"])
        arguments.extend([self._container_image(), "sh", "-lc", str(command)])
        self._log("command", {"engine": engine, "network": bool(self.cfg.data.get("sandbox_network_enabled", True)), "command": str(command)[:1000]})
        return arguments

    def create_snapshot(self, paths: list[str] | None = None) -> pathlib.Path:
        with self._lock:
            actual = self.manifest(self.project_root)
            selected = sorted(set(paths) if paths is not None else set(actual))
            name = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
            target = self.snapshots / name
            files_root = target / "files"
            existing: list[str] = []
            absent: list[str] = []
            target.mkdir(parents=True, exist_ok=False)
            for relative in selected:
                if relative in actual:
                    self._atomic_copy(
                        self._safe_target(self.project_root, relative),
                        self._safe_target(files_root, relative),
                    )
                    existing.append(relative)
                else:
                    absent.append(relative)
            atomic_json(target / "snapshot.json", {
                "created_at": dt.datetime.now().isoformat(timespec="seconds"),
                "existing": existing,
                "absent": absent,
            })
            state = self._load_state()
            state["last_snapshot"] = str(target)
            self._save_state(state)
            self._log("snapshot", {"name": name, "files": len(existing), "absent": len(absent)})
            return target

    def _restore_snapshot(self, snapshot: pathlib.Path) -> None:
        metadata = load_json(snapshot / "snapshot.json", {})
        existing = metadata.get("existing", []) if isinstance(metadata, dict) else []
        absent = metadata.get("absent", []) if isinstance(metadata, dict) else []
        for relative in existing:
            self._atomic_copy(
                self._safe_target(snapshot / "files", str(relative)),
                self._safe_target(self.project_root, str(relative)),
            )
        for relative in absent:
            target = self._safe_target(self.project_root, str(relative))
            if target.is_file():
                target.unlink()

    def restore_latest_snapshot(self) -> str:
        with self._lock:
            state = self._load_state()
            raw = str(state.get("last_snapshot", ""))
            if not raw:
                raise ValueError("Son sandbox snapshot'ı bulunamadı")
            snapshot = pathlib.Path(raw).resolve()
            try:
                snapshot.relative_to(self.snapshots.resolve())
            except ValueError as exc:
                raise ValueError("Geri yüklenecek güvenilir sandbox snapshot'ı bulunamadı") from exc
            if not snapshot.is_dir():
                raise ValueError("Son sandbox snapshot'ı bulunamadı")
            self._restore_snapshot(snapshot)
            project_manifest = self.manifest(self.project_root)
            self._sync_project_to_workspace(project_manifest)
            state["base_manifest"] = self.manifest(self.workspace)
            self._save_state(state)
            self._log("snapshot_restored", {"name": snapshot.name})
            return snapshot.name

    def transfer(self, verified: bool, force: bool = False, paths: list[str] | None = None) -> SandboxTransferResult:
        if not self.active():
            return SandboxTransferResult("disabled", message="ForceSandbox kapalı")
        with self._lock:
            state = self._load_state()
            base = state.get("base_manifest", {}) if isinstance(state.get("base_manifest", {}), dict) else {}
            current = self.manifest(self.workspace)
            changed = sorted(name for name in set(base) | set(current) if base.get(name) != current.get(name))
            if paths is not None:
                selected = {self._safe_relative(name).as_posix() for name in paths}
                changed = [name for name in changed if name in selected]
            if not changed:
                return SandboxTransferResult("clean", message="Aktarılacak değişiklik yok")
            if not force and not self.cfg.data.get("sandbox_auto_transfer", True):
                self._log("transfer_held", {"reason": "auto_transfer_off", "count": len(changed)})
                return SandboxTransferResult("held", changed, message="Otomatik aktarım kapalı; değişiklikler sandbox'ta bekliyor")
            if not force and not verified:
                self._log("transfer_held", {"reason": "verification_failed", "count": len(changed)})
                return SandboxTransferResult("held", changed, message="Doğrulama geçmedi; gerçek proje değiştirilmedi")
            actual = self.manifest(self.project_root)
            conflicts = [name for name in changed if actual.get(name) != base.get(name)]
            if conflicts:
                self._log("transfer_conflict", {"conflicts": conflicts[:100]})
                return SandboxTransferResult("conflict", changed, conflicts, message="Gerçek proje görev sırasında değişti; otomatik aktarım durduruldu")
            transfer_bytes = sum(int(current.get(name, {}).get("size", 0)) for name in changed)
            configured_maximum_mb = int(self.cfg.data.get("sandbox_max_transfer_mb", 0))
            maximum = configured_maximum_mb * 1024 * 1024 if configured_maximum_mb > 0 else None
            if maximum is not None and transfer_bytes > maximum:
                return SandboxTransferResult("held", changed, message=f"Aktarım {maximum // (1024 * 1024)} MB güvenlik sınırını aşıyor")
            snapshot_path = pathlib.Path()
            if self.cfg.data.get("sandbox_snapshot_enabled", True):
                snapshot_path = self.create_snapshot(changed)
                # create_snapshot persists last_snapshot; continue from that
                # fresh state so the transfer receipt cannot overwrite it.
                state = self._load_state()
            try:
                for relative in changed:
                    target = self._safe_target(self.project_root, relative)
                    if relative not in current:
                        if target.is_file():
                            target.unlink()
                        continue
                    self._atomic_copy(self._safe_target(self.workspace, relative), target)
                verified_actual = self.manifest(self.project_root)
                mismatches = [name for name in changed if verified_actual.get(name) != current.get(name)]
                if mismatches:
                    raise OSError("Aktarım sonrası bütünlük doğrulaması başarısız: " + ", ".join(mismatches[:10]))
            except Exception:
                if snapshot_path:
                    self._restore_snapshot(snapshot_path)
                self._log("transfer_rolled_back", {"count": len(changed)})
                raise
            updated_base = dict(base)
            for relative in changed:
                if relative in current:
                    updated_base[relative] = current[relative]
                else:
                    updated_base.pop(relative, None)
            state["base_manifest"] = updated_base
            state["last_transfer"] = {
                "time": dt.datetime.now().isoformat(timespec="seconds"),
                "files": changed[:200],
                "snapshot": str(snapshot_path) if snapshot_path else "",
            }
            self._save_state(state)
            self._log("transfer_applied", {"count": len(changed), "snapshot": snapshot_path.name if snapshot_path else ""})
            return SandboxTransferResult(
                "applied", changed, snapshot=str(snapshot_path),
                message=f"{len(changed)} değişiklik doğrulanarak gerçek projeye aktarıldı",
            )

    def cleanup(self) -> None:
        with self._lock:
            resolved = self.workspace.resolve()
            try:
                resolved.relative_to(self.base.resolve())
            except ValueError as exc:
                raise ValueError("Güvensiz sandbox temizleme yolu") from exc
            if resolved.exists():
                shutil.rmtree(resolved)
            state = self._load_state()
            state["base_manifest"] = {}
            self._save_state(state)
            self.prepare()
            self._log("cleaned")

    def recent_logs(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.log_path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(200, limit)):]:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def status_text(self, verify_engine: bool = False) -> str:
        if not self.active():
            return "ForceSandbox: kapalı"
        engine, available = self.engine_status(verify_engine)
        if available:
            engine_state = f"{engine} hazır"
        elif engine != "bulunamadı" and not verify_engine:
            engine_state = f"{engine} bulundu · henüz doğrulanmadı"
        else:
            engine_state = f"{engine} · komutlar kilitli"
        pending = len(self.pending_changes()) if self.workspace.exists() else 0
        state = self._load_state()
        last_snapshot = pathlib.Path(str(state.get("last_snapshot", ""))).name if state.get("last_snapshot") else "yok"
        return (
            f"ForceSandbox: açık · motor {engine_state}\n"
            f"İnternet: {'açık' if self.cfg.data.get('sandbox_network_enabled', True) else 'kapalı'} · "
            f"otomatik aktarım: {'açık' if self.cfg.data.get('sandbox_auto_transfer', True) else 'kapalı'} · "
            f"snapshot: {'açık' if self.cfg.data.get('sandbox_snapshot_enabled', True) else 'kapalı'}\n"
            f"Çalışma alanı: {self.workspace}\nBekleyen değişiklik: {pending} · son snapshot: {last_snapshot}"
        )


def hard_operation_risk(operation: str, details: str) -> tuple[str, str] | None:
    """Deterministic safety floor that an AI verdict cannot override."""
    lowered = details.lower().replace("`", "")
    if operation != "command":
        sensitive = (".git/config", ".git\\config", ".ssh/", ".ssh\\", "credentials", "id_rsa", "id_ed25519")
        if any(marker in lowered for marker in sensitive):
            return "block", "Kimlik bilgisi veya depo güvenlik yapılandırması değiştiriliyor."
        return None
    destructive_patterns = (
        r"\bformat(?:\.com)?\b", r"\bclear-disk\b", r"\binitialize-disk\b",
        r"\bshutdown(?:\.exe)?\b", r"\brestart-computer\b", r"\bstop-computer\b",
        r"\bremove-item\b[^\n]*(?:-recurse|-r\b)[^\n]*(?:[a-z]:\\|/|\.\.)",
        r"\brm\s+-[a-z]*r[a-z]*f?\s+(?:/|~|\.\.)", r"\bdel\s+/[sq]\b",
        r"\bgit\s+(?:reset\s+--hard|clean\s+-[^\s]*f)",
        r"\b(?:reg\s+delete|bcdedit|diskpart|cipher\s+/w)\b",
        r"\b(?:invoke-expression|iex)\b[^\n]*(?:downloadstring|invoke-webrequest|curl|wget)",
        r"\bpowershell(?:\.exe)?\b[^\n]*(?:-enc|-encodedcommand)\b",
    )
    if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in destructive_patterns):
        return "block", "Komut sistem, disk, geçmiş veya proje dışı veriler üzerinde geri döndürülemez etki oluşturabilir."
    return None


def parse_file_view_command(command: str) -> tuple[str, str, int] | None:
    """Recognize strict, read-only file viewing commands for direct execution."""
    raw = str(command).strip()
    wrapper = re.fullmatch(
        r"powershell(?:\.exe)?\s+(?:(?:-NoProfile|-NonInteractive)\s+)*-Command\s+(.+)",
        raw, re.IGNORECASE,
    )
    if wrapper:
        raw = wrapper.group(1).strip().strip('"\'').strip()
    path = r'(?P<path>"[^"\r\n]+"|\'[^\'\r\n]+\'|[^|;&<>\r\n]+?)'
    cat = re.fullmatch(
        rf"cat\s+{path}(?:\s*\|\s*(?P<direction>tail|head)\s+(?:-n\s+)?-?(?P<count>\d+))?",
        raw, re.IGNORECASE,
    )
    if cat:
        direction = (cat.group("direction") or "all").lower()
        return cat.group("path").strip().strip('"\''), direction, int(cat.group("count") or 0)
    type_match = re.fullmatch(rf"type\s+{path}", raw, re.IGNORECASE)
    if type_match:
        return type_match.group("path").strip().strip('"\''), "all", 0
    content = re.fullmatch(
        rf"Get-Content(?:\s+-(?:LiteralPath|Path))?\s+{path}(?:\s+-(?P<option>Tail|TotalCount)\s+(?P<count>\d+))?",
        raw, re.IGNORECASE,
    )
    if content:
        option = (content.group("option") or "").lower()
        direction = "tail" if option == "tail" else "head" if option == "totalcount" else "all"
        return content.group("path").strip().strip('"\''), direction, int(content.group("count") or 0)
    return None


def is_known_safe_read_command(command: str) -> bool:
    if parse_file_view_command(command):
        return True
    raw = str(command).strip()
    if any(marker in raw for marker in (";", "&&", "||", ">", "`", "$(")):
        return False
    return bool(re.fullmatch(
        r"(?i)(?:pwd|Get-Location|dir|Get-ChildItem(?:\s+[-\w.*'\"\\/:]+)*|"
        r"Test-Path\s+[^\r\n]+|git\s+(?:status|diff|log|show)(?:\s+[^\r\n]+)?|"
        r"python(?:\.exe)?\s+--version|node(?:\.exe)?\s+--version)",
        raw,
    ))
