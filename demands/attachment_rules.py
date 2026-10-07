from pathlib import PurePath
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


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

HTTP_URL_VALIDATOR = URLValidator(schemes=["http", "https"])


def attachment_original_name(uploaded_file):
    name = str(uploaded_file.name).replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(character for character in name if 32 <= ord(character) != 127)
    return (name.strip() or "attachment")[:255]


def validate_http_result_url(value):
    result_url = (value or "").strip()
    if not result_url:
        raise ValidationError("必须填写成果链接。")

    try:
        HTTP_URL_VALIDATOR(result_url)
    except ValidationError as exc:
        raise ValidationError("成果链接必须是有效的 HTTP/HTTPS 地址。") from exc

    if urlsplit(result_url).scheme.lower() not in {"http", "https"}:
        raise ValidationError("成果链接只允许使用 HTTP 或 HTTPS。")
    return result_url


def validate_submission_materials(result_url, uploaded_files):
    files = list(uploaded_files or [])
    result_url = validate_http_result_url(result_url)

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
