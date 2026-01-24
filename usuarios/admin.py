from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario

class UsuarioAdmin(UserAdmin):
    model = Usuario
    fieldsets = UserAdmin.fieldsets + (
        ('Información Extra', {'fields': ('rol', 'telefono', 'direccion')}),
    )
    list_display = ['username', 'email', 'rol', 'is_staff']

admin.site.register(Usuario, UsuarioAdmin)