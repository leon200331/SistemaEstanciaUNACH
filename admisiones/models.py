from django.db import models, transaction
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.conf import settings
import uuid
import re  # Para las validaciones numéricas del algoritmo


class Solicitud(models.Model):
    # =========================
    # ARCHIVO / CONTROL
    # =========================
    pdf = models.FileField(upload_to="pdf_solicitudes/", null=True, blank=True)

    folio = models.PositiveIntegerField(
        unique=True,
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
        help_text="Folio consecutivo (1–1000). Se asigna automáticamente al guardar."
    )

    created_at = models.DateTimeField(auto_now_add=True)

    # =========================
    # ESTADO GENERAL (SPRINT 2)
    # =========================
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

    # =========================
    # EVALUACIÓN POR ÁREAS (SPRINT 3)
    # =========================
    class EstadoEvaluacion(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        APROBADO = "APROBADO", "Aprobado"
        RECHAZADO = "RECHAZADO", "Rechazada"

    estado_psicologia = models.CharField(
        max_length=20,
        choices=EstadoEvaluacion.choices,
        default=EstadoEvaluacion.PENDIENTE
    )
    observaciones_psicologia = models.TextField(null=True, blank=True)

    # =========================
    # VALORACIÓN PSICOLÓGICA
    # =========================
    fecha_aplicacion_psicologia = models.DateField(null=True, blank=True)
    como_lo_llaman_en_casa = models.CharField(max_length=120, blank=True, default="")
    edad_psicologia = models.PositiveIntegerField(null=True, blank=True)
    lugar_nacimiento_menor_psicologia = models.CharField(max_length=150, blank=True, default="")

    nombre_padre_psicologia = models.CharField(max_length=150, blank=True, default="")
    edad_padre_psicologia = models.PositiveIntegerField(null=True, blank=True)
    nacionalidad_padre_psicologia = models.CharField(max_length=80, blank=True, default="")
    estado_civil_padre_psicologia = models.CharField(max_length=80, blank=True, default="")
    religion_padre_psicologia = models.CharField(max_length=80, blank=True, default="")
    ocupacion_padre_psicologia = models.CharField(max_length=120, blank=True, default="")
    lugar_trabajo_padre_psicologia = models.CharField(max_length=150, blank=True, default="")
    horario_trabajo_padre_psicologia = models.CharField(max_length=120, blank=True, default="")
    escolaridad_padre_psicologia = models.CharField(max_length=120, blank=True, default="")
    estudiante_padre_psicologia = models.BooleanField(default=False)
    licenciatura_padre_psicologia = models.CharField(max_length=150, blank=True, default="")
    semestre_padre_psicologia = models.CharField(max_length=20, blank=True, default="")

    nombre_madre_psicologia = models.CharField(max_length=150, blank=True, default="")
    edad_madre_psicologia = models.PositiveIntegerField(null=True, blank=True)
    nacionalidad_madre_psicologia = models.CharField(max_length=80, blank=True, default="")
    estado_civil_madre_psicologia = models.CharField(max_length=80, blank=True, default="")
    religion_madre_psicologia = models.CharField(max_length=80, blank=True, default="")
    ocupacion_madre_psicologia = models.CharField(max_length=120, blank=True, default="")
    lugar_trabajo_madre_psicologia = models.CharField(max_length=150, blank=True, default="")
    horario_trabajo_madre_psicologia = models.CharField(max_length=120, blank=True, default="")
    escolaridad_madre_psicologia = models.CharField(max_length=120, blank=True, default="")
    estudiante_madre_psicologia = models.BooleanField(default=False)
    licenciatura_madre_psicologia = models.CharField(max_length=150, blank=True, default="")
    semestre_madre_psicologia = models.CharField(max_length=20, blank=True, default="")

    numero_gesta_psicologia = models.CharField(max_length=50, blank=True, default="")
    embarazo_planeado_psicologia = models.CharField(max_length=20, blank=True, default="")
    dificultad_embarazo_psicologia = models.TextField(blank=True, default="")
    estado_animo_madre_embarazo_psicologia = models.TextField(blank=True, default="")
    momento_supieron_sexo_bebe_psicologia = models.TextField(blank=True, default="")
    quien_eligio_nombre_bebe_psicologia = models.TextField(blank=True, default="")
    motivo_nombre_bebe_psicologia = models.TextField(blank=True, default="")

    tipo_nacimiento_psicologia = models.CharField(max_length=50, blank=True, default="")
    semanas_gestacion_psicologia = models.CharField(max_length=100, blank=True, default="")
    dificultad_nacimiento_psicologia = models.TextField(blank=True, default="")
    peso_al_nacer_psicologia = models.CharField(max_length=20, blank=True, default="")
    talla_al_nacer_psicologia = models.CharField(max_length=20, blank=True, default="")
    apego_inmediato_psicologia = models.CharField(max_length=100, blank=True, default="")
    metodo_alimentacion_inicio_psicologia = models.CharField(max_length=20, blank=True, default="")

    edad_destete_psicologia = models.CharField(max_length=30, blank=True, default="")
    motivo_destete_psicologia = models.TextField(blank=True, default="")

    edad_balbuceo_psicologia = models.CharField(max_length=30, blank=True, default="")
    edad_primera_palabra_psicologia = models.CharField(max_length=30, blank=True, default="")
    lenguaje_actual_psicologia = models.CharField(max_length=100, blank=True, default="")
    dificultad_lenguaje_psicologia = models.TextField(blank=True, default="")

    edad_se_sento_solo_psicologia = models.CharField(max_length=30, blank=True, default="")
    gateo_psicologia = models.CharField(max_length=10, blank=True, default="")
    edad_gateo_psicologia = models.CharField(max_length=30, blank=True, default="")
    edad_marcha_independiente_psicologia = models.CharField(max_length=30, blank=True, default="")
    dominancia_manual_psicologia = models.CharField(max_length=100, blank=True, default="")

    comportamiento_general_psicologia = models.TextField(blank=True, default="")
    relacion_otros_ninos_psicologia = models.TextField(blank=True, default="")
    apego_figura_familiar_psicologia = models.CharField(max_length=10, blank=True, default="")
    apego_con_quien_psicologia = models.CharField(max_length=120, blank=True, default="")
    se_viste_solo_psicologia = models.CharField(max_length=10, blank=True, default="")
    se_pone_prendas_solo_psicologia = models.CharField(max_length=10, blank=True, default="")
    cuales_prendas_se_pone_psicologia = models.CharField(max_length=200, blank=True, default="")
    se_quita_prendas_solo_psicologia = models.CharField(max_length=10, blank=True, default="")
    cuales_prendas_se_quita_psicologia = models.CharField(max_length=200, blank=True, default="")
    intenta_banarse_solo_psicologia = models.CharField(max_length=10, blank=True, default="")
    se_cepilla_dientes_solo_psicologia = models.CharField(max_length=10, blank=True, default="")
    come_solo_psicologia = models.CharField(max_length=10, blank=True, default="")
    toma_vaso_solo_psicologia = models.CharField(max_length=10, blank=True, default="")
    iniciativa_para_jugar_psicologia = models.CharField(max_length=10, blank=True, default="")

    realiza_siestas_psicologia = models.CharField(max_length=10, blank=True, default="")
    cuantas_siestas_psicologia = models.CharField(max_length=20, blank=True, default="")
    con_quien_duerme_psicologia = models.CharField(max_length=120, blank=True, default="")
    hora_duerme_noche_psicologia = models.CharField(max_length=20, blank=True, default="")
    hora_despierta_manana_psicologia = models.CharField(max_length=20, blank=True, default="")
    necesita_algo_para_dormir_psicologia = models.CharField(max_length=10, blank=True, default="")
    que_necesita_para_dormir_psicologia = models.CharField(max_length=200, blank=True, default="")
    despierta_con_frecuencia_psicologia = models.CharField(max_length=10, blank=True, default="")

    actividades_tarde_psicologia = models.TextField(blank=True, default="")
    actividad_extra_tarde_psicologia = models.TextField(blank=True, default="")
    juego_favorito_psicologia = models.CharField(max_length=150, blank=True, default="")
    cancion_favorita_psicologia = models.CharField(max_length=150, blank=True, default="")
    personaje_favorito_psicologia = models.CharField(max_length=150, blank=True, default="")
    tiempo_pantallas_psicologia = models.CharField(max_length=100, blank=True, default="")
    socializa_tardes_con_quien_psicologia = models.CharField(max_length=150, blank=True, default="")
    lugar_para_jugar_psicologia = models.CharField(max_length=150, blank=True, default="")
    comparte_juguetes_psicologia = models.CharField(max_length=100, blank=True, default="")
    conducta_lider_juego_psicologia = models.CharField(max_length=100, blank=True, default="")
    relacion_con_otros_ninos_detalle_psicologia = models.TextField(blank=True, default="")
    se_adapta_nuevos_entornos_psicologia = models.CharField(max_length=100, blank=True, default="")
    actividades_fin_semana_psicologia = models.TextField(blank=True, default="")

    controla_orinar_psicologia = models.CharField(max_length=50, blank=True, default="")
    controla_defecar_psicologia = models.CharField(max_length=50, blank=True, default="")
    edad_comenzo_avisar_psicologia = models.CharField(max_length=30, blank=True, default="")
    donde_realiza_necesidades_psicologia = models.CharField(max_length=100, blank=True, default="")
    algo_significativo_control_esfinteres_psicologia = models.TextField(blank=True, default="")
    duerme_con_panal_noche_psicologia = models.CharField(max_length=50, blank=True, default="")
    reaccion_no_controla_esfinteres_psicologia = models.TextField(blank=True, default="")
    que_hace_responsable_cuando_sucede_psicologia = models.TextField(blank=True, default="")

    persona_aparte_padres_crianza_psicologia = models.TextField(blank=True, default="")
    persona_aparte_padres_cuidado_psicologia = models.TextField(blank=True, default="")
    periodos_cuidado_psicologia = models.TextField(blank=True, default="")
    relacion_padre_madre_con_nino_psicologia = models.TextField(blank=True, default="")
    tiempo_papa_dia_psicologia = models.CharField(max_length=100, blank=True, default="")
    tiempo_mama_dia_psicologia = models.CharField(max_length=100, blank=True, default="")
    metodo_mejorar_conducta_casa_psicologia = models.TextField(blank=True, default="")
    dificultad_actual_hogar_entorno_psicologia = models.TextField(blank=True, default="")
    beneficio_esperado_hijo_estancia_psicologia = models.TextField(blank=True, default="")
    beneficio_personal_estancia_psicologia = models.TextField(blank=True, default="")

    psicologia_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="solicitudes_psicologia"
    )
    psicologia_en = models.DateTimeField(null=True, blank=True)

    estado_nutricion = models.CharField(
        max_length=20,
        choices=EstadoEvaluacion.choices,
        default=EstadoEvaluacion.PENDIENTE
    )

    observaciones_nutricion = models.TextField(null=True, blank=True)

    # =========================
    # VALORACIÓN NUTRICIONAL PRESENCIAL
    # =========================
    edad_nutricion = models.CharField(max_length=50, blank=True, default="")
    sexo_nutricion = models.CharField(max_length=20, blank=True, default="")
    fecha_nacimiento_nutricion = models.CharField(max_length=50, blank=True, default="")

    peso_nacer = models.CharField(max_length=50, blank=True, default="")
    talla_nacer = models.CharField(max_length=50, blank=True, default="")
    peso_actual = models.CharField(max_length=50, blank=True, default="")
    talla_actual = models.CharField(max_length=50, blank=True, default="")

    seno_materno = models.CharField(max_length=20, blank=True, default="")
    tiempo_seno_materno = models.CharField(max_length=100, blank=True, default="")
    motivo_no_seno = models.TextField(blank=True, default="")
    acude_lactancia = models.CharField(max_length=20, blank=True, default="")

    tipo_alimentacion_lactante = models.CharField(max_length=50, blank=True, default="")
    formula_infantil = models.CharField(max_length=20, blank=True, default="")
    cual_formula = models.CharField(max_length=150, blank=True, default="")
    edad_inicio_formula = models.CharField(max_length=100, blank=True, default="")

    formula_especial = models.CharField(max_length=20, blank=True, default="")
    cual_formula_especial = models.CharField(max_length=150, blank=True, default="")
    causa_formula_especial = models.TextField(blank=True, default="")

    cantidad_leche_formula = models.CharField(max_length=100, blank=True, default="")
    cada_cuantas_horas_leche = models.CharField(max_length=100, blank=True, default="")

    presentacion_leche = models.CharField(max_length=50, blank=True, default="")
    presentacion_leche_otra = models.CharField(max_length=150, blank=True, default="")

    forma_proporcionar_formula = models.CharField(max_length=50, blank=True, default="")
    forma_proporcionar_formula_otra = models.CharField(max_length=150, blank=True, default="")

    complicaciones_alimentacion = models.CharField(max_length=20, blank=True, default="")
    tipo_complicacion = models.CharField(max_length=50, blank=True, default="")
    tipo_complicacion_otra = models.CharField(max_length=150, blank=True, default="")

    agrega_alimento_formula = models.CharField(max_length=20, blank=True, default="")
    cual_agrega_formula = models.CharField(max_length=150, blank=True, default="")

    edad_cambio_leche = models.CharField(max_length=100, blank=True, default="")
    edad_inicio_alimentacion_complementaria = models.CharField(max_length=100, blank=True, default="")

    orden_verduras = models.CharField(max_length=150, blank=True, default="")
    orden_frutas = models.CharField(max_length=150, blank=True, default="")
    orden_carnes = models.CharField(max_length=150, blank=True, default="")
    orden_jugo_frutas = models.CharField(max_length=150, blank=True, default="")
    orden_yema_huevo = models.CharField(max_length=150, blank=True, default="")
    orden_huevo_entero = models.CharField(max_length=150, blank=True, default="")
    orden_arroz = models.CharField(max_length=150, blank=True, default="")
    orden_galleta_pan = models.CharField(max_length=150, blank=True, default="")
    orden_pastas = models.CharField(max_length=150, blank=True, default="")
    orden_leguminosas = models.CharField(max_length=150, blank=True, default="")
    orden_citricos = models.CharField(max_length=150, blank=True, default="")

    alergia_alimentos = models.CharField(max_length=20, blank=True, default="")
    cual_alergia = models.CharField(max_length=150, blank=True, default="")
    reaccion_alergia = models.TextField(blank=True, default="")

    restriccion_alimentaria_actual = models.CharField(max_length=20, blank=True, default="")
    detalle_restriccion_alimentaria = models.TextField(blank=True, default="")

    presentacion_alimentos = models.CharField(max_length=50, blank=True, default="")
    orden_alimentos = models.CharField(max_length=50, blank=True, default="")
    frecuencia_solidos = models.CharField(max_length=50, blank=True, default="")

    alimentos_agrado_frutas = models.TextField(blank=True, default="")
    alimentos_agrado_verduras = models.TextField(blank=True, default="")
    alimentos_agrado_cereales = models.TextField(blank=True, default="")
    alimentos_agrado_leguminosas = models.TextField(blank=True, default="")
    alimentos_agrado_aoa = models.TextField(blank=True, default="")
    alimentos_agrado_lacteos = models.TextField(blank=True, default="")

    consume_agua = models.CharField(max_length=20, blank=True, default="")
    cantidad_agua = models.CharField(max_length=100, blank=True, default="")

    desayuna = models.CharField(max_length=20, blank=True, default="")
    hora_desayuno = models.CharField(max_length=50, blank=True, default="")
    come = models.CharField(max_length=20, blank=True, default="")
    hora_comida = models.CharField(max_length=50, blank=True, default="")
    cena = models.CharField(max_length=20, blank=True, default="")
    hora_cena = models.CharField(max_length=50, blank=True, default="")
    colacion = models.CharField(max_length=20, blank=True, default="")
    hora_colacion = models.CharField(max_length=50, blank=True, default="")

    acostumbra_comer_desayuno = models.TextField(blank=True, default="")
    acostumbra_comer_comida = models.TextField(blank=True, default="")
    acostumbra_comer_cena = models.TextField(blank=True, default="")
    acostumbra_comer_colaciones = models.TextField(blank=True, default="")

    misma_alimentacion_familia = models.CharField(max_length=20, blank=True, default="")
    detalle_misma_alimentacion = models.TextField(blank=True, default="")

    consume_golosinas = models.CharField(max_length=20, blank=True, default="")
    frecuencia_golosinas = models.CharField(max_length=100, blank=True, default="")
    cuales_golosinas = models.CharField(max_length=150, blank=True, default="")

    consume_refrescos = models.CharField(max_length=20, blank=True, default="")
    frecuencia_refrescos = models.CharField(max_length=100, blank=True, default="")
    cuales_refrescos = models.CharField(max_length=150, blank=True, default="")

    consume_jugos = models.CharField(max_length=20, blank=True, default="")
    frecuencia_jugos = models.CharField(max_length=100, blank=True, default="")
    cuales_jugos = models.CharField(max_length=150, blank=True, default="")

    donde_consume_alimentos = models.CharField(max_length=50, blank=True, default="")
    donde_consume_alimentos_otro = models.CharField(max_length=150, blank=True, default="")

    compania_comida = models.CharField(max_length=50, blank=True, default="")
    compania_comida_otro = models.CharField(max_length=150, blank=True, default="")

    come_con = models.CharField(max_length=50, blank=True, default="")
    consume_bebidas_en = models.CharField(max_length=50, blank=True, default="")
    consume_bebidas_en_otro = models.CharField(max_length=150, blank=True, default="")

    come_solo_o_ayuda = models.CharField(max_length=50, blank=True, default="")

    observaciones_nutricion_clinica = models.TextField(blank=True, default="")
    fecha_elaboracion_nutricion = models.CharField(max_length=50, blank=True, default="")

    nutricion_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="solicitudes_nutricion"
    )

    nutricion_en = models.DateTimeField(null=True, blank=True)

    estado_medico = models.CharField(
        max_length=20,
        choices=EstadoEvaluacion.choices,
        default=EstadoEvaluacion.PENDIENTE
    )

    observaciones_medico = models.TextField(null=True, blank=True)

    medico_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="solicitudes_medico"
    )
    medico_en = models.DateTimeField(null=True, blank=True)

    # =========================
    # DATOS DEL TUTOR
    # =========================
    nombres_tutor = models.CharField(max_length=80)
    apellido_paterno_tutor = models.CharField(max_length=60)
    apellido_materno_tutor = models.CharField(max_length=60, blank=True)

    matricula = models.CharField(max_length=20, blank=True)

    # --- CAMPOS LIBERADOS DE RESTRICCIONES (SPRINT DE CORRECCIÓN) ---
    programa_educativo = models.CharField(max_length=250, blank=True, null=True)
    estado_domicilio = models.CharField(max_length=100, blank=True, null=True)
    ciudad = models.CharField(max_length=100, blank=True, null=True)
    # ------------------------------------------------------------------

    programa_educativo_otro = models.CharField(max_length=80, blank=True)
    unidad_academica = models.CharField(max_length=120, blank=True)

    correo = models.EmailField(blank=True)
    celular = models.CharField(max_length=10, blank=True)

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

    # =========================
    # DATOS DEL MENOR
    # =========================
    nombres_menor = models.CharField(max_length=80, blank=True)
    apellido_paterno_menor = models.CharField(max_length=60, blank=True)
    apellido_materno_menor = models.CharField(max_length=60, blank=True)

    fecha_nacimiento_menor = models.DateField(null=True, blank=True)
    curp_menor = models.CharField(max_length=18, blank=True)

    # =========================
    # HELPERS
    # =========================
    def nombre_tutor_completo(self):
        return f"{self.nombres_tutor} {self.apellido_paterno_tutor} {self.apellido_materno_tutor}".strip()

    def nombre_menor_completo(self):
        return f"{self.nombres_menor} {self.apellido_paterno_menor} {self.apellido_materno_menor}".strip()

    def evaluaciones_completas(self) -> bool:
        return all([
            self.estado_psicologia != self.EstadoEvaluacion.PENDIENTE,
            self.estado_nutricion != self.EstadoEvaluacion.PENDIENTE,
            self.estado_medico != self.EstadoEvaluacion.PENDIENTE,
        ])

    def todas_aprobadas(self) -> bool:
        return all([
            self.estado_psicologia == self.EstadoEvaluacion.APROBADO,
            self.estado_nutricion == self.EstadoEvaluacion.APROBADO,
            self.estado_medico == self.EstadoEvaluacion.APROBADO,
        ])

    def __str__(self):
        return f"Solicitud Folio {self.folio}" if self.folio else f"Solicitud #{self.id}"

    # =========================
    # FOLIO AUTOMÁTICO
    # =========================
    def save(self, *args, **kwargs):
        if self.folio is None:
            with transaction.atomic():
                last = Solicitud.objects.select_for_update().order_by("-folio").first()
                next_folio = 1 if (not last or not last.folio) else (last.folio + 1)

                if next_folio > 1000:
                    raise ValueError("Se alcanzó el límite de folios (1–1000).")

                self.folio = next_folio

        super().save(*args, **kwargs)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["estado"]),
            models.Index(fields=["estado_psicologia"]),
            models.Index(fields=["estado_nutricion"]),
            models.Index(fields=["estado_medico"]),
            models.Index(fields=["folio"]),
        ]


