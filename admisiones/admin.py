from django.contrib import admin

from .models import (
    Solicitud,
    LinkCaptura,
    SolicitudInscripcion,
    BitacoraLactante,
    BitacoraMaternal,
    AsistenciaPersonal,
    AutorizacionSuplencia,
    MovimientoSuplencia,
    Incidencia,
)


# ====================================================================
# SOLICITUDES DE ADMISIÓN
# ====================================================================
@admin.register(Solicitud)
class SolicitudAdmin(admin.ModelAdmin):
    list_display = (
        "folio",
        "estado",
        "estado_psicologia",
        "estado_nutricion",
        "estado_medico",
        "tiene_suplencia_en_filtros",
        "tiene_pendiente_revision_titular",
        "created_at",
    )
    list_filter = (
        "estado",
        "estado_psicologia",
        "estado_nutricion",
        "estado_medico",
        "psicologia_es_suplencia",
        "nutricion_es_suplencia",
        "medico_es_suplencia",
        "psicologia_pendiente_revision_titular",
        "nutricion_pendiente_revision_titular",
        "medico_pendiente_revision_titular",
        "created_at",
    )
    search_fields = (
        "folio",
        "nombres_tutor",
        "apellido_paterno_tutor",
        "apellido_materno_tutor",
        "nombres_menor",
        "apellido_paterno_menor",
        "apellido_materno_menor",
        "curp_menor",
        "correo",
    )
    readonly_fields = (
        "created_at",
        "dictaminado_en",
        "psicologia_en",
        "nutricion_en",
        "medico_en",
        "psicologia_revisado_en",
        "nutricion_revisado_en",
        "medico_revisado_en",
    )
    ordering = ("-created_at",)
    list_per_page = 30

    @admin.display(boolean=True, description="Suplencia")
    def tiene_suplencia_en_filtros(self, obj):
        return bool(
            getattr(obj, "psicologia_es_suplencia", False)
            or getattr(obj, "nutricion_es_suplencia", False)
            or getattr(obj, "medico_es_suplencia", False)
        )

    @admin.display(boolean=True, description="Pendiente titular")
    def tiene_pendiente_revision_titular(self, obj):
        return bool(
            getattr(obj, "psicologia_pendiente_revision_titular", False)
            or getattr(obj, "nutricion_pendiente_revision_titular", False)
            or getattr(obj, "medico_pendiente_revision_titular", False)
        )


@admin.register(LinkCaptura)
class LinkCapturaAdmin(admin.ModelAdmin):
    list_display = ("solicitud", "token", "usado", "creado_en")
    list_filter = ("usado", "creado_en")
    search_fields = ("token", "solicitud__folio", "solicitud__correo")
    readonly_fields = ("token", "creado_en")
    ordering = ("-creado_en",)


# ====================================================================
# EXPEDIENTES / INSCRIPCIONES
# ====================================================================
@admin.register(SolicitudInscripcion)
class SolicitudInscripcionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "solicitud_ingreso",
        "estado",
        "trabajo_social_es_suplencia",
        "trabajo_social_pendiente_revision_titular",
        "created_at",
    )
    list_filter = (
        "estado",
        "trabajo_social_es_suplencia",
        "trabajo_social_pendiente_revision_titular",
        "estado_pago",
        "reporte_final_aprobado",
        "directora_aprobado",
        "created_at",
    )
    search_fields = (
        "solicitud_ingreso__folio",
        "solicitud_ingreso__nombres_tutor",
        "solicitud_ingreso__apellido_paterno_tutor",
        "solicitud_ingreso__nombres_menor",
        "solicitud_ingreso__curp_menor",
        "usuario_tutor__username",
        "usuario_tutor__email",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "trabajo_social_revisado_en",
        "pago_recibido_presencial_en",
        "pago_validado_en",
        "pago_rechazado_en",
        "reporte_final_en",
        "directora_en",
    )
    ordering = ("-created_at",)
    list_per_page = 30


# ====================================================================
# BITÁCORAS DE SALA
# ====================================================================
@admin.register(BitacoraLactante)
class BitacoraLactanteAdmin(admin.ModelAdmin):
    list_display = ("alumno", "maestra", "fecha", "estado")
    list_filter = ("estado", "fecha")
    search_fields = (
        "alumno__solicitud_ingreso__nombres_menor",
        "alumno__solicitud_ingreso__apellido_paterno_menor",
        "maestra__username",
        "maestra__email",
    )
    ordering = ("-fecha",)


