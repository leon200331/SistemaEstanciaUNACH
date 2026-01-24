from django.db import models
from django.contrib.auth.models import AbstractUser

class Usuario(AbstractUser):
    ROLES = (
        ('admin', 'Administrador'),
        ('directora', 'Directora'),
        ('trabajo_social', 'Trabajadora Social'),
        ('medica', 'Médica'),
        ('nutriologa', 'Nutrióloga'),
        ('psicologa', 'Psicóloga'),
        ('coordinadora', 'Coordinadora de Sala'),
        ('vigilante', 'Vigilante'),
        ('asistente', 'Asistente Educativa'),
        ('tutor', 'Padre/Tutor'),
    )

    rol = models.CharField(max_length=20, choices=ROLES, default='tutor')
    telefono = models.CharField(max_length=15, blank=True, null=True)
    direccion = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.username} - {self.get_rol_display()}"