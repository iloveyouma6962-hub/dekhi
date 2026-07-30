import os
import random
import uuid
import shutil
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
import yt_dlp

app = FastAPI(title="Video Downloader API", version="1.0.0")

PROXIES_FILE = "proxies.txt"
COOKIES_FILE = "cookies.txt"
DOWNLOAD_DIR = "downloads"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def get_random_proxy() -> str | None:
    if os.path.exists(PROXIES_FILE):
        with open(PROXIES_FILE, "r") as f:
            proxies = [line.strip() for line in f if line.strip()]
            if proxies:
                return random.choice(proxies)
    return None

def get_base_ydl_opts() -> dict:
    opts = {
        'quiet': True,
        'no_warnings': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
    }
    
    proxy = get_random_proxy()
    if proxy:
        opts['proxy'] = proxy
        
    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE
        
    return opts

def format_size(bytes_size: int | float | None) -> str:
    if not bytes_size:
        return "Unknown Size"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} TB"

def cleanup_temp_dir(dir_path: str):
    if os.path.exists(dir_path):
        shutil.rmtree(dir_path)

class URLRequest(BaseModel):
    url: HttpUrl

class DownloadRequest(BaseModel):
    url: HttpUrl
    format_id: str = "best"

@app.post("/api/info", summary="Extract Video Metadata")
async def get_video_info(request: URLRequest):
    ydl_opts = get_base_ydl_opts()
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(str(request.url), download=False)
            
            formats_data = []
            formats = info.get('formats', [])
            
            if not formats:
                formats_data.append({
                    "format_id": "best",
                    "resolution": "Default",
                    "ext": info.get('ext', 'mp4'),
                    "size": format_size(info.get('filesize') or info.get('filesize_approx')),
                    "url": info.get('url')
                })
            else:
                for f in formats:
                    if f.get('vcodec') != 'none' and f.get('vcodec') is not None:
                        formats_data.append({
                            "format_id": f.get('format_id'),
                            "resolution": f.get('format_note') or f.get('resolution') or "Unknown",
                            "ext": f.get('ext'),
                            "size": format_size(f.get('filesize') or f.get('filesize_approx')),
                            "url": f.get('url')
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
    session_id = str(uuid.uuid4())
    temp_dir = os.path.join(DOWNLOAD_DIR, session_id)
    os.makedirs(temp_dir, exist_ok=True)
    
    fid = request.format_id.strip() if request.format_id else "best"
    
    # "string", "best" বা খালি থাকলে স্মার্ট ফলব্যাক ফরম্যাট সিলেক্ট করবে
    if fid in ["best", "string", "sd", "hd", ""]:
        format_str = "bestvideo+bestaudio/best"
    else:
        format_str = f"{fid}+bestaudio/bestvideo+{fid}/{fid}/best"
    
    ydl_opts = get_base_ydl_opts()
    ydl_opts.update({
        'outtmpl': f'{temp_dir}/%(title)s.%(ext)s',
        'format': format_str,
        'merge_output_format': 'mp4',
    })
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(str(request.url), download=True)
            filename = ydl.prepare_filename(info)
            base, _ = os.path.splitext(filename)
            final_file = f"{base}.mp4"
            
            if not os.path.exists(final_file):
                files = os.listdir(temp_dir)
                if files:
                    final_file = os.path.join(temp_dir, files[0])
                else:
                    final_file = filename
                
            background_tasks.add_task(cleanup_temp_dir, temp_dir)
            
            return FileResponse(
                path=final_file,
                media_type="video/mp4",
                filename=os.path.basename(final_file)
            )
            
    except Exception as e:
        cleanup_temp_dir(temp_dir)
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
