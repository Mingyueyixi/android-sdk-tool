# encoding: utf-8
"""构建环境自动配置：JDK + Android SDK + gradlew 修复。

自 scripts/utils/install_env.py 迁移，编排新方案的各个工具类。
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

from .android_sdk_installer import AndroidSDKInstaller
from .jdk_installer import JdkInstaller


def _fix_gradlew_permissions(project_root: Path) -> None:
    """修复 gradlew 的换行符和执行权限（Linux/macOS）"""
    if platform.system() == "Windows":
        return
    gradlew = project_root / "gradlew"
    if not gradlew.is_file():
        return
    # 修复 CRLF → LF
    content = gradlew.read_bytes()
    if b"\r\n" in content or b"\r" in content:
        gradlew.write_bytes(content.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
        print(f"已修复 gradlew 换行符: {gradlew}")
    # 修复执行权限
    gradlew.chmod(0o755)
    print(f"已修复 gradlew 执行权限: {gradlew}")


def _read_gradle_properties(project_root: Path) -> dict[str, str]:
    """从 gradle.properties 读取键值对"""
    props = {}
    prop_file = project_root / "gradle.properties"
    if not prop_file.is_file():
        return props
    for line in prop_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            props[k.strip()] = v.strip()
    return props


def _resolve_sdk_packages(project_root: Path) -> list[str]:
    """根据 gradle.properties 解析需要的 Android SDK 包"""
    props = _read_gradle_properties(project_root)
    packages = ["platform-tools"]
    compile_sdk = props.get("COMPILE_SDK_VERSION")
    build_tools = props.get("BUILD_TOOLS_VERSION")
    if compile_sdk:
        packages.append(f"platforms;android-{compile_sdk}")
    if build_tools:
        packages.append(f"build-tools;{build_tools}")
    return packages


def resolve_sdk_packages(project_root: Path | None = None) -> list[str]:
    """解析需要的 Android SDK 包（无工程时仅安装基础组件）"""
    if not project_root:
        return ["platform-tools"]
    return _resolve_sdk_packages(Path(project_root))


def install_android_sdk(project_root: Path | None = None):
    """安装 Android SDK（cmdline-tools + SDK 组件）

    检查系统 ANDROID_HOME 是否有效（sdkmanager 存在），否则用默认路径。
    """
    project_root = Path(project_root) if project_root else Path(os.getcwd())
    packages = _resolve_sdk_packages(project_root)

    # 检查系统 ANDROID_HOME 是否有效（sdkmanager 存在），否则用默认路径
    sdk_home = os.environ.get("ANDROID_HOME", "")
    installer = AndroidSDKInstaller(sdk_home=sdk_home if sdk_home else None)
    if not installer.is_installed():
        installer = AndroidSDKInstaller()  # 回退到默认路径
    installer.install_cmdline_tools()
    installer.install_packages(packages)
    installer._update_process_env()
    return installer


# 便捷函数
get_jdk_version = JdkInstaller.get_version


def install_jdk(version: str = "17"):
    """安装 JDK，下载解压后更新当前进程 os.environ"""
    JdkInstaller().install(version)


class InstallEnvTask:
    """安装构建环境（Android SDK、JDK）"""

    def __init__(self, project_root: str | None = None):
        self._project_root = Path(project_root) if project_root else Path(os.getcwd())

    def run(self):
        install_jdk()
        install_android_sdk(self._project_root)
        _fix_gradlew_permissions(self._project_root)


def main():
    """命令行入口：一键配置构建环境（JDK + Android SDK）"""
    InstallEnvTask().run()


if __name__ == "__main__":
    main()
