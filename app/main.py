from __future__ import annotations

import html
import secrets
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .storage import (
    add_queue_item,
    clear_tokens,
    delete_queue_item,
    get_queue_item,
    get_tokens,
    init_db,
    list_queue,
    update_queue_item,
)
from .tiktok_api import (
    TikTokAPIError,
    build_authorize_url,
    creator_info,
    direct_post,
    exchange_code,
    generate_pkce,
    post_status,
)

app = FastAPI(title="TikTok Local Publisher")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax")


@app.on_event("startup")
def startup() -> None:
    init_db()


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{html.escape(title)}</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;max-width:980px;margin:40px auto;padding:0 18px;line-height:1.45}}
nav a{{margin-right:14px}} .card{{border:1px solid #ddd;border-radius:12px;padding:16px;margin:16px 0}}
label{{display:block;margin:10px 0}} input[type=text],input[type=datetime-local],select{{width:100%;max-width:720px;padding:8px}}
button,.btn{{display:inline-block;padding:9px 14px;border-radius:8px;border:1px solid #aaa;background:#fafafa;color:#111;text-decoration:none;cursor:pointer}}
.warn{{background:#fff5d8;padding:12px;border-radius:8px}} .ok{{background:#eaf8ee;padding:12px;border-radius:8px}}
.err{{background:#ffeaea;padding:12px;border-radius:8px;white-space:pre-wrap}} code{{background:#f3f3f3;padding:2px 4px;border-radius:4px}}
table{{border-collapse:collapse;width:100%}} td,th{{border-bottom:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}}
small{{color:#555}}
</style></head><body>
<nav><a href='/'>Inicio</a><a href='/queue'>Cola</a><a href='/reposts'>Reposts</a></nav><hr>
<h1>{html.escape(title)}</h1>{body}</body></html>"""
    )


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    tokens = get_tokens()
    if not tokens:
        body = """
<div class='warn'>No hay una cuenta conectada. Configura <code>.env</code>, registra el redirect URI y autoriza TikTok.</div>
<p><a class='btn' href='/auth/start'>Conectar con TikTok</a></p>
"""
        return page("TikTok Local Publisher", body)

    creator = None
    creator_error = None
    try:
        creator = await creator_info()
    except Exception as exc:
        creator_error = str(exc)

    body = "<div class='ok'>Cuenta TikTok conectada.</div>"
    if creator_error:
        body += f"<div class='err'>No pude obtener creator_info: {html.escape(creator_error)}</div>"
    elif creator:
        body += "<div class='card'><b>Creator info</b><pre>" + html.escape(str(creator)) + "</pre></div>"
    body += """
<div class='card'>
<h2>Flujo recomendado</h2>
<p>Agrega videos a la cola y, cuando toque publicarlos, abre el elemento y confirma sus opciones. El envío no se ejecuta sin una confirmación explícita.</p>
<p><a class='btn' href='/queue'>Ir a la cola</a> <a class='btn' href='/auth/disconnect'>Desconectar</a></p>
</div>
"""
    return page("TikTok Local Publisher", body)


@app.get("/auth/start")
def auth_start(request: Request):
    try:
        verifier, challenge = generate_pkce()
        state = secrets.token_urlsafe(32)
        request.session["oauth_state"] = state
        request.session["pkce_verifier"] = verifier
        return RedirectResponse(build_authorize_url(state, challenge))
    except RuntimeError as exc:
        return page("Configuración incompleta", f"<div class='err'>{html.escape(str(exc))}</div>")


@app.get("/auth/callback/")
async def auth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None, error_description: str | None = None):
    if error:
        return page("OAuth rechazado", f"<div class='err'>{html.escape(error)}: {html.escape(error_description or '')}</div>")
    expected_state = request.session.get("oauth_state")
    verifier = request.session.get("pkce_verifier")
    if not code or not state or state != expected_state or not verifier:
        raise HTTPException(status_code=400, detail="Callback OAuth inválido o state no coincide.")
    try:
        await exchange_code(code, verifier)
    except TikTokAPIError as exc:
        return page("Error OAuth", f"<div class='err'>{html.escape(str(exc))}</div>")
    request.session.pop("oauth_state", None)
    request.session.pop("pkce_verifier", None)
    return RedirectResponse("/", status_code=303)


@app.get("/auth/disconnect")
def disconnect():
    clear_tokens()
    return RedirectResponse("/", status_code=303)


@app.get("/queue", response_class=HTMLResponse)
def queue_page() -> HTMLResponse:
    rows = list_queue()
    items = ""
    for r in rows:
        items += (
            "<tr>"
            f"<td>{r['id']}</td>"
            f"<td>{html.escape(r['original_name'])}<br><small>{html.escape(r['title'])}</small></td>"
            f"<td>{html.escape(r['planned_for'] or 'sin fecha')}</td>"
            f"<td>{html.escape(r['status'])}</td>"
            f"<td><a class='btn' href='/queue/{r['id']}'>Abrir</a></td>"
            "</tr>"
        )
    if not items:
        items = "<tr><td colspan='5'>La cola está vacía.</td></tr>"
    body = f"""
<div class='card'>
<h2>Agregar video</h2>
<form method='post' action='/queue/add' enctype='multipart/form-data'>
<label>Video <input type='file' name='video' accept='video/mp4,video/quicktime,video/webm' required></label>
<label>Título/caption <input type='text' name='title' maxlength='2200'></label>
<label>Fecha planificada <input type='datetime-local' name='planned_for'></label>
<button type='submit'>Guardar en cola</button>
</form>
</div>
<div class='warn'>La fecha sirve para organizar la cola. Este proyecto no publica de forma desatendida: TikTok exige que el creador conserve control y dé consentimiento antes de enviar el contenido.</div>
<table><thead><tr><th>ID</th><th>Video</th><th>Plan</th><th>Estado</th><th></th></tr></thead><tbody>{items}</tbody></table>
"""
    return page("Cola de publicaciones", body)


@app.post("/queue/add")
async def queue_add(video: UploadFile = File(...), title: str = Form(""), planned_for: str = Form("")):
    ext = Path(video.filename or "video.mp4").suffix.lower()
    if ext not in {".mp4", ".mov", ".webm"}:
        return page("Formato no válido", "<div class='err'>Usa MP4, MOV o WebM.</div>")
    stored = settings.queue_dir / f"{uuid.uuid4().hex}{ext}"
    with stored.open("wb") as out:
        shutil.copyfileobj(video.file, out)
    add_queue_item(str(stored), video.filename or stored.name, title.strip(), planned_for or None)
    return RedirectResponse("/queue", status_code=303)


@app.get("/queue/{item_id}", response_class=HTMLResponse)
async def queue_item_page(item_id: int) -> HTMLResponse:
    item = get_queue_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Elemento no encontrado")
    try:
        creator = await creator_info()
        options = creator.get("privacy_level_options", ["SELF_ONLY"])
        comment_disabled = bool(creator.get("comment_disabled", False))
        duet_disabled = bool(creator.get("duet_disabled", False))
        stitch_disabled = bool(creator.get("stitch_disabled", False))
    except Exception as exc:
        options = ["SELF_ONLY"]
        comment_disabled = duet_disabled = stitch_disabled = False
        creator = {"error": str(exc)}

    opts = "".join(f"<option value='{html.escape(x)}'>{html.escape(x)}</option>" for x in options)
    status_html = ""
    if item.get("publish_id"):
        status_html = f"<p>publish_id: <code>{html.escape(item['publish_id'])}</code> <a class='btn' href='/queue/{item_id}/status'>Consultar estado</a></p>"
    if item.get("last_error"):
        status_html += f"<div class='err'>{html.escape(item['last_error'])}</div>"

    body = f"""
<div class='card'>
<p><b>Archivo:</b> {html.escape(item['original_name'])}</p>
<p><b>Planificado:</b> {html.escape(item['planned_for'] or 'sin fecha')}</p>
<p><b>Estado local:</b> {html.escape(item['status'])}</p>
{status_html}
</div>
<form class='card' method='post' action='/queue/{item_id}/publish'>
<h2>Confirmar publicación</h2>
<label>Título/caption <input type='text' name='title' maxlength='2200' value='{html.escape(item['title'], quote=True)}'></label>
<label>Privacidad <select name='privacy_level' required><option value='' selected disabled>Selecciona…</option>{opts}</select></label>
<label><input type='checkbox' name='allow_comment' {'disabled' if comment_disabled else ''}> Permitir comentarios</label>
<label><input type='checkbox' name='allow_duet' {'disabled' if duet_disabled else ''}> Permitir Duet</label>
<label><input type='checkbox' name='allow_stitch' {'disabled' if stitch_disabled else ''}> Permitir Stitch</label>
<label><input type='checkbox' name='brand_organic'> Promociona mi propia marca/negocio</label>
<label><input type='checkbox' name='brand_content'> Contenido de marca / colaboración pagada</label>
<label><input type='checkbox' name='is_aigc'> Marcar como contenido generado por IA</label>
<div class='warn'>Debes revisar la vista previa/archivo y las opciones antes de publicar. Al publicar, aceptas la confirmación de uso de música de TikTok y las políticas aplicables.</div>
<label><input type='checkbox' name='consent' required> Confirmo que revisé este video y autorizo expresamente su envío a TikTok.</label>
<button type='submit'>Publicar ahora</button>
</form>
<form method='post' action='/queue/{item_id}/delete' onsubmit="return confirm('¿Eliminar de la cola y borrar el archivo local?')"><button>Eliminar de cola</button></form>
<div class='card'><small>creator_info actual: {html.escape(str(creator))}</small></div>
"""
    return page(f"Publicación #{item_id}", body)


@app.post("/queue/{item_id}/publish")
async def publish_item(
    item_id: int,
    title: str = Form(""),
    privacy_level: str = Form(...),
    allow_comment: str | None = Form(None),
    allow_duet: str | None = Form(None),
    allow_stitch: str | None = Form(None),
    brand_organic: str | None = Form(None),
    brand_content: str | None = Form(None),
    is_aigc: str | None = Form(None),
    consent: str | None = Form(None),
):
    if consent is None:
        raise HTTPException(status_code=400, detail="Se requiere consentimiento explícito.")
    item = get_queue_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Elemento no encontrado")
    path = Path(item["stored_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="El archivo local ya no existe")
    update_queue_item(item_id, status="UPLOADING", title=title, last_error=None)
    try:
        publish_id = await direct_post(
            path,
            title=title,
            privacy_level=privacy_level,
            disable_comment=allow_comment is None,
            disable_duet=allow_duet is None,
            disable_stitch=allow_stitch is None,
            brand_content=brand_content is not None,
            brand_organic=brand_organic is not None,
            is_aigc=is_aigc is not None,
        )
        update_queue_item(item_id, status="SUBMITTED", publish_id=publish_id, last_error=None)
    except Exception as exc:
        update_queue_item(item_id, status="ERROR", last_error=str(exc))
    return RedirectResponse(f"/queue/{item_id}", status_code=303)


@app.get("/queue/{item_id}/status")
async def check_status(item_id: int):
    item = get_queue_item(item_id)
    if not item or not item.get("publish_id"):
        raise HTTPException(status_code=404, detail="No hay publish_id")
    try:
        data = await post_status(item["publish_id"])
        status = data.get("status", "UNKNOWN")
        update_queue_item(item_id, status=status, last_error=None)
        return page("Estado TikTok", f"<div class='card'><pre>{html.escape(str(data))}</pre></div><p><a class='btn' href='/queue/{item_id}'>Volver</a></p>")
    except Exception as exc:
        update_queue_item(item_id, last_error=str(exc))
        return page("Error consultando estado", f"<div class='err'>{html.escape(str(exc))}</div>")


@app.post("/queue/{item_id}/delete")
def delete_item(item_id: int):
    delete_queue_item(item_id)
    return RedirectResponse("/queue", status_code=303)


@app.get("/reposts", response_class=HTMLResponse)
def reposts_page() -> HTMLResponse:
    body = """
<div class='warn'><b>No hay una API pública normal para eliminar reposts.</b> La lista pública de scopes incluye publicar/subir videos, pero no un permiso de “remove repost”. La Research API puede consultar reposts para investigadores autorizados, no borrarlos.</div>
<div class='card'>
<h2>Limpieza compatible</h2>
<ol>
<li>Abre TikTok en tu navegador o app.</li>
<li>Ve a tu perfil y a la pestaña de Reposts/Republicados.</li>
<li>Abre cada video republicado.</li>
<li>Usa Compartir → Quitar republicación / Remove repost.</li>
</ol>
<p>Este proyecto no contiene Selenium/Playwright/Appium para imitar clics, aleatorizar pausas, ocultar automatización, resolver CAPTCHAs o evadir controles anti-bot.</p>
<p><a class='btn' href='https://www.tiktok.com/' target='_blank' rel='noopener'>Abrir TikTok</a></p>
</div>
"""
    return page("Reposts", body)
