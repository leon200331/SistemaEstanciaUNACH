"""
Django settings for config project.

Configurado para:
- Operación diaria con autorización por correo institucional o QR.
- Correos en modo simulado local, sin SMTP ni autenticación.
- Archivos estáticos, media y PDF con xhtml2pdf.

IMPORTANTE SOBRE CORREO:
- Ya no se deja configurado el correo Gmail estancia.unach@gmail.com.
- El sistema NO envía correos reales en este modo.
- Los correos se muestran en la terminal para evitar errores de autenticación.
- Se mantiene la validación de correos @unach.mx en formularios y vistas.
"""

from pathlib import Path
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# ======================================================================
# SEGURIDAD BÁSICA
# ======================================================================

# En producción conviene mover esta clave a una variable de entorno.
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-s7-0z41j0-3#h%zd5ohhl^zfaxgt7yd8go!b9f5!_&(_2y#v6_",
)

# En producción debe ser False.
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in ["1", "true", "yes", "si", "sí"]

# Para usar QR desde celular, entra al sistema usando la IP de tu computadora.
# Ejemplo:
#   python manage.py runserver 0.0.0.0:8000
#   http://192.168.1.50:8000
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,0.0.0.0,testserver",
    ).split(",")
    if host.strip()
]

# Para pruebas locales con QR desde celular, Django debe aceptar la IP LAN
# de tu computadora. Si no defines DJANGO_ALLOWED_HOSTS y estás en DEBUG,
# se permite cualquier host únicamente en desarrollo. En producción define
# DJANGO_ALLOWED_HOSTS con el dominio oficial o la IP del servidor.
if DEBUG and not os.getenv("DJANGO_ALLOWED_HOSTS"):
    ALLOWED_HOSTS = ["*"]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]


# ======================================================================
# APLICACIONES
# ======================================================================

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "usuarios",
    "admisiones",
]


# ======================================================================
# MIDDLEWARE
# ======================================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "config.middleware.NoCacheMiddleware",
]

ROOT_URLCONF = "config.urls"


# ======================================================================
# TEMPLATES
# ======================================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.static",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# ======================================================================
# BASE DE DATOS
# ======================================================================

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# ======================================================================
# VALIDACIÓN DE CONTRASEÑAS
# ======================================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# ======================================================================
# INTERNACIONALIZACIÓN
# ======================================================================

LANGUAGE_CODE = "es-mx"
TIME_ZONE = "America/Mexico_City"
USE_I18N = True
USE_TZ = True


# ======================================================================
# ARCHIVOS ESTÁTICOS Y MULTIMEDIA
# ======================================================================

STATIC_URL = "static/"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

STATIC_ROOT = BASE_DIR / "staticfiles"

STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# ======================================================================
# USUARIOS Y LOGIN
# ======================================================================

AUTH_USER_MODEL = "usuarios.Usuario"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "root"
LOGOUT_REDIRECT_URL = "login"


# ======================================================================
# SEGURIDAD Y SESIONES
# ======================================================================

SESSION_COOKIE_AGE = int(os.getenv("SESSION_COOKIE_AGE", "86400"))
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True


# ======================================================================
# CORREO - MODO LOCAL / SIMULADO
# ======================================================================
#
# IMPORTANTE:
# Este proyecto queda configurado para NO enviar correos reales.
# Django imprimirá el contenido del correo en la terminal donde corre
# python manage.py runserver.
#
# Con esto NO se conecta a Gmail, NO usa SMTP y NO pide autenticación.
# Por eso ya no deben aparecer errores como:
#   530 5.7.0 Authentication Required
#
# Si en el futuro la UNACH quiere envío real, entonces esta sección se
# cambia a smtp.EmailBackend y sistemas debe proporcionar el SMTP oficial.
#

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Estos datos se dejan únicamente como referencia interna.
# No se usan para autenticar mientras EMAIL_BACKEND sea console.EmailBackend.
EMAIL_HOST = ""
EMAIL_PORT = 0
EMAIL_USE_TLS = False
EMAIL_USE_SSL = False
EMAIL_HOST_USER = ""
EMAIL_HOST_PASSWORD = ""

