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
            self.status_callback(index, "Processing...")
            
        # Use a simpler, more robust hook that doesn't rely on 'status' field presence
        def ytdlp_progress_hook(d):
            if not self.is_running:
                raise Exception("Stopped")
            
            # Print to logs for debugging Render
            print(f"yt-dlp hook: {d.get('status', 'unknown')} - {d.get('_percent_str', 'N/A')}")
            
            if d.get('status') == 'downloading':
                if self.progress_callback:
                    p_str = d.get('_percent_str', '0%').replace('%','')
                    try:
                        # Handle ANSI codes if present
                        p_str = strip_ansi(p_str)
                        self.progress_callback(index, int(float(p_str)))
                    except: pass
                if self.status_callback:
                    self.status_callback(index, "Downloading...")
            elif d.get('status') == 'finished':
                if self.progress_callback:
                    self.progress_callback(index, 100)

        # Minimalist Options - The "Nuclear Option" for compatibility
        # Remove all fancy headers, anti-bot, IP binding, etc.
        # Just pure, raw yt-dlp with cookie/cache disabled.
        
        ydl_opts = {
            'outtmpl': os.path.join(self.dest_folder, '%(title)s.%(ext)s'),
            'progress_hooks': [ytdlp_progress_hook],
            'quiet': False,
            'verbose': True,
            'no_warnings': False,
            
            # Use system default network stack (safest on cloud)
            # 'source_address': '0.0.0.0', # REMOVED
            # 'force_ipv4': True, # REMOVED - Let OS decide
            
            # Disable cache to prevent stale headers
            'cachedir': False,
            
            # Basic retries
            'socket_timeout': 30,
            'retries': 10,
            
            # Compatibility
            'nocheckcertificate': True,
            'ignoreerrors': True,
            
            # Format: prioritizing mp4
            'format': 'best[ext=mp4]/best',
        }
        
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
