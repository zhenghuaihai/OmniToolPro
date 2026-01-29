import streamlit as st
import os
import asyncio
import zipfile
import shutil
import config
import pandas as pd
import re
import imageio_ffmpeg
import stat
import time
from core.downloader import BatchDownloader
from core.audio_extractor import extract_audio
from core.transcriber import Transcriber
from core.summarizer import Summarizer

# --- FFmpeg Setup ---
def setup_ffmpeg():
    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        project_dir = os.getcwd()
        bin_dir = os.path.join(project_dir, "bin")
        os.makedirs(bin_dir, exist_ok=True)
        symlink_path = os.path.join(bin_dir, "ffmpeg")
        if os.path.exists(symlink_path):
            os.remove(symlink_path)
        os.symlink(ffmpeg_exe, symlink_path)
        st_mode = os.stat(symlink_path)
        os.chmod(symlink_path, st_mode.st_mode | stat.S_IEXEC)
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]
    except Exception as e:
        print(f"FFmpeg setup warning: {e}")

setup_ffmpeg()

# --- Page Config & CSS ---
st.set_page_config(page_title="OmniTool Pro", page_icon="⚡", layout="wide")

st.markdown("""
<style>
    /* Main Background & Fonts */
    .stApp {
        background-color: #F8FAFC;
        font-family: 'Inter', sans-serif;
    }
    
    /* Sidebar Styling */
    section[data-testid="stSidebar"] {
        background-color: #FFFFFF;
        border-right: 1px solid #E2E8F0;
    }
    
    /* Custom Headers */
    h1, h2, h3 {
        color: #0F172A;
        font-weight: 700;
    }
    
    /* Buttons - Indigo 600 */
    .stButton>button {
        background-color: #4F46E5;
        color: white;
        border-radius: 8px;
        border: none;
        font-weight: 600;
        transition: all 0.2s;
    }
    .stButton>button:hover {
        background-color: #4338CA;
        box-shadow: 0 4px 6px -1px rgba(79, 70, 229, 0.1), 0 2px 4px -1px rgba(79, 70, 229, 0.06);
    }
    
    /* Secondary Buttons */
    div[data-testid="stHorizontalBlock"] button {
        background-color: #F1F5F9;
        color: #475569;
    }
    
    /* Text Areas */
    .stTextArea textarea {
        border-radius: 12px;
        border: 1px solid #E2E8F0;
        background-color: #FFFFFF;
        padding: 1rem;
        font-family: monospace;
        font-size: 0.9rem;
    }
    .stTextArea textarea:focus {
        border-color: #4F46E5;
        box-shadow: 0 0 0 2px rgba(79, 70, 229, 0.1);
    }
    
    /* DataFrames / Tables */
    div[data-testid="stDataFrame"] {
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        background-color: white;
        padding: 0.5rem;
    }
    
    /* Cards */
    .css-card {
        background-color: white;
        border: 1px solid #E2E8F0;
        border-radius: 16px;
        padding: 1.5rem;
        box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06);
    }
    
    /* Status Badge */
    .status-badge {
        display: inline-flex;
        align-items: center;
        padding: 0.25rem 0.75rem;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .status-badge.success { background-color: #DCFCE7; color: #166534; }
    .status-badge.processing { background-color: #E0E7FF; color: #3730A3; }
    
    /* Summary Card Gradient */
    .summary-card {
        background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%);
        color: white;
        border-radius: 16px;
        padding: 1.5rem;
        box-shadow: 0 10px 15px -3px rgba(79, 70, 229, 0.3);
        margin-bottom: 1.5rem;
    }
    .summary-card h3 { color: white !important; }
    .summary-card p { color: rgba(255, 255, 255, 0.9); }
    
</style>
""", unsafe_allow_html=True)

# --- State Management ---
if "app_mode" not in st.session_state:
    st.session_state.app_mode = "Batch Download"
if "api_key" not in st.session_state:
    st.session_state.api_key = config.DEEPSEEK_API_KEY
if "save_mode" not in st.session_state:
    st.session_state.save_mode = "Web Zip"
if "batch_tasks" not in st.session_state:
    st.session_state.batch_tasks = []
