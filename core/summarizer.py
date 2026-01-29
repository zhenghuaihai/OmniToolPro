from openai import OpenAI

class Summarizer:
    def __init__(self, api_key, base_url=None, model="gpt-3.5-turbo"):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.client = None

    def _get_client(self):
        if not self.client:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self.client

    def summarize(self, text, custom_prompt=None):
        if not text:
            return ""
            
        try:
            client = self._get_client()
            system_content = custom_prompt if custom_prompt else "You are a helpful assistant. Please summarize the following video transcript. Capture the key points and be concise."
            
            response = client.chat.completions.create(
                model="deepseek-chat", # Force use deepseek-chat which is valid for DeepSeek API
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": text}
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Summarization Error: {str(e)}"

    def refine_transcript(self, text):
        """
        Refine the transcript: add punctuation, fix formatting, and make it readable.
        """
        if not text: return ""
        try:
            client = self._get_client()
            system_content = """你是一位专业的中文编辑。用户将提供一段可能缺乏标点符号和段落的原始视频逐字稿（可能是繁体中文）。
你的任务是将其转换为一份“格式优美的简体中文逐字稿”：
1. 必须输出简体中文（Simplified Chinese）。
2. 根据上下文添加正确的标点符号（逗号、句号、问号等）。
3. 将文本分成逻辑清晰、易于阅读的段落。
4. 修正明显的错别字或大小写错误。
5. 保持内容逐字对应（不要总结，不要删除文字，不要改变原意）。
6. 仅返回格式化后的文本。
"""
            
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": text}
                ],
                timeout=60
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Refine Error: {e}")
            return text

    def summarize(self, text, custom_prompt=None):
        if not text:
            return ""
            
        try:
            client = self._get_client()
            system_content = custom_prompt if custom_prompt else """你是一位专业的视频内容分析师。请为以下视频逐字稿撰写一份结构清晰的摘要。
要求：
1. 使用简体中文。
2. 结构化输出：
   - **核心观点**：用一句话概括视频主旨。
   - **关键要点**：列出3-5个关键信息点，使用列表符号。
   - **总结**：简短的总结段落。
3. 格式清晰，分段合理，易于快速阅读。
"""
            
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": text}
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Summarization Error: {str(e)}"
