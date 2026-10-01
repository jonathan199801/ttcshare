from __future__ import annotations

import hashlib
import mimetypes
import secrets
import string
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .config import settings
from .storage import get_tokens, save_tokens

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
API_BASE = "https://open.tiktokapis.com"


class TikTokAPIError(RuntimeError):
    pass


def generate_pkce() -> tuple[str, str]:
    # TikTok Desktop docs explicitly require SHA-256 represented as hex.
    alphabet = string.ascii_letters + string.digits + "-._~"
    verifier = "".join(secrets.choice(alphabet) for _ in range(64))
    challenge = hashlib.sha256(verifier.encode("utf-8")).hexdigest()
    return verifier, challenge


def build_authorize_url(state: str, challenge: str) -> str:
    settings.validate_for_oauth()
    params = {
        "client_key": settings.client_key,
        "response_type": "code",
        "scope": settings.scopes,
        "redirect_uri": settings.redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str, code_verifier: str) -> dict:
    settings.validate_for_oauth()
    data = {
        "client_key": settings.client_key,
        "client_secret": settings.client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": settings.redirect_uri,
        "code_verifier": code_verifier,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(TOKEN_URL, data=data, headers={"Cache-Control": "no-cache"})
    if r.status_code >= 400:
        raise TikTokAPIError(f"OAuth token error {r.status_code}: {r.text}")
    payload = r.json()
    if "access_token" not in payload:
        raise TikTokAPIError(f"Respuesta OAuth inesperada: {payload}")
    save_tokens(payload)
    return payload


async def refresh_tokens_if_needed(force: bool = False) -> dict:
    tokens = get_tokens()
    if not tokens:
        raise TikTokAPIError("No hay una cuenta TikTok conectada.")
    now = int(time.time())
    # Refresh 10 minutes before expiration.
    if not force and int(tokens["expires_at"]) - now > 600:
        return tokens
    settings.validate_for_oauth()
    data = {
        "client_key": settings.client_key,
        "client_secret": settings.client_secret,
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(TOKEN_URL, data=data, headers={"Cache-Control": "no-cache"})
    if r.status_code >= 400:
        raise TikTokAPIError(f"Refresh token error {r.status_code}: {r.text}")
    payload = r.json()
    if "access_token" not in payload:
        raise TikTokAPIError(f"Respuesta refresh inesperada: {payload}")
    save_tokens(payload)
    return get_tokens() or payload


async def _access_token() -> str:
    tokens = await refresh_tokens_if_needed()
    return str(tokens["access_token"])


async def creator_info() -> dict:
    token = await _access_token()
    url = f"{API_BASE}/v2/post/publish/creator_info/query/"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={},
        )
    payload = r.json()
    _raise_for_tiktok(r, payload)
    return payload.get("data", {})


def compute_chunk_plan(video_size: int) -> tuple[int, int]:
    mib = 1024 * 1024
    if video_size <= 64 * mib:
        return video_size, 1
    chunk_size = 32 * mib
    total_chunk_count = video_size // chunk_size
    if total_chunk_count < 1:
        total_chunk_count = 1
    return chunk_size, total_chunk_count


async def init_direct_post(
    file_path: Path,
    *,
    title: str,
    privacy_level: str,
    disable_comment: bool,
    disable_duet: bool,
    disable_stitch: bool,
    brand_content: bool,
    brand_organic: bool,
    is_aigc: bool,
) -> dict:
    token = await _access_token()
    size = file_path.stat().st_size
    chunk_size, total_chunk_count = compute_chunk_plan(size)
    body = {
        "post_info": {
            "title": title,
            "privacy_level": privacy_level,
            "disable_comment": disable_comment,
            "disable_duet": disable_duet,
            "disable_stitch": disable_stitch,
            "brand_content_toggle": brand_content,
            "brand_organic_toggle": brand_organic,
            "is_aigc": is_aigc,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunk_count,
        },
    }
    url = f"{API_BASE}/v2/post/publish/video/init/"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=body,
        )
    payload = r.json()
    _raise_for_tiktok(r, payload)
    return payload["data"]


async def upload_file(upload_url: str, file_path: Path) -> None:
    size = file_path.stat().st_size
    chunk_size, total_chunk_count = compute_chunk_plan(size)
    mime = mimetypes.guess_type(file_path.name)[0] or "video/mp4"
    if mime not in {"video/mp4", "video/quicktime", "video/webm"}:
        mime = "video/mp4"

    timeout = httpx.Timeout(connect=30, read=300, write=300, pool=30)
    async with httpx.AsyncClient(timeout=timeout) as client:
        with file_path.open("rb") as f:
            offset = 0
            for index in range(total_chunk_count):
                if index == total_chunk_count - 1:
                    bytes_to_read = size - offset
                else:
                    bytes_to_read = chunk_size
                data = f.read(bytes_to_read)
                if not data:
                    raise TikTokAPIError("El archivo terminó antes de lo esperado durante la carga.")
                end = offset + len(data) - 1
                r = await client.put(
                    upload_url,
                    headers={
                        "Content-Type": mime,
                        "Content-Length": str(len(data)),
                        "Content-Range": f"bytes {offset}-{end}/{size}",
                    },
                    content=data,
                )
                expected = 201 if index == total_chunk_count - 1 else 206
                if r.status_code not in {expected, 201, 206}:
                    raise TikTokAPIError(
                        f"Fallo cargando chunk {index + 1}/{total_chunk_count}: "
                        f"HTTP {r.status_code} {r.text}"
                    )
                offset = end + 1

    if offset != size:
        raise TikTokAPIError(f"Carga incompleta: {offset}/{size} bytes.")


async def direct_post(file_path: Path, **post_info) -> str:
    init = await init_direct_post(file_path, **post_info)
    upload_url = init.get("upload_url")
    publish_id = init.get("publish_id")
    if not upload_url or not publish_id:
        raise TikTokAPIError(f"TikTok no devolvió upload_url/publish_id: {init}")
    await upload_file(upload_url, file_path)
    return str(publish_id)


async def post_status(publish_id: str) -> dict:
    token = await _access_token()
    url = f"{API_BASE}/v2/post/publish/status/fetch/"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={"publish_id": publish_id},
        )
    payload = r.json()
    _raise_for_tiktok(r, payload)
    return payload.get("data", {})


def _raise_for_tiktok(response: httpx.Response, payload: dict) -> None:
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    code = error.get("code")
    if response.status_code >= 400 or (code and code != "ok"):
        message = error.get("message") or response.text
        raise TikTokAPIError(f"TikTok API error {response.status_code} / {code}: {message}")
