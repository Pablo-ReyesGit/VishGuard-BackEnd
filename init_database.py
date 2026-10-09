from database import init_db, test_connection

if test_connection():
    init_db()
    print("✅ Tablas de VishGuard creadas o ya existentes en Neon.")
else:
    print("❌ No se crearon las tablas porque falló la conexión.")