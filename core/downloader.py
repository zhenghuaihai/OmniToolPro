import os
import aiohttp
import aiofiles
import asyncio
import yt_dlp
import re
from core.audio_extractor import get_ffmpeg_path

def strip_ansi(text):
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

class BatchDownloader:
    def __init__(self, tasks, dest_folder, progress_callback=None, status_callback=None):
        """
        tasks: list of dict {'url': str, 'filename': str, 'index': int}
        progress_callback: func(index, percent)
        status_callback: func(index, status_text)
        """
        self.tasks = tasks
        self.dest_folder = dest_folder
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.is_running = True
        self.downloaded_files = [] 

    async def run_async(self):
        self.downloaded_files = []
        timeout = aiohttp.ClientTimeout(total=600) # 10 mins timeout
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Limit concurrency to avoid blocking
            semaphore = asyncio.Semaphore(5) 
            
            async def download_wrapper(task):
                async with semaphore:
                    # Check if URL is suitable for yt-dlp
                    if self.is_ytdlp_url(task['url']):
                        await self.download_with_ytdlp(task)
                    else:
                        await self.download_file(session, task)

            coroutines = [download_wrapper(task) for task in self.tasks]
            await asyncio.gather(*coroutines)
        
        return self.downloaded_files

    def is_ytdlp_url(self, url):
        return True

    async def download_with_ytdlp(self, task):
        if not self.is_running: return
        
        index = task['index']
        url = task['url']
        
        if self.status_callback:
            self.status_callback(index, "Connecting...")
            
        def ytdlp_progress_hook(d):
            if not self.is_running:
                raise Exception("Stopped")
            if d['status'] == 'downloading':
                if self.progress_callback:
                    p = d.get('_percent_str', '0%').replace('%','')
                    try:
                        self.progress_callback(index, int(float(p)))
                    except: pass
                if self.status_callback:
                    self.status_callback(index, "Downloading...")
            elif d['status'] == 'finished':
                if self.progress_callback:
                    self.progress_callback(index, 100)

        # Force a generic User-Agent that works well on servers
        # Using a very standard Chrome UA
        ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

        ydl_opts = {
            'outtmpl': os.path.join(self.dest_folder, '%(title)s.%(ext)s'),
            'progress_hooks': [ytdlp_progress_hook],
            'quiet': False,
            'verbose': True,
            'no_warnings': False,
            'socket_timeout': 30,
            'retries': 10,
            
            # CRITICAL: Do NOT force source_address on Render/Cloud if they use NAT/IPv6
            # Removing 'source_address' might actually fix it if '0.0.0.0' is blocked
            # 'source_address': '0.0.0.0', 
            
            'user_agent': ua,
            'nocheckcertificate': True,
            'ignoreerrors': True, # Don't crash on one error
            
            # Cookies from a browser (optional, can be passed if needed)
            # 'cookiesfrombrowser': ('chrome',), 
            
            # Format: prioritizing mp4 but falling back to anything
            'format': 'best[ext=mp4]/best',
        }
        
        # Check for ffmpeg but don't fail if missing (yt-dlp can download without it sometimes)
        ffmpeg_path = get_ffmpeg_path()
        if ffmpeg_path and os.path.exists(ffmpeg_path):
             ydl_opts['ffmpeg_location'] = os.path.dirname(ffmpeg_path)
        
        try:
            loop = asyncio.get_running_loop()
            
            # Direct download attempt without pre-extraction (faster, less prone to blocking)
            await loop.run_in_executor(None, lambda: self._run_ytdlp(ydl_opts, url))
            
            if self.status_callback:
                self.status_callback(index, "Completed")
            
            # Scan for the file we just downloaded
            # Since we didn't get the filename upfront, we look for the most recent file
            # This is a robust fallback
            files = sorted(
                [os.path.join(self.dest_folder, f) for f in os.listdir(self.dest_folder)],
                key=os.path.getmtime,
                reverse=True
            )
            if files:
                self.downloaded_files.append(files[0])

        except Exception as e:
            error_msg = strip_ansi(str(e))
            if self.status_callback:
                self.status_callback(index, f"Error: {error_msg}")
            print(f"Download Error for {url}: {e}")

    def _run_ytdlp(self, opts, url):
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    async def download_file(self, session, task):
        if not self.is_running:
            return

        index = task['index']
        url = task['url']
        filename = task.get('filename')
        retries = 3
        
        if not filename:
            filename = url.split('/')[-1]
            if '?' in filename:
                filename = filename.split('?')[0]
            if not filename:
                filename = f"file_{index}"

        filepath = os.path.join(self.dest_folder, filename)
        
        for attempt in range(retries):
            if not self.is_running:
                return

            if self.status_callback:
                status_text = "Downloading..." if attempt == 0 else f"Retrying ({attempt+1}/{retries})..."
                self.status_callback(index, status_text)

            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        total_size = int(response.headers.get('content-length', 0))
                        downloaded = 0
                        
                        async with aiofiles.open(filepath, mode='wb') as f:
                            async for chunk in response.content.iter_chunked(8192):
                                if not self.is_running:
                                    if self.status_callback:
                                        self.status_callback(index, "Stopped")
                                    return
                                await f.write(chunk)
                                downloaded += len(chunk)
                                if total_size > 0 and self.progress_callback:
                                    percent = int(downloaded * 100 / total_size)
                                    self.progress_callback(index, percent)
                        
                        if self.status_callback:
                            self.status_callback(index, "Completed")
                        if self.progress_callback:
                            self.progress_callback(index, 100)
                        self.downloaded_files.append(filepath)
                        return # Success, exit loop
                    else:
                        error_msg = f"HTTP Error {response.status}"
            except Exception as e:
                error_msg = f"Error: {str(e)}"
            
            # If we are here, it failed
            if attempt < retries - 1:
                await asyncio.sleep(1) # Wait before retry
            else:
                # Final failure
                if self.status_callback:
                    self.status_callback(index, f"Failed: {error_msg}")

    def stop(self):
        self.is_running = False
