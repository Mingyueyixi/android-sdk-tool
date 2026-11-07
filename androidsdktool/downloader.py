# encoding: utf-8
"""通用文件下载工具，支持 sha1 校验。"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Callable, Optional

import requests


class Downloader:
    """通用文件下载工具类"""

    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }

    def __init__(self, dest_dir: Path | str | None = None):
        self._default_dest_dir = Path(dest_dir) if dest_dir else Path.home() / "Downloads"

    @staticmethod
    def sha1_of(file_path: Path) -> str:
        """计算文件 sha1 值"""
        h = hashlib.sha1()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _checksum_ok(self, file_path: Path, sha1: str) -> bool:
        actual = self.sha1_of(file_path)
        if actual.lower() == sha1.lower():
            return True
        print(f"sha1 校验失败: 期望 {sha1}，实际 {actual}")
        return False

    def download(
        self,
        url: str,
        dest_dir: Optional[Path | str] = None,
        filename: Optional[str] = None,
        label: str = "文件",
        sha1: Optional[str] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> Path:
        """下载文件到目标目录，已存在且校验通过则跳过。

        Args:
            url: 下载地址
            dest_dir: 下载目标目录，默认使用构造时指定的目录（无则为 ~/Downloads）
            filename: 保存的文件名，默认从 URL 中提取
            label: 日志中显示的名称，如 "JDK"、"cmdline-tools"
            sha1: 期望的 sha1 值，提供时会对已存在/下载完成的文件进行校验
            on_progress: 进度回调 (downloaded_bytes, total_bytes)

        Returns:
            下载后的文件路径

        Raises:
            RuntimeError: sha1 校验失败
        """
        target_dir = Path(dest_dir) if dest_dir else self._default_dest_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        if filename is None:
            filename = os.path.basename(url.split("?")[0])
        dest_file = target_dir / filename

        if dest_file.exists():
            if not sha1:
                print(f"{label} {filename} 已存在，跳过下载")
                return dest_file
            if self._checksum_ok(dest_file, sha1):
                print(f"{label} {filename} 已存在，sha1 校验通过，跳过下载")
                return dest_file
            print(f"{label} {filename} 已存在，但 sha1 校验失败，重新下载...")
            dest_file.unlink()

        print(f"正在下载 {label}: {filename} ...")
        try:
            with requests.get(url, stream=True, timeout=(10, 30), headers=self._HEADERS) as res:
                res.raise_for_status()
                content_length = int(res.headers.get("Content-Length") or 0)
                downloaded = 0
                with open(dest_file, "wb") as f:
                    for chunk in res.iter_content(1024 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if on_progress:
                            on_progress(downloaded, content_length)
                        elif content_length:
                            progress = min(100, int(100 * downloaded / content_length))
                            print(f"\r下载进度: {progress}%", end="", flush=True)
                        else:
                            print(f"\r已下载: {downloaded} bytes", end="", flush=True)
                print()
        except Exception as e:
            # 下载中断时清理半成品文件，避免下次误判为已下载
            try:
                dest_file.unlink()
            except OSError:
                pass
            raise

        print(f"{label} 下载完成: {dest_file}")
        if sha1 and not self._checksum_ok(dest_file, sha1):
            try:
                dest_file.unlink()
            except OSError:
                pass
            raise RuntimeError(f"{label} {filename} sha1 校验失败，已删除损坏文件")
        return dest_file
