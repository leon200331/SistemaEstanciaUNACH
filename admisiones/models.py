from django.db import models, transaction
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.conf import settings
import uuid


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
        RECHAZADO = "RECHAZADO", "Rechazado"

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

    numero_gesta_psicologia = models.CharField(max_length=20, blank=True, default="")
    embarazo_planeado_psicologia = models.CharField(max_length=20, blank=True, default="")
    dificultad_embarazo_psicologia = models.TextField(blank=True, default="")
    estado_animo_madre_embarazo_psicologia = models.TextField(blank=True, default="")
    momento_supieron_sexo_bebe_psicologia = models.TextField(blank=True, default="")
    quien_eligio_nombre_bebe_psicologia = models.TextField(blank=True, default="")
    motivo_nombre_bebe_psicologia = models.TextField(blank=True, default="")

    tipo_nacimiento_psicologia = models.CharField(max_length=50, blank=True, default="")
    semanas_gestacion_psicologia = models.CharField(max_length=20, blank=True, default="")
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

    # --- Domicilio estructurado del tutor principal ---
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
        EN_REVISION = "EN_REVISION", "Enviada para Revisión"
        EN_FILTROS = "EN_FILTROS", "En filtros"
        FINALIZADA = "FINALIZADA", "Inscripción Finalizada y Aprobada"
        RECHAZADA = "RECHAZADA", "Rechazada"

    estado = models.CharField(
        max_length=20,
        choices=EstadoInscripcion.choices,
        default=EstadoInscripcion.NUEVA
    )

    avance_academico = models.CharField(max_length=50, null=True, blank=True, verbose_name="Avance Académico")
    estado_civil_tutor = models.CharField(max_length=50, null=True, blank=True, verbose_name="Estado Civil")
    parentesco_tutor = models.CharField(max_length=50, null=True, blank=True, verbose_name="Parentesco Confirmado")

    class SexoChoices(models.TextChoices):
        M = "M", "Masculino"
        F = "F", "Femenino"

    estado_nacimiento_menor = models.CharField(max_length=100, null=True, blank=True, verbose_name="Estado de Nacimiento")
    municipio_nacimiento_menor = models.CharField(max_length=100, null=True, blank=True, verbose_name="Municipio de Nacimiento")

    edad_anios_menor = models.PositiveIntegerField(null=True, blank=True)
    edad_meses_menor = models.PositiveIntegerField(null=True, blank=True)

    sexo_menor = models.CharField(max_length=2, choices=SexoChoices.choices, null=True, blank=True, verbose_name="Sexo")
    tipo_sangre_menor = models.CharField(max_length=20, null=True, blank=True, verbose_name="Tipo de Sangre")

    parentesco_segundo_padre = models.CharField(max_length=50, null=True, blank=True)

    nombres_segundo_padre = models.CharField(max_length=80, null=True, blank=True, verbose_name="Nombre(s)")
    apellido_paterno_segundo_padre = models.CharField(max_length=60, null=True, blank=True, verbose_name="Apellido Paterno")
    apellido_materno_segundo_padre = models.CharField(max_length=60, null=True, blank=True, verbose_name="Apellido Materno")

    estado_civil_segundo_padre = models.CharField(max_length=50, null=True, blank=True, verbose_name="Estado Civil Padre/Madre")
    ocupacion_segundo_padre = models.CharField(max_length=100, null=True, blank=True, verbose_name="Ocupación Padre/Madre")

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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Inscripción {self.id} - Solicitud {self.solicitud_ingreso_id}"

class HistoriaClinicaMedica(models.Model):
    inscripcion = models.OneToOneField(
        SolicitudInscripcion,
        on_delete=models.CASCADE,
        related_name="historia_clinica_medica"
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
        return f"Historia clínica - Inscripción {self.inscripcion_id}"