class LinkCaptura(models.Model):
    """
    Link único (token) para capturar solicitud.
    - Se marca como usado cuando el tutor finaliza (estado pasa a RECIBIDA)
    - Se puede definir vigencia (por ejemplo 7 días)
    """
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

    class Meta:
        indexes = [
            models.Index(fields=["token"]),
            models.Index(fields=["usado"]),
        ]


# =========================================================
# SPRINT 2: MÓDULO DE INSCRIPCIÓN
# =========================================================
class SolicitudInscripcion(models.Model):
    solicitud_ingreso = models.OneToOneField(
        "admisiones.Solicitud",
        on_delete=models.CASCADE,
        related_name="inscripcion_oficial",
        verbose_name="Solicitud de Ingreso Base"
    )

    usuario_tutor = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expediente_inscripcion",
        verbose_name="Cuenta del Tutor"
    )

    class EstadoInscripcion(models.TextChoices):
        NUEVA = "NUEVA", "Nueva"
        EN_PROCESO = "EN_PROCESO", "En Proceso (Capturando datos)"
        DEVUELTA = "DEVUELTA", "Devuelta"
        EN_REVISION = "EN_REVISION", "Enviada para Revisión"
        FILTROS = "FILTROS", "En filtros (Físicos)"
        ESPERANDO_DIRECTORA = "ESPERANDO_DIRECTORA", "Esperando Veredicto de Dirección"
        SALA_EN_REVISION = "SALA_EN_REVISION", "Sala Propuesta a Dirección"
        SALA_RECHAZADA = "SALA_RECHAZADA", "Sala Rechazada por Dirección"
        SALA_APROBADA = "SALA_APROBADA", "Sala Aprobada por Dirección"
        ACEPTADO_ESPERANDO_PAGO = "ACEPTADO_ESPERANDO_PAGO", "Aceptado - Esperando Pago"
        FINALIZADA = "FINALIZADA", "Inscripción Finalizada y Aprobada"
        RECHAZADA = "RECHAZADA", "Rechazada"

    estado = models.CharField(
        max_length=30,
        choices=EstadoInscripcion.choices,
        default=EstadoInscripcion.NUEVA
    )

    # --- CAMPO NUEVO AÑADIDO: SALA ASIGNADA ---
    sala_asignada = models.ForeignKey(
        "admisiones.Sala",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alumnos_asignados",
        verbose_name="Sala Asignada"
    )

    # === SISTEMA DE ASIGNACIÓN INTELIGENTE DE SALAS (AGREGADO) ===
    sala_recomendada = models.CharField(max_length=10, blank=True, null=True,
                                        verbose_name="Sala Recomendada por Sistema")
    motivo_recomendacion_sala = models.TextField(blank=True, null=True, verbose_name="Justificación del Algoritmo")
    sala_bloqueada = models.BooleanField(default=False, verbose_name="Candado del Semestre (Fijada por TS)")

    # --- ¡CAMPO NUEVO PARA EL PING PONG! ---
    motivo_rechazo_sala = models.TextField(blank=True, null=True,
                                           verbose_name="Comentario de Directora (Rechazo de Sala)")
    # =============================================================

    avance_academico = models.CharField(max_length=50, null=True, blank=True, verbose_name="Avance Académico")
    estado_civil_tutor = models.CharField(max_length=50, null=True, blank=True, verbose_name="Estado Civil")
    parentesco_tutor = models.CharField(max_length=50, null=True, blank=True, verbose_name="Parentesco Confirmado")

    class SexoChoices(models.TextChoices):
        M = "M", "Masculino"
        F = "F", "Femenino"

    estado_nacimiento_menor = models.CharField(max_length=100, null=True, blank=True,
                                               verbose_name="Estado de Nacimiento")
    municipio_nacimiento_menor = models.CharField(max_length=100, null=True, blank=True,
                                                  verbose_name="Municipio de Nacimiento")

    edad_anios_menor = models.PositiveIntegerField(null=True, blank=True)
    edad_meses_menor = models.PositiveIntegerField(null=True, blank=True)

    sexo_menor = models.CharField(max_length=2, choices=SexoChoices.choices, null=True, blank=True, verbose_name="Sexo")
    tipo_sangre_menor = models.CharField(max_length=20, null=True, blank=True, verbose_name="Tipo de Sangre")

    # --- DATOS DE PAREJA / SEGUNDO TUTOR (PUNTO 5) ---
    parentesco_segundo_padre = models.CharField(max_length=50, null=True, blank=True)

    vinculo_segundo_padre = models.CharField(
        max_length=20,
        choices=[('BIOLOGICO', 'Padre/Madre de sangre'), ('POLITICO', 'Madrastra/Padrastro')],
        null=True, blank=True,
        verbose_name="Vínculo de la pareja con el menor"
    )

    nombres_segundo_padre = models.CharField(max_length=80, null=True, blank=True, verbose_name="Nombre(s)")
    apellido_paterno_segundo_padre = models.CharField(max_length=60, null=True, blank=True,
                                                      verbose_name="Apellido Paterno")
    apellido_materno_segundo_padre = models.CharField(max_length=60, null=True, blank=True,
                                                      verbose_name="Apellido Materno")
    estado_civil_segundo_padre = models.CharField(max_length=50, null=True, blank=True,
                                                  verbose_name="Estado Civil Padre/Madre")
    ocupacion_segundo_padre = models.CharField(max_length=100, null=True, blank=True,
                                               verbose_name="Ocupación Padre/Madre")

    estado_domicilio_segundo_padre = models.CharField(max_length=100, null=True, blank=True)
    ciudad_segundo_padre = models.CharField(max_length=100, null=True, blank=True)
    codigo_postal_segundo_padre = models.CharField(max_length=10, null=True, blank=True)
    calle_segundo_padre = models.CharField(max_length=150, null=True, blank=True)
    numero_exterior_segundo_padre = models.CharField(max_length=20, null=True, blank=True)
    numero_interior_segundo_padre = models.CharField(max_length=20, null=True, blank=True)

    celular_segundo_padre = models.CharField(max_length=15, null=True, blank=True, verbose_name="Celular Padre/Madre")
    correo_segundo_padre = models.EmailField(null=True, blank=True, verbose_name="Correo Padre/Madre")

    contacto_1_nombres = models.CharField(max_length=80, null=True, blank=True)
    contacto_1_apellido_paterno = models.CharField(max_length=60, null=True, blank=True)
    contacto_1_apellido_materno = models.CharField(max_length=60, null=True, blank=True)
    contacto_1_parentesco = models.CharField(max_length=50, null=True, blank=True)
    contacto_1_telefono = models.CharField(max_length=15, null=True, blank=True)

    contacto_2_nombres = models.CharField(max_length=80, null=True, blank=True)
    contacto_2_apellido_paterno = models.CharField(max_length=60, null=True, blank=True)
    contacto_2_apellido_materno = models.CharField(max_length=60, null=True, blank=True)
    contacto_2_parentesco = models.CharField(max_length=50, null=True, blank=True)
    contacto_2_telefono = models.CharField(max_length=15, null=True, blank=True)

    contacto_3_nombres = models.CharField(max_length=80, null=True, blank=True)
    contacto_3_apellido_paterno = models.CharField(max_length=60, null=True, blank=True)
    contacto_3_apellido_materno = models.CharField(max_length=60, null=True, blank=True)
    contacto_3_parentesco = models.CharField(max_length=50, null=True, blank=True)
    contacto_3_telefono = models.CharField(max_length=15, null=True, blank=True)

    acepto_reglamentos = models.BooleanField(default=False)
    fecha_aceptacion = models.DateTimeField(null=True, blank=True)

    # =========================================================
    # EXPEDIENTE DIGITAL (DOCUMENTOS OBLIGATORIOS)
    # =========================================================

    # --- 1. DEL MENOR ---
    doc_menor_certificado_medico = models.FileField(upload_to="expedientes/menor/", null=True, blank=True,
                                                    verbose_name="Certificado Médico")
    doc_menor_cartilla_vacunacion = models.FileField(upload_to="expedientes/menor/", null=True, blank=True,
                                                     verbose_name="Cartilla de Vacunación")
    doc_menor_grupo_sanguineo = models.FileField(upload_to="expedientes/menor/", null=True, blank=True,
                                                 verbose_name="Grupo Sanguíneo")
    doc_menor_acta_nacimiento = models.FileField(upload_to="expedientes/menor/", null=True, blank=True,
                                                 verbose_name="Acta de Nacimiento")
    doc_menor_fotos = models.FileField(upload_to="expedientes/menor/", null=True, blank=True,
                                       verbose_name="3 Fotos Infantiles")
    doc_menor_laboratorio = models.FileField(upload_to="expedientes/menor/", null=True, blank=True,
                                             verbose_name="Estudios de Laboratorio")

    # --- 2. DEL BENEFICIARIO (TUTOR) Y PAREJA ---
    doc_tutor_acta_nacimiento = models.FileField(upload_to="expedientes/tutor/", null=True, blank=True,
                                                 verbose_name="Acta de Nacimiento Tutor")
    doc_tutor_ine = models.FileField(upload_to="expedientes/tutor/", null=True, blank=True,
                                     verbose_name="Copia de INE Tutor")
    doc_tutor_fotos = models.FileField(upload_to="expedientes/tutor/", null=True, blank=True,
                                       verbose_name="3 Fotos Infantiles Tutor")

    # NUEVO CAMPO: FOTO DE LA PAREJA (PUNTO 9)
    doc_segundo_padre_fotos = models.FileField(upload_to="expedientes/tutor/", null=True, blank=True,
                                               verbose_name="Foto de la Pareja / Segundo Tutor")

    doc_tutor_domicilio = models.FileField(upload_to="expedientes/tutor/", null=True, blank=True,
                                           verbose_name="Comprobante de Domicilio")
    doc_tutor_pago = models.FileField(upload_to="expedientes/tutor/", null=True, blank=True,
                                      verbose_name="Comprobante de Pago Inscripción")
    doc_tutor_historial = models.FileField(upload_to="expedientes/tutor/", null=True, blank=True,
                                           verbose_name="Historial Académico")
    doc_tutor_horario = models.FileField(upload_to="expedientes/tutor/", null=True, blank=True,
                                         verbose_name="Horario de Clases")

    # --- 3. DE LOS AUTORIZADOS (PUNTO 9) ---
    doc_autorizado_carta = models.FileField(upload_to="expedientes/autorizado/", null=True, blank=True,
                                            verbose_name="Carta de Autorización")
    doc_autorizado_ine = models.FileField(upload_to="expedientes/autorizado/", null=True, blank=True,
                                          verbose_name="Copia de INE Autorizado")

    # NUEVOS CAMPOS: FOTOS INDIVIDUALES PARA LOS 3 CONTACTOS DE EMERGENCIA (PUNTO 9)
    doc_contacto_1_fotos = models.FileField(upload_to="expedientes/autorizado/", null=True, blank=True,
                                            verbose_name="Foto Familiar Autorizado 1")
    doc_contacto_2_fotos = models.FileField(upload_to="expedientes/autorizado/", null=True, blank=True,
                                            verbose_name="Foto Familiar Autorizado 2")
    doc_contacto_3_fotos = models.FileField(upload_to="expedientes/autorizado/", null=True, blank=True,
                                            verbose_name="Foto Familiar Autorizado 3")

    # --- REGLAMENTO ---
    reglamento_firmado = models.FileField(upload_to="reglamentos_firmados/", null=True, blank=True,
                                          verbose_name="Reglamento Firmado (PDF)")

    # --- CONTROL DE TRABAJO SOCIAL ---
    observaciones = models.TextField(null=True, blank=True, verbose_name="Observaciones (Correcciones)")
    comentario_tutor = models.TextField(null=True, blank=True, verbose_name="Comentario del Tutor al reenviar")

    # === CAMPOS NUEVOS PARA EL REPORTE FINAL DE INGRESO (TS) ===
    reporte_final_aprobado = models.BooleanField(null=True, blank=True, verbose_name="¿Se autoriza inscripción?")
    reporte_final_motivos = models.TextField(blank=True, null=True, verbose_name="Motivos de rechazo")
    reporte_final_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                          related_name='reportes_ts')
    reporte_final_en = models.DateTimeField(null=True, blank=True)

    # === FIRMA DE LA DIRECTORA ===
    directora_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='firmas_directora')
    directora_en = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # === MÉTODO DEL ALGORITMO AGREGADO ===
    def evaluar_y_recomendar_sala(self):
        """
        Algoritmo que evalúa los 3 dictámenes (Psicológico, Nutricional y Médico)
        y la edad cronológica para recomendar la sala ideal (L1, L2, L3, M1, M2, M3).
        """
        if not self.edad_anios_menor and not self.edad_meses_menor:
            return "L1", "No hay datos de edad suficientes. Se asigna L1 por defecto."

        anios = self.edad_anios_menor or 0
        meses = self.edad_meses_menor or 0
        edad_total_meses = (anios * 12) + meses

        sol = self.solicitud_ingreso

        # 1. SALA BASE POR EDAD CRONOLÓGICA (Aproximación estándar)
        if edad_total_meses < 7:
            sala_base = "L1"
        elif 7 <= edad_total_meses <= 12:
            sala_base = "L2"
        elif 13 <= edad_total_meses <= 18:
            sala_base = "L3"
        elif 19 <= edad_total_meses <= 24:
            sala_base = "M1"
        elif 25 <= edad_total_meses <= 30:
            sala_base = "M2"
        else:
            sala_base = "M3"

        # 2. SISTEMA DE PUNTUACIÓN (Penalizaciones / Alertas)
        alertas = []
        puntos_retraso = 0

        # --- A) Filtro Psicológico ---
        if str(sol.gateo_psicologia).upper() == "NO":
            puntos_retraso += 1
            alertas.append("No gatea aún.")

        if not sol.edad_marcha_independiente_psicologia and edad_total_meses > 18:
            puntos_retraso += 1
            alertas.append("No camina de forma independiente.")

        if str(sol.come_solo_psicologia).upper() == "NO":
            puntos_retraso += 1
            alertas.append("No come solo, requiere apoyo total.")

        if str(sol.se_adapta_nuevos_entornos_psicologia).upper() == "NO":
            alertas.append("Presenta dificultad para adaptarse a nuevos entornos (apego).")

        # --- B) Filtro Nutricional ---
        if str(sol.presentacion_alimentos).upper() in ["PURE", "MACHACADO"] and edad_total_meses > 12:
            puntos_retraso += 1
            alertas.append("Aún consume alimentos en papilla/puré.")

        # --- C) Filtro Médico (Si existe la historia clínica) ---
        if hasattr(self, 'historia_clinica_medica'):
            hc = self.historia_clinica_medica
            if hc:
                try:
                    semanas = int(re.sub(r'\D', '', hc.semanas_gestacion)) if hc.semanas_gestacion else 40
                    if semanas < 37:
                        puntos_retraso += 1
                        alertas.append(f"Nacimiento prematuro ({semanas} semanas).")
                except:
                    pass

        # 3. CÁLCULO DE SALA FINAL (Ajuste hacia abajo si hay retrasos/dependencia)
        jerarquia_salas = ["L1", "L2", "L3", "M1", "M2", "M3"]
        indice_actual = jerarquia_salas.index(sala_base)

        # Si tiene puntos de retraso, lo bajamos de sala proporcionalmente (máximo hasta L1)
        if puntos_retraso > 0:
            nuevo_indice = max(0, indice_actual - (1 if puntos_retraso <= 2 else 2))
            sala_recomendada = jerarquia_salas[nuevo_indice]
        else:
            sala_recomendada = sala_base

        # Construimos la justificación
        justificacion = f"Edad cronológica: {edad_total_meses} meses (Base: {sala_base}). "
        if puntos_retraso > 0:
            justificacion += f"Se ajustó a la sala {sala_recomendada} por las siguientes consideraciones integrales: " + ", ".join(
                alertas)
        else:
            justificacion += "El desarrollo es acorde a su edad. No se detectaron alertas que requieran ajuste de sala."

        self.sala_recomendada = sala_recomendada
        self.motivo_recomendacion_sala = justificacion
        self.save(update_fields=['sala_recomendada', 'motivo_recomendacion_sala'])

        return sala_recomendada, justificacion

    def __str__(self):
        return f"Expediente de Inscripción {self.id} - Solicitud {self.solicitud_ingreso_id}"


