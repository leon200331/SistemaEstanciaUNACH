from functools import wraps

from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone


# =========================================================
# SEGURIDAD CENTRALIZADA POR ROL
# =========================================================
# Regla general del sistema:
# - Sin sesión: login.
# - Con sesión pero sin rol correcto: se cierra sesión y vuelve a login.
# - Solo se permite acceso cruzado cuando existe suplencia activa autorizada
#   por Dirección para el área cubierta.
# - Las maestras usan un módulo separado de apoyo temporal de sala.


AREA_DIRECCION = "DIRECCION"
AREA_MEDICA = "MEDICA"
AREA_NUTRICION = "NUTRICION"
AREA_PSICOLOGIA = "PSICOLOGIA"
AREA_PEDAGOGICA = "PEDAGOGICA"
AREA_TRABAJO_SOCIAL = "TRABAJO_SOCIAL"
AREA_MAESTRA = "MAESTRA"


def _texto_grupos(user):
    if not user or not getattr(user, "is_authenticated", False):
        return ""
    try:
        return " ".join(g.name.strip().lower() for g in user.groups.all())
    except Exception:
        return ""


def area_usuario(user):
    return str(getattr(user, "area_operativa", "") or "").strip().upper()


def tipo_usuario(user):
    return str(getattr(user, "tipo_persona", "") or "").strip().upper()


