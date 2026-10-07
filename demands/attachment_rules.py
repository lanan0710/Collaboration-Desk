from pathlib import PurePath

from django.core.exceptions import ValidationError


MAX_ATTACHMENT_COUNT = 5
MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024
MAX_ATTACHMENT_TOTAL_SIZE = 50 * 1024 * 1024
ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".7z",
    ".csv",
    ".doc",
    ".docx",
    ".gif",
    ".gz",
    ".jpeg",
    ".jpg",
    ".json",
    ".md",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".rar",
    ".tar",
    ".tgz",
    ".txt",
    ".webp",
    ".xls",
    ".xlsx",
    ".zip",
}


def attachment_original_name(uploaded_file):
    name = str(uploaded_file.name).replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(character for character in name if 32 <= ord(character) != 127)
    return (name.strip() or "attachment")[:255]


def validate_submission_materials(result_url, uploaded_files):
    files = list(uploaded_files or [])
    result_url = (result_url or "").strip()

    if not result_url and not files:
        raise ValidationError("成果链接和附件至少需要提供一项。")
    if len(files) > MAX_ATTACHMENT_COUNT:
        raise ValidationError(f"一次最多上传 {MAX_ATTACHMENT_COUNT} 个附件。")

    total_size = 0
    for uploaded_file in files:
        original_name = attachment_original_name(uploaded_file)
        extension = PurePath(original_name).suffix.lower()
        if extension not in ALLOWED_ATTACHMENT_EXTENSIONS:
            raise ValidationError(
                f"附件“{original_name}”的文件类型不受支持，请使用文档、图片或压缩包格式。"
            )
        size = getattr(uploaded_file, "size", None)
        if size is None or size <= 0:
            raise ValidationError("不能上传空文件。")
        if size > MAX_ATTACHMENT_SIZE:
            raise ValidationError(
                f"附件“{uploaded_file.name}”超过 20 MiB 的单文件限制。"
            )
        total_size += size

    if total_size > MAX_ATTACHMENT_TOTAL_SIZE:
        raise ValidationError("附件总大小不能超过 50 MiB。")
    return result_url, files
