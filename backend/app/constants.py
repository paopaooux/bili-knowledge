STAGES = ["parse", "acquire", "transcribe", "generate", "organize", "publish"]
STAGE_LABELS = {
    "parse": "解析",
    "acquire": "获取字幕/下载音频",
    "transcribe": "转写",
    "generate": "生成知识稿",
    "organize": "归档知识",
    "publish": "发布文档",
}
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}
