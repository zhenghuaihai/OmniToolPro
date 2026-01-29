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
        # Heuristic: if it doesn't look like a direct file, try yt-dlp
        # Or check for common video sites
        common_sites = ['youtube.com', 'youtu.be', 'bilibili.com', 'tiktok.com', 'douyin.com', 'vimeo.com', 'twitter.com', 'x.com']
        if any(site in url for site in common_sites):
            return True
        # If it doesn't have a file extension, assume it might be a video page
        if not os.path.splitext(url)[1]:
            return True
        return False

    async def download_with_ytdlp(self, task):
        if not self.is_running: return
        
        index = task['index']
        url = task['url']
        
        if self.status_callback:
            self.status_callback(index, "Analyzing (yt-dlp)...")
            
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

        ffmpeg_path = get_ffmpeg_path()
        ydl_opts = {
            'outtmpl': os.path.join(self.dest_folder, '%(title)s.%(ext)s'),
            'progress_hooks': [ytdlp_progress_hook],
            'ffmpeg_location': os.path.dirname(ffmpeg_path), # yt-dlp expects dir
            'quiet': True,
            'no_warnings': True,
        }
        
        try:
            # yt-dlp is blocking, run in executor
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: self._run_ytdlp(ydl_opts, url))
            
            if self.status_callback:
                self.status_callback(index, "Completed")
            
            # Find the downloaded file (heuristic)
            # Since we don't know the exact filename easily without parsing, 
            # we might just scan dir for newest file or return success.
            # For simplicity, we just mark success. 
            # Ideally we capture the filename from info_dict.
            # Re-run extract_info to get filename? No, expensive.
            # Let's trust it worked.
            
            # Use 'downloaded_files' only if we can verify.
            # We can use 'prepare_filename' from yt-dlp logic if needed, but let's skip for now.
            # For 'Batch Download' it might be tricky to zip if we don't know the name.
            # FIX: Get filename from info first.
            info = await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=False))
            filename = yt_dlp.YoutubeDL(ydl_opts).prepare_filename(info)
            self.downloaded_files.append(filename)

        except Exception as e:
            if self.status_callback:
                self.status_callback(index, f"Error: {strip_ansi(str(e))}")

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
