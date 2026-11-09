"""Responsive CustomTkinter interface. Run with python main.py."""
import sys

if __name__ == '__main__' and '--download-worker' in sys.argv:
    from worker import main as worker_main
    worker_main()
    raise SystemExit

from pathlib import Path
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import filedialog, messagebox

import customtkinter as ctk

from downloader import (available_heights, download_options, find_ffmpeg,
                        readable_bytes, readable_time, validate_url)
from jobs import WorkerJob
from preferences import load_preferences, preferences_path, save_preferences


class AutoHideScrollableFrame(ctk.CTkScrollableFrame):
    """Keep scrolling available without reserving space when content fits.

    CustomTkinter exposes no auto-hide option; keep its canvas/scrollbar
    integration isolated here.
    """
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._scrollbar.grid_remove()
        self._parent_canvas.configure(yscrollcommand=self._update_scrollbar)

    def _update_scrollbar(self, first, last):
        self._scrollbar.set(first, last)
        overflowing = self.winfo_reqheight() > self._parent_canvas.winfo_height()
        visible = bool(self._scrollbar.winfo_manager())
        if overflowing and not visible:
            self._scrollbar.grid()
        elif not overflowing and visible:
            self._scrollbar.grid_remove()
            self._parent_canvas.yview_moveto(0)


class SelectableText(ctk.CTkTextbox):
    """Read-only, wrapping text with standard selection and clipboard actions."""
    def __init__(self, master, text='', **kwargs):
        super().__init__(master, height=28, corner_radius=0, border_width=0,
                         border_spacing=0, fg_color='transparent',
                         activate_scrollbars=False, wrap='word', padx=0, pady=4,
                         cursor='xterm', takefocus=True, exportselection=False,
                         **kwargs)
        self._text = None
        self._resize_pending = False
        self._textbox.configure(selectbackground='#A63535', selectforeground='white',
                                inactiveselectbackground='#A63535')
        self._textbox.bind('<Configure>', self._schedule_resize, add='+')
        self._textbox.bind('<Control-a>', self._select_all)
        self._textbox.bind('<Control-c>', self._copy)
        self._textbox.bind('<Control-Insert>', self._copy)
        self._menu = tk.Menu(self, tearoff=False)
        self._menu.add_command(label='Copy', command=self._copy)
        self._menu.add_command(label='Select all', command=self._select_all)
        self._textbox.bind('<Button-3>', self._show_menu)
        self._style_menu()
        self.configure(text=text)

    def _style_menu(self):
        colors = ctk.ThemeManager.theme['DropdownMenu']
        self._menu.configure(
            background=self._apply_appearance_mode(colors['fg_color']),
            foreground=self._apply_appearance_mode(colors['text_color']),
            activebackground=self._apply_appearance_mode(colors['hover_color']),
            activeforeground=self._apply_appearance_mode(colors['text_color']), borderwidth=0)

    def _set_appearance_mode(self, mode_string):
        super()._set_appearance_mode(mode_string)
        if hasattr(self, '_menu'):
            self._style_menu()

    def configure(self, **kwargs):
        text = kwargs.pop('text', None)
        super().configure(**kwargs)
        if text is not None and text != self._text:
            self._text = text
            super().configure(state='normal')
            self.delete('1.0', 'end')
            self.insert('1.0', text)
            super().configure(state='disabled')
            self._schedule_resize()

    def cget(self, name):
        return self._text if name == 'text' else super().cget(name)

    def _schedule_resize(self, _event=None):
        if not self._resize_pending:
            self._resize_pending = True
            self.after_idle(self._fit_height)

    def _fit_height(self):
        self._resize_pending = False
        if self._textbox.winfo_width() <= 1:
            return
        count = self._textbox.count('1.0', 'end-1c', 'displaylines')
        lines = (count[0] if count else 0) + 1
        font = tkfont.Font(root=self, font=self._textbox.cget('font'))
        height = max(28, (lines * font.metrics('linespace') + 8) / self._get_widget_scaling())
        if abs(self.cget('height') - height) > .5:
            super().configure(height=height)

    def _select_all(self, _event=None):
        self._textbox.focus_set()
        self.tag_add('sel', '1.0', 'end-1c')
        return 'break'

    def _copy(self, _event=None):
        selected = self._textbox.tag_ranges('sel')
        text = self.get(*selected) if selected else self._text
        self.clipboard_clear()
        self.clipboard_append(text)
        return 'break'

    def _show_menu(self, event):
        self._textbox.focus_set()
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()


