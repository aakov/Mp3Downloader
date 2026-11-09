"""Download policy and formatting helpers, independent of the GUI."""
from pathlib import Path
import shutil
import sys
from urllib.parse import urlparse


def validate_url(url):
    parsed = urlparse(url.strip())
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Enter a valid http:// or https:// video URL.')
    return url.strip()


def available_heights(info):
    return sorted({int(f['height']) for f in info.get('formats', [])
                   if f.get('height') and f.get('vcodec') not in (None, 'none')
                   and not f.get('has_drm')}, reverse=True)


def find_ffmpeg():
    roots = [Path(__file__).resolve().parent]
    if getattr(sys, 'frozen', False):
        roots.insert(0, Path(sys.executable).parent)
    for root in roots:
        for folder in [root / 'ffmpeg' / 'bin', *sorted(root.glob('ffmpeg-*/bin'))]:
            if (folder / 'ffmpeg.exe').is_file() and (folder / 'ffprobe.exe').is_file():
                return str(folder)
    executable = shutil.which('ffmpeg')
    if executable and shutil.which('ffprobe'):
        return str(Path(executable).parent)
    raise ValueError('FFmpeg and FFprobe are required. Add them to PATH or place them in ffmpeg/bin beside the app.')


def download_options(folder, media, quality, ffmpeg_location, audio_format='Original'):
    opts = {
        'outtmpl': str(Path(folder) / '%(title).180B [%(id)s].%(ext)s'),
        'noplaylist': True, 'quiet': True,
        'ffmpeg_location': ffmpeg_location, 'windowsfilenames': True,
        'socket_timeout': 20,
    }
    if media == 'audio':
        if audio_format not in ('Original', 'MP3'):
            raise ValueError('Choose Original or MP3 audio.')
        opts.update(format='bestaudio/best', postprocessors=[{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'best' if audio_format == 'Original' else 'mp3',
        }])
        if audio_format == 'MP3':
            opts['postprocessors'][0]['preferredquality'] = '0'
    elif media == 'video':
        height = int(quality)
        if height <= 0:
            raise ValueError('Choose a video resolution.')
        opts['format'] = f'bestvideo[height={height}]+bestaudio/best[height={height}][acodec!=none]'
        opts['merge_output_format'] = 'mkv'
    else:
        raise ValueError('Choose audio or video.')
    return opts


def readable_bytes(value):
    if value is None:
        return 'Unknown'
    value = max(0, float(value))
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024 or unit == 'TiB':
            return f'{value:.1f} {unit}'
        value /= 1024


def readable_time(seconds):
    if seconds is None:
        return 'Unknown'
    seconds = max(0, int(seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f'{hours:d}:{minutes:02d}:{seconds:02d}'