class HistoriaClinicaMedica(models.Model):
    inscripcion = models.OneToOneField(
        SolicitudInscripcion,
        on_delete=models.CASCADE,
        related_name="historia_clinica_medica",
        null=True,
        blank=True
    )

    nombre_paciente = models.CharField(max_length=200, blank=True)
    edad = models.CharField(max_length=20, blank=True)
    sexo = models.CharField(max_length=20, blank=True)
    lugar_fecha_elaboracion = models.CharField(max_length=255, blank=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    religion = models.CharField(max_length=100, blank=True)
    quien_cuida_menor = models.CharField(max_length=150, blank=True)

    nombre_padre = models.CharField(max_length=200, blank=True)
    edad_padre = models.CharField(max_length=20, blank=True)
    tabaquismo_padre = models.BooleanField(default=False)
    alcoholismo_padre = models.BooleanField(default=False)
    drogas_padre = models.BooleanField(default=False)
    enfermedades_actuales_padre = models.TextField(blank=True)
    alergias_padre = models.TextField(blank=True)

    nombre_madre = models.CharField(max_length=200, blank=True)
    edad_madre = models.CharField(max_length=20, blank=True)
    tabaquismo_madre = models.BooleanField(default=False)
    alcoholismo_madre = models.BooleanField(default=False)
    drogas_madre = models.BooleanField(default=False)
    enfermedades_actuales_madre = models.TextField(blank=True)
    enfermedades_infancia_madre = models.TextField(blank=True)
    alergias_madre = models.TextField(blank=True)

    numero_gestas = models.CharField(max_length=10, blank=True)
    complicaciones_embarazo = models.TextField(blank=True)
    medicamentos_embarazo = models.TextField(blank=True)
    exposicion_radiacion = models.TextField(blank=True)
    sufrimiento_fetal = models.TextField(blank=True)
    semanas_gestacion = models.CharField(max_length=50, blank=True)
    tipo_parto = models.CharField(max_length=100, blank=True)
    motivo_cesarea = models.TextField(blank=True)

    enfermedades_actuales = models.TextField(blank=True)
    enfermedades_neonatales = models.TextField(blank=True)
    enfermedades_exantematicas = models.TextField(blank=True)
    internamientos_quirurgicos = models.TextField(blank=True)
    alergia_medicamentos = models.TextField(blank=True)
    alergia_alimentos = models.TextField(blank=True)
    personas_enfermas_casa = models.TextField(blank=True)

    vomitos = models.TextField(blank=True)
    excreta_acuosa = models.TextField(blank=True)
    fiebre = models.TextField(blank=True)
    tos = models.TextField(blank=True)
    rinorrea = models.TextField(blank=True)
    erupciones = models.TextField(blank=True)
    dificultad_respiratoria = models.TextField(blank=True)

    peso_actual = models.CharField(max_length=20, blank=True)
    talla = models.CharField(max_length=20, blank=True)
    temperatura = models.CharField(max_length=20, blank=True)
    frecuencia_cardiaca = models.CharField(max_length=20, blank=True)
    frecuencia_respiratoria = models.CharField(max_length=20, blank=True)
    tension_arterial = models.CharField(max_length=20, blank=True)
    estado_nutricional = models.CharField(max_length=100, blank=True)

    diagnostico = models.TextField(blank=True)
    pronostico = models.TextField(blank=True)
    elaborado_por = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Historia clínica - Solicitud {self.inscripcion_id}"


# =========================================================
# ÉPICA 3: CONFIGURACIÓN DE SEMESTRE Y SALAS
# =========================================================

class Semestre(models.Model):
    class SedeChoices(models.TextChoices):
        TUXTLA = "TUXTLA", "Tuxtla"
        TAPACHULA = "TAPACHULA", "Tapachula"

    class EstadoSemestre(models.TextChoices):
        CONFIGURACION = "CONFIGURACION", "En Configuración"
        ACTIVO = "ACTIVO", "Activo"
        CERRADO = "CERRADO", "Cerrado"

    nombre = models.CharField(max_length=100, help_text="Ej. Enero - Junio 2026")
    sede = models.CharField(max_length=20, choices=SedeChoices.choices, default=SedeChoices.TUXTLA)

    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()

    estado = models.CharField(max_length=20, choices=EstadoSemestre.choices, default=EstadoSemestre.CONFIGURACION)

    medico_asignado = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name="semestres_medico")
    nutriologa_asignada = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                            related_name="semestres_nutricion")
    psicologa_asignada = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                           related_name="semestres_psicologia")

    fecha_encuesta_satisfaccion = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombre} ({self.sede})"


