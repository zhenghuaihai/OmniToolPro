# Web 应用迁移计划 (Python/Streamlit)

用户希望将现有的本地 PyQt6 桌面应用转换为 Web 应用，以便于分发。考虑到现有 Python 业务逻辑（下载、Whisper、DeepSeek）的复用性，以及快速开发的需要，我建议使用 **Streamlit** 框架。它能极快地将 Python 脚本转换为交互式 Web 应用，非常适合数据处理工具。

## 1. 技术栈变更
*   **前端/框架**: 移除 `PyQt6`，替换为 `Streamlit`。Streamlit 内置了美观的 UI 组件，无需手写 HTML/CSS。
*   **核心逻辑**: 保留 `core/` 下的 `downloader.py` (需调整为同步或适配 Streamlit 的 async 运行方式), `transcriber.py`, `summarizer.py`, `audio_extractor.py`。这些业务逻辑代码 90% 可以复用。
*   **部署**: Web 应用可以直接部署在服务器上，用户通过浏览器访问，无需安装客户端。

## 2. 迁移步骤

### 第一阶段：环境与依赖调整
1.  **清理**: 移除 PyQt6 相关代码和依赖。
2.  **安装**: 添加 `streamlit` 到 `requirements.txt`。

### 第二阶段：核心逻辑适配
1.  **异步处理**: Streamlit 运行在同步模式下较好控制，但为了性能，可以使用 `asyncio` 配合 `streamlit.empty()` 进行进度更新。需要微调 `downloader.py` 的回调机制，使其适配 Streamlit 的进度条。
2.  **状态管理**: 使用 `st.session_state` 来管理下载任务列表、API Key、处理状态等。

### 第三阶段：UI 重构 (Web 化)
1.  **主布局**: 使用 `st.sidebar` 实现导航（"批量下载" vs "视频分析"）。
2.  **批量下载页面**:
    *   使用 `st.text_area` 输入 URL。
    *   使用 `st.text_input` 输入保存路径 (Web 版通常下载到服务器临时目录，然后提供 Zip 打包下载，或者如果是本地部署则保留本地路径选择)。**考虑到用户可能在本地运行 Web 界面，我们保留“服务器端路径”输入，同时提供“下载到浏览器”的选项（如果技术可行）。** *修正：作为工具站，通常是服务器处理完提供下载链接。我们将实现“处理后打包下载”的流程。*
3.  **视频分析页面**:
    *   支持 `st.file_uploader` 上传本地视频。
    *   支持 URL 输入。
    *   处理流程：下载/上传 -> 提取音频 -> Whisper 转写 -> DeepSeek 摘要 -> 显示结果 -> 提供 Zip 下载。

### 第四阶段：功能实现细节
*   **DeepSeek 配置**: 在侧边栏提供 API Key 配置输入框。
*   **实时反馈**: 使用 `st.progress` 和 `st.status` (Streamlit 新特性) 显示下载和处理进度。

## 3. 交付物
*   `app.py`: 新的 Web 应用入口。
*   更新后的 `requirements.txt`。
*   移除旧的 `ui/` 文件夹（PyQt 代码）。

## 关键优势
*   **分发容易**: 用户只需浏览器即可访问。
*   **开发极快**: 复用现有核心 Python 代码。
*   **美观**: Streamlit 默认界面简洁现代。
