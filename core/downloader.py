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
            self.status_callback(index, "Initializing...")
            
        def ytdlp_progress_hook(d):
            # IMPORTANT: Do not raise Exception here, it can crash the thread silently
            if not self.is_running:
                return 
            
            # Print to stdout so we can see it in Render logs
            print(f"HOOK [{d.get('status')}]: {d.get('_percent_str')}")

            if d.get('status') == 'downloading':
                if self.status_callback:
                    self.status_callback(index, "Downloading...")
                if self.progress_callback:
                    try:
                        p_str = d.get('_percent_str', '0%').replace('%','')
                        p_str = strip_ansi(p_str)
                        self.progress_callback(index, int(float(p_str)))
                    except: 
                        pass
            elif d.get('status') == 'finished':
                if self.progress_callback:
                    self.progress_callback(index, 100)
                if self.status_callback:
                    self.status_callback(index, "Processing File...")

        # ---------------------------------------------------------------------
        # THE FIX: Cookies + Cloudflare Warp / Proxy logic (if available)
        # ---------------------------------------------------------------------
        cookies_path = os.path.join(os.getcwd(), 'cookies.txt')
        
        ydl_opts = {
            'outtmpl': os.path.join(self.dest_folder, '%(title)s.%(ext)s'),
            'progress_hooks': [ytdlp_progress_hook],
            'quiet': False,
            'verbose': True,
            'no_warnings': False,
            
            # --- Network ---
            # Increase timeout significantly for slow cloud starts
            'socket_timeout': 60,
            'retries': 20,
            
            # --- Anti-Block ---
            # Sometimes 'android' client works better on cloud IPs than 'web'
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                },
            },
            
            # --- Format ---
            # Relax format to ensure SOMETHING downloads
            'format': 'best',
            
            # --- Certs ---
            'nocheckcertificate': True,
            'ignoreerrors': True,
        }
        
        if os.path.exists(cookies_path):
            ydl_opts['cookiefile'] = cookies_path
        
        ffmpeg_path = get_ffmpeg_path()
        if ffmpeg_path and os.path.exists(ffmpeg_path):
             ydl_opts['ffmpeg_location'] = os.path.dirname(ffmpeg_path)
        
        try:
            loop = asyncio.get_running_loop()
            
            # Use run_in_executor to prevent blocking the async loop
            print(f"Starting download for: {url}")
            await loop.run_in_executor(None, lambda: self._run_ytdlp(ydl_opts, url))
            print(f"Download finished for: {url}")
            
            # Verify file existence
            files = sorted(
                [os.path.join(self.dest_folder, f) for f in os.listdir(self.dest_folder)],
                key=os.path.getmtime,
                reverse=True
            )
            
            found = False
            if files:
                # Check if the newest file was created recently (within last 5 mins)
                # to avoid picking up old files
                import time
                if time.time() - os.path.getmtime(files[0]) < 300:
                    valid_files = [f for f in files if not f.endswith('.part') and not f.endswith('.ytdl')]
                    if valid_files:
                        self.downloaded_files.append(valid_files[0])
                        found = True
            
            if found:
                if self.status_callback:
                    self.status_callback(index, "Completed")
            else:
                # If yt-dlp didn't raise but no file found, it might be a silent failure or merge
                if self.status_callback:
                    self.status_callback(index, "Failed (No File)")

        except Exception as e:
            error_msg = strip_ansi(str(e))
            print(f"Download Exception: {e}")
            if self.status_callback:
                self.status_callback(index, f"Error: {error_msg}")

    def _run_ytdlp(self, opts, url):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as e:
            # Re-raise to be caught by the async wrapper
            raise e

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