class DownloaderApp(ctk.CTk):
    def __init__(self, preferences_file=None, job_factory=WorkerJob):
        self.preferences_file = Path(preferences_file) if preferences_file is not None else preferences_path()
        self.preferences = load_preferences(self.preferences_file)
        ctk.set_default_color_theme(str(Path(__file__).with_name('youtube_theme.json')))
        ctk.set_appearance_mode(self.preferences.appearance)
        super().__init__()
        self.title('YouTube Media Downloader')
        self.iconbitmap(str(Path(__file__).with_name('yt_download.ico')))
        self.geometry('860x650')
        self.minsize(680, 600)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.busy = False
        self.info = None
        self.checked_url = None
        self.job_factory = job_factory
        self.job = None
        self.cancelling = False
        self.closing = False
        self.save_after = None
        self.preference_error_shown = False
        self.preferred_video_height = self.preferences.video_height
        self.started = None
        self.fullscreen = False
        self.url = tk.StringVar()
        self.folder = tk.StringVar(value=self.preferences.output_folder)
        self.media = tk.StringVar(value=self.preferences.media)
        self.audio_format = tk.StringVar(value=self.preferences.audio_format)
        self.appearance = tk.StringVar(value=self.preferences.appearance)
        self.video_quality = tk.StringVar(value='Check link first')
        self._build_ui()
        self.url.trace_add('write', self._url_changed)
        for variable in (self.folder, self.media, self.audio_format, self.appearance):
            variable.trace_add('write', self._schedule_preferences)
        self.bind('<F11>', self.toggle_fullscreen)
        self.bind('<Escape>', self.exit_fullscreen)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self._poll)

    def _build_ui(self):
        self.ui_font = ctk.CTkFont(family='Segoe UI', size=14)
        body = AutoHideScrollableFrame(self, fg_color='transparent')
        body.grid(row=0, column=0, sticky='nsew', padx=28, pady=20)
        body.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(body, fg_color='transparent')
        header.grid(row=0, column=0, sticky='ew')
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text='Media Downloader', font=ctk.CTkFont(family='Segoe UI', size=28, weight='bold')).grid(row=0, column=0, sticky='w')
        self.theme_switch = ctk.CTkSwitch(header, text='Dark mode', variable=self.appearance,
                                         onvalue='Dark', offvalue='Light',
                                         command=self.change_theme, font=self.ui_font)
        self.theme_switch.grid(row=0, column=1, padx=(16, 0), sticky='e')
        SelectableText(body, text='Paste a video link to get started.', font=self.ui_font).grid(row=1, column=0, sticky='ew', pady=(0, 14))
        link = ctk.CTkFrame(body, fg_color='transparent')
        link.grid(row=2, column=0, sticky='ew')
        link.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(link, textvariable=self.url, placeholder_text='Video URL', height=38)
        self.url_entry.grid(row=0, column=0, sticky='ew', padx=(0, 10))
        self.check_button = ctk.CTkButton(link, text='Check link', width=110, command=self.check_link)
        self.check_button.grid(row=0, column=1)
        self.title_label = SelectableText(body, text='No video selected', font=self.ui_font)
        self.title_label.grid(row=3, column=0, sticky='ew', pady=(8, 12))
        self.mode_switch = ctk.CTkSegmentedButton(body, values=['Audio', 'Video (MKV)'], command=self._mode_changed)
        self.mode_switch.set('Audio')
        self.mode_switch.grid(row=4, column=0, sticky='w', pady=(0, 12))
        self.audio_frame = ctk.CTkFrame(body)
        self.audio_frame.grid(row=5, column=0, sticky='ew')
        ctk.CTkLabel(self.audio_frame, text='Format').pack(side='left', padx=12, pady=12)
        self.audio_menu = ctk.CTkOptionMenu(self.audio_frame, values=['Original', 'MP3'], variable=self.audio_format)
        self.audio_menu.pack(side='left', padx=12)
        self.video_frame = ctk.CTkFrame(body)
        self.video_frame.grid(row=5, column=0, sticky='ew')
        ctk.CTkLabel(self.video_frame, text='Resolution').pack(side='left', padx=12, pady=12)
        self.video_menu = ctk.CTkOptionMenu(self.video_frame, values=['Check link first'], variable=self.video_quality,
                                          command=self._video_quality_changed, state='disabled')
        self.video_menu.pack(side='left', padx=12)
        self.video_frame.grid_remove()
        self.hint = SelectableText(body, text='Check the link, choose a video quality, then download.', font=self.ui_font)
        self.hint.grid(row=6, column=0, sticky='ew', pady=(4, 12))
        ctk.CTkLabel(body, text='Save to', anchor='w').grid(row=7, column=0, sticky='w')
        output = ctk.CTkFrame(body, fg_color='transparent')
        output.grid(row=8, column=0, sticky='ew', pady=(4, 18))
        output.grid_columnconfigure(0, weight=1)
        self.folder_entry = ctk.CTkEntry(output, textvariable=self.folder)
        self.folder_entry.grid(row=0, column=0, sticky='ew', padx=(0, 10))
        self.browse_button = ctk.CTkButton(output, text='Browse', width=110, command=self.browse)
        self.browse_button.grid(row=0, column=1)
        self.status = SelectableText(body, text='Ready', font=self.ui_font)
        self.status.grid(row=9, column=0, sticky='ew')
        self.progress = ctk.CTkProgressBar(body)
        self.progress.grid(row=10, column=0, sticky='ew', pady=8)
        self.progress.set(0)
        self.stats = SelectableText(body, text='Speed: —   |   ETA: —   |   Elapsed: —', font=self.ui_font)
        self.stats.grid(row=11, column=0, sticky='ew')
        actions = ctk.CTkFrame(body, fg_color='transparent')
        actions.grid(row=12, column=0, sticky='ew', pady=(16, 10))
        actions.grid_columnconfigure(0, weight=1)
        self.download_button = ctk.CTkButton(actions, text='Download audio', height=40, command=self.start_download)
        self.download_button.grid(row=0, column=0, sticky='ew')
        self.cancel_button = ctk.CTkButton(actions, text='Cancel', width=100, height=40, command=self.cancel_download)
        self.cancel_button.grid(row=0, column=1, padx=(10, 0))
        ctk.CTkButton(body, text='Fullscreen (F11)', command=self.toggle_fullscreen,
                      fg_color='transparent', text_color=('#A63535', '#DF9393'),
                      hover_color=('#F4E5E5', '#382828'),
                      border_color=('#A63535', '#DF9393'), border_width=1).grid(row=13, column=0, sticky='e')
        for entry in (self.url_entry, self.folder_entry):
            entry._entry.configure(selectbackground='#A63535', selectforeground='white')
        self._mode_changed('Audio' if self.preferences.media == 'audio' else 'Video (MKV)')

    def change_theme(self):
        ctk.set_appearance_mode(self.appearance.get())

    def _schedule_preferences(self, *_):
        if self.save_after is not None:
            self.after_cancel(self.save_after)
        self.save_after = self.after(400, self._persist_preferences)

    def _persist_preferences(self):
        if self.save_after is not None:
            self.after_cancel(self.save_after)
            self.save_after = None
        self.preferences.output_folder = self.folder.get()
        self.preferences.media = self.media.get()
        self.preferences.audio_format = self.audio_format.get()
        self.preferences.appearance = self.appearance.get()
        self.preferences.video_height = self.preferred_video_height
        try:
            save_preferences(self.preferences_file, self.preferences)
            self.preference_error_shown = False
        except OSError as exc:
            if not self.preference_error_shown:
                self.preference_error_shown = True
                messagebox.showwarning('Preferences not saved', f'Could not save settings: {exc}', parent=self)

    def _video_quality_changed(self, value):
        self.preferred_video_height = int(value.removesuffix('p'))
        self._schedule_preferences()

    def _mode_changed(self, value):
        self.mode_switch.set(value)
        self.media.set('audio' if value == 'Audio' else 'video')
        if self.media.get() == 'audio':
            self.audio_frame.grid()
            self.video_frame.grid_remove()
            self.check_button.grid_remove()
            self.title_label.grid_remove()
            self.url_entry.grid_configure(padx=0)
            self.hint.grid_remove()
        else:
            self.audio_frame.grid_remove()
            self.check_button.grid()
            self.title_label.grid()
            self.url_entry.grid_configure(padx=(0, 10))
            self.video_frame.grid()
            self.hint.grid()
        self._refresh_controls()

    def _url_changed(self, *_):
        self.info = None
        self.checked_url = None
        self.video_quality.set('Check link first')
        self.video_menu.configure(values=['Check link first'])
        self.title_label.configure(text='No video selected')
        self._refresh_controls()

    def _refresh_controls(self):
        state = 'disabled' if self.busy else 'normal'
        for widget in (self.url_entry, self.check_button, self.folder_entry,
                       self.browse_button, self.mode_switch, self.audio_menu):
            widget.configure(state=state)
        # CustomTkinter shares one text color across both tabs by default.
        # Keep white text on the selected red tab and dark text on light gray.
        for value, button in self.mode_switch._buttons_dict.items():
            button.configure(text_color=('#FFFFFF', '#FFFFFF') if value == self.mode_switch.get()
                             else ('#0F0F0F', '#F1F1F1'))
        has_video = bool(self.info and available_heights(self.info))
        self.video_menu.configure(state='normal' if has_video and not self.busy else 'disabled')
        can_download = not self.busy and (self.media.get() == 'audio' or has_video)
        self.download_button.configure(state='normal' if can_download else 'disabled',
                                       fg_color=('#C33F3F', '#C33F3F') if can_download else ('#D6D6D6', '#343434'),
                                       text='Download audio' if self.media.get() == 'audio' else 'Download video')
        if self.busy:
            self.cancel_button.grid()
            self.cancel_button.configure(state='disabled' if self.cancelling else 'normal')
        else:
            self.cancel_button.grid_remove()

    def _set_busy(self, value):
        self.busy = value
        self._refresh_controls()

    def browse(self):
        folder = filedialog.askdirectory(parent=self, initialdir=self.folder.get())
        if folder:
            self.folder.set(folder)

    def _launch(self, request):
        # Lock controls before starting the worker to prevent duplicate jobs.
        self.cancelling = False
        self._set_busy(True)
        try:
            self.job = self.job_factory(request)
        except Exception as exc:
            self.progress.stop()
            self.progress.configure(mode='determinate')
            self.progress.set(0)
            self._set_busy(False)
            self.status.configure(text='Could not start the download worker. You can retry.')
            messagebox.showerror('Worker error', str(exc), parent=self)

    def cancel_download(self):
        if not self.busy or self.job is None or self.cancelling:
            return
        try:
            cancelled = self.job.cancel()
        except OSError as exc:
            self.closing = False
            messagebox.showerror('Cannot cancel', str(exc), parent=self)
            return
        if cancelled:
            self.cancelling = True
            self.status.configure(text='Cancelling…')
            self.stats.configure(text='Stopping the download and media processing…')
            self._refresh_controls()

    def check_link(self):
        if self.busy or self.media.get() != 'video':
            return
        try:
            url = validate_url(self.url.get())
        except ValueError as exc:
            messagebox.showerror('Invalid URL', str(exc), parent=self)
            return
        self.status.configure(text='Checking available formats…')
        self.progress.configure(mode='indeterminate')
        self.progress.start()

        self._launch({'operation': 'metadata', 'url': url,
                      'options': {'quiet': True, 'noplaylist': True, 'socket_timeout': 20}})

    def start_download(self):
        if self.busy:
            return
        try:
            url = validate_url(self.url.get())
            if not self.folder.get().strip():
                raise ValueError('Choose an output folder.')
            folder = Path(self.folder.get()).expanduser()
            if not folder.is_dir():
                raise ValueError('Choose an existing output folder.')
            if self.media.get() == 'video' and (self.checked_url != url or not self.info):
                raise ValueError('Check this link before choosing a video resolution.')
            quality = self.video_quality.get().removesuffix('p') if self.media.get() == 'video' else None
            opts = download_options(folder, self.media.get(), quality, find_ffmpeg(), self.audio_format.get())
        except (ValueError, OSError) as exc:
            messagebox.showerror('Cannot download', str(exc), parent=self)
            return
        self.started = time.monotonic()
        self.progress.set(0)
        self.status.configure(text='Preparing download…')
        self.stats.configure(text='Speed: —   |   ETA: —   |   Elapsed: 0:00:00')
        self._persist_preferences()
        self._launch({'operation': 'download', 'url': url, 'folder': str(folder), 'options': opts})

    def _show_progress(self, data):
        downloaded = data.get('downloaded_bytes') or 0
        total = data.get('total_bytes') or data.get('total_bytes_estimate')
        self.progress.stop()
        if data.get('status') == 'finished':
            self.progress.configure(mode='indeterminate')
            self.progress.start()
            self.status.configure(text='Stream downloaded. Preparing next stream or processing media…')
        elif total:
            self.progress.configure(mode='determinate')
            self.progress.set(min(downloaded / total, 1))
            estimate = ' (estimated)' if not data.get('total_bytes') else ''
            self.status.configure(text=f'Current stream: {downloaded / total:.0%} — {readable_bytes(downloaded)} / {readable_bytes(total)}{estimate}')
        else:
            self.progress.configure(mode='indeterminate')
            self.progress.start()
            self.status.configure(text=f'Current stream: {readable_bytes(downloaded)} downloaded — total size unknown')
        speed = readable_bytes(data.get('speed')) + '/s' if data.get('speed') is not None else 'Unknown'
        self.stats.configure(text=f'Speed: {speed}   |   Stream ETA: {readable_time(data.get("eta"))}   |   Elapsed: {readable_time(time.monotonic() - self.started)}')

    def _poll(self):
        for event, payload in self.job.poll_events() if self.job is not None else []:
            if event == 'progress':
                if not self.cancelling:
                    self._show_progress(payload)
                continue
            if event == 'processing':
                if not self.cancelling:
                    self.progress.stop()
                    self.progress.configure(mode='indeterminate')
                    self.progress.start()
                    self.status.configure(text=f'Processing: {payload}…')
                    self.stats.configure(text='Processing media. Remaining time unavailable.')
                continue
            self.progress.stop()
            self.progress.configure(mode='determinate')
            self.job = None  # Terminal events arrive only after process-tree cleanup.
            self.cancelling = False
            self._set_busy(False)
            if event == 'metadata':
                self.checked_url, self.info = payload
                heights = available_heights(self.info)
                values = [f'{height}p' for height in heights] or ['No video available']
                self.video_menu.configure(values=values)
                chosen = next((height for height in heights if height <= self.preferred_video_height), heights[-1]) \
                    if heights and self.preferred_video_height is not None else (heights[0] if heights else None)
                self.video_quality.set(f'{chosen}p' if chosen is not None else values[0])
                self.title_label.configure(text=self.info.get('title', 'Untitled video'))
                self.status.configure(text='Ready to download')
                self.progress.set(0)
                self._refresh_controls()
            elif event == 'done':
                self.progress.set(1)
                self.status.configure(text=f'Completed — saved to {payload}')
                self.stats.configure(text=f'Finished in {readable_time(time.monotonic() - self.started)}')
            elif event == 'cancelled':
                self.progress.set(0)
                self.status.configure(text='Cancelled')
                self.stats.configure(text='Partial files are kept so the download can resume on retry.')
            elif event == 'error':
                self.progress.set(0)
                self.status.configure(text='Operation failed. You can retry.')
                self.stats.configure(text='Speed: —   |   ETA: —   |   Elapsed: —')
                if not self.closing:
                    messagebox.showerror('Download error', payload, parent=self)
        if self.closing and not self.busy:
            self.destroy()
            return
        self.after(100, self._poll)

    def toggle_fullscreen(self, _event=None):
        self.fullscreen = not self.fullscreen
        self.attributes('-fullscreen', self.fullscreen)

    def exit_fullscreen(self, _event=None):
        self.fullscreen = False
        self.attributes('-fullscreen', False)

    def close(self):
        self._persist_preferences()
        if self.busy:
            self.closing = True
            self.cancel_download()
            return
        self.destroy()


if __name__ == '__main__':
    DownloaderApp().mainloop()
