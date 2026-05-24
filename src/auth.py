import os
from typing import Optional
from quark_client import QuarkClient, get_auth_cookies
from rich.console import Console

console = Console()


def get_quark_client(cookie_string: Optional[str] = None, auto_login: bool = True) -> QuarkClient:
    cookie_string = cookie_string or os.environ.get("QUARK_COOKIES")
    if cookie_string:
        console.print("[green]使用环境变量中的 Cookie 登录[/]")
        return QuarkClient(cookies=cookie_string, auto_login=False)

    if auto_login:
        console.print("[yellow]未检测到 Cookie，启动交互式登录...[/]")
        cookie_string = get_auth_cookies()
        return QuarkClient(cookies=cookie_string, auto_login=False)

    return QuarkClient(auto_login=False)


def ensure_remote_dirs(client: QuarkClient, remote_path: str) -> str:
    parts = [p for p in remote_path.strip("/").split("/") if p]
    current_id = "0"

    for part in parts:
        found = False
        resp = client.files.list_files(current_id)
        if resp.get("status") == 200:
            for item in resp.get("data", {}).get("list", []):
                if item.get("file_name") == part and item.get("dir"):
                    current_id = item["fid"]
                    found = True
                    break

        if not found:
            console.print(f"  [dim]创建远程目录: {part}[/]")
            resp = client.files.create_folder(part, current_id)
            if resp.get("status") == 200:
                current_id = resp.get("data", {}).get("fid", current_id)
            else:
                raise RuntimeError(f"创建目录失败: {part} - {resp}")

    return current_id
