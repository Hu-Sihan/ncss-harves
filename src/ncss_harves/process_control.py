from __future__ import annotations

import os
import platform
import signal
import subprocess
from typing import Protocol, Sequence


class ProcessBackend(Protocol):
    def close(self, process: subprocess.Popen[bytes]) -> None: ...


class _WindowsJobBackend:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        try:
            import win32api
            import win32con
            import win32job
        except ImportError as exc:  # pragma: no cover - Windows installation dependent
            raise RuntimeError("pywin32 is required to own the Chrome process tree") from exc
        self._win32api = win32api
        try:
            self._job = win32job.CreateJobObject(None, "")
            info = win32job.QueryInformationJobObject(
                self._job, win32job.JobObjectExtendedLimitInformation
            )
            info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(
                self._job, win32job.JobObjectExtendedLimitInformation, info
            )
            handle = win32api.OpenProcess(
                win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE,
                False,
                process.pid,
            )
            try:
                win32job.AssignProcessToJobObject(self._job, handle)
            finally:
                handle.Close()
        except BaseException:
            job = getattr(self, "_job", None)
            if job is not None:
                win32api.CloseHandle(job)
                self._job = None
            raise

    def close(self, process: subprocess.Popen[bytes]) -> None:
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            pass
        finally:
            if self._job is not None:
                self._win32api.CloseHandle(self._job)
                self._job = None
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3.0)


class _PosixGroupBackend:
    def close(self, process: subprocess.Popen[bytes]) -> None:
        try:
            process.wait(timeout=3.0)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=3.0)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _cleanup_failed_spawn(process: subprocess.Popen[bytes]) -> None:
    """Terminate only the process tree created by the failed spawn attempt."""
    if process.poll() is not None:
        return
    if platform.system() == "Windows":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5.0,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3.0)


class ProcessOwner:
    """Owns exactly one spawned process tree; it never enumerates system processes."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        *,
        backend: ProcessBackend | None = None,
    ) -> None:
        self.process = process
        self.backend = backend or (
            _WindowsJobBackend(process) if platform.system() == "Windows" else _PosixGroupBackend()
        )
        self._closed = False

    @classmethod
    def spawn(cls, command: Sequence[str]) -> "ProcessOwner":
        kwargs: dict[str, object] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(list(command), **kwargs)  # type: ignore[arg-type]
        try:
            return cls(process)
        except BaseException:
            _cleanup_failed_spawn(process)
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.backend.close(self.process)
