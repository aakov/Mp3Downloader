import ctypes
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest

from jobs import WorkerJob
from downloader import download_options, find_ffmpeg


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='.test-job-', dir=Path(__file__).resolve().parent)
        self.jobs = []

    def tearDown(self):
        for job in self.jobs:
            job.cancel()
            job.join(5)
        self.folder.cleanup()

    def start(self, operation, real_worker=False):
        command = None if real_worker else [sys.executable, '-u', str(Path(__file__).parent / 'tests' / 'worker_fixture.py')]
        request = {'operation': operation, 'folder': self.folder.name, 'url': 'https://example.org/video',
                   'options': {'quiet': True}}
        job = WorkerJob(request, command=command)
        self.jobs.append(job)
        return job

    def wait_for(self, job, event):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            for kind, payload in job.poll_events():
                if kind == event:
                    return payload
                if kind in ('error', 'done', 'cancelled'):
                    self.fail(f'Unexpected worker event: {kind}: {payload}')
            time.sleep(.01)
        self.fail(f'Timed out waiting for {event}')

    def test_cancel_terminates_worker_and_child_and_keeps_partial_file(self):
        job = self.start('processing')
        payload = self.wait_for(job, 'processing')
        handle = None
        if os.name == 'nt':
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x100000, False, payload['child_pid'])
            self.assertTrue(handle, 'Could not observe child process')
        try:
            self.assertTrue(job.cancel())
            self.wait_for(job, 'cancelled')
            job.join(5)
            self.assertIsNotNone(job.process.poll())
            if handle:
                self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0, 'Child process survived cancellation')
            self.assertEqual(Path(self.folder.name, 'keep.part').read_bytes(), b'partial download')
            self.assertEqual(job.poll_events(), [])
        finally:
            if handle:
                kernel.CloseHandle(handle)

    def test_completed_job_is_not_reported_as_cancelled(self):
        job = self.start('complete')
        self.assertEqual(self.wait_for(job, 'done'), self.folder.name)
        self.assertFalse(job.cancel())

    def test_abrupt_worker_exit_is_reported_as_error(self):
        job = self.start('crash')
        self.assertIn('exit code 7', self.wait_for(job, 'error'))

    def test_worker_crash_cleans_up_child_holding_stdout_open(self):
        job = self.start('orphan-crash')
        self.assertIn('exit code 7', self.wait_for(job, 'error'))
        job.join(5)
        self.assertFalse(job.reader.is_alive())

    def test_real_worker_protocol_reports_errors_without_network_access(self):
        job = self.start('invalid-operation', real_worker=True)
        self.assertEqual(self.wait_for(job, 'error'), 'Unknown worker operation.')

    def audio_job(self, audio_format):
        try:
            binaries = Path(find_ffmpeg())
        except ValueError as exc:
            self.skipTest(str(exc))
        source = Path(self.folder.name) / 'source.webm'
        output = Path(self.folder.name) / 'output'
        output.mkdir()
        subprocess.run([str(binaries / 'ffmpeg.exe'), '-hide_banner', '-loglevel', 'error',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.2',
                        '-c:a', 'libopus', str(source)], check=True)
        opts = download_options(output, 'audio', None, str(binaries), audio_format)
        opts['enable_file_urls'] = True  # Local fixture only; never enabled in the application.
        job = WorkerJob({'operation': 'download', 'url': source.as_uri(),
                         'folder': str(output), 'options': opts})
        self.jobs.append(job)
        job.join(15)
        events = job.poll_events()
        self.assertIn(('done', str(output)), events)
        return binaries, source, output

    def test_original_audio_preserves_encoded_packets_exactly(self):
        binaries, source, output = self.audio_job('Original')

        def packets(path):
            result = subprocess.check_output([
                str(binaries / 'ffprobe.exe'), '-v', 'error', '-select_streams', 'a:0',
                '-show_packets', '-show_entries', 'packet=data_hash', '-show_data_hash', 'sha256',
                '-of', 'json', str(path)], text=True)
            return [packet['data_hash'] for packet in json.loads(result)['packets']]

        self.assertEqual(packets(source), packets(next(output.glob('*.opus'))))

    def test_explicit_mp3_choice_produces_mp3_audio(self):
        binaries, _source, output = self.audio_job('MP3')
        result = subprocess.check_output([
            str(binaries / 'ffprobe.exe'), '-v', 'error', '-select_streams', 'a:0',
            '-show_entries', 'stream=codec_name', '-of', 'json', str(next(output.glob('*.mp3')))], text=True)
        self.assertEqual(json.loads(result)['streams'][0]['codec_name'], 'mp3')


if __name__ == '__main__':
    unittest.main()
