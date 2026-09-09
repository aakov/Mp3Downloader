import os
import tkinter.messagebox

import customtkinter as ctk
from tkinter import filedialog, StringVar, IntVar
import yt_dlp as youtube_dl
import ffmpeg
from tqdm import tqdm


class TqdmLogger(tqdm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_n = 0

    def update_to(self, n):
        delta = n - self.last_n
        self.last_n = n
        self.update(delta)

def download_youtube_audio(url, output_path, audio_quality):
    if not output_path_entry.get().strip():
        tkinter.messagebox.showerror("Error", "Please select an output path.")
        return
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }],
        'ffmpeg_location': 'ffmpeg-N-116328-gfa5a605542-win64-gpl/bin/ffmpeg.exe',
        'noplaylist': True,
        'progress_hooks': [lambda d: update_progress_bar(d)],
    }
    try:
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        tkinter.messagebox.showinfo("Success","Audio download completed successfully.")
        progress_bar.set(1.0)
        progress_bar.set(0.0)
    except Exception as e:
        tkinter.messagebox.showerror("Error", f"An error occurred during audio download: {e}")

def download_youtube_video(url, output_path, video_quality):
    if output_path_entry.get() == None:
        tkinter.messagebox.showerror("Error", "Please select an output path.")
        return
    ydl_opts = {
        'format': f'bestvideo[height<={video_quality}]+bestaudio/best',
        'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
        'noplaylist': True,
        'ffmpeg_location': 'ffmpeg-N-116328-gfa5a605542-win64-gpl/bin/ffmpeg.exe',
        'progress_hooks': [lambda d: update_progress_bar(d)],
    }
    try:
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        tkinter.messagebox.showinfo("Success","Video download completed successfully.")
        progress_bar.set(1.0)
        progress_bar.set(0.0)
    except youtube_dl.utils.DownloadError as e:
        if 'ffmpeg' in str(e):
            tkinter.messagebox.showerror("Error","FFmpeg is required for this operation. Please ensure FFmpeg is installed and available in your system's PATH.")
        else:
            tkinter.messagebox.showerror("Error",f"An error occurred during video download: {e}")
    except Exception as e:
        tkinter.messagebox.showerror("Error",f"An error occurred: {e}")


def update_progress_bar(d):
    if d['status'] == 'downloading':
        total_bytes = d.get('total_bytes')
        downloaded_bytes = d.get('downloaded_bytes')
        if total_bytes and downloaded_bytes:

            progress_bar.set((downloaded_bytes / total_bytes))
            app.update_idletasks()
            app.update()
            # print("updated")

def browse_output_path():
    path = filedialog.askdirectory()
    output_path_entry.configure(state="normal")
    output_path_entry.delete(0, ctk.END)
    output_path_entry.insert(0, path)
    output_path_entry.configure(state="readonly")

def start_download():
    url = url_entry.get()
    output_path = output_path_entry.get()
    media_type = media_type_var.get()
    video_quality = video_quality_var.get()
    audio_quality = audio_quality_var.get()
    if media_type == 'audio':
        download_youtube_audio(url, output_path, audio_quality)
    elif media_type == 'video':
        download_youtube_video(url, output_path, video_quality)

def clear_url():
    url_entry.delete(0, ctk.END)
# Initialize the GUI
app = ctk.CTk()
app.title("YouTube Media Downloader")

# app.iconbitmap("yt_download.ico")

# URL Entry
ctk.CTkLabel(app, text="YouTube URL:").grid(row=0, column=0, padx=10, pady=10)
url_entry = ctk.CTkEntry(app, width=300)
url_entry.grid(row=0, column=1, padx=10, pady=10)

# Output Path Entry
ctk.CTkLabel(app, text="Output Path:").grid(row=1, column=0, padx=10, pady=10)
output_path_entry = ctk.CTkEntry(app, width=300)
output_path_entry.grid(row=1, column=1, padx=10, pady=10)
output_path_entry.configure(state="readonly")

clear_button = ctk.CTkButton(app, text="Clear", command=clear_url)
clear_button.grid(row=0, column=2, padx=10, pady=10)
browse_button = ctk.CTkButton(app, text="Browse", command=browse_output_path)
browse_button.grid(row=1, column=2, padx=10, pady=10)

# Media Type Selection
ctk.CTkLabel(app, text="Media Type:").grid(row=2, column=0, padx=10, pady=10)
media_type_var = StringVar(value='audio')
audio_radio = ctk.CTkRadioButton(app, text="Audio", variable=media_type_var, value='audio')
audio_radio.grid(row=2, column=1, padx=10, pady=10)
video_radio = ctk.CTkRadioButton(app, text="Video", variable=media_type_var, value='video')
video_radio.grid(row=2, column=2, padx=10, pady=10)

# Audio Quality Selection
ctk.CTkLabel(app, text="Audio Quality:").grid(row=3, column=0, padx=10, pady=10)
audio_quality_var = StringVar(value='320')
audio_quality_options = ["128", "192", "256", "320"]
audio_quality_menu = ctk.CTkOptionMenu(app, variable=audio_quality_var, values=audio_quality_options)
audio_quality_menu.grid(row=3, column=1, padx=10, pady=10)

# Video Quality Selection
ctk.CTkLabel(app, text="Video Quality:").grid(row=4, column=0, padx=10, pady=10)
video_quality_var = StringVar(value='1080')
quality_options = ["144", "240", "360", "480", "720", "1080", "1440", "2160"]
video_quality_menu = ctk.CTkOptionMenu(app, variable=video_quality_var, values=quality_options)
video_quality_menu.grid(row=4, column=1, padx=10, pady=10)


progress_bar = ctk.CTkProgressBar(app, width=300, fg_color="blue", progress_color="green")
progress_bar.set(0)
progress_bar.grid(row=5, columnspan=3, pady=10)

# Download Button
download_button = ctk.CTkButton(app, text="Download", command=start_download)
download_button.grid(row=6, columnspan=3, pady=20)

app.mainloop()
