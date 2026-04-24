from django.db import models
from django.contrib.auth.models import AbstractUser, Group
from django.core.validators import RegexValidator

class Usuario(AbstractUser):
    # =========================================================
    # 1. VALIDADORES ESTRICTOS (Condiciones de Seguridad)
    # =========================================================
    letras_validator = RegexValidator(
        regex=r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ\s]+$',
        message='Solo se permiten letras y espacios. No se aceptan números ni símbolos.'
    )

    curp_validator = RegexValidator(
        regex=r'^[A-Za-z0-9]{18}$',
        message='La CURP debe contener exactamente 18 caracteres (letras y números), sin símbolos ni espacios.'
    )

    numeros_validator = RegexValidator(
        regex=r'^\d+$',
        message='Este campo solo acepta números. No se permiten letras ni símbolos.'
    )

    # =========================================================
    # 2. ESTRUCTURA DE LA PERSONA (Reglas de Negocio)
    # =========================================================
    nombre = models.CharField(max_length=50, validators=[letras_validator], verbose_name='Nombre(s)', null=True, blank=True)
    apellido_paterno = models.CharField(max_length=50, validators=[letras_validator], verbose_name='Apellido Paterno', null=True, blank=True)
    apellido_materno = models.CharField(max_length=50, validators=[letras_validator], blank=True, null=True, verbose_name='Apellido Materno')

    curp = models.CharField(max_length=18, unique=True, validators=[curp_validator], verbose_name='CURP', null=True, blank=True)
    numero_empleado = models.CharField(max_length=20, unique=True, blank=True, null=True, validators=[numeros_validator], verbose_name='No. Empleado')

    TIPO_CHOICES = [
        ('PERSONAL', '1. Personal de la estancia'),
        ('SUPERVISOR', '2. Supervisor'),
        ('ADMIN', '3. Administración de Sistema'),
        ('BENEFICIARIO', '4. Beneficiario (Padre/Tutor)'),
        ('ALUMNO', '5. Alumno'),
    ]
    tipo_persona = models.CharField(max_length=20, choices=TIPO_CHOICES, default='BENEFICIARIO', verbose_name='Tipo de Persona')
    estatus_operativo = models.BooleanField(default=True, verbose_name='¿Está Activo?')
    telefono = models.CharField(max_length=15, blank=True, null=True)
    direccion = models.TextField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.nombre:
            self.nombre = self.nombre.title()
            self.first_name = self.nombre
        if self.apellido_paterno:
            self.apellido_paterno = self.apellido_paterno.title()
        if self.apellido_materno:
            self.apellido_materno = self.apellido_materno.title()
        if self.apellido_paterno or self.apellido_materno:
            self.last_name = f"{self.apellido_paterno or ''} {self.apellido_materno or ''}".strip()
        if self.curp:
            self.curp = self.curp.upper()
        if self.email:
            self.email = self.email.lower()
            self.username = self.email
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.apellido_paterno} {self.apellido_materno} {self.nombre} - {self.get_tipo_persona_display()}"


# --- MODELO: AUDITORÍA DE SEGURIDAD ---
class AccessLog(models.Model):
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    fecha_acceso = models.DateTimeField(auto_now_add=True)
    accion = models.CharField(max_length=255, default="Ingreso al sistema")
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    def __str__(self):
        return f"Log: {self.usuario.nombre} - {self.fecha_acceso}"


# --- MODELO: PERMISOS CRUZADOS ---
class RelacionDepartamentos(models.Model):
    rol_origen = models.ForeignKey(Group, related_name='permisos_otorgados', on_delete=models.CASCADE, verbose_name='Rol que entra (Origen)')
    rol_destino = models.ForeignKey(Group, related_name='permisos_recibidos', on_delete=models.CASCADE, verbose_name='Módulo a visitar (Destino)')
    puede_consultar = models.BooleanField(default=False, verbose_name='Solo Consultar')
    puede_validar = models.BooleanField(default=False, verbose_name='Validar / Aprobar')
    puede_observar = models.BooleanField(default=False, verbose_name='Hacer Observaciones')
    puede_descargar = models.BooleanField(default=False, verbose_name='Descargar Copias')

    class Meta:
        unique_together = ('rol_origen', 'rol_destino')
        verbose_name = 'Relación de Departamento'
        verbose_name_plural = 'Relaciones de Departamentos'

    def __str__(self):
        return f"{self.rol_origen.name} -> {self.rol_destino.name}"


# =================================================================
# NUEVO MODELO PARA EL PUNTO 25: ASIGNACIÓN DE ROL POR CICLO
# =================================================================
class AsignacionRolCiclo(models.Model):
    """
    Guarda qué rol tiene un empleado en un semestre específico.
    """
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='roles_por_ciclo')
    rol = models.ForeignKey(Group, on_delete=models.CASCADE, verbose_name='Rol Oficial')
    # Apuntamos a Semestre que está en la otra app (admisiones)
    semestre = models.ForeignKey('admisiones.Semestre', on_delete=models.CASCADE, verbose_name='Ciclo Escolar')
    fecha_asignacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Un usuario solo puede tener UN rol principal en un mismo semestre
        unique_together = ('usuario', 'semestre')
        verbose_name = 'Asignación de Rol por Ciclo'
        verbose_name_plural = 'Asignaciones de Roles por Ciclo'

    def __str__(self):
        return f"{self.usuario.nombre} como {self.rol.name} en {self.semestre.nombre}"