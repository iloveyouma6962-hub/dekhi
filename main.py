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
    """ভিডিওর সব ফরম্যাট, সাইজ এবং ডাউনলোড লিংক এক্সট্র্যাক্ট করবে"""
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

            # ফরম্যাট প্রসেসিং
            available_formats = {}
            target_qualities = ['1080p', '720p', '480p', '360p', '240p', '144p']
            
            formats = info.get('formats', [])
            
            # রেজোলিউশন অনুযায়ী সবচেয়ে সেরা স্ট্রিম খোঁজা
            for q in target_qualities:
                matching_f = None
                height_target = int(q.replace('p', ''))
                
                for f in formats:
                    if f.get('height') == height_target:
                        matching_f = f
                        break
                
                if matching_f:
                    size = matching_f.get('filesize') or matching_f.get('filesize_approx')
                    available_formats[q] = {
                        "quality": q,
                        "size": format_size(size),
                        "download_url": f"/api/v1/download?url={url}&quality={q}"
                    }

            # MP3 / Audio Option
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

    # yt-dlp এর ডাউনলোডার অপশন
    ydl_opts = {
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
    }

    if proxy:
        ydl_opts['proxy'] = proxy
    if cookies:
        ydl_opts['cookiefile'] = cookies

    # কোয়ালিটি অনুযায়ী ফরম্যাট সিলেক্ট এবং অটো-মার্জ লজিক
    if quality == 'mp3':
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '1920',
        }]
    else:
        target_height = quality.replace('p', '')
        # যদি অডিও আলাদা থাকে, তবে সেরা অডিওর সাথে FFmpeg দিয়ে মার্জ করবে
        ydl_opts['format'] = f"bestvideo[height<={target_height}]+bestaudio/bestvideo[height<={target_height}]/best"
        ydl_opts['merge_output_format'] = 'mp4'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

            # MP3 হলে এক্সটেনশন চেঞ্জ চেক
            if quality == 'mp3':
                filename = os.path.splitext(filename)[0] + ".mp3"
            else:
                filename = os.path.splitext(filename)[0] + ".mp4"

        if not os.path.exists(filename):
            # ব্যাকআপ চেক: যদি নির্দিষ্ট নামে না থাকে
            files = os.listdir(temp_dir)
            if files:
                filename = os.path.join(temp_dir, files[0])
            else:
                raise HTTPException(status_code=500, detail="File processing failed.")

        # ক্লিনআপ টাঙ্ক (ডাউনলোড শেষে টেম্প ফাইল ডিলিট করার জন্য)
        background_tasks.add_task(cleanup_temp_dir, temp_dir)

        download_name = f"FB_{quality}_{info.get('title', 'video')[:15]}.{'mp3' if quality=='mp3' else 'mp4'}"
        # চিহ্নসমূহ রিমুভ করা যাতে ফাইলে নাম ঠিক থাকে
        download_name = "".join(c for c in download_name if c.isalnum() or c in "._- ")

        # Content-Disposition: attachment এর ফলে পপ-আপ ছাড়া অটো ডাউনলোড শুরু হবে
        return FileResponse(
            path=filename,
            media_type='audio/mpeg' if quality == 'mp3' else 'video/mp4',
            filename=download_name,
            headers={"Content-Disposition": f'attachment; filename="{download_name}"'}
        )

    except Exception as e:
        cleanup_temp_dir(temp_dir)
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
