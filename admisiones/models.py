from django.db import models, transaction
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.conf import settings
import uuid


class Solicitud(models.Model):
    # PDF (si después quieres generar oficio/carta)
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

    # ✅ Dictamen / respuesta (Sprint 2)
    comentario_respuesta = models.TextField(
        null=True,
        blank=True,
        help_text="Motivo de rechazo o comentario institucional de respuesta."
    )
    dictaminado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="solicitudes_dictaminadas"
    )
    dictaminado_en = models.DateTimeField(null=True, blank=True)

    # ---------------- Tutor (El solicitante principal) ----------------
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

    # --- CAMBIO (Punto 6): Domicilio estructurado del tutor principal ---
    estado_domicilio = models.CharField(max_length=100, blank=True)
    ciudad = models.CharField(max_length=100, blank=True)
    codigo_postal = models.CharField(max_length=10, blank=True)
    calle = models.CharField(max_length=150, blank=True)
    numero_exterior = models.CharField(max_length=20, blank=True)
    numero_interior = models.CharField(max_length=20, blank=True)

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
    # --- CAMBIO (Punto 2): Nombre del menor estructurado ---
    nombres_menor = models.CharField(max_length=80, blank=True)
    apellido_paterno_menor = models.CharField(max_length=60, blank=True)
    apellido_materno_menor = models.CharField(max_length=60, blank=True)

    fecha_nacimiento_menor = models.DateField(null=True, blank=True)
    curp_menor = models.CharField(max_length=18, blank=True)

    def nombre_tutor_completo(self):
        return f"{self.nombres_tutor} {self.apellido_paterno_tutor} {self.apellido_materno_tutor}".strip()

    def nombre_menor_completo(self):
        return f"{self.nombres_menor} {self.apellido_paterno_menor} {self.apellido_materno_menor}".strip()

    def __str__(self):
        return f"Solicitud Folio {self.folio}" if self.folio else f"Solicitud #{self.id}"

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
    solicitud = models.ForeignKey(
        "admisiones.Solicitud",
        on_delete=models.CASCADE,
        related_name="links"
    )
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


# =========================================================
# SPRINT 2: MÓDULO DE INSCRIPCIÓN
# =========================================================

