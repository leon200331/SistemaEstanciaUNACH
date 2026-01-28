from django.db import models
from django.contrib.auth.models import AbstractUser


class Usuario(AbstractUser):
    ROLES = (
        # --- ROLES DE ACCESO TOTAL (Los 4 Fantásticos) ---
        ('admin', 'Administrador del Sistema'),  # Tú (Leonardo)
        ('jefa_superior', 'Jefa de Departamento/Superior'),  # La Jefa de alto rango
        ('directora', 'Directora'),  # La Directora
        ('administrativo', 'Administrativo General'),  # Para las otras 2 personas pendientes

        # --- ÁREA OPERATIVA Y MÉDICA ---
        ('coordinadora', 'Coordinadora de Sala'),
        ('trabajo_social', 'Trabajadora Social'),
        ('medica', 'Médica'),
        ('nutriologa', 'Nutrióloga'),
        ('psicologa', 'Psicóloga'),

        # --- PERSONAL DE APOYO ---
        ('vigilante', 'Vigilante'),
        ('asistente', 'Asistente Educativa'),

        # --- USUARIOS EXTERNOS ---
        ('tutor', 'Padre/Tutor'),
    )

    rol = models.CharField(max_length=30, choices=ROLES, default='tutor')  # Aumenté a 30 por si acaso
    telefono = models.CharField(max_length=15, blank=True, null=True)
    direccion = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.username} - {self.get_rol_display()}"