class DiaFestivo(models.Model):
    semestre = models.ForeignKey(Semestre, on_delete=models.CASCADE, related_name="dias_festivos")
    fecha = models.DateField()
    motivo = models.CharField(max_length=200, help_text="Ej. Día del Trabajo, Consejo Técnico, etc.")

    def __str__(self):
        return f"{self.fecha} - {self.motivo}"


class Sala(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    capacidad_maxima = models.PositiveIntegerField(default=10)

    def __str__(self):
        return self.nombre


class SalaSemestre(models.Model):
    semestre = models.ForeignKey(Semestre, on_delete=models.CASCADE, related_name="salas_activas")
    sala = models.ForeignKey(Sala, on_delete=models.CASCADE)

    inicio_recepcion = models.TimeField(null=True, blank=True)
    termino_recepcion = models.TimeField(null=True, blank=True)
    horario_desayuno = models.TimeField(null=True, blank=True)
    horario_actividades_pedagogicas = models.TimeField(null=True, blank=True)
    horario_recreo = models.TimeField(null=True, blank=True)
    horario_colacion = models.TimeField(null=True, blank=True)
    horario_siesta = models.TimeField(null=True, blank=True)
    horario_comida = models.TimeField(null=True, blank=True)
    horario_salida = models.TimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.sala.nombre} - {self.semestre.nombre}"


