"""
安全与上传限制：文件名校验、路径规范、上传约束。
"""
import os
import re
import html

from core.document_loader import SUPPORTED_EXTENSIONS

# 允许的文档扩展名（与 ingestion 中一致）
# 增加 .xdmp（部分韩文/MarkLogic 导出会用到，按文本处理）
ALLOWED_EXTENSIONS = set(SUPPORTED_EXTENSIONS)

# 单文件最大大小（字节），默认 50MB
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

# 单次上传最多文件数
MAX_FILES_PER_UPLOAD = 20


def sanitize_filename(filename: str) -> str:
    """
    规范化文件名，防止路径穿越。
    只保留 basename；若输入含 .. 则拒绝；路径分隔符会先被 basename 去掉。
    """
    if not filename or not filename.strip():
        return ""
    raw = filename.strip()
    # 反转义浏览器/前端可能传入的 HTML 实体（如 &amp; / &amp;amp;）
    # 有些场景会发生“重复转义”，因此做有限次数的迭代反转义直到稳定。
    for _ in range(3):
        nxt = html.unescape(raw)
        if nxt == raw:
            break
        raw = nxt
    # 禁止路径穿越（../ 或 .. 在任意位置）
    if ".." in raw:
        return ""
    name = os.path.basename(raw)
    if not name:
        return ""
    # 只保留安全字符（字母、数字、中文、.-_ 空格等）
    # 允许少量常见符号：& + ( )
    if not re.match(r"^[\w\u4e00-\u9fff\s.\-&+()]+$", name):
        return ""
    return name


def is_allowed_extension(filename: str) -> bool:
    """检查扩展名是否在允许列表中。"""
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def resolve_path_under(base_dir: str, filename: str) -> str | None:
    """
    将 filename 解析为 base_dir 下的路径；若输入含 .. 或结果不在 base_dir 内则返回 None。
    """
    raw = (filename or "").strip()
    if ".." in raw:
        return None
    safe = sanitize_filename(filename)
    if not safe:
        return None
    base = os.path.realpath(base_dir)
    path = os.path.realpath(os.path.join(base_dir, safe))
    if not path.startswith(base + os.sep) and path != base:
        return None
    return path
