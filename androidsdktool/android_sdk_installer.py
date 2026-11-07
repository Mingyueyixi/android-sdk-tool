# encoding: utf-8
"""Android SDK 安装器，负责下载 cmdline-tools 并通过 sdkmanager 安装必要组件。

自 scripts/utils/android_sdk_installer.py 迁移，为新方案核心实现。
相对原版的完善（均内聚在原有方法中，不改变对外签名）：
1. cmdline-tools 下载增加 sha1 校验（deps.json 提供）
2. _accept_licenses 改为 stdin 喂入 y（原 yes | 管道在 Windows 不可用）
3. 运行 sdkmanager 前自动检测 Java 环境，缺失时联动 JdkInstaller 安装
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .downloader import Downloader
from .jdk_installer import JdkInstaller

# 本模块所在目录（deps.json 所在目录）
_DEPS_DIR = Path(__file__).resolve().parent


class AndroidSDKInstaller:
    """Android SDK 安装器，负责下载 cmdline-tools 并通过 sdkmanager 安装必要组件"""

    if platform.system() == "Windows":
        _DEFAULT_SDK_HOME = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "Android" / "Sdk"
    else:
        _DEFAULT_SDK_HOME = Path(os.path.expanduser("~")) / "Android" / "Sdk"
    _DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads"

    # 不再硬编码默认包，由 install_env 从 gradle.properties 读取后传入

    @staticmethod
    def _get_os_key() -> str:
        system = platform.system()
        if system == "Windows":
            return "windows"
        elif system == "Darwin":
            return "mac"
        else:
            return "linux"

    @staticmethod
    def _sdkmanager_name() -> str:
        return "sdkmanager.bat" if platform.system() == "Windows" else "sdkmanager"

    @staticmethod
    def _java_available() -> bool:
        """检查当前是否已有可用的 Java 环境"""
        java_home = os.environ.get("JAVA_HOME", "")
        if java_home:
            try:
                if JdkInstaller.get_version(java_home) > 0:
                    return True
            except Exception:
                pass
        return shutil.which("java") is not None

    def __init__(
        self,
        sdk_home: Path | str | None = None,
        download_dir: Path | str | None = None,
    ):
        self._sdk_home = Path(sdk_home) if sdk_home else self._DEFAULT_SDK_HOME
        self._download_dir = Path(download_dir) if download_dir else self._DEFAULT_DOWNLOAD_DIR
        self._deps_config: dict | None = None

    @property
    def sdk_home(self) -> Path:
        """当前使用的 SDK 安装目录"""
        return self._sdk_home

    def _load_config(self) -> dict:
        if self._deps_config is None:
            config_path = _DEPS_DIR / "deps.json"
            with open(config_path, "r", encoding="utf-8") as f:
                self._deps_config = json.load(f)
        return self._deps_config

    def _get_cmdline_tools_info(self) -> tuple[str, Optional[str]]:
        """从 deps.json 获取当前平台 cmdline-tools 的下载 URL 和 sha1

        Returns:
            (url, sha1) 元组
        """
        config = self._load_config()
        os_key = self._get_os_key()
        entries = config.get("cmdline-tools", {}).get(os_key, [])
        if not entries:
            raise RuntimeError(f"deps.json 中未找到 cmdline-tools.{os_key} 配置")
        entry = entries[0]
        return entry["url"], entry.get("sha1")

    @property
    def _cmdline_tools_dir(self) -> Path:
        """cmdline-tools 安装目录"""
        return self._sdk_home / "cmdline-tools" / "latest"

    @property
    def _sdkmanager_path(self) -> Path:
        return self._cmdline_tools_dir / "bin" / self._sdkmanager_name()

    def is_installed(self) -> bool:
        """检查 cmdline-tools 是否已安装"""
        return self._sdkmanager_path.is_file()

    def _ensure_java(self) -> None:
        """确保 sdkmanager 运行所需的 Java 环境可用，缺失时自动安装 JDK"""
        if self._java_available():
            return
        print("未检测到可用的 Java 环境，自动安装 JDK...")
        JdkInstaller(download_dir=self._download_dir).install("17")

    def _extract_cmdline_tools(self, archive_path: Path) -> Path:
        """解压 cmdline-tools 到 SDK 目录，返回 sdkmanager 所在目录"""
        # cmdline-tools 需要解压到 $SDK_HOME/cmdline-tools/latest/
        dest = self._cmdline_tools_dir
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)

        # 解压到临时目录
        tmp_dir = self._sdk_home / ".tmp_cmdline_tools"
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        shutil.unpack_archive(str(archive_path), tmp_dir)

        # cmdline-tools 压缩包解压后通常包含一个 cmdline-tools/ 目录
        # 将其内容移动到 latest/
        extracted_root = tmp_dir
        for item in tmp_dir.iterdir():
            if item.is_dir() and item.name == "cmdline-tools":
                extracted_root = item
                break

        # 移动内容到 latest/
        shutil.move(str(extracted_root), str(dest))
        shutil.rmtree(tmp_dir, ignore_errors=True)

        # Linux/macOS 需要给 bin 下的可执行文件添加执行权限
        if platform.system() != "Windows":
            bin_dir = dest / "bin"
            if bin_dir.is_dir():
                for f in bin_dir.iterdir():
                    if f.is_file() and not f.suffix:
                        f.chmod(0o755)

        return dest

    def _run_sdkmanager(self, *args: str, stdin_input: str | None = None) -> None:
        """运行 sdkmanager"""
        cmd = [str(self._sdkmanager_path), f"--sdk_root={self._sdk_home}", *args]
        subprocess.run(
            cmd, check=True,
            input=stdin_input, text=True,
        )

    def _update_process_env(self) -> None:
        """更新当前 Python 进程的 ANDROID_HOME 环境变量"""
        sdk_home_str = str(self._sdk_home)
        os.environ["ANDROID_HOME"] = sdk_home_str
        os.environ["ANDROID_SDK_ROOT"] = sdk_home_str

        # 添加 platform-tools 和 cmdline-tools 到 PATH
        paths_to_add = [
            str(self._sdk_home / "platform-tools"),
            str(self._cmdline_tools_dir / "bin"),
        ]
        existing_path = os.environ.get("PATH", "")
        for p in paths_to_add:
            if p not in existing_path.split(os.pathsep):
                existing_path = p + os.pathsep + existing_path
        os.environ["PATH"] = existing_path
        print(f"当前进程 ANDROID_HOME 已更新: {sdk_home_str}")

    def install_cmdline_tools(self) -> None:
        """下载并安装 cmdline-tools"""
        self._ensure_java()
        if self.is_installed():
            print(f"cmdline-tools 已安装: {self._cmdline_tools_dir}")
            return

        url, sha1 = self._get_cmdline_tools_info()
        downloader = Downloader()
        archive_path = downloader.download(
            url, dest_dir=self._download_dir, label="cmdline-tools", sha1=sha1
        )

        print(f"正在解压 cmdline-tools 到 {self._cmdline_tools_dir} ...")
        self._extract_cmdline_tools(archive_path)
        print("cmdline-tools 安装完成")

    def _package_installed(self, pkg: str) -> bool:
        """检查某个 SDK 包是否已在本地安装（通过检查目录是否存在）"""
        if pkg == "platform-tools":
            return (self._sdk_home / "platform-tools").is_dir()
        if pkg.startswith("platforms;"):
            api = pkg.split(";", 1)[1]  # e.g. "android-36"
            return (self._sdk_home / "platforms" / api).is_dir()
        if pkg.startswith("build-tools;"):
            version = pkg.split(";", 1)[1]  # e.g. "36.0.0"
            return (self._sdk_home / "build-tools" / version).is_dir()
        return False

    def _accept_licenses(self) -> None:
        """自动接受所有 SDK 许可（通过 stdin 喂入 y，跨平台可用）"""
        print("正在接受 Android SDK 许可...")
        cmd = [str(self._sdkmanager_path), f"--sdk_root={self._sdk_home}", "--licenses"]
        subprocess.run(
            cmd, check=True,
            input="y\n" * 30, text=True,
        )

    def install_packages(self, packages: list[str] | None = None) -> None:
        """通过 sdkmanager 安装指定的 SDK 包

        Args:
            packages: 要安装的包列表，默认安装 platform-tools
        """
        self._ensure_java()
        if not self.is_installed():
            raise RuntimeError("cmdline-tools 未安装，请先调用 install_cmdline_tools()")

        pkgs = packages if packages is not None else ["platform-tools"]

        # 过滤掉已安装的包
        missing = [p for p in pkgs if not self._package_installed(p)]
        if not missing:
            print(f"SDK 组件已全部安装: {', '.join(pkgs)}")
            return

        # 先接受所有 SDK 许可
        self._accept_licenses()

        print(f"正在安装 Android SDK 组件: {', '.join(missing)}")
        self._run_sdkmanager("--install", *missing, stdin_input="y\n" * 10)
        print("SDK 组件安装完成")

    def install(self, packages: list[str] | None = None) -> None:
        """一键安装 Android SDK（cmdline-tools + SDK 组件）并更新当前进程 os.environ

        流程：
        1. 确保 Java 环境可用（缺失时自动安装 JDK）
        2. 下载并解压 cmdline-tools
        3. 通过 sdkmanager 安装 SDK 组件
        4. 更新 os.environ
        """
        self.install_cmdline_tools()
        self.install_packages(packages)
        self._update_process_env()
