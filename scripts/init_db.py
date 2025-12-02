"""Inicializa la base de datos creando las tablas declaradas en app.db."""
from app.db import init_db

if __name__ == "__main__":
    init_db()
    print("Tablas creadas correctamente")
