# Asistente SENA (WhatsApp)

Este proyecto expone un webhook de WhatsApp para consultar la oferta educativa del SENA.

## Configuración de base de datos

La aplicación puede usar PostgreSQL (recomendado en producción) o SQLite (por defecto en desarrollo local).

Variables de entorno principales:

- `DATABASE_URL`: cadena de conexión SQLAlchemy. Ejemplos:
  - PostgreSQL: `postgresql+psycopg2://sena:sena@localhost:5432/sena_bot`
  - SQLite (por defecto): `sqlite:///storage_simple/app.db`
- `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`: credenciales para la API de WhatsApp.

## Migraciones / creación de tablas

Se incluye un script simple para crear las tablas necesarias (`users`, `consent_events`, `interactions`, `session_state`).

```bash
python scripts/init_db.py
```

Si usas Docker Compose, el contenedor del bot ejecutará `init_db()` al arrancar, creando las tablas si no existen.

### Limpieza de interacciones antiguas

Para mantener la base de datos por debajo del límite de 1 GB (por ejemplo en Render) puedes borrar interacciones antiguas con:

```bash
PYTHONPATH=. DATABASE_URL="postgresql+psycopg2://..." python3 scripts/cleanup_interactions.py
```

Por defecto elimina registros con más de 180 días (`RETENTION_DAYS` permite ajustar el número de días). Ejecuta este comando de forma periódica desde tu máquina local (cron, tarea programada, etc.) apuntando a la base de datos de producción.

## Ejecutar con Docker Compose

El `docker-compose.yml` incluye un servicio Postgres listo para usar.

```bash
docker-compose up --build
```

- La base queda expuesta en `localhost:5432` (usuario/contraseña/db: `sena`/`sena`/`sena_bot`).
- El webhook queda en `http://localhost:8000/webhook`.
- Ajusta `DATABASE_URL` en tu `.env` si necesitas un host distinto; por defecto apunta al Postgres del compose.

## Ejecución local sin Docker

1. Instala dependencias:
   ```bash
   pip install -r requirements.txt
   ```
2. Define las variables de entorno necesarias (`WHATSAPP_TOKEN`, etc.).
3. (Opcional) Crea el SQLite local:
   ```bash
   python scripts/init_db.py
   ```
4. Ejecuta el servidor:
   ```bash
   python -m app.webhook
   ```

## Flujo de consentimiento y registro

- Al primer mensaje desde un número nuevo, el bot solicita consentimiento y datos mínimos (documento, nombre, ciudad).
- Hasta completar este flujo, no se permite la consulta normal de programas.
- Cada mensaje entrante se registra en la tabla `interactions` con solo los campos mínimos (sentido, intención, paso, etc.).

## Buscar programas

El flujo existente de búsqueda, paginación (`ver más`) y selección por índice se mantiene intacto tras el onboarding.

## Conocimiento del bot

El asistente responde exclusivamente sobre temas relacionados con el SENA:

- **Programas de formación**: usa `storage_simple/programas_enriquecido.json` (o las versiones normalizadas si existen) para entregar detalles de programas, ubicaciones y horarios.
- **Información general del SENA**: usa `data/sena_info.json`, un archivo editable por el equipo para ajustar textos, tags y enlaces (por ejemplo al registro). Cada entrada tiene `id`, `tags` (palabras/frases que activan la respuesta), `title` y `answer` en español.

Para actualizar las respuestas generales, edita `data/sena_info.json` agregando o ajustando tags y el campo `answer` (puedes usar marcadores como `<ENLACE_REGISTRO>` que luego se reemplazan con la URL oficial).
