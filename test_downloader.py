"""Offline regression tests. GUI tests exercise real Tk widgets with a fake backend."""
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from downloader import available_heights, download_options, readable_bytes, readable_time, validate_url


class DownloadPolicyTests(unittest.TestCase):
    def test_actual_resolutions_exclude_audio_and_drm(self):
        info = {'formats': [
            {'height': 720, 'vcodec': 'h264'}, {'height': 720, 'vcodec': 'vp9'},
            {'height': 1080, 'vcodec': 'av1'}, {'height': 2160, 'vcodec': 'av1', 'has_drm': True},
            {'vcodec': 'none'}, {'height': 144, 'vcodec': 'none'}]}
        self.assertEqual(available_heights(info), [1080, 720])

    def test_audio_selects_best_available_stream_and_combined_fallback(self):
        import yt_dlp
        opts = download_options('.', 'audio', None, 'ffmpeg')
        formats = [
            {'format_id': 'low', 'vcodec': 'none', 'acodec': 'aac', 'url': 'https://example.org/low'},
            {'format_id': 'high', 'vcodec': 'none', 'acodec': 'opus', 'url': 'https://example.org/high'},
            {'format_id': 'video', 'vcodec': 'h264', 'acodec': 'none', 'url': 'https://example.org/video'},
        ]
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            selector = ydl.build_format_selector(opts['format'])
            selected = list(selector({'formats': formats, 'has_merged_format': False, 'incomplete_formats': False}))
            self.assertEqual([f['format_id'] for f in selected], ['high'])
            combined = dict(formats[-1], format_id='combined', acodec='aac')
            selected = list(selector({'formats': [combined], 'has_merged_format': True, 'incomplete_formats': False}))
            self.assertEqual([f['format_id'] for f in selected], ['combined'])
        self.assertEqual(opts['postprocessors'], [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'best'}])

    def test_video_fallback_cannot_exceed_selected_resolution(self):
        import yt_dlp
        opts = download_options('.', 'video', '720', 'ffmpeg')
        formats = [
            {'format_id': 'low', 'height': 360, 'vcodec': 'h264', 'acodec': 'aac', 'url': 'https://example.org/low'},
            {'format_id': 'selected', 'height': 720, 'vcodec': 'h264', 'acodec': 'aac', 'url': 'https://example.org/selected'},
            {'format_id': 'high', 'height': 1080, 'vcodec': 'h264', 'acodec': 'aac', 'url': 'https://example.org/high'},
        ]
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            selector = ydl.build_format_selector(opts['format'])
            selected = list(selector({'formats': formats, 'has_merged_format': True, 'incomplete_formats': False}))
        self.assertEqual([f['format_id'] for f in selected], ['selected'])

    def test_validation_and_unknown_values(self):
        for url in ('', 'file:///tmp/test', 'not a link'):
            with self.assertRaises(ValueError):
                validate_url(url)
        self.assertEqual(validate_url(' https://example.org/video '), 'https://example.org/video')
        self.assertEqual(readable_time(3661), '1:01:01')
        self.assertEqual(readable_time(None), 'Unknown')
        self.assertEqual(readable_bytes(1024), '1.0 KiB')
        self.assertEqual(readable_bytes(None), 'Unknown')

    def test_mp3_is_an_explicit_conversion(self):
        opts = download_options('.', 'audio', None, 'ffmpeg', 'MP3')
        self.assertEqual(opts['postprocessors'][0]['preferredcodec'], 'mp3')
        self.assertEqual(opts['postprocessors'][0]['preferredquality'], '0')


