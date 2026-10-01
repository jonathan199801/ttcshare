# TikTok Local Publisher

Proyecto local en Python/FastAPI para conectar una cuenta mediante TikTok Login Kit (OAuth v2 + PKCE), mantener/renovar tokens en SQLite, consultar `creator_info`, preparar una cola de videos, publicar mediante Content Posting API con `FILE_UPLOAD` y consultar el estado del envío.

## Límite intencional de seguridad/compliance

El proyecto **no** implementa automatización furtiva de la interfaz de TikTok ni técnicas para “parecer humano”, evadir detección, CAPTCHAs, rate limits o controles anti-bot. Tampoco automatiza la eliminación de reposts: en la API pública normal no existe un scope para eliminar reposts. La interfaz incluye una página con el flujo manual.

La cola **no publica sola al llegar la hora**. La fecha es organizativa: TikTok exige que el creador conserve conocimiento/control del contenido y dé consentimiento explícito antes de que la integración lo envíe.

## 1. Requisitos

- Python 3.11+
- Una app creada en TikTok for Developers
- Login Kit agregado a la app
- Content Posting API agregado a la app
- Scopes aprobados/autorizados según el modo que usarás: `video.publish` para Direct Post; `video.upload` para drafts; `user.info.basic` para identidad básica

## 2. Configura TikTok for Developers

1. Crea/abre tu aplicación en TikTok for Developers.
2. Agrega **Login Kit**.
3. Configúrala como aplicación **Desktop** para el flujo local.
4. Registra exactamente este redirect URI (o cambia `.env` para que coincida):

   `http://localhost:8000/auth/callback/`

5. Agrega **Content Posting API** y habilita **Direct Post**.
6. Solicita/aprueba `video.publish` y, si deseas tenerlo disponible para futuras extensiones, `video.upload`.
7. Copia `Client Key` y `Client Secret`.

> Para Desktop, TikTok permite localhost/127.0.0.1 con puerto y requiere PKCE. Este proyecto usa SHA-256 en hex tal como lo especifica la documentación de TikTok Desktop.

## 3. Instala

### macOS / Linux

```bash
cd tiktok_local_publisher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Windows PowerShell

```powershell
cd tiktok_local_publisher
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edita `.env`:

```env
TIKTOK_CLIENT_KEY=...
TIKTOK_CLIENT_SECRET=...
TIKTOK_REDIRECT_URI=http://localhost:8000/auth/callback/
TIKTOK_SCOPES=user.info.basic,video.publish,video.upload
SESSION_SECRET=pon-aqui-un-valor-largo-y-aleatorio
DATABASE_PATH=./data/tiktok_local.db
QUEUE_DIR=./data/queue
```

No subas `.env` a Git ni compartas el Client Secret.

## 4. Ejecuta

macOS/Linux:

```bash
./run.sh
```

Windows:

```bat
run.bat
```

Luego abre `http://localhost:8000/`.

## 5. Conecta TikTok

1. Pulsa **Conectar con TikTok**.
2. TikTok abre su pantalla de autorización.
3. Acepta los scopes que necesites.
4. TikTok redirige a `/auth/callback/`.
5. El backend intercambia el `code` usando PKCE y guarda los tokens en `data/tiktok_local.db`.
6. Antes de expirar el access token, el backend lo renueva con el refresh token.

## 6. Publica un video

1. Ve a **Cola**.
2. Selecciona MP4, MOV o WebM.
3. Escribe la caption y una fecha planificada opcional.
4. Abre el elemento de la cola.
5. El servidor consulta `creator_info` para obtener opciones actuales de privacidad/interacción.
6. Selecciona manualmente privacidad, comentarios, Duet y Stitch.
7. Marca disclosure comercial/IA si aplica.
8. Revisa el archivo y marca la casilla de consentimiento.
9. Pulsa **Publicar ahora**.
10. El backend llama a `/v2/post/publish/video/init/`, recibe `upload_url` y `publish_id`, sube el video en chunks y permite consultar `/v2/post/publish/status/fetch/`.

### Notas importantes

- Un cliente Direct Post **no auditado** queda restringido a contenido privado (`SELF_ONLY`).
- TikTok indica que el límite de publicación por cuenta puede variar y suele rondar 15 posts cada 24 horas.
- TikTok requiere que `privacy_level` sea una opción obtenida desde `creator_info`.
- Videos de más de 64 MiB se envían en chunks; el código usa chunks base de 32 MiB y fusiona el remanente en el último.
- El máximo documentado para video es 4 GB; las restricciones de duración/calidad también aplican.

## 7. Reposts

En la documentación pública general de scopes aparecen `video.publish` y `video.upload`, pero no un scope para quitar reposts. TikTok posee un endpoint de **Research API** que consulta videos republicados para investigadores autorizados (`research.data.basic`), pero no es un endpoint de borrado.

Por ello `/reposts` solo ofrece un flujo manual. No contiene automatización de clics ni técnicas de evasión.

## 8. Pruebas

```bash
python -m pytest -q
```

Si no tienes pytest:

```bash
pip install pytest
python -m pytest -q
```

## Estructura

```text
app/
  config.py       variables de entorno
  storage.py      SQLite: tokens y cola
  tiktok_api.py   OAuth, refresh, creator_info, Direct Post, chunks, status
  main.py         interfaz FastAPI local
data/
  queue/           copias locales de videos en cola
requirements.txt
.env.example
run.sh
run.bat
```
