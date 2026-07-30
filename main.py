import os
import shutil
import tempfile
import uuid
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp

app = FastAPI(
    title="FB Downloader API",
    description="Facebook Video & Audio Downloader API with auto FFmpeg merging",
    version="1.0.0"
)

# আপনার ওয়েবসাইট থেকে রিকোয়েস্ট এলাউ করার জন্য CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- হেলপার ফাংশনসমূহ ----------------- #

def get_proxy():
    """proxy.txt চেক করবে, না থাকলে None (Railway IP) রিটার্ন করবে"""
    if os.path.exists("proxy.txt"):
        with open("proxy.txt", "r") as f:
            proxies = [line.strip() for line in f if line.strip()]
            if proxies:
                return proxies[0]
    return None

def get_cookies():
    """cookies.txt ফাইল থাকলে তা ব্যবহার করবে"""
    if os.path.exists("cookies.txt") and os.path.getsize("cookies.txt") > 0:
        return "cookies.txt"
    return None

def format_size(bytes_size):
    """বাইটকে MB-তে কনভার্ট করে"""
    if not bytes_size:
        return "N/A"
    mb = bytes_size / (1024 * 1024)
    return f"{mb:.2f} MB"

def cleanup_temp_dir(dir_path: str):
    """ডাউনলোড শেষে সার্ভারের স্টোরেজ খালি করার কাজ করবে"""
    try:
        shutil.rmtree(dir_path)
    except Exception as e:
        print(f"Error cleaning up directory {dir_path}: {e}")

# ----------------- API এন্ডপয়েন্টসমূহ ----------------- #

@app.get("/")
def home():
    return {"status": "online", "message": "Facebook Video Downloader API is Running!"}


@app.get("/api/v1/extract")
def extract_metadata(url: str = Query(..., description="Facebook Video URL")):
    """ফেসবুকের যেকোনো সাইজের ভিডিও এবং অডিও ফরম্যাট ডাইনামিকভাবে এক্সট্র্যাক্ট করবে"""
    proxy = get_proxy()
    cookies = get_cookies()

    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
    }
    if proxy:
        ydl_opts['proxy'] = proxy
    if cookies:
        ydl_opts['cookiefile'] = cookies

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            title = info.get('title', 'Facebook Video')
            thumbnail = info.get('thumbnail', '')
            duration = info.get('duration_string', 'N/A')

            available_formats = {}
            formats = info.get('formats', [])
            
            # ডাইনামিক ভিডিও কোয়ালিটি খোঁজার লজিক (যেকোনো সাইজের ভিডিও ধরবে)
            for f in formats:
                if f.get('vcodec') != 'none' and f.get('height'):
                    h = int(f.get('height'))
                    q_label = f"{h}p" # যেমন: 1080p, 720p, 360p ইত্যাদি
                    
                    size = f.get('filesize') or f.get('filesize_approx')
                    
                    if q_label not in available_formats:
                        available_formats[q_label] = {
                            "quality": q_label,
                            "size": format_size(size),
                            "download_url": f"/api/v1/download?url={url}&quality={q_label}"
                        }

            # অডিও/MP3 খোঁজার লজিক
            audio_size = None
            for f in formats:
                if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                    audio_size = f.get('filesize') or f.get('filesize_approx')
                    break

            available_formats['mp3'] = {
                "quality": "Audio (MP3)",
                "size": format_size(audio_size),
                "download_url": f"/api/v1/download?url={url}&quality=mp3"
            }

            return {
                "success": True,
                "title": title,
                "thumbnail": thumbnail,
                "duration": duration,
                "formats": available_formats
            }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error extracting video: {str(e)}")


@app.get("/api/v1/download")
def download_media(
    background_tasks: BackgroundTasks,
    url: str = Query(...),
    quality: str = Query(..., description="Example: 1080p, 720p, 360p, mp3")
):
    """ভিডিও/অডিও ডাউনলোড, FFmpeg দিয়ে মার্জ করে অটোমেটিক ফাইল রেসপন্স পাঠাবে"""
    temp_dir = tempfile.mkdtemp()
    file_id = str(uuid.uuid4())
    output_template = os.path.join(temp_dir, f"{file_id}.%(ext)s")

    proxy = get_proxy()
    cookies = get_cookies()

    ydl_opts = {
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
    }

    if proxy:
        ydl_opts['proxy'] = proxy
    if cookies:
        ydl_opts['cookiefile'] = cookies

    if quality == 'mp3':
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        target_height = quality.replace('p', '')
        # ভিডিও ও অডিও আলাদা থাকলে FFmpeg দিয়ে মার্জ করার অপশন
        ydl_opts['format'] = f"bestvideo[height<={target_height}]+bestaudio/bestvideo[height<={target_height}]/best"
        ydl_opts['merge_output_format'] = 'mp4'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

            if quality == 'mp3':
                filename = os.path.splitext(filename)[0] + ".mp3"
            else:
                filename = os.path.splitext(filename)[0] + ".mp4"

        if not os.path.exists(filename):
            files = os.listdir(temp_dir)
            if files:
                filename = os.path.join(temp_dir, files[0])
            else:
                raise HTTPException(status_code=500, detail="File processing failed.")

        # ব্যাকগ্রাউন্ডে ফাইল ক্লিনআপ টাস্ক
        background_tasks.add_task(cleanup_temp_dir, temp_dir)

        download_name = f"FB_{quality}_{info.get('title', 'video')[:15]}.{'mp3' if quality=='mp3' else 'mp4'}"
        download_name = "".join(c for c in download_name if c.isalnum() or c in "._- ")

        # Content-Disposition দিয়ে পপ-আপ ছাড়াই ডাইরেক্ট অটো ডাউনলোড শুরু করানো
        return FileResponse(
            path=filename,
            media_type='audio/mpeg' if quality == 'mp3' else 'video/mp4',
            filename=download_name,
            headers={"Content-Disposition": f'attachment; filename="{download_name}"'}
        )

    except Exception as e:
        cleanup_temp_dir(temp_dir)
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
