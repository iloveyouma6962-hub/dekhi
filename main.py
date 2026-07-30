import os
import random
import uuid
import shutil
from pathlib import Path
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
import yt_dlp

app = FastAPI(title="Video Downloader API", version="1.0.0")

# --- Configurations ---
PROXIES_FILE = "proxies.txt"
COOKIES_FILE = "cookies.txt"
DOWNLOAD_DIR = "downloads"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# --- Helper Functions ---
def get_random_proxy() -> str | None:
    """Reads proxies.txt and returns a random proxy if available."""
    if os.path.exists(PROXIES_FILE):
        with open(PROXIES_FILE, "r") as f:
            proxies = [line.strip() for line in f if line.strip()]
            if proxies:
                return random.choice(proxies)
    return None

def get_base_ydl_opts() -> dict:
    """Generates base options for yt-dlp, integrating proxies and cookies gracefully."""
    opts = {
        'quiet': True,
        'no_warnings': True,
    }
    
    proxy = get_random_proxy()
    if proxy:
        opts['proxy'] = proxy
        
    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE
        
    return opts

def format_size(bytes_size: int | float | None) -> str:
    """Converts bytes to human-readable string."""
    if not bytes_size:
        return "Unknown Size"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} TB"

def cleanup_temp_dir(dir_path: str):
    """Deletes the temporary directory and its contents after download."""
    if os.path.exists(dir_path):
        shutil.rmtree(dir_path)

# --- Pydantic Models ---
class URLRequest(BaseModel):
    url: HttpUrl

class DownloadRequest(BaseModel):
    url: HttpUrl
    format_id: str

# --- API Endpoints ---
@app.post("/api/info", summary="Extract Video Metadata")
async def get_video_info(request: URLRequest):
    """Fetches video metadata, thumbnail, duration, and available formats."""
    ydl_opts = get_base_ydl_opts()
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(str(request.url), download=False)
            
            formats_data = []
            for f in info.get('formats', []):
                # Filter for formats that have video
                if f.get('vcodec') != 'none' and f.get('vcodec') is not None:
                    formats_data.append({
                        "format_id": f.get('format_id'),
                        "resolution": f.get('format_note') or f.get('resolution') or "Unknown",
                        "ext": f.get('ext'),
                        "size": format_size(f.get('filesize') or f.get('filesize_approx')),
                        "url": f.get('url') # Direct stream link
                    })
            
            return {
                "title": info.get('title'),
                "thumbnail": info.get('thumbnail'),
                "duration_seconds": info.get('duration'),
                "formats": formats_data
            }
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to extract info: {str(e)}")


@app.post("/api/download", summary="Download and Merge Video")
async def download_video(request: DownloadRequest, background_tasks: BackgroundTasks):
    """
    Downloads the requested video format. If it's a high-res video (1080p+) missing audio,
    it downloads the best audio and merges them using FFmpeg. Cleans up afterward.
    """
    session_id = str(uuid.uuid4())
    temp_dir = os.path.join(DOWNLOAD_DIR, session_id)
    os.makedirs(temp_dir, exist_ok=True)
    
    # Format string: Requested video format + best audio, merge to mp4
    format_str = f"{request.format_id}+bestaudio[ext=m4a]/bestaudio/best"
    
    ydl_opts = get_base_ydl_opts()
    ydl_opts.update({
        'outtmpl': f'{temp_dir}/%(title)s.%(ext)s',
        'format': format_str,
        'merge_output_format': 'mp4',
    })
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(str(request.url), download=True)
            # Find the downloaded file path
            filename = ydl.prepare_filename(info)
            # If merged, yt-dlp changes the extension to the merged format
            base, _ = os.path.splitext(filename)
            final_file = f"{base}.mp4"
            
            if not os.path.exists(final_file):
                final_file = filename # Fallback if merging didn't change extension
                
            # Schedule the cleanup task to run AFTER the FileResponse is completely sent
            background_tasks.add_task(cleanup_temp_dir, temp_dir)
            
            return FileResponse(
                path=final_file,
                media_type="video/mp4",
                filename=os.path.basename(final_file)
            )
            
    except Exception as e:
        cleanup_temp_dir(temp_dir) # Cleanup on failure
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
