📦 Dependencias del proyecto
Las librerías usadas en el backend y para qué sirve cada una.
⚙️ Backend

FastAPI – Framework principal para construir la API en Python
Uvicorn – Servidor ASGI que ejecuta la aplicación en el puerto 8000
Pydantic – Valida que los datos que entran y salen de la API tengan el formato correcto

🔐 Autenticación y Seguridad

PyJWT – Genera y verifica los tokens JWT internos de sesión
cryptography – Soporte criptográfico de bajo nivel, usado por PyJWT internamente

🌐 Integración con Microsoft

httpx – Cliente HTTP asíncrono para llamar a los servidores de Microsoft (OAuth2 + Graph API)
python-dotenv – Carga las credenciales de Microsoft y demás configs desde el archivo .env

🗄️ Base de Datos

psycopg2-binary – Conector para PostgreSQL, listo para cuando se migre desde los archivos JSON actuales