# Remitente visual que aparecerá en el correo simulado de la terminal.
DEFAULT_FROM_EMAIL = "Estancia Infantil UNACH <no-responder@unach.mx>"
SERVER_EMAIL = DEFAULT_FROM_EMAIL


# ======================================================================
# REGLAS DE CORREO INSTITUCIONAL PARA EL SISTEMA
# ======================================================================

# Dominio institucional oficial UNACH para este proyecto.
# Regla solicitada: solo @unach.mx se considera correo institucional.
UNACH_DOMINIO_CORREO = os.getenv("UNACH_DOMINIO_CORREO", "@unach.mx").strip().lower()

UNACH_CORREOS_INSTITUCIONALES = [
    dominio.strip().lower()
    for dominio in os.getenv(
        "UNACH_CORREOS_INSTITUCIONALES",
        UNACH_DOMINIO_CORREO,
    ).split(",")
    if dominio.strip()
]

# Estas variables sirven para que las vistas validen la aprobación/envío:
# - La trabajadora social que aprueba debe tener correo @unach.mx.
# - El destinatario del PDF debe tener correo @unach.mx, si así lo decide la vista.
# - El correo de la trabajadora puede usarse como reply_to, sin dejarlo fijo.
UNACH_VALIDAR_CORREO_TRABAJADORA_SOCIAL = True
UNACH_VALIDAR_CORREO_DESTINATARIO = True
UNACH_USAR_CORREO_USUARIO_COMO_REPLY_TO = True


# ======================================================================
# AUTORIZACIÓN POR CORREO INSTITUCIONAL O QR
# ======================================================================

# Tiempo sugerido de vigencia para enlaces de autorización.
AUTORIZACION_OPERACION_MINUTOS = int(os.getenv("AUTORIZACION_OPERACION_MINUTOS", "30"))

# Si se instala qrcode[pil], las vistas pueden mostrar QR como imagen.
# Instalación:
#   pip install qrcode[pil]
QR_AUTORIZACION_ACTIVO = os.getenv("QR_AUTORIZACION_ACTIVO", "True").lower() in ["1", "true", "yes", "si", "sí"]


# ======================================================================
# CAMPO AUTO DEFAULT
# ======================================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ======================================================================
# ENDURECIMIENTO DE SEGURIDAD PARA PRODUCCIÓN
# ======================================================================
# En local se conserva compatibilidad con DEBUG=True.
# En servidor define las variables de entorno correspondientes.

DJANGO_SECURE_COOKIES = os.getenv(
    "DJANGO_SECURE_COOKIES",
    "False" if DEBUG else "True",
).lower() in ["1", "true", "yes", "si", "sí"]

SESSION_COOKIE_SECURE = DJANGO_SECURE_COOKIES
CSRF_COOKIE_SECURE = DJANGO_SECURE_COOKIES
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = os.getenv("DJANGO_CSRF_COOKIE_HTTPONLY", "False").lower() in ["1", "true", "yes", "si", "sí"]
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

SECURE_SSL_REDIRECT = os.getenv(
    "DJANGO_SECURE_SSL_REDIRECT",
    "False" if DEBUG else "True",
).lower() in ["1", "true", "yes", "si", "sí"]

SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "0" if DEBUG else "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
    "False" if DEBUG else "True",
).lower() in ["1", "true", "yes", "si", "sí"]
SECURE_HSTS_PRELOAD = os.getenv(
    "DJANGO_SECURE_HSTS_PRELOAD",
    "False" if DEBUG else "True",
).lower() in ["1", "true", "yes", "si", "sí"]

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Límite de intentos fallidos: para activarlo de forma completa se recomienda
# instalar django-axes y agregarlo a INSTALLED_APPS/MIDDLEWARE en producción.
LOGIN_INTENTOS_MAXIMOS = int(os.getenv("LOGIN_INTENTOS_MAXIMOS", "5"))
LOGIN_BLOQUEO_MINUTOS = int(os.getenv("LOGIN_BLOQUEO_MINUTOS", "15"))

# Protección operativa: evita borrados masivos accidentales desde vistas internas.
PERMITIR_BORRADO_MASIVO = os.getenv("PERMITIR_BORRADO_MASIVO", "False").lower() in ["1", "true", "yes", "si", "sí"]

