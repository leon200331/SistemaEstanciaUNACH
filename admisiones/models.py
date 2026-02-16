from django.db import models, transaction
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
import uuid


class Solicitud(models.Model):
    pdf = models.FileField(upload_to="pdf_solicitudes/", null=True, blank=True)

    # ✅ Folio consecutivo (1–1000)
    folio = models.PositiveIntegerField(
        unique=True,
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(1000)]
    )

    class Estado(models.TextChoices):
        CAPTURA = "CAPTURA", "Captura"
        RECIBIDA = "RECIBIDA", "Recibida"
        APROBADA = "APROBADA", "Aprobada"
        RECHAZADA = "RECHAZADA", "Rechazada"

    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.CAPTURA
    )

    created_at = models.DateTimeField(auto_now_add=True)

    # ---------------- Tutor ----------------
    nombres_tutor = models.CharField(max_length=80)
    apellido_paterno_tutor = models.CharField(max_length=60)
    apellido_materno_tutor = models.CharField(max_length=60, blank=True)

    matricula = models.CharField(max_length=20, blank=True)

    class ProgramaEducativo(models.TextChoices):
        ING_SISTEMAS = "ING_SISTEMAS", "Ingeniería en Sistemas"
        DERECHO = "DERECHO", "Derecho"
        MEDICINA = "MEDICINA", "Medicina"
        OTRO = "OTRO", "Otro"

    programa_educativo = models.CharField(
        max_length=30,
        choices=ProgramaEducativo.choices,
        blank=True
    )
    programa_educativo_otro = models.CharField(max_length=80, blank=True)

    unidad_academica = models.CharField(max_length=120, blank=True)

    correo = models.EmailField(blank=True)
    celular = models.CharField(max_length=10, blank=True)
    domicilio = models.CharField(max_length=200, blank=True)

    class Parentesco(models.TextChoices):
        MADRE = "MADRE", "Madre"
        PADRE = "PADRE", "Padre"
        TUTOR = "TUTOR", "Tutor"
        ABUELO = "ABUELO", "Abuelo(a)"
        OTRO = "OTRO", "Otro"

    parentesco = models.CharField(
        max_length=20,
        choices=Parentesco.choices,
        default=Parentesco.TUTOR
    )
    parentesco_otro = models.CharField(max_length=80, blank=True)

    # ---------------- Menor ----------------
    fecha_nacimiento_menor = models.DateField(null=True, blank=True)
    curp_menor = models.CharField(max_length=18, blank=True)

    def nombre_tutor_completo(self):
        return f"{self.nombres_tutor} {self.apellido_paterno_tutor} {self.apellido_materno_tutor}".strip()

    def __str__(self):
        return f"Solicitud Folio {self.folio}" if self.folio else f"Solicitud #{self.id}"

    # ✅ Folio automático consecutivo
    def save(self, *args, **kwargs):
        if self.folio is None:
            with transaction.atomic():
                last = Solicitud.objects.select_for_update().order_by("-folio").first()
                next_folio = 1 if (not last or not last.folio) else (last.folio + 1)

                if next_folio > 1000:
                    raise ValueError("Se alcanzó el límite de folios (1–1000).")

                self.folio = next_folio

        super().save(*args, **kwargs)


class LinkCaptura(models.Model):
    """
    ✅ Link único (token) para capturar solicitud.
    - Se marca como usado cuando el tutor finaliza
    - Se puede definir vigencia (por ejemplo 7 días)
    """
    solicitud = models.ForeignKey("admisiones.Solicitud", on_delete=models.CASCADE, related_name="links")
    token = models.CharField(max_length=64, unique=True, editable=False)

    creado_en = models.DateTimeField(auto_now_add=True)

    usado = models.BooleanField(default=False)
    usado_en = models.DateTimeField(null=True, blank=True)

    vigencia_dias = models.PositiveIntegerField(default=7)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = uuid.uuid4().hex
        super().save(*args, **kwargs)

    def vigente(self):
        if self.usado:
            return False
        limite = self.creado_en + timezone.timedelta(days=self.vigencia_dias)
        return timezone.now() <= limite

    def __str__(self):
        return f"LinkCaptura({self.solicitud_id}) - usado={self.usado}"
