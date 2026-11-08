# encoding: utf-8

import os
from pathlib import Path
import platform
import re
import subprocess


class _BashrcEnv(object):
    def __init__(self, name: str):
        self.name = name
        self.tag_start = f"# ---{name} start---"
        self.tag_end = f"# ---{name} end---"

    def get_decoration_env_value(self):
        """
        获取bashrc中指定环境变量的值
        :return: 环境变量值，若不存在则返回None
        """
        path_bashrc = Path(os.path.expanduser("~/.bashrc"))
        if not path_bashrc.exists():
            return None

        text = path_bashrc.read_text(encoding="utf-8")
        name = self.name

        if self.tag_start in text and self.tag_end in text:
            start_idx = text.index(self.tag_start) + len(self.tag_start)
            end_idx = text.index(self.tag_end)
            env_text = text[start_idx:end_idx].strip()
            # 提取export语句中的值
            match = re.search(r"export\s+" + re.escape(name) + r"\s*=\s*(.*)", env_text)
            if match:
                return match.group(1).strip()
        return None

    def index_tag_start_end(self, text: str):
        """
        获取bashrc中指定环境变量的值
        :param name: 环境变量名
        :return: 环境变量值，若不存在则返回None
        """
        start_idx = text.index(self.tag_start)
        end_idx = text.index(self.tag_end) + len(self.tag_end)
        return start_idx, end_idx
    
    def remove_env_value(self):
        path_bashrc = Path(os.path.expanduser("~/.bashrc"))
        if not path_bashrc.exists():
            return

        text = path_bashrc.read_text(encoding="utf-8")
        if self.tag_start in text and self.tag_end in text:
            start_idx, end_idx = self.index_tag_start_end(text)
            text = text[:start_idx] + text[end_idx:]
            path_bashrc.write_text(text, encoding="utf-8")
        
    def get_export_env_line(self, env_value: str):
        return f"""{self.tag_start}
export {self.name}={env_value}
{self.tag_end}""".strip()

    def apply_env_value(self, value: list|str, is_merge=False):
        # 先统一计算最终值，再按 bashrc 现状选择写入位置，
        # 保证任何分支（首次写入/追加/替换）的合并语义一致
        if type(value) is list:
            new_value_list = list(dict.fromkeys(value))
        else:
            new_value_list = [value]

        if is_merge:
            old_value = self.get_decoration_env_value()
            old_value_list = old_value.split(":") if old_value else []
            for v in old_value_list:
                if v == f"${self.name}":
                    # 自身引用统一移到末尾
                    continue
                if v in new_value_list:
                    # 移除重复的值，避免重复添加
                    continue
                new_value_list.append(v)
            if type(value) is list or f"${self.name}" in old_value_list:
                # PATH 类变量：末尾必须保留自身引用（如 $PATH），
                # 否则 export 会覆盖已有 PATH，导致其他命令全部失效
                new_value_list.append(f"${self.name}")
            env_value = ":".join(new_value_list)
        else:
            env_value = value if type(value) is not list else ":".join(new_value_list)

        path_bashrc = Path(os.path.expanduser("~/.bashrc"))
        env_text = self.get_export_env_line(env_value)
        if path_bashrc.exists():
            text = path_bashrc.read_text(encoding="utf-8")
            if text.find(self.tag_start) != -1 and text.find(self.tag_end) != -1:
                # 已有本变量的托管块：原地替换
                start_idx, end_idx = self.index_tag_start_end(text)
                text = "\n".join([text[:start_idx], env_text, text[end_idx:]])
            else:
                # 无托管块，直接追加
                text += "\n" + env_text
        else:
            # 文件不存在，直接写入新内容
            text = env_text + "\n"

        path_bashrc.write_text(text, encoding="utf-8")


