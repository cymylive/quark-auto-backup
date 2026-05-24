"""
Direct upload module for Quark Drive API.
Replaces quarkpan's broken upload service with a working implementation.
"""

import hashlib
import json
import logging
import mimetypes
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

import httpx

logger = logging.getLogger("quark_uploader")


def _oss_date() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')


def _file_md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class QuarkUploader:
    def __init__(self, cookies: str, httpx_client: Optional[httpx.Client] = None):
        self.cookies = cookies
        self.http = httpx_client or httpx.Client(timeout=120.0, follow_redirects=True)
        self._ensure_auth()

    def _ensure_auth(self):
        if 'quark' not in self.cookies.lower():
            service_ticket = self._get_service_ticket()
            if service_ticket:
                resp = self.http.get(
                    "https://pan.quark.cn/account/info",
                    params={"st": service_ticket, "lw": "scan"},
                )

    def _get_service_ticket(self) -> Optional[str]:
        try:
            from quark_client.config import get_config_dir
            cfg = get_config_dir() / "login_result.json"
            if cfg.exists():
                with open(cfg, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("data", {}).get("members", {}).get("service_ticket")
        except Exception:
            pass
        return None

    def _headers(self) -> Dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": "https://pan.quark.cn",
            "Referer": "https://pan.quark.cn/",
            "Cookie": self.cookies,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

    def _api_get(self, path: str, params: Optional[Dict] = None) -> Dict:
        url = f"https://drive-pc.quark.cn/1/clouddrive/{path.lstrip('/')}"
        p = {"pr": "ucpro", "fr": "pc", "uc_param_str": "", "__t": int(time.time() * 1000), "__dt": 1000}
        if params:
            p.update(params)
        resp = self.http.get(url, params=p, headers=self._headers())
        return resp.json()

    def _api_post(self, path: str, data: Optional[Dict] = None) -> Dict:
        url = f"https://drive-pc.quark.cn/1/clouddrive/{path.lstrip('/')}"
        params = {"pr": "ucpro", "fr": "pc", "uc_param_str": "", "__t": int(time.time() * 1000), "__dt": 1000}
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        resp = self.http.post(url, params=params, json=data, headers=headers)
        return resp.json()

    def upload_file(
        self,
        file_path: str,
        parent_folder_id: str = "0",
        progress_callback: Optional[Callable] = None,
    ) -> Dict:
        fp = Path(file_path)
        if not fp.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        file_size = fp.stat().st_size
        file_name = fp.name
        mime_type = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
        md5 = _file_md5(fp)
        sha1 = _file_sha1(fp)

        if progress_callback:
            progress_callback(2, "预上传...")

        pre = self._pre_upload(file_name, file_size, parent_folder_id, mime_type)
        task_id = pre.get("task_id", "")
        if not task_id:
            raise RuntimeError(f"预上传失败: {pre}")

        if progress_callback:
            progress_callback(10, "更新哈希...")
        self._update_hash(task_id, md5, sha1)

        if progress_callback:
            progress_callback(15, "获取上传授权...")

        result = self._upload_single(fp, pre, mime_type, progress_callback)

        if progress_callback:
            progress_callback(95, "完成上传...")
        self._finish(task_id, pre.get("obj_key", ""))

        if progress_callback:
            progress_callback(100, "上传完成")

        return {"status": "success", "task_id": task_id, "file_name": file_name, "file_size": file_size}

    def _pre_upload(self, file_name: str, file_size: int, parent_folder_id: str, mime_type: str) -> Dict:
        ts = int(time.time() * 1000)
        data = {
            "ccp_hash_update": True,
            "parallel_upload": True,
            "pdir_fid": parent_folder_id,
            "dir_name": "",
            "size": file_size,
            "file_name": file_name,
            "format_type": mime_type,
            "l_updated_at": ts,
            "l_created_at": ts,
        }
        resp = self._api_post("file/upload/pre", data)
        logger.debug(f"Pre-upload response: {json.dumps(resp, ensure_ascii=False)[:500]}")
        if not resp.get("status"):
            raise RuntimeError(f"预上传失败: {resp.get('message', str(resp))}")
        return resp.get("data", {})

    def _update_hash(self, task_id: str, md5: str, sha1: str):
        data = {"task_id": task_id, "md5": md5, "sha1": sha1}
        resp = self._api_post("file/update/hash", data)
        if not resp.get("status"):
            raise RuntimeError(f"更新哈希失败: {resp}")

    def _upload_single(
        self,
        fp: Path,
        pre: Dict,
        mime_type: str,
        progress_callback: Optional[Callable] = None,
    ) -> Dict:
        task_id = pre["task_id"]
        obj_key = pre.get("obj_key", "")
        upload_id = pre.get("upload_id", "")
        bucket = pre.get("bucket", "ul-zb")
        auth_info = pre.get("auth_info", "")

        auth = self._get_auth(task_id, mime_type, 1, auth_info, upload_id, obj_key, bucket)
        upload_url = auth["upload_url"]
        headers = auth["headers"]

        if progress_callback:
            progress_callback(30, "上传到 OSS...")

        with open(fp, "rb") as f:
            content = f.read()

        etag = self._put_to_oss(upload_url, content, headers)

        if progress_callback:
            progress_callback(70, "完成合并...")

        self._complete_upload(task_id, pre, mime_type, [(1, etag)])

        return {"strategy": "single", "etag": etag}

    def _get_auth(
        self,
        task_id: str,
        mime_type: str,
        part_number: int,
        auth_info: str,
        upload_id: str,
        obj_key: str,
        bucket: str,
    ) -> Dict:
        oss_date = _oss_date()
        user_agent = "aliyun-sdk-js/1.0.0 Chrome Mobile 139.0.0.0 on Google Nexus 5 (Android 6.0)"
        auth_meta = (
            f"PUT\n\n{mime_type}\n{oss_date}\n"
            f"x-oss-date:{oss_date}\n"
            f"x-oss-user-agent:{user_agent}\n"
            f"/{bucket}/{obj_key}?partNumber={part_number}&uploadId={upload_id}"
        )

        data = {"task_id": task_id, "auth_info": auth_info, "auth_meta": auth_meta}
        resp = self._api_post("file/upload/auth", data)

        logger.debug(f"Auth response: {json.dumps(resp, ensure_ascii=False)[:500]}")
        if not resp.get("status"):
            raise RuntimeError(f"获取上传授权失败: {resp.get('message', str(resp))}")

        auth_data = resp.get("data", {})
        auth_key = auth_data.get("auth_key", "")

        # Try to use upload_url from API response if available
        api_upload_url = auth_data.get("upload_url", "") or auth_data.get("url", "")
        if api_upload_url and ("oss" in api_upload_url or "aliyuncs" in api_upload_url):
            upload_url = api_upload_url
            logger.debug(f"Using upload_url from API: {upload_url[:100]}")
        else:
            # Use Quark's own PDS domain (fixed: oss-cn-shenzhen.aliyuncs.com -> pds.quark.cn)
            upload_url = (
                f"https://{bucket}.pds.quark.cn/"
                f"{obj_key}?partNumber={part_number}&uploadId={upload_id}"
            )

        headers = {
            "Content-Type": mime_type,
            "x-oss-date": oss_date,
            "x-oss-user-agent": user_agent,
        }
        if auth_key:
            headers["Authorization"] = auth_key

        return {"upload_url": upload_url, "headers": headers}

    def _put_to_oss(self, url: str, content: bytes, headers: Dict) -> str:
        resp = self.http.put(url, content=content, headers=headers)
        logger.debug(f"OSS PUT {resp.status_code} - {url[:80]}...")
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"OSS上传失败: HTTP {resp.status_code}\n"
                f"URL: {url[:150]}...\n"
                f"Response: {resp.text[:300]}"
            )
        etag = resp.headers.get("etag", "").strip('"')
        if not etag:
            raise RuntimeError("OSS未返回ETag")
        return etag

    def _complete_upload(
        self,
        task_id: str,
        pre: Dict,
        mime_type: str,
        parts: list,
    ):
        obj_key = pre.get("obj_key", "")
        upload_id = pre.get("upload_id", "")
        bucket = pre.get("bucket", "ul-zb")
        auth_info = pre.get("auth_info", "")
        callback_info = pre.get("callback", {})

        xml_parts = []
        for pn, etag in parts:
            xml_parts.append(f"<Part>\n<PartNumber>{pn}</PartNumber>\n<ETag>\"{etag}\"</ETag>\n</Part>")
        xml_data = '<?xml version="1.0" encoding="UTF-8"?>\n<CompleteMultipartUpload>\n' + \
            '\n'.join(xml_parts) + '\n</CompleteMultipartUpload>'

        import base64
        xml_md5 = base64.b64encode(hashlib.md5(xml_data.encode()).digest()).decode()

        oss_date = _oss_date()
        callback_b64 = base64.b64encode(json.dumps(callback_info, separators=(",", ":")).encode()).decode()

        user_agent = "aliyun-sdk-js/1.0.0 Chrome 139.0.0.0 on OS X 10.15.7 64-bit"
        auth_meta = (
            f"POST\n{xml_md5}\napplication/xml\n{oss_date}\n"
            f"x-oss-callback:{callback_b64}\n"
            f"x-oss-date:{oss_date}\n"
            f"x-oss-user-agent:{user_agent}\n"
            f"/{bucket}/{obj_key}?uploadId={upload_id}"
        )

        data = {"task_id": task_id, "auth_meta": auth_meta, "auth_info": auth_info}
        resp = self._api_post("file/upload/auth", data)
        if not resp.get("status"):
            raise RuntimeError(f"获取合并授权失败: {resp}")

        auth_data = resp.get("data", {})
        auth_key = auth_data.get("auth_key", "")

        post_url = f"https://{bucket}.pds.quark.cn/{obj_key}?uploadId={upload_id}"
        post_headers = {
            "Content-Type": "application/xml",
            "x-oss-date": oss_date,
            "x-oss-user-agent": user_agent,
            "x-oss-callback": callback_b64,
            "Content-MD5": xml_md5,
        }
        if auth_key:
            post_headers["Authorization"] = auth_key

        merge_resp = self.http.post(post_url, content=xml_data, headers=post_headers)
        if merge_resp.status_code not in (200, 203):
            logger.debug(f"POST merge status {merge_resp.status_code}, continuing via finish API")

    def _finish(self, task_id: str, obj_key: str = ""):
        data = {"task_id": task_id}
        if obj_key:
            data["obj_key"] = obj_key
        resp = self._api_post("file/upload/finish", data)
        if not resp.get("status"):
            raise RuntimeError(f"完成上传失败: {resp}")
