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
- Cada mensaje entrante/saliente se registra en la tabla `interactions`.

## Buscar programas

El flujo existente de búsqueda, paginación (`ver más`) y selección por índice se mantiene intacto tras el onboarding.
