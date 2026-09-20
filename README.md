# RIQSSI Backend

API FastAPI para análisis de videos y audio.

## Local

```powershell
Copy-Item .env.example .env
# Edita .env con tu PostgreSQL y SMTP
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

La API queda en `http://localhost:8000` y la documentación en `/docs`.

## Migraciones

En una base nueva ejecuta antes de arrancar la API:

```powershell
alembic upgrade head
```

En una base existente, conserva los datos y registra el esquema actual como baseline:

```powershell
alembic stamp 0001_initial_schema
```

Las próximas modificaciones de modelos deben añadirse como revisiones Alembic. La lógica de cambios heredada de `app.main` debe retirarse después de aplicar este baseline en todos los entornos.

## Render con Docker

Crea un servicio Web en Render usando este directorio como raíz y `Dockerfile` como Docker runtime. Render debe inyectar `PORT` automáticamente. Configura `DATABASE_URL` usando la conexión interna del PostgreSQL de Render y define `FRONTEND_URLS` con la URL exacta de Vercel.

Variables mínimas:

- `DATABASE_URL`
- `FRONTEND_URLS`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_NAME`, `SMTP_FROM_EMAIL`
- `MODEL_PATH_AUDIO`, `MODEL_PATH_VIDEO`
- `STORAGE_PATH_VIDEOS`, `STORAGE_PATH_AUDIO`, `STORAGE_PATH_FRAMES`, `STORAGE_PATH_THUMBS`, `STORAGE_PATH_MFCC`

## Advertencia de producción

La implementación actual todavía guarda videos, pistas, miniaturas, MFCC y comprobantes en `storage/`, que es efímero en Render. También autentica por `nombreuser` y almacena/compara `clave` sin hashing. Antes de aceptar usuarios públicos hay que migrar los objetos a Supabase Storage, implementar JWT o sesiones verificadas y migrar las contraseñas a hashes.

`app.main` también ejecuta creación y cambios de tablas durante el import. Para producción debe reemplazarse por migraciones versionadas (por ejemplo Alembic) ejecutadas como paso de deploy.
