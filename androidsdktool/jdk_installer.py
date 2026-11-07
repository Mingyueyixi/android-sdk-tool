# encoding: utf-8
"""JDK 自动安装配置工具。

从 deps.json 读取当前平台的 JDK 下载地址，下载解压到 ~/.jdks，
并更新当前进程的 JAVA_HOME 与 PATH（不污染系统配置）。
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from .downloader import Downloader

# 本模块所在目录（deps.json 所在目录）
_DEPS_DIR = Path(__file__).resolve().parent


class JdkInstaller:
    """JDK 安装器，负责下载、解压 JDK 到 ~/.jdks 并设置环境变量"""

    _DEFAULT_JDKS_HOME = Path(os.path.expanduser("~")) / ".jdks"
    _DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads"

    @staticmethod
    def _resolve_bin_dir(jdk_root: Path) -> Path:
        """解析 JDK 的 bin 目录。

        macOS 的 Adoptium tar.gz 解压后是 Contents/Home/bin/java，
        而 Windows/Linux 是直接 bin/java。
        """
        if platform.system() == "Darwin":
            contents_home = jdk_root / "Contents" / "Home"
            if contents_home.is_dir():
                return contents_home / "bin"
        return jdk_root / "bin"

    @staticmethod
    def _resolve_java_home(jdk_root: Path) -> Path:
        """解析 JAVA_HOME 路径。

        macOS 需要指向 Contents/Home，Windows/Linux 就是 jdk 根目录。
        """
        if platform.system() == "Darwin":
            contents_home = jdk_root / "Contents" / "Home"
            if contents_home.is_dir():
                return contents_home
        return jdk_root

    @staticmethod
    def get_version(java_home: str) -> int:
        """获取指定 JAVA_HOME 下的 JDK 主版本号，失败返回 0"""
        java_home_path = Path(java_home)
        bin_dir = JdkInstaller._resolve_bin_dir(java_home_path)
        java_bin = "java.exe" if platform.system() == "Windows" else "java"
        result = subprocess.run(
            [str(bin_dir / java_bin), "-version"],
            capture_output=True, text=True
        )
        m = re.search(r'version "([^"]+)"', result.stderr)
        if not m:
            return 0
        v = m.group(1)
        # Java 8: "1.8.0_xxx" → 8, Java 17: "17.0.12" → 17
        major = int(v.split(".")[0]) if v.split(".")[0] != "1" else int(v.split(".")[1])
        return major

    @staticmethod
    def _get_os_key() -> str:
        """返回 deps.json 中对应的 os 字段"""
        system = platform.system()
        if system == "Windows":
            return "windows"
        elif system == "Darwin":
            return "mac"
        else:
            return "linux"

    def __init__(self, jdks_home: Path | str | None = None, download_dir: Path | str | None = None):
        self._jdks_home = Path(jdks_home) if jdks_home else self._DEFAULT_JDKS_HOME
        self._download_dir = Path(download_dir) if download_dir else self._DEFAULT_DOWNLOAD_DIR
        self._deps_config: dict | None = None

    def _load_config(self) -> dict:
        if self._deps_config is None:
            config_path = _DEPS_DIR / "deps.json"
            with open(config_path, "r", encoding="utf-8") as f:
                self._deps_config = json.load(f)
        return self._deps_config

    def _get_download_url(self) -> str:
        """从 deps.json 获取当前平台 JDK 下载 URL"""
        config = self._load_config()
        os_key = self._get_os_key()
        entries = config.get("jdks", {}).get(os_key, [])
        if not entries:
            raise RuntimeError(f"deps.json 中未找到 jdks.{os_key} 配置")
        # 优先匹配当前架构，否则取第一个
        machine = platform.machine().lower()
        arch_map = {"amd64": "x64", "x86_64": "x64", "aarch64": "aarch64"}
        current_arch = arch_map.get(machine, machine)
        for entry in entries:
            if entry.get("arch") == current_arch:
                return entry["url"]
        return entries[0]["url"]

    def _extract(self, archive_path: Path) -> Path:
        """解压 JDK 到 _jdks_home，返回解压后的 JDK 根目录（保留压缩包自带目录名）"""
        shutil.unpack_archive(str(archive_path), self._jdks_home)

        # 找到解压后的根目录（压缩包通常只有一层子目录）
        for item in self._jdks_home.iterdir():
            if item.is_dir():
                return item

        raise RuntimeError("解压后未找到 JDK 目录")

    def _update_process_env(self, jdk_dir: Path) -> None:
        """更新当前 Python 进程的 os.environ"""
        java_home = self._resolve_java_home(jdk_dir)
        java_home_str = str(java_home)
        bin_dir = self._resolve_bin_dir(jdk_dir)
        bin_path = str(bin_dir)
        os.environ["JAVA_HOME"] = java_home_str
        existing_path = os.environ.get("PATH", "")
        if bin_path not in existing_path.split(os.pathsep):
            os.environ["PATH"] = bin_path + os.pathsep + existing_path
        print(f"当前进程 JAVA_HOME 已更新: {java_home_str}")

    def _find_existing(self, version: str) -> Path | None:
        """在 _jdks_home 目录下查找是否已有满足版本的 JDK，返回其路径或 None"""
        version_int = int(version)
        self._jdks_home.mkdir(parents=True, exist_ok=True)
        for item in self._jdks_home.iterdir():
            if not item.is_dir():
                continue
            if item.name.startswith("."):
                continue
            try:
                if self.get_version(str(item)) >= version_int:
                    return item
            except Exception:
                continue
        return None

    def install(self, version: str = "17") -> None:
        """下载并安装 JDK 到 _jdks_home 目录，更新当前进程 os.environ

        流程：
        1. 检查系统当前 java 版本是否满足要求 → 直接使用
        2. 若 _jdks_home 下已有解压好的 JDK → 直接更新 os.environ
        3. 否则 → 下载 → 解压 → 更新 os.environ
        """
        min_version = int(version)
        max_version = min_version + 4  # 允许最大版本，如要求 17 则 21 也可用

        # 1. 检查系统当前 java 版本
        java_home = os.environ.get("JAVA_HOME", "")
        if java_home:
            try:
                major = self.get_version(java_home)
                if min_version <= major <= max_version:
                    print(f"系统 Java {major} ({java_home}) 满足要求 ({min_version}~{max_version})，直接使用")
                    self._update_process_env(Path(java_home))
                    return
            except Exception:
                pass

        self._jdks_home.mkdir(parents=True, exist_ok=True)

        # 2. 检查 _jdks_home 下是否已有解压好的 JDK
        existing_jdk = self._find_existing(version)
        if existing_jdk:
            print(f"{self._jdks_home} 中已有 JDK {existing_jdk.name} (>= {version})，直接使用")
            self._update_process_env(existing_jdk)
            return

        # 3. 下载并解压 JDK
        url = self._get_download_url()
        downloader = Downloader()
        archive_path = downloader.download(url, dest_dir=self._download_dir, label="JDK")
        archive_stem = Path(urlparse(url).path).stem
        # 检查解压目标是否已存在
        for item in self._jdks_home.iterdir():
            if item.is_dir() and not item.name.startswith(".") and item.name.startswith(archive_stem):
                print(f"{self._jdks_home} 中已有解压好的 JDK: {item.name}，直接使用")
                self._update_process_env(item)
                return

        print(f"正在解压 JDK 到 {self._jdks_home} ...")
        jdk_root = self._extract(archive_path)
        print(f"JDK 安装完成: {jdk_root}")

        # 更新当前进程环境变量
        self._update_process_env(jdk_root)
