from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from .models import Solicitud, LinkCaptura, SolicitudInscripcion, BitacoraLactante, BitacoraMaternal

# ====================================================================
# SOLUCIÓN SEGURA PARA EL DISEÑO DE USUARIOS (GRUPOS Y PERMISOS)
# ====================================================================
# Usamos un try/except para evitar el error "NotRegistered" si el servidor se recarga
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    # Esto garantiza que veas los cuadros de Grupos y Permisos (Imagen 3)
    list_display = ("username", "email", "first_name", "last_name", "is_staff")
    ordering = ("username",)

# ====================================================================
# REGISTRO DE SOLICITUDES (TU CÓDIGO ORIGINAL)
# ====================================================================
@admin.register(Solicitud)
class SolicitudAdmin(admin.ModelAdmin):
    list_display = (
        "folio",
        "estado",
        "estado_psicologia",
        "estado_nutricion",
        "estado_medico",
        "created_at",
    )
    list_filter = (
        "estado",
        "estado_psicologia",
        "estado_nutricion",
        "estado_medico",
        "created_at",
    )
    search_fields = (
        "folio",
        "nombres_tutor",
        "apellido_paterno_tutor",
        "curp_menor",
    )
    ordering = ("-created_at",)

@admin.register(LinkCaptura)
class LinkCapturaAdmin(admin.ModelAdmin):
    list_display = ("solicitud", "token", "usado", "creado_en")
    list_filter = ("usado",)
    search_fields = ("token",)

# ====================================================================
# REGISTRO DE NUEVOS MODELOS (EXPEDIENTES Y BITÁCORAS)
# ====================================================================
@admin.register(SolicitudInscripcion)
class SolicitudInscripcionAdmin(admin.ModelAdmin):
    list_display = ("id", "solicitud_ingreso", "estado", "created_at")
    list_filter = ("estado",)

@admin.register(BitacoraLactante)
class BitacoraLactanteAdmin(admin.ModelAdmin):
    list_display = ("alumno", "maestra", "fecha", "estado")
    list_filter = ("estado", "fecha")
    search_fields = ("alumno__solicitud_ingreso__nombres_menor",)

@admin.register(BitacoraMaternal)
class BitacoraMaternalAdmin(admin.ModelAdmin):
    list_display = ("alumno", "maestra", "fecha", "estado")
    list_filter = ("estado", "fecha")
    search_fields = ("alumno__solicitud_ingreso__nombres_menor",)