class AsignacionMaestra(models.Model):
    class RolMaestra(models.TextChoices):
        TITULAR = "TITULAR", "Maestra Titular"
        TITULAR_2 = "TITULAR_2", "Segunda Titular"
        SUPLENTE = "SUPLENTE", "Maestra Suplente / Apoyo"

    sala_semestre = models.ForeignKey(SalaSemestre, on_delete=models.CASCADE, related_name="maestras_asignadas")
    maestra = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mis_salas")
    rol = models.CharField(max_length=20, choices=RolMaestra.choices, default=RolMaestra.TITULAR)

    horario_desayuno_maestra = models.TimeField(null=True, blank=True)
    horario_tiempo_fuera = models.TimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.maestra.get_full_name()} ({self.get_rol_display()}) en {self.sala_semestre.sala.nombre}"


# =========================================================
# ENCUESTA DE SATISFACCIÓN B
# =========================================================

class EncuestaSatisfaccion(models.Model):
    semestre = models.ForeignKey(Semestre, on_delete=models.CASCADE, related_name="encuestas")
    tutor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mis_encuestas")
    inscripcion = models.ForeignKey(SolicitudInscripcion, on_delete=models.CASCADE, null=True, blank=True)

    fecha_respuesta = models.DateTimeField(auto_now_add=True)

    q1_info_completa = models.BooleanField(verbose_name="¿Recibió información completa de la permanencia diaria?",
                                           default=True)
    q2_seguro = models.BooleanField(
        verbose_name="¿Considera que su hija y/o hijo se encuentra seguro durante su permanencia en la Estancia Infantil?",
        default=True)
    q3_orientacion_nutricion = models.BooleanField(
        verbose_name="¿Considera que la orientación sobre la alimentación adecuada de hija y/o hijo fue de utilidad?",
        default=True)
    q4_orientacion_medica = models.BooleanField(
        verbose_name="¿Considera que la orientación médica de hija y/o hijo fue de utilidad?", default=True)
    q5_orientacion_pedagogica = models.BooleanField(
        verbose_name="¿Considera que la orientación pedagógica de hija y/o hijo fue de utilidad?", default=True)
    q6_orientacion_psicologica = models.BooleanField(
        verbose_name="¿Considera que la orientación psicológica recibida fue de utilidad?", default=True)
    q7_apoyo_estudios = models.BooleanField(
        verbose_name="¿Considera que el servicio prestado durante este semestre fue de apoyo para continuar sus estudios?",
        default=True)

    comentarios = models.TextField(blank=True, null=True, verbose_name="Comentarios y sugerencias:")

    puntaje_total = models.PositiveIntegerField(default=0, help_text="Calculado automáticamente (0 a 7)")

    def save(self, *args, **kwargs):
        puntaje = 0
        if self.q1_info_completa: puntaje += 1
        if self.q2_seguro: puntaje += 1
        if self.q3_orientacion_nutricion: puntaje += 1
        if self.q4_orientacion_medica: puntaje += 1
        if self.q5_orientacion_pedagogica: puntaje += 1
        if self.q6_orientacion_psicologica: puntaje += 1
        if self.q7_apoyo_estudios: puntaje += 1

        self.puntaje_total = puntaje
        super().save(*args, **kwargs)

    def nivel_satisfaccion(self):
        if self.puntaje_total == 7:
            return "Excelente"
        elif self.puntaje_total >= 5:
            return "Bueno"
        elif self.puntaje_total >= 3:
            return "Regular"
        else:
            return "Malo (Alerta)"

    def __str__(self):
        return f"Encuesta de {self.tutor} - {self.semestre.nombre} (Puntaje: {self.puntaje_total})"