def usuario_es_admin(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    if tipo_usuario(user) == "ADMIN":
        return True
    grupos = _texto_grupos(user)
    return "administrador" in grupos or "gobierno ti" in grupos or "sistema" in grupos


def usuario_es_directora(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if tipo_usuario(user) == "PERSONAL" and area_usuario(user) == AREA_DIRECCION:
        return True
    grupos = _texto_grupos(user)
    return "directora" in grupos or "direccion" in grupos or "dirección" in grupos


def usuario_es_supervisora(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if tipo_usuario(user) == "SUPERVISOR":
        return True
    grupos = _texto_grupos(user)
    return "supervisor" in grupos or "supervisora" in grupos or "secretaria de direccion" in grupos or "secretaria de dirección" in grupos


def usuario_es_beneficiario(user):
    return bool(user and getattr(user, "is_authenticated", False) and tipo_usuario(user) == "BENEFICIARIO")


def usuario_es_area(user, area):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return tipo_usuario(user) == "PERSONAL" and area_usuario(user) == str(area or "").upper()


def usuario_es_maestra(user):
    if usuario_es_area(user, AREA_MAESTRA):
        return True
    grupos = _texto_grupos(user)
    return "maestra" in grupos or "asistente" in grupos or "sala" in grupos


def usuario_tiene_suplencia_activa(user, area_cubierta):
    """
    Valida suplencias de filtros, Pedagógica o Trabajo Social.
    Se importa el modelo aquí para evitar ciclos de importación.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    area_cubierta = str(area_cubierta or "").strip().upper()
    if not area_cubierta:
        return False

    try:
        from admisiones.models import AutorizacionSuplencia
    except Exception:
        return False

    ahora = timezone.now()
    return AutorizacionSuplencia.objects.filter(
        suplente=user,
        area_cubierta=area_cubierta,
        estado="ACTIVA",
        inicio__lte=ahora,
        fin__gte=ahora,
    ).exists()


def usuario_tiene_apoyo_sala_activo(user):
    """
    Valida apoyo temporal de maestra en otra sala.
    Este flujo es separado de las suplencias de filtros.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    try:
        from admisiones.models import ApoyoSalaMaestra
    except Exception:
        return False
    return ApoyoSalaMaestra.objects.filter(maestra_apoyo=user, estado="ACTIVO", fin__isnull=True).exists()


def ruta_por_rol(user):
    """
    Ruta principal esperada para cada rol.
    Se usa en login y para decidir a dónde enviar usuarios válidos.
    """
    if usuario_es_admin(user):
        return "panel_gobierno_ti"
    if usuario_es_supervisora(user):
        return "panel_supervisor"
    if usuario_es_directora(user):
        return "dashboard_directiva"
    if usuario_es_beneficiario(user):
        return "portal_padres_home"
    if usuario_es_area(user, AREA_TRABAJO_SOCIAL):
        return "dashboard_admin"
    if usuario_es_area(user, AREA_PSICOLOGIA):
        return "psicologia_pendientes"
    if usuario_es_area(user, AREA_NUTRICION):
        return "nutricion_pendientes"
    if usuario_es_area(user, AREA_MEDICA):
        return "medico_pendientes"
    if usuario_es_area(user, AREA_PEDAGOGICA):
        return "dashboard_coordinadora"
    if usuario_es_maestra(user):
        return "dashboard_maestra"
    return "login"


def acceso_denegado_login(request, mensaje="Acceso denegado. Inicia sesión con una cuenta autorizada."):
    """
    Política solicitada: si no corresponde el rol, cerrar sesión y volver al login.
    """
    try:
        messages.error(request, mensaje)
    except Exception:
        pass
    try:
        logout(request)
    except Exception:
        pass
    return redirect("login")


def solo_roles(*areas, permitir_admin=True, permitir_suplencia=False, mensaje=None):
    """
    Decorador general para vistas internas.
    areas usa valores como: PSICOLOGIA, NUTRICION, MEDICA, PEDAGOGICA,
    TRABAJO_SOCIAL, DIRECCION, MAESTRA, SUPERVISION, BENEFICIARIO, ADMIN.
    """
    areas_normalizadas = {str(area or "").strip().upper() for area in areas if area}

    def decorador(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = getattr(request, "user", None)

            if not user or not getattr(user, "is_authenticated", False):
                return redirect("login")

            if not getattr(user, "is_active", True) or not getattr(user, "estatus_operativo", True):
                return acceso_denegado_login(request, "Tu cuenta está inactiva. Contacta al administrador.")

            if permitir_admin and usuario_es_admin(user):
                return view_func(request, *args, **kwargs)

            if "ADMIN" in areas_normalizadas and usuario_es_admin(user):
                return view_func(request, *args, **kwargs)
            if "SUPERVISION" in areas_normalizadas and usuario_es_supervisora(user):
                return view_func(request, *args, **kwargs)
            if "BENEFICIARIO" in areas_normalizadas and usuario_es_beneficiario(user):
                return view_func(request, *args, **kwargs)
            if "DIRECCION" in areas_normalizadas and usuario_es_directora(user):
                return view_func(request, *args, **kwargs)
            if "MAESTRA" in areas_normalizadas and usuario_es_maestra(user):
                return view_func(request, *args, **kwargs)

            for area in areas_normalizadas:
                if area in {AREA_MEDICA, AREA_NUTRICION, AREA_PSICOLOGIA, AREA_PEDAGOGICA, AREA_TRABAJO_SOCIAL}:
                    if usuario_es_area(user, area):
                        return view_func(request, *args, **kwargs)
                    if permitir_suplencia and usuario_tiene_suplencia_activa(user, area):
                        return view_func(request, *args, **kwargs)

            return acceso_denegado_login(
                request,
                mensaje or "No tienes permiso para entrar a este panel. Se cerró la sesión por seguridad.",
            )
        return _wrapped
    return decorador


solo_admin = solo_roles("ADMIN", permitir_admin=True)
solo_directora = solo_roles("DIRECCION", permitir_admin=True)
solo_supervisora = solo_roles("SUPERVISION", permitir_admin=False)
solo_beneficiario = solo_roles("BENEFICIARIO", permitir_admin=False)
solo_maestra = solo_roles("MAESTRA", permitir_admin=False)
solo_trabajo_social = solo_roles("TRABAJO_SOCIAL", permitir_admin=True, permitir_suplencia=True)
solo_psicologia = solo_roles("PSICOLOGIA", permitir_admin=True, permitir_suplencia=True)
solo_nutricion = solo_roles("NUTRICION", permitir_admin=True, permitir_suplencia=True)
solo_medica = solo_roles("MEDICA", permitir_admin=True, permitir_suplencia=True)
solo_pedagogica = solo_roles("PEDAGOGICA", permitir_admin=True, permitir_suplencia=True)
