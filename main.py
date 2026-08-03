import os
import uuid
import glob
import re
import time
import urllib.parse
import requests
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp

app = FastAPI(title="Facebook Video Downloader API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Auto delete unused files older than 10 minutes
def cleanup_old_files(max_age_seconds=600):
    now = time.time()
    for filepath in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
        if os.path.isfile(filepath):
            if now - os.path.getmtime(filepath) > max_age_seconds:
                try:
                    os.remove(filepath)
                except Exception:
                    pass

# Instant file deletion
def remove_single_file(filepath: str):
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except Exception:
            pass

# Unique filename generator
def generate_unique_filename(raw_title: str, quality: str) -> str:
    clean_title = re.sub(r'[^\w\s-]', '', raw_title or 'Video').strip()
    clean_title = re.sub(r'[-\s]+', '_', clean_title)[:25]
    
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    short_id = str(uuid.uuid4())[:4]
    
    if not clean_title:
        clean_title = "Video"
        
    return f"FB_{quality}p_{clean_title}_{timestamp}_{short_id}.mp4"

# File size formatter function (Bytes to KB/MB/GB)
def get_readable_file_size(filepath: str) -> str:
    if not os.path.exists(filepath):
        return "Unknown Size"
    
    size_bytes = os.path.getsize(filepath)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"

# Facebook URL & Redirect Resolver
def get_canonical_facebook_url(url: str) -> str:
    url = urllib.parse.unquote(url)
    
    pfbid_match = re.search(r'(pfbid[a-zA-Z0-9]+)', url)
    if pfbid_match:
        return f"https://m.facebook.com/story.php?story_fbid={pfbid_match.group(1)}"

    mobile_headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
    }
    
    try:
        res = requests.get(url, headers=mobile_headers, allow_redirects=True, timeout=8)
        final_url = res.url
        
        pfbid_match_redirect = re.search(r'(pfbid[a-zA-Z0-9]+)', final_url)
        if pfbid_match_redirect:
            return f"https://m.facebook.com/story.php?story_fbid={pfbid_match_redirect.group(1)}"
            
        final_url = final_url.replace("www.facebook.com", "m.facebook.com").replace("web.facebook.com", "m.facebook.com")
        return final_url
    except Exception:
        if "facebook.com" in url:
            url = url.replace("www.facebook.com", "m.facebook.com").replace("web.facebook.com", "m.facebook.com")
        return url


# ==================== API ENDPOINTS ====================

@app.get("/")
async def root():
    return {
        "status": "online",
        "message": "Facebook Video Downloader API is running successfully!"
    }

@app.get("/api/process")
async def process_video(
    url: str = Query(..., description="Facebook Video URL"),
    quality: str = Query("1080", regex="^(720|1080)$")
):
    cleanup_old_files()

    target_url = get_canonical_facebook_url(url)
    file_id = str(uuid.uuid4())[:10]
    output_template = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    if quality == "1080":
        format_str = "bestvideo[height<=1080]+bestaudio/bestvideo[height<=1080]/hd/sd/best"
    else:
        format_str = "bestvideo[height<=720]+bestaudio/bestvideo[height<=720]/sd/best"

    ydl_opts = {
        'format': format_str,
        'outtmpl': output_template,
        'merge_output_format': 'mp4',
        'quiet': False,
        'no_warnings': True,
        'noplaylist': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }

    if os.path.exists("cookies.txt") and os.path.getsize("cookies.txt") > 0:
        ydl_opts['cookiefile'] = "cookies.txt"

    if os.path.exists("proxy.txt") and os.path.getsize("proxy.txt") > 0:
        with open("proxy.txt", "r") as f:
            proxy = f.read().strip()
            if proxy:
                ydl_opts['proxy'] = proxy

    try:
        video_title = "Facebook Video"
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
                if info and 'title' in info:
                    video_title = info['title']
        except Exception as dl_err:
            if "ffmpeg" in str(dl_err).lower() or "postprocessing" in str(dl_err).lower():
                ydl_opts['format'] = 'hd/sd/best'
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(target_url, download=True)
                    if info and 'title' in info:
                        video_title = info['title']
            else:
                raise dl_err

        downloaded_files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_id}.*"))
        if not downloaded_files:
            raise HTTPException(status_code=400, detail="Video process failed. Check if video is public.")

        # Calculate File Size
        file_size = get_readable_file_size(downloaded_files[0])
        unique_filename = generate_unique_filename(video_title, quality)

        return {
            "success": True,
            "title": video_title,
            "file_size": file_size,
            "file_id": file_id,
            "filename": unique_filename,
            "stream_url": f"/api/stream/{file_id}",
            "download_url": f"/api/download-file/{file_id}?filename={urllib.parse.quote(unique_filename)}"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.get("/api/stream/{file_id}")
async def stream_video(file_id: str):
    downloaded_files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_id}.*"))
    if not downloaded_files:
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(path=downloaded_files[0], media_type="video/mp4")

@app.get("/api/download-file/{file_id}")
async def download_file(
    file_id: str, 
    filename: str = Query("facebook_video.mp4"),
    background_tasks: BackgroundTasks = None
):
    downloaded_files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_id}.*"))
    if not downloaded_files:
        raise HTTPException(status_code=404, detail="Video file expired or not found")
    
    filepath = downloaded_files[0]
    background_tasks.add_task(remove_single_file, filepath)
    
    return FileResponse(
        path=filepath,
        filename=filename,
        media_type="video/mp4"
    )
