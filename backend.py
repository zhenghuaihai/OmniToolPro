import os
import asyncio
import uuid
import time
import re
from typing import List, Dict, Any
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from core.downloader import BatchDownloader
from core.audio_extractor import extract_audio
from core.transcriber import Transcriber
from core.summarizer import Summarizer
import config
import imageio_ffmpeg
import stat

# --- Setup ---
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global State
# In a real app, use a database (SQLite/Redis)
DOWNLOAD_TASKS: Dict[str, Dict[str, Any]] = {}
ANALYSIS_TASKS: Dict[str, Dict[str, Any]] = {}

# Ensure directories
os.makedirs("downloads/batch", exist_ok=True)
os.makedirs("downloads/analysis", exist_ok=True)
os.makedirs("bin", exist_ok=True)

# Helper: Extract URLs
def extract_urls_from_text(text: str) -> List[str]:
    urls = []
    # Match http/https URLs
    found = re.findall(r'https?://[^\s]+', text)
    for url in found:
        # Clean trailing punctuation often caught by greedy regex
        clean_url = url.strip('.,;!?`"\'()[]<>')
        if clean_url:
            urls.append(clean_url)
    return list(set(urls))

# FFmpeg Setup (Same as app.py)
def setup_ffmpeg():
    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        project_dir = os.getcwd()
        bin_dir = os.path.join(project_dir, "bin")
        symlink_path = os.path.join(bin_dir, "ffmpeg")
        if os.path.exists(symlink_path):
            os.remove(symlink_path)
        os.symlink(ffmpeg_exe, symlink_path)
        st = os.stat(symlink_path)
        os.chmod(symlink_path, st.st_mode | stat.S_IEXEC)
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]
    except Exception as e:
        print(f"FFmpeg setup warning: {e}")

setup_ffmpeg()

# --- Models ---
class BatchDownloadRequest(BaseModel):
    urls: List[str]

class AnalysisRequest(BaseModel):
    urls: List[str]
    api_key: str = None

import zipfile

@app.post("/api/batch-download-zip")
async def download_all_zip(req: BatchDownloadRequest):
    # This endpoint is slightly different. It expects a list of Task IDs (or we just zip everything in current session?)
    # For simplicity, let's accept a list of Task IDs that the frontend knows about.
    # Actually, the frontend sends URLs to start tasks.
    # Let's make a new endpoint that takes a list of COMPLETED task IDs and zips them.
    pass

class ZipRequest(BaseModel):
    task_ids: List[str]

@app.post("/api/create-zip")
async def create_zip(req: ZipRequest):
    files_to_zip = []
    for tid in req.task_ids:
        if tid in DOWNLOAD_TASKS:
            task = DOWNLOAD_TASKS[tid]
            if task.get("status") == "COMPLETED" and task.get("filename"):
                fpath = os.path.join("downloads/batch", task["filename"])
                if os.path.exists(fpath):
                    files_to_zip.append(fpath)
    
    if not files_to_zip:
        raise HTTPException(status_code=400, detail="No valid completed files found to zip")
        
    zip_filename = f"batch_download_{int(time.time())}.zip"
    zip_path = os.path.join("downloads", zip_filename)
    
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for file in files_to_zip:
            zipf.write(file, arcname=os.path.basename(file))
            
    return {"zip_url": f"/api/download-zip/{zip_filename}"}

@app.get("/api/download-zip/{filename}")
async def download_zip(filename: str):
    file_path = os.path.join("downloads", filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, filename=filename)
    raise HTTPException(status_code=404, detail="Zip file not found")


async def process_download_task(task_id: str, url: str):
    task = DOWNLOAD_TASKS[task_id]
    task["status"] = "PROCESSING"
    
    def progress_cb(idx, percent):
        task["progress"] = percent
    
    def status_cb(idx, status):
        # Map some status text to simpler states if needed
        pass

    try:
        # We reuse BatchDownloader logic but for a single file for simplicity in this architecture
        # or we could group them. The frontend sends line-by-line or batch?
        # The frontend sends a batch in the text area. 
        # But let's assume the frontend will call this API for each URL or a batch.
        # Let's support single URL processing per background task to keep it simple.
        
        dl_tasks = [{'index': 0, 'url': url}]
        downloader = BatchDownloader(dl_tasks, "downloads/batch", progress_cb, status_cb)
        
        # Run async
        await downloader.run_async()
        
        if downloader.downloaded_files:
            task["status"] = "COMPLETED"
            task["progress"] = 100
            task["filename"] = os.path.basename(downloader.downloaded_files[0])
        else:
            task["status"] = "ERROR"
            task["error"] = "Download failed"
            
    except Exception as e:
        task["status"] = "ERROR"
        task["error"] = str(e)

