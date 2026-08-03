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

        unique_filename = generate_unique_filename(video_title, quality)

        return {
            "success": True,
            "title": video_title,
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

# ==================== 100% ENGLISH FRONTEND ====================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Facebook Video Downloader</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-gray-100 min-h-screen flex items-center justify-center p-4">

    <!-- Responsive Container -->
    <div class="bg-white rounded-2xl shadow-xl w-full max-w-md md:max-w-5xl p-6 sm:p-8 border border-gray-100 transition-all">
        
        <!-- Desktop Grid Layout -->
        <div class="md:grid md:grid-cols-2 md:gap-8 items-start">
            
            <!-- Left Column: Inputs -->
            <div class="space-y-5">
                <div class="text-center md:text-left">
                    <div class="inline-flex items-center justify-center w-14 h-14 bg-blue-100 text-blue-600 rounded-2xl mb-2">
                        <i class="fa-brands fa-facebook-f text-2xl"></i>
                    </div>
                    <h1 class="text-2xl font-extrabold text-gray-800">FB Downloader Pro</h1>
                    <p class="text-gray-500 text-sm mt-1">Download Facebook Videos in 720p & 1080p Full HD</p>
                </div>

                <div class="space-y-4">
                    <div>
                        <label class="block text-sm font-semibold text-gray-700 mb-1">Facebook Video URL:</label>
                        <div class="flex gap-2">
                            <div class="relative flex-1">
                                <input type="url" id="videoUrl" required oninput="toggleClearBtn()"
                                    placeholder="https://www.facebook.com/watch/?v=..."
                                    class="w-full pl-10 pr-10 py-3 rounded-xl border border-gray-300 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all text-gray-700 text-sm">
                                <div class="absolute left-3 top-3.5 text-gray-400">
                                    <i class="fa-solid fa-link"></i>
                                </div>
                                <!-- Clear Button (X) -->
                                <button type="button" id="clearBtn" onclick="clearUrl()" 
                                    class="hidden absolute right-3 top-3 text-gray-400 hover:text-gray-600 transition-colors p-1">
                                    <i class="fa-solid fa-circle-xmark text-lg"></i>
                                </button>
                            </div>
                            <!-- 1-Click Paste Button -->
                            <button type="button" onclick="pasteUrl()"
                                class="px-4 py-3 bg-gray-100 hover:bg-gray-200 text-gray-700 font-semibold rounded-xl text-sm border border-gray-300 flex items-center space-x-1.5 transition-all active:scale-95">
                                <i class="fa-regular fa-clipboard"></i>
                                <span>Paste</span>
                            </button>
                        </div>
                    </div>

                    <div>
                        <label class="block text-sm font-semibold text-gray-700 mb-1">Select Video Quality:</label>
                        <div class="grid grid-cols-2 gap-3">
                            <label class="cursor-pointer">
                                <input type="radio" name="quality" value="720" class="peer hidden">
                                <div class="p-3 text-center border-2 border-gray-200 rounded-xl peer-checked:border-blue-600 peer-checked:bg-blue-50 peer-checked:text-blue-600 hover:border-blue-300 transition-all font-semibold text-gray-600 text-sm">
                                    <i class="fa-solid fa-video mr-1"></i> 720p HD
                                </div>
                            </label>
                            <label class="cursor-pointer">
                                <input type="radio" name="quality" value="1080" checked class="peer hidden">
                                <div class="p-3 text-center border-2 border-gray-200 rounded-xl peer-checked:border-blue-600 peer-checked:bg-blue-50 peer-checked:text-blue-600 hover:border-blue-300 transition-all font-semibold text-gray-600 text-sm">
                                    <i class="fa-solid fa-film mr-1"></i> 1080p Full HD
                                </div>
                            </label>
                        </div>
                    </div>

                    <button type="button" id="fetchBtn" onclick="processVideo()"
                        class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-3.5 px-4 rounded-xl shadow-lg hover:shadow-blue-200 transition-all flex items-center justify-center space-x-2 active:scale-98">
                        <i class="fa-solid fa-gear"></i>
                        <span>Get Video Preview</span>
                    </button>
                </div>

                <!-- Alert Message -->
                <div id="statusMessage" class="hidden p-3 rounded-xl text-center text-sm font-medium"></div>
            </div>

            <!-- Right Column: Video Preview & Download Area -->
            <div class="mt-6 md:mt-0">
                <!-- Loading State -->
                <div id="loadingState" class="hidden py-8 bg-blue-50 rounded-2xl border border-blue-100 text-center">
                    <div class="inline-block animate-spin rounded-full h-9 w-9 border-4 border-blue-600 border-t-transparent mb-2"></div>
                    <p class="text-blue-800 font-semibold text-sm">Processing Video...</p>
                    <p class="text-blue-600 text-xs mt-1">Merging audio and video formats. Please wait...</p>
                </div>

                <!-- Placeholder (Initial State Only - Hides when video is loaded) -->
                <div id="emptyState" class="flex flex-col items-center justify-center border-2 border-dashed border-gray-200 rounded-2xl p-8 text-center min-h-[280px]">
                    <i class="fa-solid fa-circle-play text-5xl text-gray-300 mb-3"></i>
                    <p class="text-gray-500 font-medium text-sm">Enter a Facebook link above and click Get Video Preview</p>
                </div>

                <!-- Video Result Card -->
                <div id="videoResultCard" class="hidden space-y-4 bg-gray-50 md:bg-white p-4 md:p-0 rounded-2xl md:rounded-none border md:border-none border-gray-200">
                    <h3 id="videoTitle" class="font-bold text-gray-800 text-sm line-clamp-2"></h3>
                    
                    <!-- Video Player -->
                    <div class="rounded-xl overflow-hidden bg-black shadow">
                        <video id="videoPlayer" controls class="w-full max-h-72 object-contain"></video>
                    </div>

                    <!-- Unique Download Button -->
                    <a id="downloadButton" href="" download class="w-full bg-green-600 hover:bg-green-700 text-white font-bold py-3.5 px-4 rounded-xl shadow-lg hover:shadow-green-200 transition-all flex items-center justify-center space-x-2 active:scale-98">
                        <i class="fa-solid fa-download"></i>
                        <span>Download Video File</span>
                    </a>
                </div>
            </div>

        </div>
    </div>

    <script>
        const videoUrlInput = document.getElementById('videoUrl');
        const clearBtn = document.getElementById('clearBtn');
        const fetchBtn = document.getElementById('fetchBtn');
        const loadingState = document.getElementById('loadingState');
        const emptyState = document.getElementById('emptyState');
        const statusMessage = document.getElementById('statusMessage');
        const videoResultCard = document.getElementById('videoResultCard');
        const videoPlayer = document.getElementById('videoPlayer');
        const videoTitle = document.getElementById('videoTitle');
        const downloadButton = document.getElementById('downloadButton');

        // Toggle Clear (X) button visibility
        function toggleClearBtn() {
            if (videoUrlInput.value.length > 0) {
                clearBtn.classList.remove('hidden');
            } else {
                clearBtn.classList.add('hidden');
            }
        }

        // Clear input box
        function clearUrl() {
            videoUrlInput.value = '';
            toggleClearBtn();
            videoUrlInput.focus();
        }

        // 1-Click Paste from Clipboard
        async function pasteUrl() {
            try {
                const text = await navigator.clipboard.readText();
                if (text) {
                    videoUrlInput.value = text;
                    toggleClearBtn();
                }
            } catch (err) {
                alert('Clipboard permission denied or unsupported browser.');
            }
        }

        async function processVideo() {
            const urlInput = videoUrlInput.value.trim();
            const quality = document.querySelector('input[name="quality"]:checked').value;

            if (!urlInput) {
                showStatus("Please enter a valid Facebook video URL!", "bg-yellow-100", "text-yellow-800");
                return;
            }

            // HIDE empty placeholder & HIDE previous result
            statusMessage.classList.add('hidden');
            videoResultCard.classList.add('hidden');
            emptyState.classList.add('hidden'); // Fully hides placeholder box
            loadingState.classList.remove('hidden');
            fetchBtn.disabled = true;
            fetchBtn.classList.add('opacity-50', 'cursor-not-allowed');

            try {
                const response = await fetch(`/api/process?url=${encodeURIComponent(urlInput)}&quality=${quality}`);
                
                if (!response.ok) {
                    const errData = await response.json();
                    throw new Error(errData.detail || "Could not process video. Check URL.");
                }

                const data = await response.json();

                // Load preview
                videoPlayer.src = data.stream_url;
                videoTitle.innerText = data.title;
                downloadButton.href = data.download_url;
                downloadButton.setAttribute("download", data.filename);

                // Show video card ONLY, keep placeholder HIDDEN
                loadingState.classList.add('hidden');
                emptyState.classList.add('hidden'); // Extra check to ensure placeholder is gone
                videoResultCard.classList.remove('hidden');
                
            } catch (err) {
                loadingState.classList.add('hidden');
                emptyState.classList.remove('hidden'); // Show placeholder only on error
                showStatus(`Error: ${err.message}`, "bg-red-100", "text-red-800");
            } finally {
                fetchBtn.disabled = false;
                fetchBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            }
        }

        function showStatus(text, bgColor, textColor) {
            statusMessage.className = `p-3 rounded-xl text-center text-sm font-medium ${bgColor} ${textColor}`;
            statusMessage.innerText = text;
            statusMessage.classList.remove('hidden');
        }
    </script>
</body>
</html>
"""

# ==================== API ENDPOINTS ====================

@app.get("/", response_class=HTMLResponse)
async def render_frontend():
    return HTMLResponse(content=HTML_TEMPLATE, status_code=200)

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

        unique_filename = generate_unique_filename(video_title, quality)

        return {
            "success": True,
            "title": video_title,
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
