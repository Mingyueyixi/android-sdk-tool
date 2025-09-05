#encoding:utf-8
#@description: apk签名工具

# encoding: utf-8

import json
import os
from pathlib import Path
import subprocess
import platform
import onceutils
from .install_sdk import AndroidSDKInstaller


def run_cmd(
    cmd: str | list,
    prt=True,
    cwd=None,
    check=True,
    env: None = None,
):
    if prt:
        if isinstance(cmd, str):
            print(cmd)
        else:
            cmd = [str(x) for x in cmd]
            print(" ".join(cmd))

    return subprocess.run(
        cmd,
        text=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        shell=True,
        check=check,
        env=env,
    )

class LocalEntity(object):

    def __init__(self, local_path: Path):
        # 私有属性不参与json序列化
        self._local_path = local_path
        self._text = None

    def load(self):
        if not self._local_path.is_file():
            return
        try:
            self._text = self._local_path.read_text()
            text_dict = json.loads(self._text)
            for k, v in text_dict.items():
                if k.startswith("_"):            
                    continue                    
                # 更新配置对象属性
                self.__dict__[k] = v
        except:
            print(f"配置文件格式错误: {self._local_path}")
           
    def to_json(self):
        json_dict = {}
        for k, v in self.__dict__.items():
            if not k.startswith("_"):
                json_dict[k] = v            
        return json.dumps(json_dict, indent=2)
    
    def save(self):
        data = self.to_json()        
        if self._text == data:
            return
        # 配置文件有更新，保存到文件
        self._local_path.write_text(data)
        self._text = data

class ApkSigner(object):
    def __init__(self, apksigner_path: str):
        self.apksigner_path = apksigner_path

    def sign_apk(
        self, apk_path, keystore_path, keystore_alias, keystore_password, alias_pwd
    ):
        if not os.path.isfile(apk_path):
            print(f"APK文件不存在: {apk_path}")
            return

        if not os.path.isfile(keystore_path):
            print(f"密钥库文件不存在: {keystore_path}")
            return
        apk_dir = Path(apk_path).parent
        out_apk_path = f"{Path(apk_path).stem}.signed.apk"
        out_apk_path = apk_dir / out_apk_path.replace("_jiagu", "")

        cmd = [
            self.apksigner_path,
            "sign",
            "--ks",
            keystore_path,
            "--ks-key-alias",
            keystore_alias,
            "--ks-pass",
            f"pass:{keystore_password}",
            "--key-pass",
            f"pass:{alias_pwd}",
            "--out",
            out_apk_path,
            "--v1-signing-enabled",
            "true",
            "--v2-signing-enabled",
            "true",
            "--v3-signing-enabled",
            "true",
            "--v4-signing-enabled",
            "false",
            apk_path,
        ]

        try:
            run_cmd(cmd, check=True)
            print(f"APK签名成功: {out_apk_path}")
            self.verify_apk(out_apk_path)
        except subprocess.CalledProcessError as e:
            print(f"APK签名失败: {e}")

    def verify_apk(self, apk_path):
        cmd = [self.apksigner_path, "verify", apk_path]
        print(f"检查 APK 的签名是否可在 APK 支持的所有 Android 平台上被确认为有效...")
        try:
            run_cmd(cmd, check=True)
            print("true")
        except subprocess.CalledProcessError as e:
            print(f"false, APK签名检验异常: {e}")


class AppConfig(LocalEntity):

    def __init__(self, local_path: Path):
        super().__init__(local_path)
        self.android_home = None
        self.build_tools_version = None
        self.keystores = {}


    def load(self):
        super().load()
        if not self.android_home or not os.path.isdir(self.android_home):
            # 配置文件中的android_home路径不存在，尝试从环境变量中获取
            android_home = os.environ.get("ANDROID_HOME")
            print(f"read android_home from environment variable： {android_home}")
            self.android_home = android_home
        return self


