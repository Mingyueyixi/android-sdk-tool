# encoding: utf-8
from .downloader import Downloader
from .jdk_installer import JdkInstaller
from .android_sdk_installer import AndroidSDKInstaller

# install_env 采用延迟导入：直接运行 `python -m androidsdktool.install_env` 时，
# 若包 __init__ 先导入该模块会触发 runpy 的 RuntimeWarning（模块已存在于
# sys.modules 但尚未执行完毕）。通过 PEP 562 的 __getattr__ 保持
# `from androidsdktool import InstallEnvTask` 等用法可用。
_EXPORTS_INSTALL_ENV = (
    "InstallEnvTask",
    "install_android_sdk",
    "install_jdk",
    "resolve_sdk_packages",
)

__all__ = [
    "Downloader",
    "JdkInstaller",
    "AndroidSDKInstaller",
    # 以下符号由模块级 __getattr__ 延迟提供（PEP 562）
    *_EXPORTS_INSTALL_ENV,  # noqa: F822, E0603
]


def __getattr__(name: str):
    if name in _EXPORTS_INSTALL_ENV:
        from . import install_env
        return getattr(install_env, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