# --- SISTEMA DE COMUNICACIÓN Y SEGURIDAD PARA DIRECCIÓN ---

class MensajeDirectora(models.Model):
    remitente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    asunto = models.CharField(max_length=200)
    contenido = models.TextField()
    fecha_envio = models.DateTimeField(auto_now_add=True)
    leido = models.BooleanField(default=False)

    # Esta es la lógica para separar apartados:
    es_alumno_inscrito = models.BooleanField(default=False, help_text="Si es Falso, es de un aspirante en registro")

    def __str__(self):
        return f"{self.asunto} - {self.remitente.email}"


class Incidencia(models.Model):
    NIVEL_CHOICES = [
        ('ALTO', 'Alto Riesgo (Urgente)'),
        ('BAJO', 'Bajo Riesgo (Seguimiento)'),
    ]
    alumno = models.ForeignKey(SolicitudInscripcion, on_delete=models.CASCADE, related_name="incidencias")
    descripcion = models.TextField()
    nivel = models.CharField(max_length=10, choices=NIVEL_CHOICES, default='BAJO')
    fecha_reporte = models.DateTimeField(auto_now_add=True)
    resuelta = models.BooleanField(default=False)
    registrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f"Incidencia {self.nivel}: {self.alumno.solicitud_ingreso.nombres_menor}"


