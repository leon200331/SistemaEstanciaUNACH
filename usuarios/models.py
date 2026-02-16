from django.db import models
from django.contrib.auth.models import AbstractUser
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
        regex=r'^[A-Za-z0-9]{18}$',  # Letras y números, exactamente 18
        message='La CURP debe contener exactamente 18 caracteres (letras y números), sin símbolos ni espacios.'
    )

    numeros_validator = RegexValidator(
        regex=r'^\d+$',  # Solo números (dígitos)
        message='Este campo solo acepta números. No se permiten letras ni símbolos.'
    )

    # =========================================================
    # 2. ESTRUCTURA DE LA PERSONA (Reglas de Negocio)
    # =========================================================
    nombre = models.CharField(max_length=50, validators=[letras_validator], verbose_name='Nombre(s)', null=True,
                              blank=True)
    apellido_paterno = models.CharField(max_length=50, validators=[letras_validator], verbose_name='Apellido Paterno',
                                        null=True, blank=True)
    apellido_materno = models.CharField(max_length=50, validators=[letras_validator], blank=True, null=True,
                                        verbose_name='Apellido Materno')

    # CURP: Única e irrepetible
    curp = models.CharField(max_length=18, unique=True, validators=[curp_validator], verbose_name='CURP', null=True,
                            blank=True)

    # Número de empleado: Único, pero opcional (Padres y Alumnos no tienen)
    numero_empleado = models.CharField(max_length=20, unique=True, blank=True, null=True,
                                       validators=[numeros_validator], verbose_name='No. Empleado')

    # =========================================================
    # 3. ROLES (Tipos de Persona fijos)
    # =========================================================
    TIPO_CHOICES = [
        ('PERSONAL', '1. Personal de la estancia'),
        ('SUPERVISOR', '2. Supervisor'),
        ('ADMIN', '3. Administración de Sistema'),
        ('BENEFICIARIO', '4. Beneficiario (Padre/Tutor)'),
        ('ALUMNO', '5. Alumno'),
    ]
    # Reemplazamos tu antiguo 'rol' por este nuevo sistema estricto
    tipo_persona = models.CharField(max_length=20, choices=TIPO_CHOICES, default='BENEFICIARIO',
                                    verbose_name='Tipo de Persona')

    # Estatus solicitado por el profesor
    estatus_operativo = models.BooleanField(default=True, verbose_name='¿Está Activo?')

    # Mantenemos los campos que ya tenías
    telefono = models.CharField(max_length=15, blank=True, null=True)
    direccion = models.TextField(blank=True, null=True)

    # =========================================================
    # 4. MAGIA AUTOMÁTICA (Formateo antes de guardar)
    # =========================================================
    def save(self, *args, **kwargs):
        # 1. Convertir Nombres a Primera Letra Mayúscula (Tipo Título)
        if self.nombre:
            self.nombre = self.nombre.title()
            self.first_name = self.nombre  # Sincronizamos con el sistema de Django

        if self.apellido_paterno:
            self.apellido_paterno = self.apellido_paterno.title()

        if self.apellido_materno:
            self.apellido_materno = self.apellido_materno.title()

        # Unimos los apellidos para el sistema interno de Django
        if self.apellido_paterno or self.apellido_materno:
            self.last_name = f"{self.apellido_paterno or ''} {self.apellido_materno or ''}".strip()

        # 2. Convertir CURP a MAYÚSCULAS siempre
        if self.curp:
            self.curp = self.curp.upper()

        # 3. Forzar correos a minúsculas
        if self.email:
            self.email = self.email.lower()
            self.username = self.email  # Obligamos a que el login sea con correo

        super().save(*args, **kwargs)

    def __str__(self):
        # Mostramos Apellidos y Nombre, y su tipo de rol
        return f"{self.apellido_paterno} {self.apellido_materno} {self.nombre} - {self.get_tipo_persona_display()}"


# --- MODELO: AUDITORÍA DE SEGURIDAD (Sin cambios, estaba perfecto) ---
class AccessLog(models.Model):
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    fecha_acceso = models.DateTimeField(auto_now_add=True)
    accion = models.CharField(max_length=255, default="Ingreso al sistema")
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    def __str__(self):
        return f"Log: {self.usuario.nombre} - {self.fecha_acceso}"