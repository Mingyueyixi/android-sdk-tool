import hashlib
import json
from pathlib import Path
import platform
import shutil
import sys
from urllib import parse
from urllib.parse import urljoin
import urllib.request
from lxml import etree
import re
import xml.etree.ElementTree as ET
import os
import subprocess
import requests

google_repository_url = "https://dl.google.com/android/repository/"
http_client = requests.Session()


class AndroidSDKInstaller:
    def __init__(self):
        pass

    def _get_namespace(self, element):
        """
        提取XML命名空间
        """
        # 获取tag中的命名空间，例如：{http://schemas.android.com/sdk/android/repo/repository2/03}remotePackage
        if element.tag.startswith("{"):
            return element.tag[1 : element.tag.find("}")]
        return None

    def _get_default_sdk_path(self):
        """
        根据不同操作系统返回 Android SDK 的默认安装路径
        这些路径是 Android Studio 默认使用的路径
        """
        system = os.name
        if system == "nt":  # Windows
            # Windows 系统下的默认路径
            return os.path.join(
                os.environ.get("LOCALAPPDATA", "C:\\Users\\Public"), "Android", "Sdk"
            )
        elif system == "posix":  # Unix/Linux/Mac
            # 检查是否为 macOS
            if "darwin" in os.sys.platform.lower():
                # macOS 系统下的默认路径
                return os.path.join(os.path.expanduser("~"), "Library", "Android", "sdk")
            else:
                # Linux 系统下的默认路径
                return os.path.join(os.path.expanduser("~"), "Android", "Sdk")
        else:
            # 其他系统使用用户主目录下的 Android/Sdk
            return os.path.join(os.path.expanduser("~"), "Android", "Sdk")

    def _get_all_cmdline_tools_archives(self):
        """
        获取所有 cmdline-tools 的 archive 信息
        """
        url = f"{google_repository_url}repository2-3.xml"

        try:
            # 获取 XML 内容
            print("Fetching XML data from Google repository...")
            with urllib.request.urlopen(url) as response:
                data = response.read()
            print("Parsing XML data...")
            # 使用 lxml 解析 XML
            root = etree.fromstring(data)
            # 查找所有 cmdline-tools 相关的 remotePackage
            packages = []
            # 使用 XPath 查找所有 path 以 "cmdline-tools" 开头的 remotePackage 元素
            cmdline_packages = root.xpath(
                '//remotePackage[starts-with(@path, "cmdline-tools")]'
            )
            print(f"Found {len(cmdline_packages)} cmdline-tools packages")

            # 遍历所有 cmdline-tools 包
            for package in cmdline_packages:
                path = package.get("path")
                # print(f"Processing package: {path}")

                # 创建包信息字典
                package_info = {}
                package_info["path"] = path

                # 从 path 中提取版本信息
                # path 格式类似于 "cmdline-tools;19.0" 或 "cmdline-tools;latest"
                package_info["version"] = path.split(";")[1] if ";" in path else "unknown"

                # 查找 revision 信息
                revision_elements = package.xpath(".//revision")
                if revision_elements:
                    revision_elem = revision_elements[0]
                    # 提取完整的 revision 字段信息
                    revision = {}
                    major_elem = revision_elem.xpath(".//major")
                    minor_elem = revision_elem.xpath(".//minor")
                    micro_elem = revision_elem.xpath(".//micro")
                    preview_elem = revision_elem.xpath(".//preview")

                    if major_elem:
                        revision["major"] = major_elem[0].text
                    if minor_elem:
                        revision["minor"] = minor_elem[0].text
                    if micro_elem:
                        revision["micro"] = micro_elem[0].text
                    if preview_elem:
                        revision["preview"] = preview_elem[0].text

                    package_info["revision"] = revision

                # 按 host-os 组织 archive 信息
                package_info["archives"] = {}

                # 查找所有的 archive 信息
                for archive in package.xpath(".//archive"):
                    # 获取 host OS 信息
                    host_os = archive.xpath(".//host-os")
                    if host_os:
                        os_name = host_os[0].text
                        archive_info = {}

                        # 获取下载信息
                        complete = archive.xpath(".//complete")
                        if complete:
                            size = complete[0].xpath(".//size")
                            if size:
                                archive_info["size"] = size[0].text

                            checksum = complete[0].xpath(".//checksum")
                            if checksum:
                                archive_info["checksum"] = checksum[0].text
                                # 获取 checksum 类型
                                ctype = checksum[0].get("type")
                                if ctype:
                                    archive_info["checksum-type"] = ctype

                            url_elem = complete[0].xpath(".//url")
                            if url_elem:
                                archive_info["url"] = url_elem[0].text

                        # 只有当有 url 时才添加到结果中
                        if "url" in archive_info and archive_info["url"]:
                            package_info["archives"][os_name] = archive_info
                            # print(f"  Found archive for {os_name}: {archive_info}")

                # 只有当有 archive 信息时才添加到结果中
                if package_info["archives"]:
                    packages.append(package_info)
                    # print(f"  Added package info: {package_info}")

            return packages

        except Exception as e:
            print(f"Error fetching or parsing XML: {e}")
            return []

    def _get_latest_cmdline_tools_version(self, all_cmdline_tools=None):
        """
        获取最新的 cmdline-tools 版本
        """
        if all_cmdline_tools is None:
            all_cmdline_tools = self._get_all_cmdline_tools_archives()

        if not all_cmdline_tools:
            print("No cmdline-tools packages found")
            return None

        # 按版本信息排序，取最新版本
        def version_key(package):
            # 优先使用 revision 信息
            if "revision" in package:
                revision = package["revision"]
                # 构建可比较的版本元组，预览版版本号设为0
                major = int(revision.get("major", 0))
                minor = int(revision.get("minor", 0))
                micro = int(revision.get("micro", 0))
                preview = revision.get("preview")
                # 如果是预览版，版本号设为0
                if preview is not None:
                    return (0, 0, 0)
                return (major, minor, micro)
            # 如果没有 revision 信息，使用从 path 提取的版本
            version = package["version"]
            if version == "latest":
                return (9999, 0, 0)  # 将 "latest" 视为非常高的版本
            # 简单的版本分割
            parts = version.split(".")
            if len(parts) >= 2:
                try:
                    major = int(parts[0])
                    minor = int(parts[1])
                    micro = int(parts[2]) if len(parts) > 2 else 0
                    return (major, minor, micro)
                except ValueError:
                    pass
            return (0, 0, 0)

        # 按版本排序，取最高版本
        latest_package = max(all_cmdline_tools, key=version_key)
        return latest_package

    def _check_file_checksum(self, file_path, checksum, checksum_type):
        with open(file_path, "rb") as f:
            if checksum_type == "sha1":
                file_checksum = hashlib.sha1(f.read()).hexdigest()
            return file_checksum == checksum

    def _download_cmdline_tools(self, url, checksum, checksum_type):
        try:
            with http_client.get(url, stream=True, timeout=(10, 10)) as res:
                res.raise_for_status()

                # 获取用户下载目录
                download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
                os.makedirs(download_dir, exist_ok=True)

                # 解析链接，获取最后的/部分，不要query参数
                url_info = parse.urlparse(url)
                filename = os.path.basename(url_info.path)
                download_file = Path(download_dir, filename)

                if download_file.exists():
                    if checksum and self._check_file_checksum(download_file, checksum, checksum_type):
                        print(f"File {filename} already exists, and checksum matches")
                        return download_file
                    else:
                        print(
                            f"File {filename} already exists, but checksum does not match, downloading again..."
                        )

                content_length = int(res.headers.get("Content-Length") or 0)
                downloaded = 0
                with open(download_file, "wb") as f:
                    for chunk in res.iter_content(1024 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if content_length:
                            progress = int(100 * downloaded / content_length)
                            print(f"\rDownloading {filename}...{progress}%", end="", flush=True)
                        else:
                            print(f"\rDownloading {filename}...{downloaded} bytes", end="", flush=True)
                print()

            print(f"Downloaded {filename}, start checking checksum...")
            if checksum and not self._check_file_checksum(download_file, checksum, checksum_type):
                print(
                    f"Downloaded failed, Checksum failed for {filename} , expected checksum: {checksum}, please redownload it."
                )
                try:
                    download_file.unlink()
                except Exception:
                    pass
                return None
            print(f"Downloaded successfully")
            return download_file
        except Exception as e:
            print(f"Download failed: {e}")
            return None

    def _get_cmdline_tools_lasted_dir(self, sdk_dir: Path):
        return sdk_dir / "cmdline-tools/latest"

    def _install_cmd_line_tools(self, zip_path: Path, sdk_dir: Path):
        cmdline_tools_lasted_dir = self._get_cmdline_tools_lasted_dir(sdk_dir)
        if cmdline_tools_lasted_dir.exists():
            shutil.rmtree(cmdline_tools_lasted_dir)

        unzip_dir = sdk_dir / ".temp/cmdline-tools"
        if unzip_dir.exists():
            shutil.rmtree(unzip_dir)
        shutil.unpack_archive(zip_path, unzip_dir)
        child_dir = unzip_dir / "cmdline-tools"
        if not child_dir.exists():
            child_dir = unzip_dir / "tools"

        if child_dir.exists():
            cmdline_tools_lasted_dir.parent.mkdir(parents=True, exist_ok=True)
            child_dir.rename(cmdline_tools_lasted_dir)
            shutil.rmtree(unzip_dir)

    def _build_exec_env_value_by_cmd(self, add_list: list, value_list: list):
        result = []
        all_list = set(value_list + add_list)
        for path in all_list:
            if " " in path:
                # cmd中，空格会被截断，需要用双引号括起来
                path = f'"{path}"'
            # cmd中%%是变量引用，会被自动转成实际值，需要使用^来保留原始值
            path = path.replace("^%", "%")
            path = path.replace("%", "^%")
            result.append(path)
        # cmd的值，不需要用双引号括起来，否则变量会被自动展开
        return ";".join(result)

    def _query_win_env_value(self, name, is_sys=False):
        """
        使用cmd命令查询特定环境变量的值
        """
        # 执行windows命令，从注册表获取用户path原始值
        if is_sys:
            # 获取系统级别环境变量
            cmd = rf'reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v {name}'
        else:
            # 获取用户环境变量
            cmd = rf'reg query "HKCU\Environment" /v {name}'
        print(cmd)
        result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, check=False)
        if not result.returncode == 0:
            return None, None, None
        
        cmd_stdout = result.stdout.decode()
        m = re.search(rf"{name}\s+(REG_.*?)\s+(.*)", cmd_stdout, re.I)
        # 注册表值类型：https://learn.microsoft.com/zh-cn/windows/win32/sysinfo/registry-value-types
        reg_value_type = m.group(1)
        env_value = m.group(2).strip()
        item_list = [p for p in env_value.split(";") if p.strip()]
        return env_value, reg_value_type, item_list
        
    def _append_env_value_by_powershell(self, name, add_list: list, value_type="REG_EXPAND_SZ"):
        """
        使用powershell为特定环境变量追加值，如path环境变量追加
        """
        env_value, reg_value_type, item_list = self._query_win_env_value(name)        
        if not reg_value_type:
            reg_value_type = value_type if value_type else "REG_EXPAND_SZ"

        pre_list = []
        if item_list:
            pre_list = item_list + add_list
        else:
            pre_list = add_list
        new_value = ";".join(set(pre_list))
        new_value = f'"{new_value}"'
        cmd = rf'powershell.exe reg add "HKCU\Environment" /v {name} /t {reg_value_type} /d {new_value} /f'
        print(cmd)
        os.system(cmd)

    def _append_env_value_by_cmd(self, name, add_list: list, value_type="REG_EXPAND_SZ", is_sys=True, existing_env_data=None):
        """
        使用cmd为特定环境变量追加值，如path环境变量追加
        
        Args:
            name: 环境变量名
            add_list: 要添加的值列表
            value_type: 注册表值类型
            is_sys: 是否为系统环境变量
            existing_env_data: 已经查询到的环境变量数据 (env_value, reg_value_type, item_list)，避免重复查询
        """
        if existing_env_data:
            env_value, reg_value_type, item_list = existing_env_data
        else:
            env_value, reg_value_type, item_list = self._query_win_env_value(name, is_sys=is_sys)
            
        if not reg_value_type:            
            reg_value_type = value_type if value_type else "REG_EXPAND_SZ"
        
        pre_item_list = []    
        # cmd中，%%是变量引用，会被自动转成实际值，需要使用^来保留原始值
        for item in item_list + add_list if item_list else add_list:
            # 把所有%全部替换成^%, 注意%前方不能有^，避免出现^^%
            item = re.sub(r"(?<!\^)%", r"^%", item)
            # cmd 中，带空格的路径还需要用双引号括起来，否则会被截断
            # 考虑路径中存在%%以及多个空格的情况，同时cmd这里不支持单引号，所以将空格部分都双引号括起来
            iter = re.finditer(r'(?<!")\s+(?!")', item)
            text = []
            last_end = 0
            while iter and True:
                try:
                    m = next(iter)
                    start = m.start()
                    end = m.end()
                    text.append(item[last_end:start])
                    text.append('"' + item[start:end] + '"')
                    last_end = end
                except StopIteration:
                    break
            if text:
                text.append(item[last_end:])
                item = "".join(text)        
            pre_item_list.append(item)
        new_value = ";".join(set(pre_item_list))
        if is_sys:
            # 系统级别环境变量，需要管理员权限
            cmd = rf'reg add "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v {name} /t {reg_value_type} /d {new_value} /f'            
        else:
            cmd = rf'reg add "HKCU\Environment" /v {name} /t {reg_value_type} /d {new_value} /f'
        print(cmd)
        os.system(cmd)

    def _set_win_env_value(self, name, value, value_type="REG_EXPAND_SZ", is_sys=False):
        """
        直接设置 Windows 环境变量值，替换已有值。
        """
        key = (
            "HKLM\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment"
            if is_sys
            else "HKCU\\Environment"
        )
        value = str(value)
        cmd = rf'reg add "{key}" /v {name} /t {value_type} /d "{value}" /f'
        print(cmd)
        os.system(cmd)

    def _set_android_home_windows(self, android_home: Path,  env_var_name="ANDROID_HOME"):
        """
        把ANDROID_HOME设置为Windows系统下的路径
        """
        android_home_str = str(android_home)
        env_value, reg_value_type, item_list = self._query_win_env_value(env_var_name, is_sys=False)
        if env_value:
            current_value = env_value.strip('"')
            if os.path.normcase(os.path.normpath(current_value)) != os.path.normcase(os.path.normpath(android_home_str)):
                self._set_win_env_value(env_var_name, android_home_str, is_sys=False)
        else:
            self._set_win_env_value(env_var_name, android_home_str, is_sys=False)

        # windows 的path路径添加
        add_list = [
            fr"%{env_var_name}%\tools\bin",
            fr"%{env_var_name}%\platform-tools",
            fr"%{env_var_name}%\cmdline-tools\latest\bin",
        ]
        
        path_value, reg_path_type, path_item_list = self._query_win_env_value("Path", is_sys=False)
        sys_path_value, reg_path_type, sys_path_item_list = self._query_win_env_value("Path", is_sys=True)
        merged_path_items = set(path_item_list + sys_path_item_list)
        
        # 过滤掉已经存在的路径
        filtered_add_list = [item for item in add_list if item not in merged_path_items]
        
        # 传入已查询到的Path环境变量数据，避免重复查询
        if filtered_add_list:
            self._append_env_value_by_cmd("Path", filtered_add_list, 
                                        existing_env_data=(path_value, reg_path_type, path_item_list), 
                                        is_sys=False)

    def _set_android_home_unix(self, android_home: Path,  env_var_name="ANDROID_HOME"):
        """
        把ANDROID_HOME设置为Unix/Linux/Mac系统下的路径
        """
        # 确定需要更新的配置文件
        home_dir = os.path.expanduser("~")
        
        # 确定当前用户的shell
        shell = os.environ.get("SHELL", "")
        
        # 选择适当的 shell 配置文件
        if "zsh" in shell:
            config_file = os.path.join(home_dir, ".zshrc")
        elif "bash" in shell:
            bash_profile = os.path.join(home_dir, ".bash_profile")
            bashrc = os.path.join(home_dir, ".bashrc")
            config_file = bash_profile if os.path.exists(bash_profile) else bashrc
        else:
            profile = os.path.join(home_dir, ".profile")
            config_file = profile if os.path.exists(profile) else os.path.join(home_dir, ".bashrc")

        # 确保配置文件所在目录存在
        config_dir = os.path.dirname(config_file)
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
            
        # 如果文件不存在，创建空文件
        if not os.path.exists(config_file):
            with open(config_file, "w") as f:
                f.write("")
        
        # 读取现有配置
        with open(config_file, "r") as f:
            content = f.read()

        # 使用正则表达式检查是否已存在ANDROID_HOME和PATH设置
        android_home_pattern = re.compile(rf'^\s*export\s+{env_var_name}\s*=.*$', re.MULTILINE)
        path_android_pattern = re.compile(rf'^\s*export\s+PATH\s*=.*{env_var_name}.*$', re.MULTILINE)
        
        android_home_exists = bool(android_home_pattern.search(content))
        path_with_android_exists = bool(path_android_pattern.search(content))

        # 构建要添加的内容
        android_home_line = f"export {env_var_name}={android_home}\n"
        path_line = f"export PATH=$PATH:${env_var_name}/tools/bin:${env_var_name}/platform-tools:${env_var_name}/cmdline-tools/latest/bin\n"
        
        # 添加ANDROID_HOME和PATH设置（如果不存在）
        new_content = content
        if not android_home_exists:
            # 在文件使用ANDROID_HOME之前添加ANDROID_HOME设置
            lines = new_content.splitlines()
            add_to_lines = False
            for line in range(len(lines)):  
                text = lines[line]              
                if f"${env_var_name}" in text:
                    lines.insert(line, android_home_line.strip())
                    add_to_lines = True
                    break
            if add_to_lines:
                new_content = "\n".join(lines)            
            else:
                new_content = new_content + "\n" + android_home_line
        else:
            # 更新现有的ANDROID_HOME值
            new_content = android_home_pattern.sub(f"export {env_var_name}={android_home}", new_content)
            
        if not path_with_android_exists:
            # 添加PATH设置
            new_content = new_content.rstrip() + f"\n{path_line}\n"
            
        # 写入更新后的内容
        with open(config_file, "w") as f:
            f.write(new_content)

        print(f"Updated {config_file} with {env_var_name} and PATH")

    def _set_android_home_env(self, android_sdk_dir: Path, env_var_name="ANDROID_HOME"):
        """
        把ANDROID_HOME写入到系统配置中
        """
        if platform.system() == "Windows":
            self._set_android_home_windows(android_sdk_dir, env_var_name)
        else:
            self._set_android_home_unix(android_sdk_dir, env_var_name)

    def _print_all_versions(self, all_archives: list, os_name: str):
        text = []
        for package in all_archives:
            path = package["path"]
            archive = package["archives"].get(os_name)
            url = archive["url"] if archive else None
            checksum = archive["checksum"] if archive else None
            checksum_type = archive["checksum-type"] if archive else None
            # url 拼接为完整的下载链接
            if url:
                url = urljoin(google_repository_url, url)
            text.append(f"{path} {url} {checksum_type}:{checksum}")
        print("\n".join(text))

    def _is_cmd_tools_exit(self, sdk_dir:str):
        cmdline_tools_dir = self._get_cmdline_tools_lasted_dir(Path(sdk_dir))
        # 目录非空
        return cmdline_tools_dir.exists() and cmdline_tools_dir.is_dir() and any(cmdline_tools_dir.iterdir())
    
    def _get_sdkmanager_path(self, android_home):
        """
        返回 sdkmanager 的绝对路径。
        """
        sdkmanager_path = Path(android_home) / "cmdline-tools" / "latest" / "bin" / "sdkmanager"
        if platform.system() == "Windows":
            sdkmanager_path = sdkmanager_path.with_suffix(".bat")

        if sdkmanager_path.exists():
            return sdkmanager_path

        sdkmanager_path = Path(android_home) / "tools" / "bin" / "sdkmanager"
        if platform.system() == "Windows":
            sdkmanager_path = sdkmanager_path.with_suffix(".bat")

        if sdkmanager_path.exists():
            return sdkmanager_path

        return None

    def _get_latest_build_tools_version(self, android_home):
        """
        通过sdkmanager获取最新的build-tools版本
        """
        sdkmanager_path = self._get_sdkmanager_path(android_home)
        if not sdkmanager_path:
            print("未找到 sdkmanager 工具")
            return None
        
        try:
            # 获取可用的包列表
            cmd = [str(sdkmanager_path), "--list"]
            print("正在获取可用的build-tools版本列表...")
            result = subprocess.run(
                cmd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=android_home
            )
            
            if result.returncode != 0:
                print(f"获取包列表失败: {result.stderr}")
                return None
            
            # 解析输出，查找 build-tools 相关行
            lines = result.stdout.split('\n')
            build_tools_versions = []
            
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("build-tools;") or "build-tools;" in stripped:
                    # 提取版本号
                    parts = stripped.split("build-tools;")
                    if len(parts) > 1:
                        version = parts[1].split()[0]
                        build_tools_versions.append(version)
            
            if not build_tools_versions:
                print("未找到任何build-tools版本")
                return None
            
            # 按版本号排序，返回最新版本
            def version_key(version_str):
                # 分割版本号为主版本号、次版本号和修订号
                parts = version_str.split(".")
                try:
                    return [int(part) for part in parts]
                except ValueError:
                    # 如果无法转换为整数，返回默认值
                    return [0, 0, 0]
            
            latest_version = max(build_tools_versions, key=version_key)
            print(f"找到最新build-tools版本: {latest_version}")
            return latest_version
            
        except Exception as e:
            print(f"获取build-tools版本时出现异常: {e}")
            return None
    
    def _get_latest_platforms_version(self, android_home):
        """
        通过sdkmanager获取最新的platforms版本（只取纯数字版本号，如 android-36）
        """
        sdkmanager_path = self._get_sdkmanager_path(android_home)
        if not sdkmanager_path:
            print("未找到 sdkmanager 工具")
            return None

        try:
            cmd = [str(sdkmanager_path), "--list"]
            print("正在获取可用的platforms版本列表...")
            result = subprocess.run(
                cmd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=android_home
            )

            if result.returncode != 0:
                print(f"获取包列表失败: {result.stderr}")
                return None

            lines = result.stdout.split('\n')
            platforms_versions = []

            for line in lines:
                stripped = line.strip()
                if stripped.startswith("platforms;android-"):
                    # 提取 android- 后面的版本号
                    parts = stripped.split("platforms;android-")
                    if len(parts) > 1:
                        version = parts[1].split()[0]
                        # 只保留纯数字版本号（过滤 Baklava/CANARY/CinnamonBun/ext 等非数字版本）
                        if re.match(r'^\d+(\.\d+)*$', version):
                            platforms_versions.append(version)

            if not platforms_versions:
                print("未找到任何platforms版本")
                return None

            def version_key(version_str):
                parts = version_str.split(".")
                try:
                    return [int(part) for part in parts]
                except ValueError:
                    return [0]

            latest_version = max(platforms_versions, key=version_key)
            print(f"找到最新platforms版本: android-{latest_version}")
            return latest_version

        except Exception as e:
            print(f"获取platforms版本时出现异常: {e}")
            return None

    def _install_build_tools(self, android_home, build_tools_version=None):
        """
        使用sdkmanager安装指定版本的build-tools，如果没有指定版本则安装最新版本
        """
        if not build_tools_version:
            build_tools_version = self._get_latest_build_tools_version(android_home)
            if not build_tools_version:
                print("无法获取最新build-tools版本")
                return False

        print(f"正在安装 build-tools 版本 {build_tools_version}...")

        return self._run_sdkmanager_install(android_home, f"build-tools;{build_tools_version}")

    def _install_platform_tools(self, android_home):
        """
        使用sdkmanager安装platform-tools
        """
        print("正在安装 platform-tools...")
        return self._run_sdkmanager_install(android_home, "platform-tools")

    def _install_platforms(self, android_home, platforms_version=None):
        """
        使用sdkmanager安装指定版本的platforms，如果没有指定版本则安装最新版本
        """
        if not platforms_version:
            platforms_version = self._get_latest_platforms_version(android_home)
            if not platforms_version:
                print("无法获取最新platforms版本")
                return False

        print(f"正在安装 platforms 版本 android-{platforms_version}...")

        return self._run_sdkmanager_install(android_home, f"platforms;android-{platforms_version}")

    def _run_sdkmanager_install(self, android_home, package):
        """
        执行sdkmanager安装命令
        """
        sdkmanager_path = self._get_sdkmanager_path(android_home)
        if not sdkmanager_path:
            print("未找到 sdkmanager 工具")
            return False

        try:
            cmd = [str(sdkmanager_path), package]
            print(f"执行命令: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                text=True,
                input="y\n",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=android_home
            )

            if result.returncode == 0:
                print(f"{package} 安装成功")
                return True
            else:
                print(f"安装失败: {result.stderr}")
                return False
        except Exception as e:
            print(f"安装过程中出现异常: {e}")
            return False

    def _install_ext_options(self, android_home):
        """
        安装扩展选项：build-tools、platform-tools、platforms
        """
        print("开始安装扩展选项...")
        self._install_build_tools(android_home)
        self._install_platform_tools(android_home)
        self._install_platforms(android_home)
        print("扩展选项安装完成")

    def run(self):
        # 当前系统名称
        os_name = platform.system()
        print(f"Current OS: {os_name}")
        if os_name == "darwin":
            os_name = "macosx"
        else:
            os_name = os_name.lower()

        all_archives = self._get_all_cmdline_tools_archives()
        if not all_archives:
            return
        self._print_all_versions(all_archives, os_name)

        android_sdk_dir_default = self._get_default_sdk_path()
        lasted_archive = self._get_latest_cmdline_tools_version(all_archives)
        url = urljoin(google_repository_url, lasted_archive["archives"][os_name]["url"])
        checksum = lasted_archive["archives"][os_name]["checksum"]
        checksum_type = lasted_archive["archives"][os_name]["checksum-type"]

        sys_android_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        sys_android_sdk_root = os.environ.get("ANDROID_SDK_ROOT")
        sdk_env_var_name = "ANDROID_SDK_ROOT" if sys_android_sdk_root else "ANDROID_HOME"

        # 预设所有可选动作
        actions = {
            "install_cmdline":     "Install cmdline-tools",
            "install_cmdline_ext": "Install cmdline-tools and ext options",
            "exit":                "Exit",
        }

        # 显示选项
        action_keys = list(actions.keys())
        print("Please choose an option:")
        for i, name in enumerate(action_keys, start=1):
            print(f"  {i}. {actions[name]}")
        print()

        valid_keys = "/".join(str(i) for i in range(1, len(action_keys) + 1))
        choice = input(f"Enter your choice ({valid_keys}): ").strip()

        # 通过索引获取用户选择的动作
        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(action_keys):
                raise ValueError
        except ValueError:
            print("Invalid choice, exiting...")
            return

        action = action_keys[idx]

        if action == "exit":
            print("Exiting...")
            return

        # install_cmdline 或 install_cmdline_ext，先确定安装路径
        if sys_android_home:
            # 用户已设置过环境变量，让其选择安装到默认路径还是已有路径
            print(f"Detected {sdk_env_var_name}={sys_android_home}")
            print(f"  1. Install to default path ({android_sdk_dir_default})")
            print(f"  2. Install to existing path ({sys_android_home})")
            path_choice = input("Enter your choice (1/2): ").strip()
            if path_choice == "1":
                target_sdk_path = android_sdk_dir_default
                set_env = True
            elif path_choice == "2":
                target_sdk_path = sys_android_home
                set_env = False
            else:
                print("Invalid choice, exiting...")
                return
        else:
            target_sdk_path = android_sdk_dir_default
            set_env = True

        # 下载 cmdline-tools
        cmdline_archive_file = self._download_cmdline_tools(url, checksum, checksum_type)
        if not cmdline_archive_file:
            print("cmdline-tools download failed; aborting.")
            return

        # 安装 cmdline-tools
        self._install_cmd_line_tools(cmdline_archive_file, Path(target_sdk_path))

        # 设置环境变量
        if set_env:
            self._set_android_home_env(target_sdk_path, env_var_name=sdk_env_var_name)

        # 安装扩展选项
        if action == "install_cmdline_ext":
            self._install_ext_options(target_sdk_path)

        print(f"Android SDK installed to {target_sdk_path}")


def main():
    installer = AndroidSDKInstaller()
    installer.run()


if __name__ == "__main__":
    main()