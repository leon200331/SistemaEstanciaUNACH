from django.contrib import admin
from .models import Solicitud, LinkCaptura


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