class KeyTools(object):

    def __init__(self, keystore_path, password):
        self.keystore_path = keystore_path
        self.password = password

    def verify_pwd(self):
        env = os.environ.copy()
        env["JAVA_TOOL_OPTIONS"] = "-Duser.language=en -Duser.country=US"
        result = run_cmd(
            cmd=f"keytool -list -v -keystore {self.keystore_path} -storepass {self.password}",
            env=env,
            check=False,
            prt=False,
        )
        if not result.returncode == 0:
            print(f"{result.stdout}\n{result.stderr}\n密码校验失败")
            return None
        text = onceutils.bin2text(result.stdout)
        lines = text.split("\n")
        infos = {}
        for line in lines:
            line: str = line.strip()
            if ":" in line:
                k, v = line.split(":", 1)
                infos[k.strip()] = v.strip()
        return infos

    def verify_alias(self, alias: str, key_pwd: str) -> bool:
        """
        验证密钥库中的别名
        :param alias: 要验证的别名
        :return: 如果别名存在返回 True，否则返回 False
        """
        try:
            env = os.environ.copy()
            env["JAVA_TOOL_OPTIONS"] = "-Duser.language=en -Duser.country=US"
            # 构造 keytool 命令
            cmd = [
                "keytool",
                "-list",
                "-v",
                "-keystore", self.keystore_path,
                "-storepass", self.password,
                "-alias", alias,
                "-keypass", key_pwd,
            ]

            # 执行命令
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)

            # 解析输出
            output = result.stdout
            # print(output)
            # print(result.stderr)

            # 检查别名是否存在
            if not f"Alias name: {alias}" in output:
                print(f"别名 '{alias}' 不存在。")                
            else:                                
                # "Warning:  Different store and key passwords not supported for PKCS12 KeyStores. Ignoring user-specified -keypass value."
                if "Warning:  Different store and key passwords" in result.stderr:
                    print(f"别名 '{alias}' 的密码校验失败")
                else:
                    return True
        except subprocess.CalledProcessError as e:
            # 如果命令执行失败，说明别名不存在
            print(f"校验别名失败: {e.stderr}")
        return False
            
class KeystoreItem(object):
    def __init__(
        self,
        path: str = None,
        pwd: str = None,
        key_alias: str = None,
        key_pwd: str = None,
    ):
        self.path = path
        self.pwd = pwd
        self.key_alias = key_alias
        self.key_pwd = key_pwd

    def to_json(self):
        return json.dumps(self.__dict__, indent=2)

    @staticmethod
    def from_json(json_str):
        data = json.loads(json_str)
        return KeystoreItem(
            data["path"], data["pwd"], data["key_alias"], data["key_pwd"]
        )


def execute_sign_apk_task(
    app_config: AppConfig, app_config_path: Path, apk_signer_path: Path
):
    """
    签名APK
    """
    apk_path = input("输入APK文件路径：\n").strip().replace("\\", "/")

    keystores: dict = app_config.keystores
    create_num = len(keystores) + 1
    keystore_key_list = [k for k in keystores.keys()]

    sign_list_text = []
    for i, k in enumerate(keystores.keys()):
        item = keystores[k]
        item_path = item.get("path", "")
        text = f"{i+1}. {k}"
        if not os.path.isfile(item_path):
            text += " (配置有误：签名文件不存在)"
        sign_list_text.append(text)
                
    sign_list_text = "\n".join(sign_list_text)
    select_num = input(f"签名配置列表：\n{sign_list_text} \n请输入数字选择：\n").strip()

    keystore_item = keystores[keystore_key_list[int(select_num) - 1]]
    keystore = keystore_item["path"]
    alias = keystore_item["key_alias"]
    keystore_pwd = keystore_item["pwd"]
    alias_pwd = keystore_item["key_pwd"]

    if not os.path.isfile(keystore):
        print(f"配置有误，签名文件不存在: {keystore}")
        return

    apk_signer = ApkSigner(str(apk_signer_path))
    apk_signer.sign_apk(apk_path, keystore, alias, keystore_pwd, alias_pwd)


def execute_add_keystore_task(app_config:AppConfig, app_config_path:Path):
    """
    添加签名配置
    """
    keystore_item = {}
    
    while True:
        keystore_item["path"] = input("输入密钥库文件路径：\n").strip()
        if not os.path.isfile(keystore_item["path"]):
            print(f"密钥库文件不存在: {keystore_item['path']}")
            continue       
        break

    while True:
        keystore_item["pwd"] = input("输入密钥库密码：\n").strip()
        keytools = KeyTools(keystore_item["path"], keystore_item["pwd"])
        infos = keytools.verify_pwd()
        if not infos:
            continue
        keystore_item["key_alias"] = infos.get("Alias name", None)
        break

    while keystore_item["key_alias"]:
        print(f"密钥库别名：{keystore_item['key_alias']}")
        keystore_item["key_pwd"] = input("输入密钥库别名密码：\n").strip()
        # 验证别名密码
        if not keytools.verify_alias(keystore_item["key_alias"], keystore_item["key_pwd"]):
            continue
        break
    keystore_item_key = None
    key_name = os.path.basename(keystore_item["path"])
    keystore_item_key = input(f"输入签名配置名称（默认取文件名：{key_name}）：\n").strip()            
    if not keystore_item_key:
        keystore_item_key = key_name
    app_config.keystores[keystore_item_key] = keystore_item
    app_config.save()    
    print(f"{keystore_item_key}\n {json.dumps(keystore_item, indent=2)} \n已保存到配置文件。")