class _WindowsEnv:
    @staticmethod
    def query_env_value(name, is_sys=False):
        """
        使用cmd命令查询特定环境变量的值
        """
        # 执行windows命令，从注册表获取用户path原始值
        key = _WindowsEnv.get_env_reg_key(is_sys)
        cmd = f'reg query "{key}" /v {name}'
        result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, check=False)
        if result.returncode != 0:
            return None, None

        cmd_stdout = result.stdout.decode()
        m = re.search(rf"{name}\s+(REG_.*?)\s+(.*)", cmd_stdout, re.I)
        # 注册表值类型：https://learn.microsoft.com/zh-cn/windows/win32/sysinfo/registry-value-types
        reg_value_type = m.group(1)
        env_value = m.group(2).strip()
        return reg_value_type, env_value

    @staticmethod
    def get_env_reg_key(is_sys: bool):
        return "HKLM\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment" if is_sys else "HKCU\\Environment"
    
    @staticmethod
    def remove_env_value(name:str, is_sys=False):
        """
        使用cmd命令删除特定环境变量的值
        """
        key = _WindowsEnv.get_env_reg_key(is_sys)
        cmd = f'reg delete "{key}" /v {name} /f'
        result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, check=False)
        if result.returncode != 0:
            print(f"⚠️ 删除环境变量 {name} 失败，可能不存在。")
            
    @staticmethod
    def apply_env_value(name: str, value: list | str, is_sys=False, is_merge=False):
        """
        使用powershell为特定环境变量设置值。
        不使用cmd，因为cmd中，对于%%变量引用，会被自动转成实际值，需要使用^来保留原始值，处理起来比较麻烦
        """
        if type(value) is list:
            new_value = ";".join(dict.fromkeys(value))
        else:
            new_value = value
        key = _WindowsEnv.get_env_reg_key(is_sys)
        # REG_EXPAND_SZ 类型的值支持环境变量的动态解析，而普通字符串类型（REG_SZ）不会解析环境变量。也就是%VAR%自动解析
        value_type = "REG_EXPAND_SZ"
        value_old_type, value_old = _WindowsEnv.query_env_value(name, is_sys=is_sys)
        if is_merge and value_old:
            # 合并值，去重
            old_value_list = value_old.strip().split(";")
            new_value_list = new_value.strip().split(";")
            for v in old_value_list:
                if v in new_value_list:
                    # 移除重复的值，避免重复添加
                    new_value_list.remove(v)

            # 合并新旧值，新值在前，旧值在后，这样新值才最先被找到
            merged_value_list = new_value_list + old_value_list
            merged_value = ";".join(merged_value_list)
            new_value = merged_value
            if value_old_type != value_type:
                print(f"⚠️ 环境变量 {name} 的类型为 {value_old_type}，与预期的 {value_type} 不符，可能会导致问题。")

        cmd = f"""powershell -c "reg add '{key}' /v {name} /t '{value_type}' /d '{new_value}' /f" """        
        # 默认命令
        # cmd = f'reg add "{key}" /v {name} /t "{value_type}" /d "{new_value}" /f'       
        print(f"执行命令: {cmd}")
        subprocess.run(cmd, check=True)


class EnvUtil:
    @staticmethod
    def query_env_value_windows(name, is_sys=False):
        return _WindowsEnv.query_env_value(name, is_sys=is_sys)

    @staticmethod
    def query_env_value_bashrc(name):
        return _BashrcEnv(name).get_decoration_env_value()

    @staticmethod
    def set_env_value_windows(name, value: list | str, is_sys=False):
        _WindowsEnv.apply_env_value(name, value, is_sys=is_sys)

    @staticmethod
    def set_env_value_bashrc(name, value: list|str):
        _BashrcEnv(name).apply_env_value(value, )

    @staticmethod
    def put_env_value_bashrc(name, value: list | str):
        _BashrcEnv(name).apply_env_value(value, is_merge=True)

    @staticmethod
    def put_env_value_windows(name, value: list | str, is_sys=False):
        _WindowsEnv.apply_env_value(name, value, is_sys=is_sys, is_merge=True)

    @staticmethod
    def set_env_value(name, value: list | str):
        if platform.system() == "Windows":
            _WindowsEnv.apply_env_value(name, value)
        else:
            _BashrcEnv(name).apply_env_value(value)

    @staticmethod
    def put_env_value(name, value: list | str):
        if platform.system() == "Windows":
            _WindowsEnv.apply_env_value(name, value, is_merge=True)
        else:
            _BashrcEnv(name).apply_env_value(value, is_merge=True)

    @staticmethod
    def remove_env_value_bashrc(name:str):
        _BashrcEnv(name).remove_env_value()

    @staticmethod
    def remove_env_value_windows(name:str, is_sys=False):
        _WindowsEnv.remove_env_value(name, is_sys=is_sys)

    @staticmethod
    def remove_env_value(name:str):
        """删除环境变量（跨平台入口，仅当前用户作用域）"""
        if platform.system() == "Windows":
            _WindowsEnv.remove_env_value(name)
        else:
            _BashrcEnv(name).remove_env_value()

def test_windows_env():
    EnvUtil.put_env_value_windows("PATH", "C:\\test2")

def test_bashrc_env():
    EnvUtil.put_env_value_bashrc("PATH", "C:\\test2")