class GuiTests(unittest.TestCase):
    def setUp(self):
        from main import DownloaderApp
        from pathlib import Path
        self.folder = tempfile.TemporaryDirectory(prefix='.test-gui-', dir=Path(__file__).resolve().parent)
        self.preferences_file = Path(self.folder.name) / 'settings.json'
        self.app = DownloaderApp(preferences_file=self.preferences_file)
        self.app.withdraw()
        self.errors = patch('main.messagebox.showerror').start()
        self.warnings = patch('main.messagebox.showwarning').start()
        self.requests = []
        self.app.folder.set(self.folder.name)
        self.app.url.set('https://example.org/video')

    def tearDown(self):
        # Tk/CustomTkinter schedule callbacks on the interpreter as well as
        # widgets; remove them before creating the next test's root window.
        try:
            for callback in self.app.tk.call('after', 'info'):
                self.app.tk.call('after', 'cancel', callback)
            self.app.destroy()
        except tk.TclError:
            pass
        self.folder.cleanup()
        patch.stopall()

    def pump(self):
        deadline = time.monotonic() + 4
        while self.app.busy and time.monotonic() < deadline:
            self.app.update()
            time.sleep(.01)
        self.assertFalse(self.app.busy, 'Worker did not finish')

    def backend(self, fail=False, block=False):
        requests = self.requests
        class FakeJob:
            def __init__(self, request):
                self.request = request
                self.cancelled = False
                self.finished = False
                requests.append(request)

            def cancel(self):
                self.cancelled = True
                return True

            def poll_events(self):
                if self.finished or (block and not self.cancelled):
                    return []
                self.finished = True
                if self.cancelled:
                    return [('cancelled', None)]
                if fail:
                    return [('error', 'Simulated network failure')]
                if self.request['operation'] == 'metadata':
                    return [('metadata', (self.request['url'], {'title': 'Example', 'formats': [
                        {'height': 2160, 'vcodec': 'h264'}, {'height': 720, 'vcodec': 'h264'}]}))]
                return [('progress', {'status': 'downloading', 'downloaded_bytes': 512,
                                      'total_bytes_estimate': 1024, 'speed': 256, 'eta': 2}),
                        ('processing', 'FFmpegExtractAudio'), ('done', self.request['folder'])]
        return patch.object(self.app, 'job_factory', FakeJob)

    def test_metadata_modes_and_url_invalidation(self):
        self.assertFalse(self.app.check_button.winfo_manager())
        self.assertFalse(self.app.video_frame.winfo_manager())
        self.app._mode_changed('Video (MKV)')
        self.assertEqual(self.app.check_button.winfo_manager(), 'grid')
        with self.backend():
            self.app.check_link()
            self.assertEqual(self.app.download_button.cget('state'), 'disabled')
            self.pump()
        self.assertEqual(self.app.video_menu.cget('values'), ['2160p', '720p'])
        self.app._mode_changed('Video (MKV)')
        self.assertEqual(self.app.download_button.cget('state'), 'normal')
        self.app.url.set('https://example.org/other')
        self.assertEqual(self.app.download_button.cget('state'), 'disabled')
        self.app._mode_changed('Audio')
        self.assertFalse(self.app.check_button.winfo_manager())
        self.assertEqual(self.app.download_button.cget('state'), 'normal')
        self.assertEqual(self.app.download_button.cget('text'), 'Download audio')

    def test_success_locks_controls_and_completes(self):
        with self.backend(), patch('main.find_ffmpeg', return_value='ffmpeg'):
            self.app.start_download()
            self.assertEqual(self.app.download_button.cget('state'), 'disabled')
            self.app.start_download()  # duplicate click must be ignored
            self.pump()
        self.assertEqual(self.app.progress.get(), 1)
        self.assertIn('Completed', self.app.status.cget('text'))
        self.assertEqual(self.app.download_button.cget('state'), 'normal')
        self.errors.assert_not_called()
        self.assertEqual(len(self.requests), 1)

    def test_failure_unlocks_controls(self):
        with self.backend(fail=True), patch('main.find_ffmpeg', return_value='ffmpeg'):
            self.app.start_download()
            self.pump()
        self.assertEqual(self.app.download_button.cget('state'), 'normal')
        self.errors.assert_called_once()

    def test_worker_start_failure_unlocks_controls(self):
        with patch.object(self.app, 'job_factory', side_effect=OSError('Simulated process launch failure')):
            self.app._mode_changed('Video (MKV)')
            self.app.check_link()
        self.assertFalse(self.app.busy)
        self.assertFalse(self.app.cancel_button.winfo_manager())
        self.assertEqual(self.app.check_button.cget('state'), 'normal')
        self.errors.assert_called_once()

    def test_progress_statistics_and_fullscreen(self):
        self.app.started = time.monotonic() - 5
        self.app._show_progress({'status': 'downloading', 'downloaded_bytes': 512,
                                 'total_bytes_estimate': 1024, 'speed': 256, 'eta': 2})
        self.assertEqual(self.app.progress.get(), .5)
        self.assertIn('estimated', self.app.status.cget('text'))
        self.assertIn('256.0 B/s', self.app.stats.cget('text'))
        self.assertIn('0:00:02', self.app.stats.cget('text'))
        self.app._show_progress({'status': 'downloading', 'downloaded_bytes': 10})
        self.assertIn('unknown', self.app.status.cget('text'))
        self.app.toggle_fullscreen()
        self.assertTrue(self.app.fullscreen)
        self.app.exit_fullscreen()
        self.assertFalse(self.app.fullscreen)

    def test_cancel_unlocks_only_after_worker_exits_and_allows_retry(self):
        with self.backend(block=True), patch('main.find_ffmpeg', return_value='ffmpeg'):
            self.app.start_download()
            self.assertTrue(self.app.busy)
            self.app.cancel_download()
            self.assertTrue(self.app.busy)
            self.assertEqual(self.app.cancel_button.cget('state'), 'disabled')
            self.pump()
        self.assertEqual(self.app.status.cget('text'), 'Cancelled')
        self.assertEqual(self.app.download_button.cget('state'), 'normal')
        self.assertFalse(self.app.cancel_button.winfo_manager())
        with self.backend(), patch('main.find_ffmpeg', return_value='ffmpeg'):
            self.app.start_download()
            self.pump()
        self.assertIn('Completed', self.app.status.cget('text'))
        self.errors.assert_not_called()

    def test_preferences_survive_restart_without_stale_metadata(self):
        from main import DownloaderApp
        self.app._mode_changed('Video (MKV)')
        self.app.audio_format.set('MP3')
        self.app.appearance.set('Dark')
        self.app.change_theme()
        self.app._video_quality_changed('1080p')
        # Dispose interpreter callbacks before constructing the next Tk root.
        for callback in self.app.tk.call('after', 'info'):
            self.app.tk.call('after', 'cancel', callback)
        self.app.close()
        self.app = DownloaderApp(preferences_file=self.preferences_file)
        self.app.withdraw()
        self.assertEqual(self.app.folder.get(), self.folder.name)
        self.assertEqual(self.app.media.get(), 'video')
        self.assertEqual(self.app.audio_format.get(), 'MP3')
        self.assertEqual(self.app.appearance.get(), 'Dark')
        self.assertEqual(self.app.url.get(), '')
        self.assertEqual(self.app.download_button.cget('state'), 'disabled')
        self.app.url.set('https://example.org/other')
        with self.backend():
            self.app.check_link()
            self.pump()
        self.assertEqual(self.app.video_quality.get(), '720p')
        self.assertEqual(self.app.preferred_video_height, 1080)

    def test_close_cancels_active_operation(self):
        with self.backend(block=True), patch('main.find_ffmpeg', return_value='ffmpeg'):
            self.app.start_download()
            self.app.close()
            self.assertTrue(self.app.closing)
            self.assertTrue(self.app.cancelling)
            self.pump()
        self.errors.assert_not_called()


if __name__ == '__main__':
    unittest.main()
