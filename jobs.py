"""Managed worker process; cancellation also terminates FFmpeg descendants."""
import ctypes
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading


class WindowsJob:
    def __init__(self, process):
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [('ProcessTime', ctypes.c_longlong), ('JobTime', ctypes.c_longlong),
                        ('LimitFlags', wintypes.DWORD), ('MinWorkingSet', ctypes.c_size_t),
                        ('MaxWorkingSet', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                        ('SchedulingClass', wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ('ReadOps', 'WriteOps', 'OtherOps', 'ReadBytes', 'WriteBytes', 'OtherBytes')]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', BasicLimits), ('IoInfo', IoCounters),
                        ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                        ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class WorkerJob:
    def __init__(self, request, command=None):
        self.events = queue.Queue()
        self.lock = threading.RLock()
        self.latest_progress = None
        self.cancelled = False
        self.terminal = None
        self.tree = None
        if command is None:
            command = ([sys.executable, '--download-worker'] if getattr(sys, 'frozen', False)
                       else [sys.executable, '-u', str(Path(__file__).with_name('worker.py'))])
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            start_new_session=os.name != 'nt')
        try:
            if os.name == 'nt':
                self.tree = WindowsJob(self.process)
            self.process.stdin.write(json.dumps(request) + '\n')
            self.process.stdin.flush()
            self.process.stdin.close()
        except Exception:
            self._kill_tree()
            self.process.kill()
            self.process.wait()
            self.process.stdin.close()
            self.process.stdout.close()
            raise
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.watcher = threading.Thread(target=self._watch, daemon=True)
        self.reader.start()
        self.watcher.start()

    def _watch(self):
        # A surviving child can keep the stdout pipe open after a worker crash.
        # Watch the process separately so EOF is never required to stop children.
        self.process.wait()
        with self.lock:
            self._kill_tree()

    def _kill_tree(self):
        if self.tree is not None:
            self.tree.close()
        elif os.name != 'nt':
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def cancel(self):
        with self.lock:
            if self.terminal is not None or self.process.poll() is not None:
                return False
            self.cancelled = True
            self._kill_tree()
            return True

    def _read(self):
        try:
            for line in self.process.stdout:
                event, payload = json.loads(line)
                with self.lock:
                    if event == 'progress':
                        self.latest_progress = payload
                    elif event in ('metadata', 'done', 'error'):
                        self.terminal = (event, payload)
                    else:
                        self.events.put((event, payload))
        except (OSError, ValueError) as exc:
            with self.lock:
                self.terminal = ('error', f'Worker communication failed: {exc}')
                self._kill_tree()
        finally:
            self.process.stdout.close()
            exit_code = self.process.wait()
            with self.lock:
                self._kill_tree()
                terminal = (('cancelled', None) if self.cancelled else self.terminal
                            or ('error', f'Download worker stopped unexpectedly (exit code {exit_code}).'))
                self.events.put(terminal)

    def poll_events(self):
        with self.lock:
            progress, self.latest_progress = self.latest_progress, None
        result = [('progress', progress)] if progress is not None else []
        while True:
            try:
                result.append(self.events.get_nowait())
            except queue.Empty:
                return result

    def join(self, timeout=None):
        self.reader.join(timeout)
        self.watcher.join(timeout)
