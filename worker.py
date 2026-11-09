"""JSON-lines worker protocol. Runs without importing or accessing Tk widgets."""
import contextlib
import ctypes
import json
import os
import sys
import time


def run(request, emit):
    import yt_dlp
    from yt_dlp.postprocessor.ffmpeg import FFmpegExtractAudioPP
    from yt_dlp.utils import PostProcessingError

    class OriginalAudioPP(FFmpegExtractAudioPP):
        def run_ffmpeg(self, path, out_path, codec, more_opts):
            if codec != 'copy':
                raise PostProcessingError('This audio codec cannot be extracted without conversion. '
                                          'Select MP3 to convert it, or keep the downloaded source file.')
            return super().run_ffmpeg(path, out_path, codec, more_opts)

    opts = dict(request['options'])
    last_progress = 0

    def progress(data):
        nonlocal last_progress
        now = time.monotonic()
        if data.get('status') != 'finished' and now - last_progress < .1:
            return
        last_progress = now
        emit('progress', {key: data.get(key) for key in (
            'status', 'downloaded_bytes', 'total_bytes', 'total_bytes_estimate', 'speed', 'eta')})

    def processing(data):
        emit('processing', data.get('postprocessor', 'media'))

    opts.update(progress_hooks=[progress], postprocessor_hooks=[processing])
    original = any(pp.get('key') == 'FFmpegExtractAudio' and pp.get('preferredcodec') == 'best'
                   for pp in opts.get('postprocessors', []))
    if original:
        opts['postprocessors'] = [pp for pp in opts['postprocessors']
                                  if pp.get('key') != 'FFmpegExtractAudio']
    with yt_dlp.YoutubeDL(opts) as ydl:
        if request['operation'] == 'metadata':
            info = ydl.extract_info(request['url'], download=False)
            if not info or info.get('_type') in ('playlist', 'multi_video'):
                raise ValueError('Enter a single video link, not a playlist.')
            if info.get('is_live'):
                raise ValueError('Live streams are not supported by this app.')
            emit('metadata', (request['url'], {
                'title': info.get('title', 'Untitled video'),
                'formats': [{key: f.get(key) for key in ('height', 'vcodec', 'has_drm')}
                            for f in info.get('formats', [])],
            }))
        elif request['operation'] == 'download':
            if original:
                ydl.add_post_processor(OriginalAudioPP(ydl, preferredcodec='best'))
            if ydl.download([request['url']]):
                raise RuntimeError('The downloader reported a failure. Please retry.')
            emit('done', request['folder'])
        else:
            raise ValueError('Unknown worker operation.')


def main():
    _restore_standard_streams()
    output = sys.stdout

    def emit(event, payload):
        output.write(json.dumps([event, payload], ensure_ascii=True) + '\n')
        output.flush()

    try:
        # The parent assigns this process to its kill-on-close job before
        # sending the request, so FFmpeg cannot start outside that job.
        request = json.loads(sys.stdin.readline())
        with contextlib.redirect_stdout(sys.stderr):
            run(request, emit)
    except Exception as exc:
        emit('error', str(exc))


def _restore_standard_streams():
    """Reopen inherited pipes when this is a windowed PyInstaller worker."""
    if os.name != 'nt' or all(getattr(sys, name, None) is not None
                              for name in ('stdin', 'stdout', 'stderr')):
        return

    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    get_std_handle = kernel32.GetStdHandle
    get_std_handle.argtypes = [wintypes.DWORD]
    get_std_handle.restype = wintypes.HANDLE
    invalid_handle = ctypes.c_void_p(-1).value
    specs = (
        ('stdin', -10, 'r', os.O_RDONLY),
        ('stdout', -11, 'w', os.O_WRONLY),
        ('stderr', -12, 'w', os.O_WRONLY),
    )
    for name, std_handle, mode, flags in specs:
        if getattr(sys, name, None) is not None:
            continue
        handle = get_std_handle(std_handle & 0xFFFFFFFF)
        if handle in (None, 0, invalid_handle):
            raise OSError(ctypes.get_last_error(), f'No inherited {name} handle is available.')
        descriptor = msvcrt.open_osfhandle(int(handle), flags | os.O_BINARY)
        stream = os.fdopen(descriptor, mode, encoding='utf-8', buffering=1 if mode == 'w' else -1)
        setattr(sys, name, stream)


if __name__ == '__main__':
    main()
