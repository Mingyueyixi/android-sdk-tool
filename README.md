# android sdk tool box

tools for android sdk

## install android sdk / jdk

```shell
uv run python -m androidsdktool.install_env
```

或在代码中调用：

```python
from androidsdktool import InstallEnvTask, install_jdk, install_android_sdk

install_jdk("17")                       # 自动下载解压 JDK 到 ~/.jdks，更新 JAVA_HOME
install_android_sdk()                   # 自动下载 cmdline-tools 并安装 SDK 组件
InstallEnvTask().run()                  # 一键配置构建环境（JDK + SDK + gradlew 修复）
```

自动配置流程：

1. 从 `deps.json` 读取当前平台的 JDK / cmdline-tools 下载地址（cmdline-tools 带 sha1 校验）
2. 已存在且校验通过的压缩包跳过下载
3. 通过 `sdkmanager` 自动接受许可，并按需安装组件（已安装的自动跳过）
4. 仅更新当前进程环境变量，不修改系统配置

如工程根目录存在 `gradle.properties`，会读取其中的 `COMPILE_SDK_VERSION`、
`BUILD_TOOLS_VERSION` 自动安装对应版本的组件。

## 模块结构

| 模块 | 职责 |
|---|---|
| `deps.json` | 各平台 JDK / cmdline-tools 下载源（含 sha1） |
| `downloader.py` | 通用下载器，支持 sha1 校验与中断清理 |
| `jdk_installer.py` | JDK 安装器（`~/.jdks` 复用、版本区间匹配、macOS 兼容） |
| `android_sdk_installer.py` | SDK 核心安装器（cmdline-tools + sdkmanager 组件安装） |
| `install_env.py` | 环境自动配置编排与命令行入口（JDK + SDK + gradlew 修复） |

## apk 签名

```shell
uv run python -m androidsdktool.apk_signer
```