# =========================================================
# MÓDULO DE BITÁCORAS DIARIAS (NUEVO)
# =========================================================

class BitacoraBase(models.Model):
    class EstadoBitacora(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador (Sin enviar)"
        ENVIADO = "ENVIADO", "Enviado a Coordinación"
        APROBADO = "APROBADO", "Aprobado (Palomita)"
        RECHAZADO = "RECHAZADO", "Rechazado (Tacha)"
        EN_DIRECTIVA = "EN_DIRECTIVA", "Enviada a Dirección"  # <-- AGREGADO PARA EL FLUJO FINAL

    alumno = models.ForeignKey(SolicitudInscripcion, on_delete=models.CASCADE, related_name="%(class)s_bitacoras")
    maestra = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                related_name="%(class)s_creadas")
    fecha = models.DateField(default=timezone.now)

    estado = models.CharField(max_length=20, choices=EstadoBitacora.choices, default=EstadoBitacora.BORRADOR)
    comentarios_coordinadora = models.TextField(null=True, blank=True, help_text="Espacio en blanco para correcciones")

    archivo_pdf = models.FileField(upload_to="bitacoras_pdfs/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class BitacoraLactante(BitacoraBase):
    # Se llenará con el contenido del documento que envíes
    datos_json = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"Bitácora Lactante - {self.alumno.solicitud_ingreso.nombres_menor} - {self.fecha}"


class BitacoraMaternal(BitacoraBase):
    # Se llenará con el contenido del documento que envíes
    datos_json = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"Bitácora Maternal - {self.alumno.solicitud_ingreso.nombres_menor} - {self.fecha}"