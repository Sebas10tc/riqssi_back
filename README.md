# RIQSSI Backend

API FastAPI para autenticación, administración, almacenamiento y análisis de deepfakes mediante modelos de audio y video.

## Tecnologías

- FastAPI y Uvicorn
- PostgreSQL y SQLAlchemy
- Alembic
- JWT y bcrypt
- Supabase Storage
- OpenCV, librosa, PyTorch y scikit-learn
- FFmpeg y yt-dlp

## Desarrollo local

```powershell
cd C:\RIQSSI\RIQSSI_BACK
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

La API queda en `http://localhost:8000` y Swagger en `http://localhost:8000/docs`.

## Configuración

Partiendo de `.env.example`, configura al menos:

- `DATABASE_URL`: conexión PostgreSQL.
- `JWT_SECRET_KEY`: clave aleatoria larga usada para firmar tokens.
- `JWT_ALGORITHM` y `JWT_EXPIRE_MINUTES`.
- `FRONTEND_URLS`: dominios permitidos separados por comas.
- `MODEL_PATH_AUDIO` y `MODEL_PATH_VIDEO`.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_NAME` y `SMTP_FROM_EMAIL`.
- `SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY`.
- `YAPE_QR_URL`: URL HTTPS pública del QR de Yape.

Los archivos que deben conservarse se suben a Supabase Storage. Configura `SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY` para usar las rutas que guardan archivos; esas operaciones fallarán si falta la configuración. Las rutas `STORAGE_PATH_*` indican dónde se crean o procesan archivos localmente antes de subirlos. En Render, el disco local del contenedor es efímero y no debe usarse como almacenamiento persistente.

## Seguridad de contraseñas

Las contraseñas nuevas se almacenan con hash bcrypt, no en texto plano. Para cuentas antiguas que aún tengan la contraseña en texto plano, el backend verifica la contraseña durante el inicio de sesión y, si es correcta, la reemplaza por un hash bcrypt.

## Supabase Storage

La aplicación usa buckets privados para:

- `videos`
- `audio_tracks`
- `video_tracks`
- `video_frames`
- `thumbnails`
- `mfcc_data`
- `payment_proofs`

Los nombres pueden cambiarse con las variables `SUPABASE_BUCKET_*`. El bucket público `yape` solo contiene opcionalmente `qr.png` para mostrar el QR de pago.

No uses secretos de Supabase ni claves privadas en el frontend.

## Migraciones

Crear una revisión después de modificar modelos:

```powershell
alembic revision --autogenerate -m "descripcion del cambio"
alembic upgrade head
```

En una base existente:

```powershell
alembic current
alembic history
```

La revisión inicial se encuentra en `alembic/versions/`.

## Endpoints principales

- `/register`, `/login`, `/recover-password`, `/change-password`
- `/admin/*`: operaciones administrativas protegidas por JWT y rol.
- `/membership/*`: membresías y comprobantes de pago.
- `/video/upload`, `/links/download`
- `/tracks/*`: extracción y reparación de pistas.
- `/video-analysis/*` y `/audio-analysis/*`
- `/analysis/*`: reporte y veredicto final.
- `/historial/*`: historial del usuario.

Todos los endpoints detallados están documentados en `/docs` y `/redoc`.

## Pruebas

```powershell
python -m pytest tests
```

## Render con Docker

El despliegue usa `Dockerfile` y `render.yaml`. Antes de iniciar Uvicorn, Docker ejecuta:

```sh
alembic -c /app/alembic.ini upgrade head
```

Configura `DATABASE_URL` con la URL interna de PostgreSQL de Render y `FRONTEND_URLS` con el dominio exacto de Vercel. Render debe inyectar `PORT`.