@admin.register(BitacoraMaternal)
class BitacoraMaternalAdmin(admin.ModelAdmin):
    list_display = ("alumno", "maestra", "fecha", "estado")
    list_filter = ("estado", "fecha")
    search_fields = (
        "alumno__solicitud_ingreso__nombres_menor",
        "alumno__solicitud_ingreso__apellido_paterno_menor",
        "maestra__username",
        "maestra__email",
    )
    ordering = ("-fecha",)


# ====================================================================
# INCIDENCIAS
# ====================================================================
@admin.register(Incidencia)
class IncidenciaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tipo",
        "categoria",
        "nivel",
        "estado",
        "es_suplencia",
        "pendiente_revision_titular",
        "registrada_por",
        "fecha_reporte",
    )
    list_filter = (
        "tipo",
        "categoria",
        "nivel",
        "estado",
        "es_suplencia",
        "pendiente_revision_titular",
        "fecha_reporte",
    )
    search_fields = (
        "descripcion",
        "resolucion",
        "comentario_cierre",
        "alumno__solicitud_ingreso__folio",
        "alumno__solicitud_ingreso__nombres_menor",
        "alumno__solicitud_ingreso__apellido_paterno_menor",
        "registrada_por__username",
        "registrada_por__email",
    )
    readonly_fields = (
        "fecha_reporte",
        "created_at",
        "updated_at",
        "responsable_informado_en",
        "cerrada_en",
        "revisada_en",
    )
    ordering = ("-fecha_reporte",)
    list_per_page = 30


# ====================================================================
# PASE DE LISTA DEL PERSONAL
# ====================================================================
@admin.register(AsistenciaPersonal)
class AsistenciaPersonalAdmin(admin.ModelAdmin):
    list_display = (
        "fecha",
        "trabajador_nombre",
        "area_operativa",
        "estado",
        "registrado_por",
        "actualizado_en",
    )
    list_filter = (
        "fecha",
        "area_operativa",
        "estado",
        "semestre",
    )
    search_fields = (
        "trabajador__username",
        "trabajador__email",
        "trabajador__nombre",
        "trabajador__apellido_paterno",
        "trabajador__apellido_materno",
        "observaciones",
    )
    readonly_fields = (
        "registrado_en",
        "actualizado_en",
    )
    ordering = ("-fecha", "area_operativa")
    list_per_page = 30


# ====================================================================
# AUTORIZACIONES DE SUPLENCIA
# ====================================================================
class MovimientoSuplenciaInline(admin.TabularInline):
    model = MovimientoSuplencia
    extra = 0
    fields = (
        "creado_en",
        "usuario",
        "accion",
        "area_cubierta",
        "estado",
        "descripcion",
    )
    readonly_fields = fields
    can_delete = False
    show_change_link = True


@admin.register(AutorizacionSuplencia)
class AutorizacionSuplenciaAdmin(admin.ModelAdmin):
    list_display = (
        "fecha",
        "area_cubierta",
        "tipo_cobertura",
        "titular_nombre",
        "suplente_nombre",
        "autorizada_por",
        "estado",
        "inicio",
        "fin",
    )
    list_filter = (
        "fecha",
        "area_cubierta",
        "tipo_cobertura",
        "estado",
    )
    search_fields = (
        "titular_ausente__username",
        "titular_ausente__email",
        "titular_ausente__nombre",
        "titular_ausente__apellido_paterno",
        "suplente__username",
        "suplente__email",
        "suplente__nombre",
        "suplente__apellido_paterno",
        "autorizada_por__username",
        "autorizada_por__email",
        "motivo",
        "observaciones",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "cancelada_en",
    )
    ordering = ("-fecha", "-created_at")
    list_per_page = 30
    inlines = [MovimientoSuplenciaInline]


# ====================================================================
# BITÁCORA DE MOVIMIENTOS POR SUPLENCIA
# ====================================================================
@admin.register(MovimientoSuplencia)
class MovimientoSuplenciaAdmin(admin.ModelAdmin):
    list_display = (
        "creado_en",
        "area_cubierta",
        "accion",
        "usuario_nombre",
        "titular_nombre",
        "estado",
        "alumno_nombre",
    )
    list_filter = (
        "creado_en",
        "area_cubierta",
        "accion",
        "estado",
    )
    search_fields = (
        "descripcion",
        "observaciones_revision",
        "usuario__username",
        "usuario__email",
        "usuario__nombre",
        "titular_area__username",
        "titular_area__email",
        "titular_area__nombre",
        "solicitud__folio",
        "inscripcion__solicitud_ingreso__folio",
        "incidencia__descripcion",
    )
    readonly_fields = (
        "creado_en",
    )
    ordering = ("-creado_en",)
    list_per_page = 30