async def process_analysis_task(task_id: str, url: str, api_key: str):
    task = ANALYSIS_TASKS[task_id]
    task["status"] = "PROCESSING"
    task["progress"] = 0
    
    work_dir = "downloads/analysis"
    
    try:
        # 1. Download
        task["stage"] = "Downloading"
        dl_tasks = [{'index': 0, 'url': url}]
        downloader = BatchDownloader(dl_tasks, work_dir, None, None)
        files = await downloader.run_async()
        
        if not files:
            raise Exception("Download failed")
            
        video_path = files[0]
        base_name = os.path.basename(video_path)
        task["progress"] = 30
        
        # 2. Extract Audio
        task["stage"] = "Extracting Audio"
        audio_path = os.path.join(work_dir, f"{base_name}.wav")
        success, err = extract_audio(video_path, audio_path)
        if not success:
            raise Exception(f"Audio extraction failed: {err}")
            
        task["progress"] = 50
        
        # 3. Transcribe
        task["stage"] = "Transcribing"
        transcriber = Transcriber() # Loads Whisper
        # Run in thread to avoid blocking event loop
        loop = asyncio.get_running_loop()
        transcript_res = await loop.run_in_executor(None, transcriber.transcribe, audio_path)
        
        raw_text = transcript_res['text']
        # mock segments if not present (Transcriber modification earlier added segments return)
        segments = transcript_res.get('segments', []) 
        
        task["progress"] = 70
        
        # 4. Refine & Summarize
        task["stage"] = "Summarizing"
        key_to_use = api_key if api_key else config.DEEPSEEK_API_KEY
        summarizer = Summarizer(key_to_use, config.DEEPSEEK_BASE_URL)
        
        refined_text = await loop.run_in_executor(None, summarizer.refine_transcript, raw_text)
        summary = await loop.run_in_executor(None, summarizer.summarize, refined_text)
        
        # Cleanup
        if os.path.exists(audio_path):
            os.remove(audio_path)
            
        task["status"] = "COMPLETED"
        task["progress"] = 100
        task["result"] = {
            "summary": summary,
            "transcript": [{"id": str(i), "timestamp": f"{int(s['start']//60):02d}:{int(s['start']%60):02d}", "text": s['text'], "speaker": "Speaker"} for i, s in enumerate(segments)],
            "full_transcript": refined_text,
            "tags": ["#AI", "#Analysis"] # Mock tags
        }
        
    except Exception as e:
        task["status"] = "ERROR"
        task["error"] = str(e)
        print(f"Analysis Error: {e}")

# --- API Endpoints ---

@app.get("/")
async def read_root():
    return FileResponse("static/index.html")

@app.post("/api/batch-download")
async def start_batch_download(req: BatchDownloadRequest, background_tasks: BackgroundTasks):
    new_tasks = []
    # Extract URLs from all input lines
    all_text = "\n".join(req.urls)
    clean_urls = extract_urls_from_text(all_text)
    
    if not clean_urls:
        # Fallback: if no URLs extracted, try using the raw lines (might be direct links)
        # But filtering empty lines
        clean_urls = [u for u in req.urls if u.strip()]

    for url in clean_urls:
        task_id = str(uuid.uuid4())
        DOWNLOAD_TASKS[task_id] = {
            "id": task_id,
            "url": url,
            "status": "PENDING",
            "progress": 0
        }
        background_tasks.add_task(process_download_task, task_id, url)
        new_tasks.append(DOWNLOAD_TASKS[task_id])
    return new_tasks

@app.get("/api/download-tasks")
async def get_download_tasks():
    return list(DOWNLOAD_TASKS.values())

@app.post("/api/analyze")
async def start_analysis(req: AnalysisRequest, background_tasks: BackgroundTasks):
    new_tasks = []
    # Extract URLs from all input lines
    all_text = "\n".join(req.urls)
    clean_urls = extract_urls_from_text(all_text)

    if not clean_urls:
         clean_urls = [u for u in req.urls if u.strip()]

    for url in clean_urls:
        task_id = str(uuid.uuid4())
        ANALYSIS_TASKS[task_id] = {
            "id": task_id,
            "url": url,
            "status": "PENDING", # Mapped to 'PROCESSING' in frontend usually
            "progress": 0
        }
        background_tasks.add_task(process_analysis_task, task_id, url, req.api_key)
        new_tasks.append(ANALYSIS_TASKS[task_id])
    return new_tasks

@app.get("/api/analysis-tasks")
async def get_analysis_tasks():
    return list(ANALYSIS_TASKS.values())

@app.get("/api/analysis-result/{task_id}")
async def get_analysis_result(task_id: str):
    if task_id not in ANALYSIS_TASKS:
        raise HTTPException(status_code=404, detail="Task not found")
    return ANALYSIS_TASKS[task_id]

@app.get("/api/download-result/{task_id}")
async def download_result(task_id: str):
    if task_id in DOWNLOAD_TASKS:
        task = DOWNLOAD_TASKS[task_id]
        if task.get("status") == "COMPLETED" and task.get("filename"):
            file_path = os.path.join("downloads/batch", task["filename"])
            if os.path.exists(file_path):
                return FileResponse(file_path, filename=task["filename"])
    raise HTTPException(status_code=404, detail="File not found")

@app.get("/api/download-transcript/{task_id}")
async def download_transcript(task_id: str):
    if task_id in ANALYSIS_TASKS:
        task = ANALYSIS_TASKS[task_id]
        if task.get("status") == "COMPLETED" and task.get("result"):
            transcript = task["result"].get("full_transcript", "")
            if not transcript:
                raise HTTPException(status_code=404, detail="No transcript available")
                
            filename = f"transcript_{task_id}.txt"
            file_path = os.path.join("downloads/analysis", filename)
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(transcript)
                
            return FileResponse(file_path, filename=filename)
            
    raise HTTPException(status_code=404, detail="Task not found or not completed")

# Mount Static
app.mount("/", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
