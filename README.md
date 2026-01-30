---
title: OmniTool Pro
emoji: ⚡
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 8000
---

# OmniTool Pro - Media Research Suite

A powerful batch media downloader and analysis tool, powered by DeepSeek & Whisper.

## Features
- **Media Archiver**: Batch download videos from public URLs.
- **Content Insight**: Generate transcripts and AI summaries from videos.
- **Fair Use**: Designed for personal research and archiving.

## Deployment
This project is configured for **Hugging Face Spaces** (Docker SDK).
The `Dockerfile` handles system dependencies (FFmpeg) and Python environment.

## Environment Variables
To run this on Hugging Face Spaces, you must set the following Secret:
- `DEEPSEEK_API_KEY`: Your DeepSeek API Key.