class SolicitudInscripcion(models.Model):
    solicitud_ingreso = models.OneToOneField(
        'admisiones.Solicitud',
        on_delete=models.CASCADE,
        related_name="inscripcion_oficial",
        verbose_name="Solicitud de Ingreso Base"
    )

    usuario_tutor = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="expediente_inscripcion",
        verbose_name="Cuenta del Tutor"
    )

    class EstadoInscripcion(models.TextChoices):
        NUEVA = "NUEVA", "Nueva"
        EN_PROCESO = "EN_PROCESO", "En Proceso (Capturando datos)"
        EN_REVISION = "EN_REVISION", "Enviada para Revisión"
        FINALIZADA = "FINALIZADA", "Inscripción Finalizada y Aprobada"

    estado = models.CharField(
        max_length=20,
        choices=EstadoInscripcion.choices,
        default=EstadoInscripcion.NUEVA
    )

    # =======================================================
    # PASO 8: COMPLEMENTO DE INFORMACIÓN DEL BENEFICIARIO
    # =======================================================
    avance_academico = models.CharField(max_length=50, null=True, blank=True, verbose_name="Avance Académico")
    estado_civil_tutor = models.CharField(max_length=50, null=True, blank=True, verbose_name="Estado Civil")

    # Campo extra necesario para tu lógica de JS excluyente
    parentesco_tutor = models.CharField(max_length=50, null=True, blank=True, verbose_name="Parentesco Confirmado")

    # =======================================================
    # PASO 10: COMPLEMENTO DE INFORMACIÓN DEL MENOR
    # =======================================================
    class SexoChoices(models.TextChoices):
        M = "M", "Masculino"
        F = "F", "Femenino"

    # --- CAMBIO (Punto 4): Lugar de Nacimiento Estructurado ---
    estado_nacimiento_menor = models.CharField(max_length=100, null=True, blank=True,
                                               verbose_name="Estado de Nacimiento")
    municipio_nacimiento_menor = models.CharField(max_length=100, null=True, blank=True,
                                                  verbose_name="Municipio de Nacimiento")

    # Edades
    edad_anios_menor = models.PositiveIntegerField(null=True, blank=True)
    edad_meses_menor = models.PositiveIntegerField(null=True, blank=True)

    sexo_menor = models.CharField(max_length=2, choices=SexoChoices.choices, null=True, blank=True, verbose_name="Sexo")
    tipo_sangre_menor = models.CharField(max_length=20, null=True, blank=True, verbose_name="Tipo de Sangre")

    # =======================================================
    # PASO 9: INFORMACIÓN GENERAL (SECCIÓN 3 Y 4 DEL PDF)
    # =======================================================
    # Datos del Padre / Madre (Sección 3)
    parentesco_segundo_padre = models.CharField(max_length=50, null=True, blank=True)

    # --- CAMBIO (Punto 2): Nombre del otro tutor estructurado ---
    nombres_segundo_padre = models.CharField(max_length=80, null=True, blank=True, verbose_name="Nombre(s)")
    apellido_paterno_segundo_padre = models.CharField(max_length=60, null=True, blank=True,
                                                      verbose_name="Apellido Paterno")
    apellido_materno_segundo_padre = models.CharField(max_length=60, null=True, blank=True,
                                                      verbose_name="Apellido Materno")

    estado_civil_segundo_padre = models.CharField(max_length=50, null=True, blank=True,
                                                  verbose_name="Estado Civil Padre/Madre")
    ocupacion_segundo_padre = models.CharField(max_length=100, null=True, blank=True,
                                               verbose_name="Ocupación Padre/Madre")

    # --- CAMBIO (Punto 6): Dirección estructurada del segundo tutor ---
    estado_domicilio_segundo_padre = models.CharField(max_length=100, null=True, blank=True)
    ciudad_segundo_padre = models.CharField(max_length=100, null=True, blank=True)
    codigo_postal_segundo_padre = models.CharField(max_length=10, null=True, blank=True)
    calle_segundo_padre = models.CharField(max_length=150, null=True, blank=True)
    numero_exterior_segundo_padre = models.CharField(max_length=20, null=True, blank=True)
    numero_interior_segundo_padre = models.CharField(max_length=20, null=True, blank=True)

    celular_segundo_padre = models.CharField(max_length=15, null=True, blank=True, verbose_name="Celular Padre/Madre")
    correo_segundo_padre = models.EmailField(null=True, blank=True, verbose_name="Correo Padre/Madre")

    # =======================================================
    # TELÉFONOS DE FAMILIARES AUTORIZADOS
    # =======================================================
    # --- CAMBIO (Punto 7): Estructura de nombres en Contacto 1 ---
    contacto_1_nombres = models.CharField(max_length=80, null=True, blank=True)
    contacto_1_apellido_paterno = models.CharField(max_length=60, null=True, blank=True)
    contacto_1_apellido_materno = models.CharField(max_length=60, null=True, blank=True)
    contacto_1_parentesco = models.CharField(max_length=50, null=True, blank=True)
    contacto_1_telefono = models.CharField(max_length=15, null=True, blank=True)

    # --- CAMBIO (Punto 7): Estructura de nombres en Contacto 2 ---
    contacto_2_nombres = models.CharField(max_length=80, null=True, blank=True)
    contacto_2_apellido_paterno = models.CharField(max_length=60, null=True, blank=True)
    contacto_2_apellido_materno = models.CharField(max_length=60, null=True, blank=True)
    contacto_2_parentesco = models.CharField(max_length=50, null=True, blank=True)
    contacto_2_telefono = models.CharField(max_length=15, null=True, blank=True)

    # --- CAMBIO (Punto 7): Estructura de nombres en Contacto 3 ---
    contacto_3_nombres = models.CharField(max_length=80, null=True, blank=True)
    contacto_3_apellido_paterno = models.CharField(max_length=60, null=True, blank=True)
    contacto_3_apellido_materno = models.CharField(max_length=60, null=True, blank=True)
    contacto_3_parentesco = models.CharField(max_length=50, null=True, blank=True)
    contacto_3_telefono = models.CharField(max_length=15, null=True, blank=True)

    # =======================================================
    # PASO 11: ACEPTACIÓN DE REGLAMENTOS
    # =======================================================
    acepto_reglamentos = models.BooleanField(default=False)
    fecha_aceptacion = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Inscripción - Folio: {self.solicitud_ingreso.folio} ({self.estado})"