def isVsCodeInstalled():
    return subprocess.call("code --version", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0

def open_config_file(config_path: Path):
    if isVsCodeInstalled():
        # vscode打开文件, -w 等待编辑器关闭, -n 新窗口打开
        return os.system(f"code -w {str(config_path)}")   
    system = platform.system()
    print(system)
    if system == "Windows":    
        return os.system(f"notepad.exe {str(config_path)}")
    elif system == "Linux":
        return subprocess.run(f"vi {str(config_path)}", shell=True)        
    elif system == "Darwin":
        return os.system(f"open -t {str(config_path)}")
    else:            
        return os.system(f"xdg-open {str(config_path)}")    

def open_config_dir(config_dir: Path):
    if platform.system() == "Windows":
        return os.system(f"explorer {str(config_dir.parent)}")
    elif platform.system() == "Darwin":
        # mac下用open命令打开目录
        return os.system(f"open {str(config_dir.parent)}")
    else:
        # 其他系统，linux用xdg-open命令打开目录
        return os.system(f"xdg-open {str(config_dir.parent)}")    
    
def execute_read_config_task(app_config: AppConfig):
    print(app_config.to_json())
    json_key = input("输入key查看签名文件信息，其他键出：\n")
    
def main():
    # 修改配置文件路径为用户目录下的配置
    config_dir = Path.home() / ".config" / "android-stk-tool"
    config_dir.mkdir(parents=True, exist_ok=True)
    app_config_path = config_dir / "apksigner_config.json"
    app_config = AppConfig(app_config_path).load()

    android_home = app_config.android_home
    if not android_home:
        print("请配置android_home")
        return

    if not app_config.build_tools_version:
        build_tools = os.path.join(android_home, "build-tools")
        if not os.path.isdir(build_tools):
            print(f"未找到build-tools目录: {build_tools}")
            return
        app_config.build_tools_version = input(
            f"请选择build-tools版本：{os.listdir(build_tools)}\n"
        )

    apk_signer_dir: Path = (
        Path(android_home) / "build-tools" / app_config.build_tools_version
    )
    if platform.system() == "Windows":
        apk_signer_path = apk_signer_dir / "apksigner.bat"
    else:
        apk_signer_path = apk_signer_dir / "apksigner"

    # 检查apksigner是否存在，如果不存在则尝试安装build-tools
    if not os.path.isfile(apk_signer_path):
        print(f"未在指定build-tools版本下找到apksigner工具: {apk_signer_path}")
        print("尝试自动安装build-tools...")
        installer = AndroidSDKInstaller()
        if installer._install_build_tools(android_home, app_config.build_tools_version):
            # 重新设置apk_signer_path
            if platform.system() == "Windows":
                apk_signer_path = apk_signer_dir / "apksigner.bat"
            else:
                apk_signer_path = apk_signer_dir / "apksigner"
            
            # 再次检查是否安装成功
            if not os.path.isfile(apk_signer_path):
                print(f"安装后仍未找到apksigner工具: {apk_signer_path}")
                return
        else:
            return

    app_config.save()
    while True:
        print("============================")
        input_num = input(
            "1. 签名APK\n2. 添加签名配置\n3. 查看签名配置\n4. 编辑签名配置\n5. 打开配置文件目录\n6. 其他项退出\n请输入数字选择："
        ).strip()
        if input_num == "1":
            execute_sign_apk_task(app_config, app_config_path, apk_signer_path)
        elif input_num == "2":
            execute_add_keystore_task(app_config, app_config_path)
        elif input_num == "3":
            execute_read_config_task(app_config)
        elif input_num == "4":
            p = open_config_file(app_config_path)
            if p != 0:
                print("编辑器打开失败")
            else:
                app_config.load()
        elif input_num == "5":
            open_config_dir(app_config_path.parent)
        else:
            break


if __name__ == "__main__":
    main()