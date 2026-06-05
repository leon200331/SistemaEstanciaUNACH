from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario, AccessLog, RelacionDepartamentos, AsignacionRolCiclo


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    """
    Administración del usuario personalizado.

    Se agrega el campo area_operativa para que el sistema pueda filtrar:
    - quién aparece en pase de lista,
    - quién puede ser suplente,
    - quién puede ser titular ausente,
    - y quién NO debe participar en suplencias.
    """

    list_display = (
        "username",
        "email",
        "nombre",
        "apellido_paterno",
        "tipo_persona",
        "area_operativa",
        "estatus_operativo",
        "is_staff",
    )
    list_filter = (
        "tipo_persona",
        "area_operativa",
        "estatus_operativo",
        "is_active",
        "is_staff",
        "is_superuser",
        "groups",
    )
    search_fields = (
        "username",
        "email",
        "nombre",
        "apellido_paterno",
        "apellido_materno",
        "curp",
        "numero_empleado",
    )
    ordering = ("-date_joined",)
    readonly_fields = ("last_login", "date_joined")
    filter_horizontal = ("groups", "user_permissions")

    fieldsets = (
        (
            "Datos de acceso",
            {
                "fields": (
                    "username",
                    "password",
                )
            },
        ),
        (
            "Datos de la persona",
            {
                "fields": (
                    "nombre",
                    "apellido_paterno",
                    "apellido_materno",
                    "curp",
                    "email",
                    "telefono",
                    "direccion",
                )
            },
        ),
        (
            "Perfil en la estancia",
            {
                "fields": (
                    "numero_empleado",
                    "tipo_persona",
                    "area_operativa",
                    "estatus_operativo",
                ),
                "description": (
                    "El área operativa solo debe asignarse a personal de la estancia. "
                    "Supervisora, administrador, beneficiarios y alumnos deben quedar sin área operativa."
                ),
            },
        ),
        (
            "Permisos del sistema",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Fechas",
            {
                "fields": (
                    "last_login",
                    "date_joined",
                )
            },
        ),
    )

    add_fieldsets = (
        (
            "Crear usuario",
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "username",
                    "password1",
                    "password2",
                    "nombre",
                    "apellido_paterno",
                    "apellido_materno",
                    "curp",
                    "numero_empleado",
                    "tipo_persona",
                    "area_operativa",
                    "estatus_operativo",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                ),
            },
        ),
    )

    @admin.display(boolean=True, description="Pase lista")
    def aparece_en_pase_lista(self, obj):
        return bool(getattr(obj, "puede_aparecer_en_pase_lista", False))

    @admin.display(boolean=True, description="Puede suplir")
    def aparece_como_suplente(self, obj):
        return bool(getattr(obj, "puede_ser_suplente", False))


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = (
        "usuario",
        "accion",
        "fecha_acceso",
        "ip_address",
    )
    list_filter = (
        "fecha_acceso",
        "accion",
    )
    search_fields = (
        "usuario__username",
        "usuario__email",
        "usuario__nombre",
        "usuario__apellido_paterno",
        "accion",
        "ip_address",
    )
    readonly_fields = (
        "usuario",
        "accion",
        "fecha_acceso",
        "ip_address",
    )
    ordering = ("-fecha_acceso",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(RelacionDepartamentos)
class RelacionDepartamentosAdmin(admin.ModelAdmin):
    list_display = (
        "rol_origen",
        "rol_destino",
        "puede_consultar",
        "puede_validar",
        "puede_observar",
        "puede_descargar",
    )
    list_filter = (
        "puede_consultar",
        "puede_validar",
        "puede_observar",
        "puede_descargar",
    )
    search_fields = (
        "rol_origen__name",
        "rol_destino__name",
    )
    ordering = ("rol_origen__name", "rol_destino__name")


@admin.register(AsignacionRolCiclo)
class AsignacionRolCicloAdmin(admin.ModelAdmin):
    list_display = (
        "usuario",
        "rol",
        "semestre",
        "sala",
        "tipo_bitacora",
        "fecha_asignacion",
    )
    list_filter = (
        "rol",
        "semestre",
        "sala",
        "tipo_bitacora",
    )
    search_fields = (
        "usuario__username",
        "usuario__email",
        "usuario__nombre",
        "usuario__apellido_paterno",
        "rol__name",
        "semestre__nombre",
        "sala",
    )
    readonly_fields = ("fecha_asignacion",)
    raw_id_fields = ("usuario",)
    ordering = ("-fecha_asignacion",)
