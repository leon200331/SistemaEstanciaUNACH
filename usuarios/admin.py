from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario, AccessLog


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    # Lo que se ve en la tabla principal del admin
    list_display = ('username', 'nombre', 'apellido_paterno', 'curp', 'tipo_persona', 'estatus_operativo')

    # Filtros laterales
    list_filter = ('tipo_persona', 'estatus_operativo', 'is_staff', 'is_superuser')

    # Buscador
    search_fields = ('username', 'nombre', 'apellido_paterno', 'curp', 'numero_empleado', 'email')

    # Orden
    ordering = ('-date_joined',)

    # Cómo se agrupan los campos al entrar a editar un usuario
    fieldsets = (
        ('Datos de Acceso', {'fields': ('username', 'password')}),
        ('Datos de la Persona',
         {'fields': ('nombre', 'apellido_paterno', 'apellido_materno', 'curp', 'email', 'telefono', 'direccion')}),
        ('Perfil en la Estancia', {'fields': ('numero_empleado', 'tipo_persona', 'estatus_operativo')}),
        ('Permisos (Sistema)', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Fechas', {'fields': ('last_login', 'date_joined')}),
    )


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'accion', 'fecha_acceso', 'ip_address')
    list_filter = ('fecha_acceso',)
    search_fields = ('usuario__username', 'usuario__nombre', 'accion')