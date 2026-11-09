"""Validated, portable application preferences. No download URLs are stored."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
import tempfile


@dataclass
class Preferences:
    output_folder: str = str(Path.home() / 'Downloads')
    media: str = 'audio'
    audio_format: str = 'Original'
    appearance: str = 'Light'
    video_height: int | None = None


def preferences_path():
    root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    return root / 'preferences.json'


def load_preferences(path):
    result = Preferences()
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError):
        return result
    if not isinstance(data, dict):
        return result
    folder = data.get('output_folder')
    if isinstance(folder, str) and folder.strip() and '\0' not in folder:
        result.output_folder = folder
    for key, choices in (('media', ('audio', 'video')), ('audio_format', ('Original', 'MP3')),
                         ('appearance', ('Light', 'Dark'))):
        if data.get(key) in choices:
            setattr(result, key, data[key])
    height = data.get('video_height')
    if type(height) is int and 0 < height <= 16384:
        result.video_height = height
    return result


def save_preferences(path, preferences):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=f'.{path.name}.', suffix='.tmp', delete=False) as file:
            temporary = Path(file.name)
            json.dump(asdict(preferences), file, indent=2)
            file.write('\n')
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