if "analysis_results" not in st.session_state:
    st.session_state.analysis_results = {} # {filename: {'transcript':..., 'summary':..., 'segments':...}}
if "analysis_queue" not in st.session_state:
    st.session_state.analysis_queue = []
if "active_analysis_id" not in st.session_state:
    st.session_state.active_analysis_id = None

# --- Helper Functions ---
def extract_urls(text):
    urls = []
    for line in text.split('\n'):
        found = re.findall(r'https?://[^\s]+', line)
        for url in found:
            clean_url = url.strip('.,;!?`"\'()[]<>')
            if clean_url:
                urls.append(clean_url)
    return list(set(urls))

def format_timestamp(seconds):
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins:02d}:{secs:02d}"

# --- Sidebar ---
with st.sidebar:
    st.markdown("""
    <div style="padding: 1rem 0; margin-bottom: 1rem;">
        <div style="display: flex; align-items: center; gap: 0.5rem;">
            <div style="width: 32px; height: 32px; background-color: #4F46E5; border-radius: 8px; display: flex; align-items: center; justify-content: center;">
                <span style="color: white; font-weight: bold;">⚡</span>
            </div>
            <div>
                <h2 style="margin: 0; font-size: 1.1rem;">OmniTool<span style="color: #4F46E5;">Pro</span></h2>
                <p style="margin: 0; font-size: 0.7rem; color: #94A3B8;">BATCH & ANALYZE SUITE</p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    st.caption("TOOLS")
    
    # Navigation
    if st.button("📥 Batch Downloader", use_container_width=True, type="primary" if st.session_state.app_mode == "Batch Download" else "secondary"):
        st.session_state.app_mode = "Batch Download"
        st.rerun()
        
    if st.button("🎥 Video Analysis", use_container_width=True, type="primary" if st.session_state.app_mode == "Video Analysis" else "secondary"):
        st.session_state.app_mode = "Video Analysis"
        st.rerun()
        
    st.divider()
    
    st.caption("SETTINGS")
    
    # Settings
    save_pref = st.selectbox("Save Preference", ["Web Zip", "Local Storage"], index=0 if st.session_state.save_mode == "Web Zip" else 1)
    if save_pref != st.session_state.save_mode:
        st.session_state.save_mode = save_pref
        
    if st.session_state.save_mode == "Local Storage":
        st.text_input("Local Path", value=os.path.join(os.getcwd(), "downloads"), disabled=True, help="Fixed to ./downloads for now")
        
    new_key = st.text_input("DeepSeek API Key", value=st.session_state.api_key, type="password")
    if new_key != st.session_state.api_key:
        st.session_state.api_key = new_key
        
    st.divider()
    
    # User Profile Mock
    st.markdown("""
    <div style="display: flex; align-items: center; gap: 0.75rem; padding: 0.5rem; background-color: #F8FAFC; border-radius: 12px;">
        <div style="width: 36px; height: 36px; background-color: #E2E8F0; border-radius: 50%; display: flex; align-items: center; justify-content: center;">👤</div>
        <div style="flex: 1;">
            <p style="margin: 0; font-size: 0.85rem; font-weight: 600; color: #1E293B;">User</p>
            <p style="margin: 0; font-size: 0.7rem; color: #64748B;">Pro Plan</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

# --- Main Content ---

# Top Bar
col_header, col_status = st.columns([0.8, 0.2])
with col_status:
    st.markdown("""
    <div style="text-align: right; font-size: 0.75rem; font-weight: 500; color: #94A3B8; display: flex; align-items: center; justify-content: flex-end; gap: 0.5rem;">
        <span style="width: 8px; height: 8px; background-color: #10B981; border-radius: 50%; box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2);"></span>
        System Operational
    </div>
    """, unsafe_allow_html=True)

if st.session_state.app_mode == "Batch Download":
    st.title("Batch Downloader")
    st.markdown("Bulk download files from Douyin, TikTok, YouTube with auto-retry.")
    
    with st.container():
        st.markdown('<div class="css-card">', unsafe_allow_html=True)
        urls_input = st.text_area("Paste links here (one per line)", height=150, placeholder="https://v.douyin.com/...\nhttps://youtube.com/...")
        
        col_actions, _ = st.columns([0.2, 0.8])
        with col_actions:
            start_dl = st.button("🚀 Start Download", type="primary", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Progress Section
    progress_placeholder = st.empty()
    
    if start_dl and urls_input:
        urls = extract_urls(urls_input)
        if not urls:
            st.error("No valid URLs found.")
        else:
            tasks = [{'index': i, 'url': url} for i, url in enumerate(urls)]
            
            # Init Status
            status_list = [{"ID": i+1, "URL": u, "Status": "Pending", "Progress": 0} for i, u in enumerate(urls)]
            progress_placeholder.dataframe(pd.DataFrame(status_list), use_container_width=True, hide_index=True)
            
            # Callbacks
            def on_progress(idx, p):
                status_list[idx]["Progress"] = p
            def on_status(idx, s):
                status_list[idx]["Status"] = s
            
            dest = "downloads/batch"
            if not os.path.exists(dest): os.makedirs(dest, exist_ok=True)
            
            downloader = BatchDownloader(tasks, dest, on_progress, on_status)
            
            async def run_batch():
                task = asyncio.create_task(downloader.run_async())
                while not task.done():
                    df = pd.DataFrame(status_list)
                    progress_placeholder.dataframe(
                        df, 
                        use_container_width=True, 
                        hide_index=True,
                        column_config={
                            "Progress": st.column_config.ProgressColumn("Progress", format="%d%%", min_value=0, max_value=100),
                            "URL": st.column_config.LinkColumn("URL")
                        }
                    )
                    await asyncio.sleep(0.5)
                return await task
            
            downloaded = asyncio.run(run_batch())
            
            # Final State
            df = pd.DataFrame(status_list)
            progress_placeholder.dataframe(
                df, 
                use_container_width=True, 
                hide_index=True,
                column_config={
                    "Progress": st.column_config.ProgressColumn("Progress", format="%d%%", min_value=0, max_value=100),
                    "URL": st.column_config.LinkColumn("URL")
                }
            )
            
            if downloaded:
                st.success(f"Completed! {len(downloaded)} files downloaded.")
                if st.session_state.save_mode == "Web Zip":
                    zip_name = "batch_download.zip"
                    zip_path = os.path.join("downloads", zip_name)
                    with zipfile.ZipFile(zip_path, 'w') as zf:
                        for f in downloaded:
                            if os.path.exists(f):
                                zf.write(f, os.path.basename(f))
                    with open(zip_path, "rb") as f:
                        st.download_button("📦 Download ZIP", f, zip_name, "application/zip", type="primary")

elif st.session_state.app_mode == "Video Analysis":
    col_head_l, col_head_r = st.columns([0.8, 0.2])
    with col_head_l:
        st.title("AI Batch Analysis")
        st.markdown("Extract transcripts, summaries, and sentiment from videos.")
    with col_head_r:
        st.markdown('<div class="status-badge success" style="margin-top: 1rem;">Engine Ready</div>', unsafe_allow_html=True)
    
    # Input Area
    with st.expander("Add Videos to Queue", expanded=not st.session_state.analysis_queue):
        new_urls = st.text_area("Video URLs", height=100, placeholder="Paste URLs here...")
        if st.button("➕ Add to Queue"):
            if new_urls:
                extracted = extract_urls(new_urls)
                for url in extracted:
                    st.session_state.analysis_queue.append({
                        "id": f"task-{int(time.time())}-{len(st.session_state.analysis_queue)}",
                        "url": url,
                        "status": "Pending"
                    })
                st.rerun()

    if st.session_state.analysis_queue:
        col_q, col_d = st.columns([0.35, 0.65])
        
        # --- Left: Queue ---
        with col_q:
            st.markdown("### Queue")
            
            # Action Bar
            if st.button("▶️ Process All Pending", use_container_width=True, type="primary"):
                # PROCESS LOGIC
                pending_indices = [i for i, t in enumerate(st.session_state.analysis_queue) if t['status'] == "Pending"]
                
                if not pending_indices:
                    st.warning("No pending tasks.")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    work_dir = "downloads/analysis"
                    os.makedirs(work_dir, exist_ok=True)
                    
                    # 1. Download Phase
                    status_text.text("Downloading videos...")
                    dl_tasks = [{'index': i, 'url': st.session_state.analysis_queue[i]['url']} for i in pending_indices]
                    
                    # Track DL progress locally
                    def dl_cb(idx, p): pass 
                    
                    downloader = BatchDownloader(dl_tasks, work_dir, dl_cb, None)
                    downloaded_files = asyncio.run(downloader.run_async())
                    
                    # 2. Analysis Phase
                    transcriber = Transcriber()
                    summarizer = Summarizer(st.session_state.api_key, config.DEEPSEEK_BASE_URL)
                    
                    for i, file_path in enumerate(downloaded_files):
                        q_idx = pending_indices[i]
                        task = st.session_state.analysis_queue[q_idx]
                        
                        try:
                            status_text.text(f"Processing {task['url']}...")
                            base_name = os.path.basename(file_path)
                            
                            # Extract Audio
                            audio_path = os.path.join(work_dir, f"{base_name}.wav")
                            extract_audio(file_path, audio_path)
                            
                            # Transcribe
                            res = transcriber.transcribe(audio_path)
                            raw_text = res['text']
                            segments = res.get('segments', [])
                            
                            # Refine & Summarize
                            refined = summarizer.refine_transcript(raw_text)
                            summary = summarizer.summarize(refined)
                            
                            # Store Result
                            st.session_state.analysis_results[task['id']] = {
                                "summary": summary,
                                "transcript": refined,
                                "segments": segments,
                                "filename": base_name
                            }
                            
                            st.session_state.analysis_queue[q_idx]['status'] = "Completed"
                            st.session_state.active_analysis_id = task['id'] # Auto select
                            
                            # Cleanup
                            if os.path.exists(audio_path): os.remove(audio_path)
                            
                        except Exception as e:
                            st.session_state.analysis_queue[q_idx]['status'] = "Error"
                            st.error(f"Error processing {task['url']}: {e}")
                            
                        progress_bar.progress((i + 1) / len(downloaded_files))
                    
                    status_text.text("All done!")
                    st.rerun()

            st.markdown("<div style='height: 1rem;'></div>", unsafe_allow_html=True)

            # Queue List
            for task in st.session_state.analysis_queue:
                is_active = st.session_state.active_analysis_id == task['id']
                status_color = "#10B981" if task['status'] == "Completed" else "#64748B"
                if task['status'] == "Error": status_color = "#EF4444"
                
                # Custom Card Button
                card_style = f"""
                padding: 1rem;
                border-radius: 12px;
                border: 1px solid {'#4F46E5' if is_active else '#E2E8F0'};
                background-color: {'#EEF2FF' if is_active else 'white'};
                cursor: pointer;
                margin-bottom: 0.5rem;
                """
                
                # We use a button that looks like a card
                if st.button(f"{'✅' if task['status']=='Completed' else '⏳'} {task['url'][:30]}...", key=task['id'], use_container_width=True):
                    st.session_state.active_analysis_id = task['id']
                    st.rerun()

        # --- Right: Detail View ---
        with col_d:
            active_id = st.session_state.active_analysis_id
            result = st.session_state.analysis_results.get(active_id)
            
            if not active_id or not result:
                st.info("Select a completed task to view details.")
            else:
                # Summary Card
                st.markdown(f"""
                <div class="summary-card">
                    <h3 style="margin-top:0;">✨ AI Executive Summary</h3>
                    <p style="font-size: 0.95rem; line-height: 1.6;">{result['summary']}</p>
                </div>
                """, unsafe_allow_html=True)
                
                # Transcript Tabs
                tab1, tab2 = st.tabs(["📜 Refined Transcript", "⏱️ Timestamped Log"])
                
                with tab1:
                    st.text_area("Copy-ready Text", value=result['transcript'], height=400)
                    
                with tab2:
                    if result.get('segments'):
                        for seg in result['segments']:
                            ts = format_timestamp(seg['start'])
                            st.markdown(f"**`{ts}`** {seg['text']}")
                    else:
                        st.caption("No timestamp data available.")

    else:
        st.info("Queue is empty. Add videos to start.")
