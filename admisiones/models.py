from django.db import models, transaction
from django.db.models import Q
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator, FileExtensionValidator
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password, check_password
import uuid
import secrets
from datetime import timedelta
import re  # Para las validaciones numéricas del algoritmo y rutas de archivos


# =========================================================
# VALIDADORES GENERALES
# =========================================================
telefono_mx_10_validator = RegexValidator(
    regex=r"^\d{10}$",
    message="El teléfono debe contener exactamente 10 dígitos, sin espacios, letras ni guiones."
)

codigo_postal_mx_validator = RegexValidator(
    regex=r"^\d{5}$",
    message="El código postal debe contener exactamente 5 dígitos."
)


# =========================================================
# FUNCIONES PARA ORGANIZAR ARCHIVOS DENTRO DE MEDIA
# =========================================================
def limpiar_matricula(valor):
    valor = str(valor or "SIN_MATRICULA").strip()
    valor = re.sub(r"[^A-Za-z0-9_-]+", "_", valor)
    return valor or "SIN_MATRICULA"


def ruta_pdf_solicitud(instance, filename):
    return f"admisiones/solicitudes/pdf/{filename}"


def ruta_doc_menor(instance, filename):
    matricula = limpiar_matricula(instance.solicitud_ingreso.matricula if instance.solicitud_ingreso else None)
    return f"inscripciones/{matricula}/menor/{filename}"


def ruta_doc_tutor(instance, filename):
    matricula = limpiar_matricula(instance.solicitud_ingreso.matricula if instance.solicitud_ingreso else None)
    return f"inscripciones/{matricula}/tutor/{filename}"


def ruta_doc_segundo_tutor(instance, filename):
    matricula = limpiar_matricula(instance.solicitud_ingreso.matricula if instance.solicitud_ingreso else None)
    return f"inscripciones/{matricula}/segundo_tutor/{filename}"


def ruta_doc_autorizado(instance, filename):
    matricula = limpiar_matricula(instance.solicitud_ingreso.matricula if instance.solicitud_ingreso else None)
    return f"inscripciones/{matricula}/autorizados/{filename}"


def ruta_reglamento(instance, filename):
    matricula = limpiar_matricula(instance.solicitud_ingreso.matricula if instance.solicitud_ingreso else None)
    return f"inscripciones/{matricula}/reglamentos/{filename}"


def ruta_comprobante_pago(instance, filename):
    matricula = limpiar_matricula(instance.solicitud_ingreso.matricula if instance.solicitud_ingreso else None)
    return f"pagos/comprobantes/{matricula}/{filename}"


def validar_tamano_archivo_pago(archivo):
    """
    Valida que el comprobante de pago no supere 5 MB.
    Aplica tanto para comprobantes subidos por el beneficiario como
    para comprobantes entregados presencialmente y digitalizados por Trabajo Social.
    """
    limite_mb = 5

    if archivo and archivo.size > limite_mb * 1024 * 1024:
        raise ValidationError(f"El comprobante de pago no debe superar {limite_mb} MB.")


def es_fin_de_semana(fecha):
    """
    Regla operativa de la estancia:
    sábado y domingo son días inhábiles automáticos.
    Los usuarios pueden iniciar sesión, pero no se permite abrir operación diaria,
    registrar entrada, salida ni bitácoras de menores.
    """
    return bool(fecha and fecha.weekday() in (5, 6))


def ruta_reporte_final_ingreso(instance, filename):
    matricula = limpiar_matricula(instance.solicitud_ingreso.matricula if instance.solicitud_ingreso else None)
    return f"inscripciones/{matricula}/reportes_finales/{filename}"


def ruta_bitacora_pdf(instance, filename):
    alumno_id = instance.alumno_id or "SIN_ALUMNO"
    return f"bitacoras/pdfs/alumno_{alumno_id}/{filename}"


def ruta_archivo_incidencia(instance, filename):
    incidencia_id = instance.incidencia_id or "SIN_INCIDENCIA"
    return f"incidencias/incidencia_{incidencia_id}/archivos/{filename}"


def ruta_archivo_seguimiento_incidencia(instance, filename):
    seguimiento_id = instance.seguimiento_id or "SIN_SEGUIMIENTO"
    incidencia_id = getattr(instance.seguimiento, "incidencia_id", "SIN_INCIDENCIA") if instance.seguimiento_id else "SIN_INCIDENCIA"
    return f"incidencias/incidencia_{incidencia_id}/seguimientos/seguimiento_{seguimiento_id}/{filename}"


# =========================================================
# CATÁLOGOS DE LA UNIVERSIDAD
# =========================================================
class Facultad(models.Model):
    nombre = models.CharField(max_length=200, unique=True, verbose_name="Nombre de la Facultad o Unidad Académica")

    def __str__(self):
        return self.nombre

    class Meta:
        verbose_name_plural = "Facultades"


class Carrera(models.Model):
    facultad = models.ForeignKey(Facultad, on_delete=models.CASCADE, related_name="carreras")
    nombre = models.CharField(max_length=200, verbose_name="Programa Educativo (Carrera)")

    def __str__(self):
        return f"{self.nombre} - {self.facultad.nombre}"


# =========================================================
# SOLICITUD DE INGRESO
# =========================================================
class Solicitud(models.Model):
    # =========================
    # ARCHIVO / CONTROL
    # =========================
    pdf = models.FileField(upload_to=ruta_pdf_solicitud, null=True, blank=True)

    folio = models.PositiveIntegerField(
        unique=True,
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
        help_text="Folio consecutivo (1–1000). Se asigna automáticamente al guardar."
    )

    created_at = models.DateTimeField(auto_now_add=True)

    # =========================
    # ESTADO GENERAL
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
    # EVALUACIÓN POR ÁREAS
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

    programa_educativo = models.CharField(max_length=250, blank=True, null=True)
    estado_domicilio = models.CharField(max_length=100, blank=True, null=True)
    ciudad = models.CharField(max_length=100, blank=True, null=True)

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
        REVISION_FINAL_TS = "REVISION_FINAL_TS", "Revisión Final de Trabajo Social"
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

    # =========================================================
    # ASIGNACIÓN A SEMESTRE Y SALA
    # Sprint 4:
    # - El alumno finalizado se asigna a un semestre.
    # - Se conserva sala_asignada para compatibilidad con código anterior.
    # - sala_semestre_asignada permite operar por sede/semestre/sala.
    # =========================================================
    semestre = models.ForeignKey(
        "admisiones.Semestre",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inscripciones",
        verbose_name="Semestre asignado"
    )

    sala_asignada = models.ForeignKey(
        "admisiones.Sala",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alumnos_asignados",
        verbose_name="Sala Asignada"
    )

    sala_semestre_asignada = models.ForeignKey(
        "admisiones.SalaSemestre",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alumnos_asignados_semestre",
        verbose_name="Sala asignada en el semestre"
    )

    sala_asignada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="salas_asignadas_por_usuario",
        verbose_name="Sala asignada por"
    )

    sala_asignada_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de asignación de sala"
    )

    sala_recomendada = models.CharField(max_length=10, blank=True, null=True,
                                        verbose_name="Sala Recomendada por Sistema")
    motivo_recomendacion_sala = models.TextField(blank=True, null=True, verbose_name="Justificación del Algoritmo")
    sala_bloqueada = models.BooleanField(default=False, verbose_name="Candado del Semestre (Fijada por TS)")

    motivo_rechazo_sala = models.TextField(blank=True, null=True,
                                           verbose_name="Comentario de Directora (Rechazo de Sala)")

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
    # EXPEDIENTE DIGITAL
    # =========================================================
    doc_menor_certificado_medico = models.FileField(upload_to=ruta_doc_menor, null=True, blank=True,
                                                    verbose_name="Certificado Médico")
    doc_menor_cartilla_vacunacion = models.FileField(upload_to=ruta_doc_menor, null=True, blank=True,
                                                     verbose_name="Cartilla de Vacunación")
    doc_menor_grupo_sanguineo = models.FileField(upload_to=ruta_doc_menor, null=True, blank=True,
                                                 verbose_name="Grupo Sanguíneo")
    doc_menor_acta_nacimiento = models.FileField(upload_to=ruta_doc_menor, null=True, blank=True,
                                                 verbose_name="Acta de Nacimiento")
    doc_menor_fotos = models.FileField(upload_to=ruta_doc_menor, null=True, blank=True,
                                       verbose_name="3 Fotos Infantiles")
    doc_menor_laboratorio = models.FileField(upload_to=ruta_doc_menor, null=True, blank=True,
                                             verbose_name="Estudios de Laboratorio")

    doc_tutor_acta_nacimiento = models.FileField(upload_to=ruta_doc_tutor, null=True, blank=True,
                                                 verbose_name="Acta de Nacimiento Tutor")
    doc_tutor_ine = models.FileField(upload_to=ruta_doc_tutor, null=True, blank=True,
                                     verbose_name="Copia de INE Tutor")
    doc_tutor_fotos = models.FileField(upload_to=ruta_doc_tutor, null=True, blank=True,
                                       verbose_name="3 Fotos Infantiles Tutor")

    doc_segundo_padre_fotos = models.FileField(upload_to=ruta_doc_segundo_tutor, null=True, blank=True,
                                               verbose_name="Foto de la Pareja / Segundo Tutor")

    doc_tutor_domicilio = models.FileField(upload_to=ruta_doc_tutor, null=True, blank=True,
                                           verbose_name="Comprobante de Domicilio")
    doc_tutor_pago = models.FileField(
        upload_to=ruta_comprobante_pago,
        null=True,
        blank=True,
        validators=[
            FileExtensionValidator(allowed_extensions=["pdf", "jpg", "jpeg", "png"]),
            validar_tamano_archivo_pago,
        ],
        verbose_name="Comprobante de Pago Inscripción"
    )

    # =========================================================
    # CONTROL DE COMPROBANTE DE PAGO
    # Se usa cuando Dirección aprueba la inscripción y el expediente
    # queda en ACEPTADO_ESPERANDO_PAGO.
    #
    # Opciones del flujo:
    # 1) El beneficiario sube el comprobante en PDF/JPG/PNG.
    # 2) El beneficiario entrega el ticket presencialmente a Trabajo Social.
    # =========================================================
    class EstadoPago(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente de comprobante"
        SUBIDO_BENEFICIARIO = "SUBIDO_BENEFICIARIO", "Subido por beneficiario"
        ENTREGADO_PRESENCIAL = "ENTREGADO_PRESENCIAL", "Entregado presencialmente"
        VALIDADO = "VALIDADO", "Pago validado"
        RECHAZADO = "RECHAZADO", "Comprobante rechazado"

    estado_pago = models.CharField(
        max_length=30,
        choices=EstadoPago.choices,
        default=EstadoPago.PENDIENTE,
        verbose_name="Estado del comprobante de pago"
    )

    pago_subido_por_beneficiario = models.BooleanField(
        default=False,
        verbose_name="¿El comprobante fue subido por el beneficiario?"
    )

    pago_entregado_presencial = models.BooleanField(
        default=False,
        verbose_name="¿El comprobante fue entregado presencialmente?"
    )

    pago_recibido_presencial_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos_presenciales_recibidos",
        verbose_name="Recibido presencialmente por"
    )

    pago_recibido_presencial_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de recepción presencial"
    )

    pago_observaciones = models.TextField(
        null=True,
        blank=True,
        verbose_name="Observaciones del comprobante de pago"
    )

    pago_validado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos_validados",
        verbose_name="Pago validado por"
    )

    pago_validado_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de validación del pago"
    )

    pago_rechazado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos_rechazados",
        verbose_name="Comprobante rechazado por"
    )

    pago_rechazado_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de rechazo del comprobante"
    )

    doc_tutor_historial = models.FileField(upload_to=ruta_doc_tutor, null=True, blank=True,
                                           verbose_name="Historial Académico")
    doc_tutor_horario = models.FileField(upload_to=ruta_doc_tutor, null=True, blank=True,
                                         verbose_name="Horario de Clases")

    doc_autorizado_carta = models.FileField(upload_to=ruta_doc_autorizado, null=True, blank=True,
                                            verbose_name="Carta de Autorización")
    doc_autorizado_ine = models.FileField(upload_to=ruta_doc_autorizado, null=True, blank=True,
                                          verbose_name="Copia de INE Autorizado")

    doc_contacto_1_fotos = models.FileField(upload_to=ruta_doc_autorizado, null=True, blank=True,
                                            verbose_name="Foto Familiar Autorizado 1")
    doc_contacto_2_fotos = models.FileField(upload_to=ruta_doc_autorizado, null=True, blank=True,
                                            verbose_name="Foto Familiar Autorizado 2")
    doc_contacto_3_fotos = models.FileField(upload_to=ruta_doc_autorizado, null=True, blank=True,
                                            verbose_name="Foto Familiar Autorizado 3")

    reglamento_firmado = models.FileField(upload_to=ruta_reglamento, null=True, blank=True,
                                          verbose_name="Reglamento Firmado (PDF)")

    observaciones = models.TextField(null=True, blank=True, verbose_name="Observaciones (Correcciones)")
    comentario_tutor = models.TextField(null=True, blank=True, verbose_name="Comentario del Tutor al reenviar")

    # =========================================================
    # REPORTE FINAL DE INGRESO FO-301-02-18
    # Se registra por Trabajo Social después de finalizar filtros.
    # La Directora lo valida y con base en esto se genera el correo final.
    # =========================================================
    reporte_final_pdf = models.FileField(
        upload_to=ruta_reporte_final_ingreso,
        null=True,
        blank=True,
        verbose_name="PDF Reporte Final de Ingreso FO-301-02-18"
    )

    reporte_final_aprobado = models.BooleanField(null=True, blank=True, verbose_name="¿Se autoriza inscripción?")
    reporte_final_motivos = models.TextField(blank=True, null=True, verbose_name="Motivos de rechazo")
    reporte_final_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                          related_name='reportes_ts')
    reporte_final_en = models.DateTimeField(null=True, blank=True)

    directora_aprobado = models.BooleanField(
        null=True,
        blank=True,
        verbose_name="¿Directora aprueba la inscripción?"
    )
    directora_observaciones = models.TextField(
        null=True,
        blank=True,
        verbose_name="Observaciones de Dirección"
    )
    directora_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='firmas_directora'
    )
    directora_en = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def tiene_comprobante_pago(self):
        """
        True si existe archivo digital o si Trabajo Social marcó entrega presencial.
        """
        return bool(self.doc_tutor_pago or self.pago_entregado_presencial)

    @property
    def pago_pendiente(self):
        """
        True si aún no se ha validado el pago.
        """
        return self.estado_pago in [
            self.EstadoPago.PENDIENTE,
            self.EstadoPago.SUBIDO_BENEFICIARIO,
            self.EstadoPago.ENTREGADO_PRESENCIAL,
            self.EstadoPago.RECHAZADO,
        ]

    @property
    def pago_validado(self):
        """
        True si Trabajo Social ya validó el comprobante o la entrega presencial.
        """
        return self.estado_pago == self.EstadoPago.VALIDADO

    def registrar_comprobante_presencial(self, usuario=None, archivo=None, observaciones=""):
        """
        Registra que Trabajo Social recibió el comprobante presencialmente.

        Reglas:
        - Si se adjunta archivo, se guarda en doc_tutor_pago como evidencia digital.
        - El estado pasa a ENTREGADO_PRESENCIAL.
        - Se registra quién lo recibió y cuándo.
        - No valida el pago automáticamente; solo registra la entrega del comprobante.
        """
        if archivo:
            self.doc_tutor_pago = archivo

        self.estado_pago = self.EstadoPago.ENTREGADO_PRESENCIAL
        self.pago_entregado_presencial = True
        self.pago_subido_por_beneficiario = False
        self.pago_recibido_presencial_por = usuario
        self.pago_recibido_presencial_en = timezone.now()
        self.pago_observaciones = observaciones or self.pago_observaciones

        self.save(update_fields=[
            "doc_tutor_pago",
            "estado_pago",
            "pago_entregado_presencial",
            "pago_subido_por_beneficiario",
            "pago_recibido_presencial_por",
            "pago_recibido_presencial_en",
            "pago_observaciones",
            "updated_at",
        ])

    # =========================================================
    # CÓDIGO DE SEGURIDAD PARA ENTREGA/RECEPCIÓN DEL MENOR
    # Segunda parte Sprint 4:
    # - Se entrega al finalizar inscripción junto con la credencial.
    # - Debe ser de 4 dígitos.
    # - Se almacena con hash, no como texto plano.
    # =========================================================
    codigo_responsable_hash = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name="Código de seguridad del responsable"
    )
    codigo_responsable_actualizado_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de actualización del código"
    )

    # Auditoría de generación / reseteo del código.
    codigo_responsable_generado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="codigos_responsable_generados",
        verbose_name="Código generado por"
    )
    codigo_responsable_generado_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de generación del código"
    )
    codigo_responsable_observaciones = models.TextField(
        blank=True,
        default="",
        verbose_name="Observaciones de generación del código"
    )
    codigo_responsable_reset_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="codigos_responsable_reseteados",
        verbose_name="Código reseteado por"
    )
    codigo_responsable_reset_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de reseteo del código"
    )
    codigo_responsable_reset_motivo = models.TextField(
        blank=True,
        default="",
        verbose_name="Motivo del reseteo del código"
    )

    # Evidencia de entrega de credencial y código al responsable.
    codigo_responsable_entregado = models.BooleanField(
        default=False,
        verbose_name="¿Código entregado al responsable?"
    )
    codigo_responsable_entregado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="codigos_responsable_entregados",
        verbose_name="Código entregado por"
    )
    codigo_responsable_entregado_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de entrega del código"
    )
    codigo_responsable_entregado_a = models.CharField(
        max_length=180,
        blank=True,
        default="",
        verbose_name="Responsable que recibió el código"
    )
    codigo_responsable_entregado_parentesco = models.CharField(
        max_length=80,
        blank=True,
        default="",
        verbose_name="Parentesco del responsable que recibió el código"
    )
    codigo_responsable_entrega_observaciones = models.TextField(
        blank=True,
        default="",
        verbose_name="Observaciones de entrega del código"
    )

    credencial_entregada = models.BooleanField(
        default=False,
        verbose_name="¿Credencial entregada?"
    )
    credencial_entregada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credenciales_entregadas",
        verbose_name="Credencial entregada por"
    )
    credencial_entregada_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de entrega de credencial"
    )

    def set_codigo_responsable(self, codigo):
        """
        Guarda el código de 4 dígitos usando hash.
        No se debe guardar el código en texto plano.
        """
        codigo = str(codigo or "").strip()

        if not re.fullmatch(r"\d{4}", codigo):
            raise ValueError("El código del responsable debe tener exactamente 4 dígitos.")

        self.codigo_responsable_hash = make_password(codigo)
        self.codigo_responsable_actualizado_en = timezone.now()

        # Si se genera o resetea un código, debe volver a confirmarse la entrega.
        if hasattr(self, "codigo_responsable_entregado"):
            self.codigo_responsable_entregado = False

    def validar_codigo_responsable(self, codigo):
        """
        Valida el código de 4 dígitos del adulto responsable.

        Se conserva por compatibilidad con vistas anteriores. Para la operación
        nueva se recomienda usar validar_codigo_de_responsable(), porque ahora
        cada tutor o familiar autorizado tiene su propio código.
        """
        codigo = str(codigo or "").strip()

        if not self.codigo_responsable_hash or not re.fullmatch(r"\d{4}", codigo):
            return False

        return check_password(codigo, self.codigo_responsable_hash)

    # =========================================================
    # RESPONSABLES AUTORIZADOS Y CÓDIGOS INDIVIDUALES
    # Nueva regla:
    # - El código ya no se maneja como un solo código por alumno.
    # - Cada tutor o familiar autorizado tiene su propio código.
    # - Los campos codigo_responsable_* quedan como compatibilidad.
    # =========================================================
    def sincronizar_responsables_autorizados(self):
        """
        Crea o actualiza los responsables autorizados usando los datos capturados
        en la inscripción: tutor principal, segundo tutor y contactos 1-3.

        Este método no genera códigos automáticamente; solo prepara la lista de
        personas para que Trabajo Social pueda generar y entregar un código
        individual a cada responsable.
        """
        return CodigoResponsableAutorizado.sincronizar_desde_inscripcion(self)

    def responsables_autorizados_activos(self):
        """
        Devuelve los responsables autorizados activos.
        Si todavía no existen, los crea desde los datos de la inscripción.
        """
        if not self.codigos_responsables_autorizados.exists():
            self.sincronizar_responsables_autorizados()

        return self.codigos_responsables_autorizados.filter(activo=True)

    def validar_codigo_de_responsable(self, responsable_id, codigo):
        """
        Valida que el código capturado pertenezca al responsable seleccionado
        y a este alumno.
        """
        responsable = self.codigos_responsables_autorizados.filter(
            id=responsable_id,
            activo=True
        ).first()

        if not responsable:
            return False, None

        return responsable.validar_codigo(codigo), responsable

    @property
    def es_lactante(self):
        if self.sala_asignada and self.sala_asignada.nombre:
            return self.sala_asignada.nombre.strip().upper().startswith('L')
        return False

    @property
    def es_maternal(self):
        if self.sala_asignada and self.sala_asignada.nombre:
            return self.sala_asignada.nombre.strip().upper().startswith('M')
        return False

    def evaluar_y_recomendar_sala(self):
        if not self.edad_anios_menor and not self.edad_meses_menor:
            return "L1", "No hay datos de edad suficientes. Se asigna L1 por defecto."

        anios = self.edad_anios_menor or 0
        meses = self.edad_meses_menor or 0
        edad_total_meses = (anios * 12) + meses

        sol = self.solicitud_ingreso

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

        alertas = []
        puntos_retraso = 0

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

        if str(sol.presentacion_alimentos).upper() in ["PURE", "MACHACADO"] and edad_total_meses > 12:
            puntos_retraso += 1
            alertas.append("Aún consume alimentos en papilla/puré.")

        if hasattr(self, 'historia_clinica_medica'):
            hc = self.historia_clinica_medica
            if hc:
                try:
                    semanas = int(re.sub(r'\D', '', hc.semanas_gestacion)) if hc.semanas_gestacion else 40
                    if semanas < 37:
                        puntos_retraso += 1
                        alertas.append(f"Nacimiento prematuro ({semanas} semanas).")
                except Exception:
                    pass

        jerarquia_salas = ["L1", "L2", "L3", "M1", "M2", "M3"]
        indice_actual = jerarquia_salas.index(sala_base)

        if puntos_retraso > 0:
            nuevo_indice = max(0, indice_actual - (1 if puntos_retraso <= 2 else 2))
            sala_recomendada = jerarquia_salas[nuevo_indice]
        else:
            sala_recomendada = sala_base

        justificacion = f"Edad cronológica: {edad_total_meses} meses (Base: {sala_base}). "
        if puntos_retraso > 0:
            justificacion += (
                f"Se ajustó a la sala {sala_recomendada} por las siguientes consideraciones integrales: "
                + ", ".join(alertas)
            )
        else:
            justificacion += "El desarrollo es acorde a su edad. No se detectaron alertas que requieran ajuste de sala."

        self.sala_recomendada = sala_recomendada
        self.motivo_recomendacion_sala = justificacion
        self.save(update_fields=['sala_recomendada', 'motivo_recomendacion_sala'])

        return sala_recomendada, justificacion

    def save(self, *args, **kwargs):
        if self.acepto_reglamentos and not self.fecha_aceptacion:
            self.fecha_aceptacion = timezone.now()

        super().save(*args, **kwargs)

    class Meta:
        indexes = [
            models.Index(fields=["estado"]),
            models.Index(fields=["estado_pago"]),
            models.Index(fields=["codigo_responsable_entregado"]),
            models.Index(fields=["semestre"]),
            models.Index(fields=["sala_semestre_asignada"]),
        ]

    def __str__(self):
        return f"Expediente de Inscripción {self.id} - Solicitud {self.solicitud_ingreso_id}"


class CodigoResponsableAutorizado(models.Model):
    """
    Código individual por persona autorizada para entregar o recoger al menor.

    Regla:
    - No existe un único código para todos los familiares del alumno.
    - Cada tutor o familiar autorizado tiene su propio código de 4 dígitos.
    - La maestra valida este código al registrar entrada y salida.
    """

    class TipoResponsable(models.TextChoices):
        TUTOR_PRINCIPAL = "TUTOR_PRINCIPAL", "Tutor principal"
        SEGUNDO_TUTOR = "SEGUNDO_TUTOR", "Segundo tutor"
        CONTACTO_1 = "CONTACTO_1", "Familiar autorizado 1"
        CONTACTO_2 = "CONTACTO_2", "Familiar autorizado 2"
        CONTACTO_3 = "CONTACTO_3", "Familiar autorizado 3"
        OTRO = "OTRO", "Otro responsable autorizado"

    inscripcion = models.ForeignKey(
        "admisiones.SolicitudInscripcion",
        on_delete=models.CASCADE,
        related_name="codigos_responsables_autorizados",
        verbose_name="Alumno / inscripción"
    )

    tipo_responsable = models.CharField(
        max_length=30,
        choices=TipoResponsable.choices,
        default=TipoResponsable.OTRO,
        verbose_name="Tipo de responsable"
    )

    nombre_completo = models.CharField(
        max_length=180,
        verbose_name="Nombre completo del responsable"
    )

    parentesco = models.CharField(
        max_length=80,
        blank=True,
        default="",
        verbose_name="Parentesco"
    )

    telefono = models.CharField(
        max_length=15,
        blank=True,
        default="",
        verbose_name="Teléfono"
    )

    correo = models.EmailField(
        blank=True,
        default="",
        verbose_name="Correo"
    )

    codigo_hash = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name="Código de seguridad cifrado"
    )

    codigo_actualizado_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de actualización del código"
    )

    codigo_generado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="codigos_responsable_persona_generados",
        verbose_name="Código generado por"
    )

    codigo_generado_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de generación del código"
    )

    codigo_observaciones = models.TextField(
        blank=True,
        default="",
        verbose_name="Observaciones de generación"
    )

    codigo_reset_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="codigos_responsable_persona_reseteados",
        verbose_name="Código reseteado por"
    )

    codigo_reset_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de reseteo del código"
    )

    codigo_reset_motivo = models.TextField(
        blank=True,
        default="",
        verbose_name="Motivo del reseteo"
    )

    codigo_entregado = models.BooleanField(
        default=False,
        verbose_name="¿Código entregado?"
    )

    codigo_entregado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="codigos_responsable_persona_entregados",
        verbose_name="Código entregado por"
    )

    codigo_entregado_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de entrega del código"
    )

    codigo_entrega_observaciones = models.TextField(
        blank=True,
        default="",
        verbose_name="Observaciones de entrega"
    )

    credencial_entregada = models.BooleanField(
        default=False,
        verbose_name="¿Credencial entregada?"
    )

    credencial_entregada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credenciales_responsable_persona_entregadas",
        verbose_name="Credencial entregada por"
    )

    credencial_entregada_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de entrega de credencial"
    )

    activo = models.BooleanField(
        default=True,
        verbose_name="Responsable activo"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @staticmethod
    def generar_codigo_plano():
        """
        Genera un código de 4 dígitos.
        El valor plano solo debe mostrarse al momento de generarlo o resetearlo.
        Después únicamente se conserva el hash.
        """
        return f"{secrets.randbelow(10000):04d}"

    @staticmethod
    def limpiar_telefono(valor):
        return re.sub(r"\D", "", str(valor or ""))[:15]

    @staticmethod
    def limpiar_nombre(valor):
        return re.sub(r"\s+", " ", str(valor or "").strip())

    @property
    def tiene_codigo(self):
        return bool(self.codigo_hash)

    @property
    def puede_validarse(self):
        return bool(self.activo and self.codigo_hash and self.codigo_entregado)

    @property
    def alumno_nombre(self):
        try:
            return self.inscripcion.solicitud_ingreso.nombre_menor_completo()
        except Exception:
            return "Sin alumno"

    def set_codigo(self, codigo, usuario=None, motivo_reset="", observaciones=""):
        """
        Guarda el código de 4 dígitos usando hash.
        Nunca se guarda el código en texto plano.
        """
        codigo = str(codigo or "").strip()

        if not re.fullmatch(r"\d{4}", codigo):
            raise ValueError("El código del responsable debe tener exactamente 4 dígitos.")

        tenia_codigo = bool(self.codigo_hash)

        self.codigo_hash = make_password(codigo)
        self.codigo_actualizado_en = timezone.now()
        self.codigo_entregado = False

        if tenia_codigo:
            self.codigo_reset_por = usuario
            self.codigo_reset_en = timezone.now()
            self.codigo_reset_motivo = motivo_reset or self.codigo_reset_motivo
        else:
            self.codigo_generado_por = usuario
            self.codigo_generado_en = timezone.now()
            self.codigo_observaciones = observaciones or self.codigo_observaciones

    def generar_nuevo_codigo(self, usuario=None, motivo_reset="", observaciones=""):
        """
        Genera, asigna y devuelve el código plano para mostrarlo una sola vez.
        """
        codigo = self.generar_codigo_plano()
        self.set_codigo(
            codigo,
            usuario=usuario,
            motivo_reset=motivo_reset,
            observaciones=observaciones,
        )
        self.save()
        return codigo

    def validar_codigo(self, codigo):
        """
        Valida el código de 4 dígitos de esta persona autorizada.
        """
        codigo = str(codigo or "").strip()

        if not self.codigo_hash or not re.fullmatch(r"\d{4}", codigo):
            return False

        return check_password(codigo, self.codigo_hash)

    def marcar_entregado(self, usuario=None, observaciones="", credencial=True):
        self.codigo_entregado = True
        self.codigo_entregado_por = usuario
        self.codigo_entregado_en = timezone.now()
        self.codigo_entrega_observaciones = observaciones or self.codigo_entrega_observaciones

        if credencial:
            self.credencial_entregada = True
            self.credencial_entregada_por = usuario
            self.credencial_entregada_en = timezone.now()

        self.save(update_fields=[
            "codigo_entregado",
            "codigo_entregado_por",
            "codigo_entregado_en",
            "codigo_entrega_observaciones",
            "credencial_entregada",
            "credencial_entregada_por",
            "credencial_entregada_en",
            "updated_at",
        ])

    @classmethod
    def datos_responsables_desde_inscripcion(cls, inscripcion):
        """
        Construye la lista de responsables autorizados desde los datos del expediente.
        """
        datos = []

        def agregar(tipo, nombre, parentesco="", telefono="", correo=""):
            nombre = cls.limpiar_nombre(nombre)

            if not nombre:
                return

            datos.append({
                "tipo_responsable": tipo,
                "nombre_completo": nombre,
                "parentesco": cls.limpiar_nombre(parentesco),
                "telefono": cls.limpiar_telefono(telefono),
                "correo": str(correo or "").strip().lower(),
            })

        solicitud = getattr(inscripcion, "solicitud_ingreso", None)

        if solicitud:
            try:
                parentesco = solicitud.get_parentesco_display()
            except Exception:
                parentesco = getattr(solicitud, "parentesco", "") or "Tutor"

            agregar(
                cls.TipoResponsable.TUTOR_PRINCIPAL,
                solicitud.nombre_tutor_completo(),
                parentesco,
                getattr(solicitud, "celular", ""),
                getattr(solicitud, "correo", ""),
            )

        agregar(
            cls.TipoResponsable.SEGUNDO_TUTOR,
            " ".join(filter(None, [
                getattr(inscripcion, "nombres_segundo_padre", ""),
                getattr(inscripcion, "apellido_paterno_segundo_padre", ""),
                getattr(inscripcion, "apellido_materno_segundo_padre", ""),
            ])),
            getattr(inscripcion, "parentesco_segundo_padre", "") or "Segundo tutor",
            getattr(inscripcion, "celular_segundo_padre", ""),
            getattr(inscripcion, "correo_segundo_padre", ""),
        )

        for numero in [1, 2, 3]:
            agregar(
                getattr(cls.TipoResponsable, f"CONTACTO_{numero}"),
                " ".join(filter(None, [
                    getattr(inscripcion, f"contacto_{numero}_nombres", ""),
                    getattr(inscripcion, f"contacto_{numero}_apellido_paterno", ""),
                    getattr(inscripcion, f"contacto_{numero}_apellido_materno", ""),
                ])),
                getattr(inscripcion, f"contacto_{numero}_parentesco", ""),
                getattr(inscripcion, f"contacto_{numero}_telefono", ""),
                "",
            )

        return datos

    @classmethod
    def sincronizar_desde_inscripcion(cls, inscripcion):
        """
        Crea o actualiza responsables autorizados desde el expediente.
        No elimina códigos existentes; solo actualiza datos de identificación.
        """
        responsables = []

        for dato in cls.datos_responsables_desde_inscripcion(inscripcion):
            obj, _ = cls.objects.get_or_create(
                inscripcion=inscripcion,
                tipo_responsable=dato["tipo_responsable"],
                defaults=dato
            )

            cambios = []
            for campo in ["nombre_completo", "parentesco", "telefono", "correo"]:
                if getattr(obj, campo) != dato[campo]:
                    setattr(obj, campo, dato[campo])
                    cambios.append(campo)

            if not obj.activo:
                obj.activo = True
                cambios.append("activo")

            if cambios:
                cambios.append("updated_at")
                obj.save(update_fields=cambios)

            responsables.append(obj)

        return responsables

    def save(self, *args, **kwargs):
        self.nombre_completo = self.limpiar_nombre(self.nombre_completo)
        self.parentesco = self.limpiar_nombre(self.parentesco)
        self.telefono = self.limpiar_telefono(self.telefono)

        if self.correo:
            self.correo = self.correo.strip().lower()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nombre_completo} - {self.parentesco} - {self.alumno_nombre}"

    class Meta:
        ordering = [
            "inscripcion__solicitud_ingreso__apellido_paterno_menor",
            "tipo_responsable",
            "nombre_completo",
        ]
        unique_together = ("inscripcion", "tipo_responsable")
        indexes = [
            models.Index(fields=["tipo_responsable"]),
            models.Index(fields=["activo"]),
            models.Index(fields=["codigo_entregado"]),
            models.Index(fields=["credencial_entregada"]),
            models.Index(fields=["codigo_generado_en"]),
            models.Index(fields=["codigo_entregado_en"]),
        ]


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
# SPRINT 4 - CONFIGURACIÓN DE SEMESTRE
# =========================================================
class Sede(models.Model):
    """
    Catálogo de sedes.
    Permite operar de forma segmentada por sede y ver la información centralizada.

    La dirección se captura por partes para evitar errores y se sincroniza
    automáticamente en el campo direccion para conservar compatibilidad con
    reportes, paneles y código anterior.
    """

    class TipoVialidad(models.TextChoices):
        CALLE = "CALLE", "Calle"
        AVENIDA = "AVENIDA", "Avenida"
        BOULEVARD = "BOULEVARD", "Boulevard"
        CARRETERA = "CARRETERA", "Carretera"
        PRIVADA = "PRIVADA", "Privada"
        ANDADOR = "ANDADOR", "Andador"
        OTRO = "OTRO", "Otro"

    clave = models.CharField(
        max_length=30,
        unique=True,
        verbose_name="Clave de sede",
        help_text="Ej. TUXTLA, TAPACHULA, SANCRISTOBAL"
    )

    nombre = models.CharField(
        max_length=120,
        unique=True,
        verbose_name="Nombre de sede"
    )

    direccion = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Dirección completa"
    )

    estado = models.CharField(max_length=100, blank=True, default="Chiapas", verbose_name="Estado")
    municipio = models.CharField(max_length=120, blank=True, default="", verbose_name="Municipio")
    ciudad_localidad = models.CharField(max_length=120, blank=True, default="", verbose_name="Ciudad / Localidad")
    colonia = models.CharField(max_length=150, blank=True, default="", verbose_name="Colonia")
    codigo_postal = models.CharField(
        max_length=5,
        blank=True,
        default="",
        validators=[codigo_postal_mx_validator],
        verbose_name="Código postal"
    )
    tipo_vialidad = models.CharField(
        max_length=20,
        choices=TipoVialidad.choices,
        default=TipoVialidad.CALLE,
        verbose_name="Tipo de vialidad"
    )
    calle_avenida = models.CharField(max_length=180, blank=True, default="", verbose_name="Calle / Avenida")
    numero_exterior = models.CharField(max_length=20, blank=True, default="", verbose_name="Número exterior")
    numero_interior = models.CharField(max_length=20, blank=True, default="", verbose_name="Número interior")
    referencia = models.CharField(max_length=255, blank=True, default="", verbose_name="Referencia")

    telefono = models.CharField(
        max_length=10,
        blank=True,
        default="",
        validators=[telefono_mx_10_validator],
        verbose_name="Teléfono de sede",
        help_text="Captura 10 dígitos, sin espacios, letras ni guiones."
    )

    correo = models.EmailField(blank=True, default="", verbose_name="Correo de sede")
    activa = models.BooleanField(default=True, verbose_name="Sede activa")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def construir_direccion(self):
        partes = []

        vialidad = " ".join([
            self.get_tipo_vialidad_display() if self.tipo_vialidad else "",
            self.calle_avenida or "",
        ]).strip()

        if vialidad:
            numero = ""
            if self.numero_exterior:
                numero = f"No. {self.numero_exterior}"
            if self.numero_interior:
                numero = f"{numero} Int. {self.numero_interior}".strip()
            partes.append(" ".join([vialidad, numero]).strip())

        if self.colonia:
            partes.append(f"Col. {self.colonia}")

        ubicacion = ", ".join(
            valor for valor in [
                self.ciudad_localidad or "",
                self.municipio or "",
                self.estado or "",
            ]
            if valor
        )

        if ubicacion:
            partes.append(ubicacion)

        if self.codigo_postal:
            partes.append(f"C.P. {self.codigo_postal}")

        if self.referencia:
            partes.append(f"Referencia: {self.referencia}")

        return ", ".join(partes).strip()

    @property
    def direccion_detallada(self):
        return self.construir_direccion() or self.direccion

    def save(self, *args, **kwargs):
        if self.clave:
            self.clave = limpiar_matricula(self.clave).upper()

        if self.telefono:
            self.telefono = re.sub(r"\D", "", self.telefono)

        if self.codigo_postal:
            self.codigo_postal = re.sub(r"\D", "", self.codigo_postal)

        if self.correo:
            self.correo = self.correo.strip().lower()

        direccion_generada = self.construir_direccion()
        if direccion_generada:
            self.direccion = direccion_generada

        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre

    class Meta:
        ordering = ["nombre"]
        indexes = [
            models.Index(fields=["clave"]),
            models.Index(fields=["activa"]),
            models.Index(fields=["municipio"]),
            models.Index(fields=["ciudad_localidad"]),
        ]


class Semestre(models.Model):
    class SedeChoices(models.TextChoices):
        # Se conserva para compatibilidad con formularios anteriores.
        TUXTLA = "TUXTLA", "Tuxtla"
        TAPACHULA = "TAPACHULA", "Tapachula"

    class EstadoSemestre(models.TextChoices):
        # CONFIGURACION se conserva para no romper registros existentes.
        CONFIGURACION = "CONFIGURACION", "En Configuración"
        BORRADOR = "BORRADOR", "Borrador"
        ACTIVO = "ACTIVO", "Activo"
        CERRADO = "CERRADO", "Cerrado"

    nombre = models.CharField(max_length=100, help_text="Ej. Enero - Junio 2026")

    # Campo anterior. Se conserva por compatibilidad.
    sede = models.CharField(
        max_length=120,
        choices=SedeChoices.choices,
        default=SedeChoices.TUXTLA,
        verbose_name="Sede"
    )

    # Nuevo campo recomendado para Sprint 4.
    sede_configurada = models.ForeignKey(
        "admisiones.Sede",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="semestres",
        verbose_name="Sede configurada"
    )

    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()

    estado = models.CharField(
        max_length=20,
        choices=EstadoSemestre.choices,
        default=EstadoSemestre.CONFIGURACION
    )

    medico_asignado = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="semestres_medico",
        verbose_name="Médica asignada"
    )
    nutriologa_asignada = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="semestres_nutricion",
        verbose_name="Nutrióloga asignada"
    )
    psicologa_asignada = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="semestres_psicologia",
        verbose_name="Psicóloga asignada"
    )

    fecha_encuesta_satisfaccion = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de generación de Encuesta de satisfacción B"
    )

    encuesta_enviada = models.BooleanField(default=False, verbose_name="¿Encuesta B enviada?")
    fecha_envio_encuesta = models.DateTimeField(null=True, blank=True, verbose_name="Fecha de envío de encuesta")
    correo_copia_encuesta = models.EmailField(
        blank=True,
        default="",
        verbose_name="Correo genérico en copia para encuesta"
    )

    iniciado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="semestres_iniciados",
        verbose_name="Iniciado por"
    )
    fecha_inicio_real = models.DateTimeField(null=True, blank=True, verbose_name="Fecha real de inicio")

    cerrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="semestres_cerrados",
        verbose_name="Cerrado por"
    )
    fecha_cierre = models.DateTimeField(null=True, blank=True, verbose_name="Fecha de cierre")

    observaciones = models.TextField(blank=True, default="", verbose_name="Observaciones del semestre")

    clonado_de = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="semestres_clonados",
        verbose_name="Semestre origen de clonación"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def sede_nombre(self):
        if self.sede_configurada:
            return self.sede_configurada.nombre
        try:
            return self.get_sede_display()
        except Exception:
            return self.sede or "Sin sede"

    def __str__(self):
        return f"{self.nombre} ({self.sede_nombre})"

    def generar_dias_operativos(self):
        """
        Genera el calendario operativo del semestre.

        Reglas:
        - Lunes a viernes quedan como días hábiles programados.
        - Sábado y domingo son inhábiles automáticos.
        - Días festivos/suspensiones/consejo técnico con afecta_recepcion=True son inhábiles.
        - Los días inhábiles se guardan como cerrados automáticamente para que no bloqueen el cierre del semestre.
        """
        if not self.fecha_inicio or not self.fecha_fin:
            return 0

        creados = 0
        fechas_no_habiles = set(
            self.dias_festivos.filter(afecta_recepcion=True).values_list("fecha", flat=True)
        )

        fecha = self.fecha_inicio
        while fecha <= self.fecha_fin:
            es_fin_semana = es_fin_de_semana(fecha)
            es_festivo_o_suspension = fecha in fechas_no_habiles
            es_habil = not es_fin_semana and not es_festivo_o_suspension

            estado_inicial = (
                DiaOperativoSemestre.EstadoDia.PROGRAMADO
                if es_habil
                else DiaOperativoSemestre.EstadoDia.CERRADO
            )

            if es_fin_semana:
                observacion_no_habil = "Día inhábil automático: la estancia no opera sábados ni domingos."
            elif es_festivo_o_suspension:
                observacion_no_habil = "Día inhábil por festivo, suspensión o consejo técnico."
            else:
                observacion_no_habil = ""

            dia, created = DiaOperativoSemestre.objects.get_or_create(
                semestre=self,
                fecha=fecha,
                defaults={
                    "es_habil": es_habil,
                    "estado": estado_inicial,
                    "observaciones": observacion_no_habil,
                }
            )

            if created:
                creados += 1
            else:
                update_fields = []

                if dia.es_habil != es_habil:
                    dia.es_habil = es_habil
                    update_fields.append("es_habil")

                # Si es sábado, domingo o día inhábil configurado, debe quedar cerrado.
                # Así no aparece como pendiente de apertura/cierre ni bloquea el cierre del semestre.
                if not es_habil and dia.estado != DiaOperativoSemestre.EstadoDia.CERRADO:
                    dia.estado = DiaOperativoSemestre.EstadoDia.CERRADO
                    update_fields.append("estado")

                if observacion_no_habil and not dia.observaciones:
                    dia.observaciones = observacion_no_habil
                    update_fields.append("observaciones")

                if update_fields:
                    dia.save(update_fields=update_fields)

            fecha += timedelta(days=1)

        return creados

    def validar_para_iniciar(self):
        """
        Validaciones para iniciar semestre:
        - Debe tener sede, fechas y personal de filtros.
        - Debe tener salas configuradas.
        - Todas las salas deben tener al menos una maestra.
        - Todas las maestras activas deben estar asignadas a una sala.
        - Solo puede existir un semestre activo por sede.
        """
        errores = []

        if not self.nombre:
            errores.append("Falta el nombre del semestre.")

        if not self.fecha_inicio or not self.fecha_fin:
            errores.append("Falta fecha de inicio o fecha de fin.")

        if self.fecha_inicio and self.fecha_fin and self.fecha_inicio > self.fecha_fin:
            errores.append("La fecha de inicio no puede ser posterior a la fecha de fin.")

        if not self.sede_configurada and not self.sede:
            errores.append("Falta configurar la sede del semestre.")

        if not self.medico_asignado:
            errores.append("Falta asignar médica.")

        if not self.nutriologa_asignada:
            errores.append("Falta asignar nutrióloga.")

        if not self.psicologa_asignada:
            errores.append("Falta asignar psicóloga.")

        salas = self.salas_activas.filter(activa=True)

        if not salas.exists():
            errores.append("Debe configurar al menos una sala activa.")

        for sala_semestre in salas:
            if not sala_semestre.maestras_asignadas.filter(activo=True).exists():
                errores.append(f"La sala {sala_semestre.sala.nombre} no tiene maestra asignada.")

        # Validar maestras activas asignadas.
        try:
            User = get_user_model()
            q_maestras = Q(groups__name__icontains="maestra") | Q(groups__name__icontains="asistente")

            campos_user = [f.name for f in User._meta.fields]
            if "tipo_persona" in campos_user:
                q_maestras = (
                    q_maestras
                    | Q(tipo_persona__icontains="MAESTRA")
                    | Q(tipo_persona__icontains="MAESTRO")
                    | Q(tipo_persona__icontains="ASISTENTE")
                )

            maestras_activas = User.objects.filter(is_active=True).filter(q_maestras).distinct()
            maestras_asignadas = User.objects.filter(
                mis_salas__sala_semestre__semestre=self,
                mis_salas__activo=True
            ).distinct()

            maestras_sin_sala = maestras_activas.exclude(id__in=maestras_asignadas.values_list("id", flat=True))

            if maestras_sin_sala.exists():
                nombres = []
                for maestra in maestras_sin_sala[:8]:
                    nombre = maestra.get_full_name() if hasattr(maestra, "get_full_name") else str(maestra)
                    nombres.append(nombre or getattr(maestra, "username", str(maestra)))
                errores.append(
                    "Hay maestras activas sin asignar a sala: " + ", ".join(nombres)
                )

        except Exception:
            # No bloquea si el modelo de usuarios no tiene todavía los roles esperados.
            pass

        activos = Semestre.objects.filter(estado=self.EstadoSemestre.ACTIVO).exclude(pk=self.pk)

        if self.sede_configurada:
            activos = activos.filter(sede_configurada=self.sede_configurada)
        else:
            activos = activos.filter(sede=self.sede)

        if activos.exists():
            errores.append("Ya existe un semestre activo para esta sede.")

        return errores

    def iniciar(self, usuario=None):
        errores = self.validar_para_iniciar()

        if errores:
            return False, errores

        self.generar_dias_operativos()
        self.estado = self.EstadoSemestre.ACTIVO
        self.iniciado_por = usuario
        self.fecha_inicio_real = timezone.now()
        self.save(update_fields=["estado", "iniciado_por", "fecha_inicio_real", "updated_at"])

        return True, []

    def validar_para_cerrar(self):
        """
        Validaciones para cerrar semestre:
        - El semestre debe estar activo.
        - La fecha fin debe estar vencida.
        - Todos los días operativos deben estar cerrados.
        - Todas las incidencias del semestre deben estar cerradas.
        """
        errores = []

        if self.estado != self.EstadoSemestre.ACTIVO:
            errores.append("Solo se puede cerrar un semestre activo.")

        if self.fecha_fin and timezone.localdate() <= self.fecha_fin:
            errores.append("No se puede cerrar: la fecha de fin del semestre aún no ha vencido.")

        if not self.dias_operativos.exists():
            errores.append("No se han generado los días operativos del semestre.")

        dias_no_cerrados = self.dias_operativos.filter(
            es_habil=True
        ).exclude(
            estado=DiaOperativoSemestre.EstadoDia.CERRADO
        )

        if dias_no_cerrados.exists():
            errores.append("No se puede cerrar: existen días operativos pendientes de cierre.")

        incidencias_abiertas = self.incidencias.filter(estado=Incidencia.EstadoIncidencia.ABIERTA)

        if incidencias_abiertas.exists():
            errores.append("No se puede cerrar: existen incidencias abiertas.")

        return errores

    def cerrar(self, usuario=None):
        errores = self.validar_para_cerrar()

        if errores:
            return False, errores

        self.estado = self.EstadoSemestre.CERRADO
        self.cerrado_por = usuario
        self.fecha_cierre = timezone.now()
        self.save(update_fields=["estado", "cerrado_por", "fecha_cierre", "updated_at"])

        return True, []

    @classmethod
    def obtener_activo(cls, sede=None):
        qs = cls.objects.filter(estado=cls.EstadoSemestre.ACTIVO)

        if sede:
            qs = qs.filter(Q(sede_configurada=sede) | Q(sede=str(sede)))

        return qs.order_by("-fecha_inicio").first()

    @property
    def puede_usarse_como_base_clonacion(self):
        """
        Solo los semestres cerrados pueden usarse como base para clonar.
        """
        return self.estado == self.EstadoSemestre.CERRADO

    @classmethod
    def existe_semestre_activo(cls):
        """
        Regla administrativa: no se debe clonar mientras exista un semestre activo.
        """
        return cls.objects.filter(estado=cls.EstadoSemestre.ACTIVO).exists()

    def clonar_configuracion(
        self,
        nombre,
        fecha_inicio,
        fecha_fin,
        fecha_encuesta_satisfaccion=None,
        usuario=None,
        observaciones=""
    ):
        """
        Crea un nuevo semestre copiando la configuración operativa del semestre cerrado.

        Se copia: sede, personal de filtros, salas, cupos, horarios y maestras.
        No se copia: alumnos, pagos, códigos, encuestas, respuestas, bitácoras,
        incidencias, calendario operativo ni cierre.
        """
        if not self.puede_usarse_como_base_clonacion:
            raise ValueError("Solo se puede clonar un semestre cerrado.")

        if Semestre.existe_semestre_activo():
            raise ValueError("No se puede clonar mientras exista un semestre activo. Primero cierra el semestre actual.")

        if fecha_inicio and fecha_fin and fecha_inicio > fecha_fin:
            raise ValueError("La fecha de inicio no puede ser posterior a la fecha de fin.")

        campos_sala_semestre = [
            "activa", "cupo",
            "entrada_maestras", "recepcion_inicio", "recepcion_fin",
            "desayuno_inicio", "desayuno_fin",
            "actividad_pedagogica_nombre", "actividad_pedagogica_inicio",
            "actividad_pedagogica_fin", "actividad_pedagogica_personal",
            "recreo_inicio", "recreo_fin",
            "colacion_inicio", "colacion_fin",
            "siesta_inicio", "siesta_fin",
            "comida_inicio", "comida_fin",
            "salida_maestras",
            "inicio_recepcion", "termino_recepcion",
            "horario_desayuno", "horario_actividades_pedagogicas",
            "horario_recreo", "horario_colacion", "horario_siesta",
            "horario_comida", "horario_salida",
        ]

        campos_asignacion_maestra = [
            "rol", "activo",
            "horario_entrada", "horario_salida",
            "desayuno_inicio", "desayuno_fin",
            "tiempo_fuera_inicio", "tiempo_fuera_fin",
            "horario_desayuno_maestra", "horario_tiempo_fuera",
        ]

        with transaction.atomic():
            nuevo_semestre = Semestre.objects.create(
                nombre=nombre,
                sede=self.sede,
                sede_configurada=self.sede_configurada,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                estado=self.EstadoSemestre.CONFIGURACION,
                medico_asignado=self.medico_asignado,
                nutriologa_asignada=self.nutriologa_asignada,
                psicologa_asignada=self.psicologa_asignada,
                fecha_encuesta_satisfaccion=fecha_encuesta_satisfaccion,
                observaciones=observaciones or f"Clonado desde {self.nombre}.",
                clonado_de=self,
            )

            for sala_origen in self.salas_activas.select_related("sala").prefetch_related("maestras_asignadas"):
                datos_sala = {campo: getattr(sala_origen, campo) for campo in campos_sala_semestre}
                sala_nueva = SalaSemestre.objects.create(
                    semestre=nuevo_semestre,
                    sala=sala_origen.sala,
                    **datos_sala
                )

                for asignacion_origen in sala_origen.maestras_asignadas.select_related("maestra"):
                    datos_asignacion = {
                        campo: getattr(asignacion_origen, campo)
                        for campo in campos_asignacion_maestra
                    }
                    AsignacionMaestra.objects.create(
                        sala_semestre=sala_nueva,
                        maestra=asignacion_origen.maestra,
                        **datos_asignacion
                    )

        return nuevo_semestre

    class Meta:
        ordering = ["-fecha_inicio", "-created_at"]
        indexes = [
            models.Index(fields=["estado"]),
            models.Index(fields=["sede"]),
            models.Index(fields=["fecha_inicio"]),
            models.Index(fields=["fecha_fin"]),
            models.Index(fields=["clonado_de"]),
        ]


class DiaFestivo(models.Model):
    class TipoDia(models.TextChoices):
        FESTIVO = "FESTIVO", "Día festivo"
        SUSPENSION = "SUSPENSION", "Suspensión de labores"
        CONSEJO = "CONSEJO", "Consejo técnico"

    semestre = models.ForeignKey(Semestre, on_delete=models.CASCADE, related_name="dias_festivos")
    fecha = models.DateField()
    tipo = models.CharField(max_length=20, choices=TipoDia.choices, default=TipoDia.FESTIVO)
    motivo = models.CharField(max_length=200, help_text="Ej. Día del Trabajo, Consejo Técnico, suspensión, etc.")
    afecta_recepcion = models.BooleanField(
        default=True,
        verbose_name="¿Afecta la recepción de niños?"
    )

    def __str__(self):
        return f"{self.fecha} - {self.get_tipo_display()} - {self.motivo}"

    class Meta:
        ordering = ["fecha"]
        unique_together = ("semestre", "fecha", "tipo")
        indexes = [
            models.Index(fields=["fecha"]),
            models.Index(fields=["tipo"]),
        ]


class Sala(models.Model):
    class TipoSala(models.TextChoices):
        LACTANTES = "LACTANTES", "Lactantes"
        MATERNAL = "MATERNAL", "Maternal"
        MIXTA = "MIXTA", "Mixta"

    sede = models.ForeignKey(
        "admisiones.Sede",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="salas",
        verbose_name="Sede"
    )
    nombre = models.CharField(max_length=50, unique=True)
    tipo_sala = models.CharField(max_length=20, choices=TipoSala.choices, default=TipoSala.LACTANTES)
    capacidad_maxima = models.PositiveIntegerField(default=10)
    descripcion = models.TextField(blank=True, default="")
    activa = models.BooleanField(default=True)

    def __str__(self):
        sede = f" - {self.sede.nombre}" if self.sede else ""
        return f"{self.nombre}{sede}"

    class Meta:
        ordering = ["nombre"]
        indexes = [
            models.Index(fields=["tipo_sala"]),
            models.Index(fields=["activa"]),
        ]


class SalaSemestre(models.Model):
    semestre = models.ForeignKey(Semestre, on_delete=models.CASCADE, related_name="salas_activas")
    sala = models.ForeignKey(Sala, on_delete=models.CASCADE)

    activa = models.BooleanField(default=True)
    cupo = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Cupo específico para este semestre"
    )

    # Horarios por sala - estructura completa Sprint 4.
    entrada_maestras = models.TimeField(null=True, blank=True, verbose_name="Horario de entrada maestras")
    recepcion_inicio = models.TimeField(null=True, blank=True, verbose_name="Inicio recepción de niños")
    recepcion_fin = models.TimeField(null=True, blank=True, verbose_name="Término recepción de niños")

    desayuno_inicio = models.TimeField(null=True, blank=True, verbose_name="Desayuno inicio")
    desayuno_fin = models.TimeField(null=True, blank=True, verbose_name="Desayuno fin")

    actividad_pedagogica_nombre = models.CharField(max_length=150, blank=True, default="", verbose_name="Actividad pedagógica")
    actividad_pedagogica_inicio = models.TimeField(null=True, blank=True, verbose_name="Actividad pedagógica inicio")
    actividad_pedagogica_fin = models.TimeField(null=True, blank=True, verbose_name="Actividad pedagógica fin")
    actividad_pedagogica_personal = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="Personal asignado a actividad pedagógica"
    )

    recreo_inicio = models.TimeField(null=True, blank=True, verbose_name="Recreo inicio")
    recreo_fin = models.TimeField(null=True, blank=True, verbose_name="Recreo fin")

    colacion_inicio = models.TimeField(null=True, blank=True, verbose_name="Colación inicio")
    colacion_fin = models.TimeField(null=True, blank=True, verbose_name="Colación fin")

    siesta_inicio = models.TimeField(null=True, blank=True, verbose_name="Siesta inicio")
    siesta_fin = models.TimeField(null=True, blank=True, verbose_name="Siesta fin")

    comida_inicio = models.TimeField(null=True, blank=True, verbose_name="Comida inicio")
    comida_fin = models.TimeField(null=True, blank=True, verbose_name="Comida fin")

    salida_maestras = models.TimeField(null=True, blank=True, verbose_name="Horario de salida maestras")

    # Campos anteriores conservados por compatibilidad.
    inicio_recepcion = models.TimeField(null=True, blank=True)
    termino_recepcion = models.TimeField(null=True, blank=True)
    horario_desayuno = models.TimeField(null=True, blank=True)
    horario_actividades_pedagogicas = models.TimeField(null=True, blank=True)
    horario_recreo = models.TimeField(null=True, blank=True)
    horario_colacion = models.TimeField(null=True, blank=True)
    horario_siesta = models.TimeField(null=True, blank=True)
    horario_comida = models.TimeField(null=True, blank=True)
    horario_salida = models.TimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def cupo_real(self):
        return self.cupo or self.sala.capacidad_maxima

    def sincronizar_horarios_compatibilidad(self):
        """
        Llena campos antiguos con los nuevos para evitar romper pantallas previas.
        """
        self.inicio_recepcion = self.recepcion_inicio or self.inicio_recepcion
        self.termino_recepcion = self.recepcion_fin or self.termino_recepcion
        self.horario_desayuno = self.desayuno_inicio or self.horario_desayuno
        self.horario_actividades_pedagogicas = self.actividad_pedagogica_inicio or self.horario_actividades_pedagogicas
        self.horario_recreo = self.recreo_inicio or self.horario_recreo
        self.horario_colacion = self.colacion_inicio or self.horario_colacion
        self.horario_siesta = self.siesta_inicio or self.horario_siesta
        self.horario_comida = self.comida_inicio or self.horario_comida
        self.horario_salida = self.salida_maestras or self.horario_salida

    def save(self, *args, **kwargs):
        self.sincronizar_horarios_compatibilidad()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.sala.nombre} - {self.semestre.nombre}"

    class Meta:
        ordering = ["semestre", "sala__nombre"]
        unique_together = ("semestre", "sala")
        indexes = [
            models.Index(fields=["activa"]),
        ]


class AsignacionMaestra(models.Model):
    class RolMaestra(models.TextChoices):
        TITULAR = "TITULAR", "Maestra Titular"
        TITULAR_2 = "TITULAR_2", "Segunda Titular"
        SUPLENTE = "SUPLENTE", "Maestra Suplente / Apoyo"

    sala_semestre = models.ForeignKey(SalaSemestre, on_delete=models.CASCADE, related_name="maestras_asignadas")
    maestra = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mis_salas")
    rol = models.CharField(max_length=20, choices=RolMaestra.choices, default=RolMaestra.TITULAR)
    activo = models.BooleanField(default=True)

    horario_entrada = models.TimeField(null=True, blank=True, verbose_name="Horario entrada maestra")
    horario_salida = models.TimeField(null=True, blank=True, verbose_name="Horario salida maestra")

    desayuno_inicio = models.TimeField(null=True, blank=True, verbose_name="Desayuno inicio maestra")
    desayuno_fin = models.TimeField(null=True, blank=True, verbose_name="Desayuno fin maestra")

    tiempo_fuera_inicio = models.TimeField(null=True, blank=True, verbose_name="Tiempo fuera inicio")
    tiempo_fuera_fin = models.TimeField(null=True, blank=True, verbose_name="Tiempo fuera fin")

    # Campos anteriores conservados por compatibilidad.
    horario_desayuno_maestra = models.TimeField(null=True, blank=True)
    horario_tiempo_fuera = models.TimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def sincronizar_horarios_compatibilidad(self):
        self.horario_desayuno_maestra = self.desayuno_inicio or self.horario_desayuno_maestra
        self.horario_tiempo_fuera = self.tiempo_fuera_inicio or self.horario_tiempo_fuera

    def save(self, *args, **kwargs):
        self.sincronizar_horarios_compatibilidad()
        super().save(*args, **kwargs)

    def __str__(self):
        nombre = self.maestra.get_full_name() if hasattr(self.maestra, "get_full_name") else str(self.maestra)
        return f"{nombre} ({self.get_rol_display()}) en {self.sala_semestre.sala.nombre}"

    class Meta:
        ordering = ["sala_semestre__sala__nombre", "rol"]
        indexes = [
            models.Index(fields=["activo"]),
            models.Index(fields=["rol"]),
        ]


class DiaOperativoSemestre(models.Model):
    """
    Calendario operativo del semestre.

    Segunda parte Sprint 4:
    - El Administrador genera el calendario.
    - La maestra abre el día cuando inicia la operación diaria.
    - La maestra cierra el día cuando todos los registros diarios estén completos.
    """
    class EstadoDia(models.TextChoices):
        PROGRAMADO = "PROGRAMADO", "Programado / pendiente de apertura"
        ABIERTO = "ABIERTO", "Abierto"
        CERRADO = "CERRADO", "Cerrado"

    semestre = models.ForeignKey(Semestre, on_delete=models.CASCADE, related_name="dias_operativos")
    fecha = models.DateField()
    es_habil = models.BooleanField(default=True)
    estado = models.CharField(max_length=20, choices=EstadoDia.choices, default=EstadoDia.PROGRAMADO)

    abierto_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dias_operativos_abiertos",
        verbose_name="Abierto por"
    )
    abierto_en = models.DateTimeField(null=True, blank=True, verbose_name="Fecha y hora de apertura")

    observaciones = models.TextField(blank=True, default="")
    cerrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dias_operativos_cerrados"
    )
    cerrado_en = models.DateTimeField(null=True, blank=True)

    @property
    def es_fin_de_semana(self):
        return es_fin_de_semana(self.fecha)

    @property
    def es_dia_operativo_real(self):
        """
        True únicamente para días hábiles donde la estancia puede operar.
        """
        return bool(self.es_habil and not self.es_fin_de_semana)

    @property
    def puede_abrirse(self):
        """
        Control central para evitar abrir operación en sábados, domingos,
        festivos, suspensiones o días ya cerrados.
        """
        return (
            self.es_dia_operativo_real
            and self.estado == self.EstadoDia.PROGRAMADO
            and self.semestre.estado == Semestre.EstadoSemestre.ACTIVO
        )

    @property
    def mensaje_no_operativo(self):
        if self.es_fin_de_semana:
            return "Hoy es sábado o domingo. La estancia no opera y no se permite registrar entradas, salidas ni bitácoras."
        if not self.es_habil:
            return "Este día está marcado como inhábil. No se permite abrir operación diaria."
        if self.estado == self.EstadoDia.CERRADO:
            return "Este día ya está cerrado. Solo puede consultarse."
        return ""

    @property
    def sede(self):
        return self.semestre.sede_configurada

    @property
    def esta_abierto(self):
        return self.estado == self.EstadoDia.ABIERTO

    @property
    def esta_cerrado(self):
        return self.estado == self.EstadoDia.CERRADO

    @property
    def esta_programado(self):
        return self.estado == self.EstadoDia.PROGRAMADO

    def abrir(self, usuario=None, observaciones=""):
        """
        Abre el día operativo de la sede/semestre.
        Cualquier maestra asignada a una sala de la sede podrá ejecutarlo desde views.
        """
        if not self.es_habil:
            return False, [self.mensaje_no_operativo or "No se puede abrir un día no hábil."]

        if self.es_fin_de_semana:
            return False, [self.mensaje_no_operativo]

        if self.estado == self.EstadoDia.CERRADO:
            return False, ["Este día ya está cerrado y solo puede consultarse."]

        if self.estado == self.EstadoDia.ABIERTO:
            return True, []

        self.estado = self.EstadoDia.ABIERTO
        self.abierto_por = usuario
        self.abierto_en = timezone.now()

        if observaciones:
            self.observaciones = observaciones

        self.save(update_fields=["estado", "abierto_por", "abierto_en", "observaciones"])
        return True, []

    def puede_cerrarse(self):
        """
        Validaciones base para cerrar el día.
        No incluye incidencias todavía.

        Reglas:
        - Todo niño que ingresó debe tener salida.
        - Todo niño que ingresó debe tener bitácora de entrada en casa completa.
        - Todo niño que ingresó debe tener bitácora durante estancia completa.
        - Las salidas anticipadas/por incidencia pueden quedar justificadas.
        """
        errores = []

        if not self.es_habil:
            errores.append("No se puede cerrar un día no hábil; queda cerrado automáticamente y no cuenta para cierre de semestre.")
            return errores

        if self.es_fin_de_semana:
            errores.append("No se puede cerrar sábado o domingo; son días inhábiles automáticos.")
            return errores

        if self.estado != self.EstadoDia.ABIERTO:
            errores.append("Solo se puede cerrar un día abierto.")

        registros_con_entrada = self.registros_alumnos.filter(entrada_en__isnull=False)

        for registro in registros_con_entrada.select_related("alumno__solicitud_ingreso"):
            nombre = registro.alumno.solicitud_ingreso.nombre_menor_completo()

            if not registro.salida_en:
                errores.append(f"{nombre} tiene entrada registrada, pero no tiene salida.")

            if not registro.tiene_bitacora_entrada_completa:
                errores.append(f"{nombre} no tiene completa la bitácora de entrada/en casa.")

            if not registro.tiene_bitacora_estancia_completa:
                errores.append(f"{nombre} no tiene completa la bitácora durante estancia.")

        return errores

    def cerrar(self, usuario=None, observaciones=""):
        errores = self.puede_cerrarse()

        if errores:
            return False, errores

        self.estado = self.EstadoDia.CERRADO
        self.cerrado_por = usuario
        self.cerrado_en = timezone.now()

        if observaciones:
            self.observaciones = observaciones

        self.save(update_fields=["estado", "cerrado_por", "cerrado_en", "observaciones"])
        return True, []

    def __str__(self):
        return f"{self.semestre.nombre} - {self.fecha} - {self.get_estado_display()}"

    class Meta:
        ordering = ["fecha"]
        unique_together = ("semestre", "fecha")
        indexes = [
            models.Index(fields=["fecha"]),
            models.Index(fields=["estado"]),
            models.Index(fields=["es_habil"]),
        ]


# =========================================================
# SPRINT 4 - SEGUNDA PARTE
# OPERACIÓN DIARIA DE MAESTRAS / BITÁCORAS
# =========================================================
class RegistroDiarioAlumno(models.Model):
    """
    Registro diario individual del menor.

    Cada niño tiene un registro por día operativo:
    - Entrada
    - Bitácora en casa
    - Bitácora durante estancia
    - Salida
    - Historial diario
    """
    class EstadoRegistro(models.TextChoices):
        SIN_ENTRADA = "SIN_ENTRADA", "Sin entrada"
        EN_ESTANCIA = "EN_ESTANCIA", "En estancia"
        SALIDA_NORMAL = "SALIDA_NORMAL", "Salida normal"
        SALIDA_ANTICIPADA = "SALIDA_ANTICIPADA", "Salida anticipada"
        SALIDA_POR_INCIDENCIA = "SALIDA_POR_INCIDENCIA", "Salida por incidencia"
        NO_ASISTIO = "NO_ASISTIO", "No asistió"
        COMPLETO = "COMPLETO", "Completo"

    dia_operativo = models.ForeignKey(
        DiaOperativoSemestre,
        on_delete=models.CASCADE,
        related_name="registros_alumnos",
        verbose_name="Día operativo"
    )
    alumno = models.ForeignKey(
        SolicitudInscripcion,
        on_delete=models.CASCADE,
        related_name="registros_diarios",
        verbose_name="Alumno"
    )
    sala_semestre = models.ForeignKey(
        SalaSemestre,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registros_diarios",
        verbose_name="Sala del semestre"
    )

    estado = models.CharField(
        max_length=30,
        choices=EstadoRegistro.choices,
        default=EstadoRegistro.SIN_ENTRADA
    )

    # Entrada del niño.
    entrada_en = models.DateTimeField(null=True, blank=True, verbose_name="Hora de entrada")
    entrada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entradas_registradas"
    )
    responsable_entrada_nombre = models.CharField(max_length=180, blank=True, default="")
    responsable_entrada_parentesco = models.CharField(max_length=80, blank=True, default="")
    responsable_entrada_telefono = models.CharField(max_length=30, blank=True, default="")
    responsable_entrada_codigo = models.ForeignKey(
        "admisiones.CodigoResponsableAutorizado",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entradas_validadas",
        verbose_name="Responsable autorizado que entregó"
    )
    credencial_entrada_validada = models.BooleanField(default=False)
    codigo_entrada_validado = models.BooleanField(default=False)
    temperatura_entrada = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)

    # Salida del niño.
    salida_en = models.DateTimeField(null=True, blank=True, verbose_name="Hora de salida")
    salida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="salidas_registradas"
    )
    responsable_salida_nombre = models.CharField(max_length=180, blank=True, default="")
    responsable_salida_parentesco = models.CharField(max_length=80, blank=True, default="")
    responsable_salida_telefono = models.CharField(max_length=30, blank=True, default="")
    responsable_salida_codigo = models.ForeignKey(
        "admisiones.CodigoResponsableAutorizado",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="salidas_validadas",
        verbose_name="Responsable autorizado que recogió"
    )
    credencial_salida_validada = models.BooleanField(default=False)
    codigo_salida_validado = models.BooleanField(default=False)
    motivo_salida = models.CharField(max_length=120, blank=True, default="")
    observacion_salida = models.TextField(blank=True, default="")

    # Preparado para sprint posterior de incidencias.
    incidencia_relacionada = models.ForeignKey(
        "admisiones.Incidencia",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registros_diarios_relacionados"
    )

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registros_diarios_creados"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def tipo_sala(self):
        if self.sala_semestre and self.sala_semestre.sala:
            return self.sala_semestre.sala.tipo_sala
        if self.alumno and self.alumno.es_lactante:
            return Sala.TipoSala.LACTANTES
        if self.alumno and self.alumno.es_maternal:
            return Sala.TipoSala.MATERNAL
        return ""

    @property
    def formulario_bitacora(self):
        """
        Decide automáticamente qué formulario mostrar.
        La maestra no debe elegirlo manualmente.
        """
        if self.tipo_sala == Sala.TipoSala.LACTANTES:
            return "LACTANTES"
        if self.tipo_sala == Sala.TipoSala.MATERNAL:
            return "MATERNAL"
        return "GENERAL"

    @property
    def dia_esta_editable(self):
        return (
            self.dia_operativo
            and self.dia_operativo.es_habil
            and not self.dia_operativo.es_fin_de_semana
            and self.dia_operativo.estado == DiaOperativoSemestre.EstadoDia.ABIERTO
            and self.dia_operativo.semestre.estado == Semestre.EstadoSemestre.ACTIVO
        )

    @property
    def tiene_bitacora_entrada_completa(self):
        try:
            return bool(self.bitacora_entrada_casa.completa)
        except BitacoraEntradaCasa.DoesNotExist:
            return False

    @property
    def tiene_bitacora_estancia_completa(self):
        try:
            return bool(self.bitacora_estancia.completa)
        except BitacoraEstancia.DoesNotExist:
            return False

    @property
    def esta_dentro(self):
        return bool(self.entrada_en and not self.salida_en)

    @property
    def tiene_salida(self):
        return bool(self.salida_en)

    @property
    def esta_completo_para_cierre(self):
        if not self.entrada_en:
            return True

        return all([
            self.salida_en,
            self.tiene_bitacora_entrada_completa,
            self.tiene_bitacora_estancia_completa,
        ])

    def registrar_entrada(
        self,
        usuario=None,
        responsable_nombre="",
        responsable_parentesco="",
        responsable_telefono="",
        responsable_autorizado=None,
        credencial_validada=False,
        codigo_validado=False,
        temperatura=None,
    ):
        if not self.dia_esta_editable:
            return False, ["El día no está abierto o el semestre no está activo."]

        if self.entrada_en:
            return False, ["Este alumno ya tiene entrada registrada."]

        self.entrada_en = timezone.now()
        self.entrada_por = usuario

        if responsable_autorizado:
            self.responsable_entrada_codigo = responsable_autorizado
            self.responsable_entrada_nombre = responsable_autorizado.nombre_completo
            self.responsable_entrada_parentesco = responsable_autorizado.parentesco
            self.responsable_entrada_telefono = responsable_autorizado.telefono
        else:
            self.responsable_entrada_nombre = responsable_nombre or ""
            self.responsable_entrada_parentesco = responsable_parentesco or ""
            self.responsable_entrada_telefono = responsable_telefono or ""

        self.credencial_entrada_validada = bool(credencial_validada)
        self.codigo_entrada_validado = bool(codigo_validado)
        self.temperatura_entrada = temperatura
        self.estado = self.EstadoRegistro.EN_ESTANCIA
        self.save()

        return True, []

    def registrar_salida(
        self,
        usuario=None,
        responsable_nombre="",
        responsable_parentesco="",
        responsable_telefono="",
        responsable_autorizado=None,
        credencial_validada=False,
        codigo_validado=False,
        tipo_salida=None,
        motivo_salida="",
        observacion_salida="",
        incidencia=None,
    ):
        if not self.dia_esta_editable:
            return False, ["El día no está abierto o el semestre no está activo."]

        if not self.entrada_en:
            return False, ["No se puede registrar salida sin entrada."]

        if self.salida_en:
            return False, ["Este alumno ya tiene salida registrada."]

        self.salida_en = timezone.now()
        self.salida_por = usuario

        if responsable_autorizado:
            self.responsable_salida_codigo = responsable_autorizado
            self.responsable_salida_nombre = responsable_autorizado.nombre_completo
            self.responsable_salida_parentesco = responsable_autorizado.parentesco
            self.responsable_salida_telefono = responsable_autorizado.telefono
        else:
            self.responsable_salida_nombre = responsable_nombre or ""
            self.responsable_salida_parentesco = responsable_parentesco or ""
            self.responsable_salida_telefono = responsable_telefono or ""

        self.credencial_salida_validada = bool(credencial_validada)
        self.codigo_salida_validado = bool(codigo_validado)
        self.motivo_salida = motivo_salida or ""
        self.observacion_salida = observacion_salida or ""

        if incidencia:
            self.incidencia_relacionada = incidencia

        self.estado = tipo_salida or self.EstadoRegistro.SALIDA_NORMAL
        self.save()

        return True, []

    def marcar_completo_si_corresponde(self):
        if self.entrada_en and self.salida_en and self.tiene_bitacora_entrada_completa and self.tiene_bitacora_estancia_completa:
            self.estado = self.EstadoRegistro.COMPLETO
            self.save(update_fields=["estado", "updated_at"])

    def __str__(self):
        nombre = self.alumno.solicitud_ingreso.nombre_menor_completo()
        return f"{nombre} - {self.dia_operativo.fecha} - {self.get_estado_display()}"

    class Meta:
        ordering = ["dia_operativo__fecha", "sala_semestre__sala__nombre", "alumno__solicitud_ingreso__apellido_paterno_menor"]
        unique_together = ("dia_operativo", "alumno")
        indexes = [
            models.Index(fields=["estado"]),
            models.Index(fields=["entrada_en"]),
            models.Index(fields=["salida_en"]),
            models.Index(fields=["responsable_entrada_codigo"]),
            models.Index(fields=["responsable_salida_codigo"]),
        ]


class BitacoraEntradaCasa(models.Model):
    """
    Primera parte de la bitácora:
    información que el adulto responsable reporta al dejar al menor.
    """
    registro_diario = models.OneToOneField(
        RegistroDiarioAlumno,
        on_delete=models.CASCADE,
        related_name="bitacora_entrada_casa"
    )

    capturada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bitacoras_entrada_casa"
    )
    capturada_en = models.DateTimeField(null=True, blank=True)

    completa = models.BooleanField(default=False)

    desperto_a_las = models.TimeField(null=True, blank=True, verbose_name="Hoy desperté a las")
    como_amanecio = models.CharField(max_length=120, blank=True, default="", verbose_name="Hoy amanecí")
    ultimo_alimento_hora = models.TimeField(null=True, blank=True, verbose_name="Mi último alimento fue a las")
    leche_descripcion = models.CharField(max_length=180, blank=True, default="", verbose_name="Leche / cantidad")
    alimentos_descripcion = models.TextField(blank=True, default="", verbose_name="Papilla o alimentos completos")
    estado_en_casa = models.CharField(max_length=180, blank=True, default="", verbose_name="En casa estuve")
    hizo_popo = models.BooleanField(null=True, blank=True, verbose_name="¿Hice popó?")
    observaciones = models.TextField(blank=True, default="", verbose_name="Observaciones de casa")

    # Permite guardar detalles específicos de Lactantes/Maternal sin crear demasiadas columnas.
    datos_extra = models.JSONField(null=True, blank=True, default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def marcar_completa(self, usuario=None):
        self.completa = True
        self.capturada_por = usuario or self.capturada_por
        self.capturada_en = timezone.now()
        self.save(update_fields=["completa", "capturada_por", "capturada_en", "updated_at"])
        self.registro_diario.marcar_completo_si_corresponde()

    def __str__(self):
        return f"Bitácora en casa - {self.registro_diario}"

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["completa"]),
            models.Index(fields=["capturada_en"]),
        ]


class BitacoraEstancia(models.Model):
    """
    Segunda parte de la bitácora:
    información observada por la maestra durante la estancia del menor.
    """
    registro_diario = models.OneToOneField(
        RegistroDiarioAlumno,
        on_delete=models.CASCADE,
        related_name="bitacora_estancia"
    )

    capturada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bitacoras_estancia"
    )
    capturada_en = models.DateTimeField(null=True, blank=True)

    completa = models.BooleanField(default=False)

    estado_durante_dia = models.CharField(max_length=180, blank=True, default="", verbose_name="Hoy durante el día estuve")
    leche_tomas = models.JSONField(null=True, blank=True, default=dict, verbose_name="Tomas de leche")
    hidratacion = models.CharField(max_length=180, blank=True, default="", verbose_name="Hidratación")
    desayuno = models.TextField(blank=True, default="", verbose_name="Desayuno")
    colacion = models.TextField(blank=True, default="", verbose_name="Colación")
    comida = models.TextField(blank=True, default="", verbose_name="Comida")
    siesta = models.CharField(max_length=180, blank=True, default="", verbose_name="Siesta")
    panal = models.CharField(max_length=180, blank=True, default="", verbose_name="Cambio de pañal")
    control_esfinteres = models.CharField(max_length=180, blank=True, default="", verbose_name="Control de esfínteres")
    actividad_pedagogica = models.TextField(blank=True, default="", verbose_name="Actividad pedagógica")
    comentario_general = models.TextField(blank=True, default="", verbose_name="Comentario general")

    # Permite guardar detalles específicos de Lactantes/Maternal sin crear demasiadas columnas.
    datos_extra = models.JSONField(null=True, blank=True, default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def marcar_completa(self, usuario=None):
        self.completa = True
        self.capturada_por = usuario or self.capturada_por
        self.capturada_en = timezone.now()
        self.save(update_fields=["completa", "capturada_por", "capturada_en", "updated_at"])
        self.registro_diario.marcar_completo_si_corresponde()

    def __str__(self):
        return f"Bitácora estancia - {self.registro_diario}"

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["completa"]),
            models.Index(fields=["capturada_en"]),
        ]


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


class EnvioEncuestaSatisfaccion(models.Model):
    """
    Control individual de envío de la Encuesta de Satisfacción B.

    Sirve para:
    - Registrar a qué tutor se envió la encuesta.
    - Validar que el correo sea institucional.
    - Permitir reenvío.
    - Mostrar estado por alumno/tutor en la vista del administrador.
    - Relacionar el envío con la respuesta registrada.
    """

    class EstadoEnvio(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        ENVIADA = "ENVIADA", "Enviada"
        REENVIADA = "REENVIADA", "Reenviada"
        CONTESTADA = "CONTESTADA", "Contestada"
        ERROR = "ERROR", "Error de envío"
        BLOQUEADA = "BLOQUEADA", "Bloqueada por correo no institucional"

    semestre = models.ForeignKey(
        Semestre,
        on_delete=models.CASCADE,
        related_name="envios_encuesta_satisfaccion",
        verbose_name="Semestre"
    )

    inscripcion = models.ForeignKey(
        SolicitudInscripcion,
        on_delete=models.CASCADE,
        related_name="envios_encuesta_satisfaccion",
        verbose_name="Alumno / inscripción"
    )

    tutor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="envios_encuesta_satisfaccion",
        verbose_name="Tutor responsable"
    )

    correo_destino = models.EmailField(
        verbose_name="Correo institucional del tutor"
    )

    correo_copia = models.EmailField(
        blank=True,
        default="",
        verbose_name="Correo genérico en copia"
    )

    token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        verbose_name="Token de respuesta"
    )

    estado = models.CharField(
        max_length=20,
        choices=EstadoEnvio.choices,
        default=EstadoEnvio.PENDIENTE,
        verbose_name="Estado del envío"
    )

    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="encuestas_satisfaccion_enviadas",
        verbose_name="Enviado por"
    )

    enviado_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de envío"
    )

    reenviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="encuestas_satisfaccion_reenviadas",
        verbose_name="Reenviado por"
    )

    reenviado_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de reenvío"
    )

    contestado_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de respuesta"
    )

    intentos_envio = models.PositiveIntegerField(
        default=0,
        verbose_name="Intentos de envío"
    )

    ultimo_error = models.TextField(
        blank=True,
        default="",
        verbose_name="Último error de envío"
    )

    observaciones = models.TextField(
        blank=True,
        default="",
        verbose_name="Observaciones administrativas"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def correo_institucional_valido(self):
        return bool(self.correo_destino and self.correo_destino.lower().endswith("@unach.mx"))

    @property
    def respuesta(self):
        return EncuestaSatisfaccion.objects.filter(
            semestre=self.semestre,
            inscripcion=self.inscripcion
        ).order_by("-fecha_respuesta").first()

    @property
    def tiene_respuesta(self):
        return self.respuesta is not None

    def marcar_enviada(self, usuario=None, correo_copia=""):
        self.estado = self.EstadoEnvio.ENVIADA
        self.enviado_por = usuario
        self.enviado_en = timezone.now()
        self.correo_copia = correo_copia or self.correo_copia
        self.intentos_envio = (self.intentos_envio or 0) + 1
        self.ultimo_error = ""
        self.save(update_fields=[
            "estado",
            "enviado_por",
            "enviado_en",
            "correo_copia",
            "intentos_envio",
            "ultimo_error",
            "updated_at",
        ])

    def marcar_reenviada(self, usuario=None, correo_copia=""):
        self.estado = self.EstadoEnvio.REENVIADA
        self.reenviado_por = usuario
        self.reenviado_en = timezone.now()
        self.correo_copia = correo_copia or self.correo_copia
        self.intentos_envio = (self.intentos_envio or 0) + 1
        self.ultimo_error = ""
        self.save(update_fields=[
            "estado",
            "reenviado_por",
            "reenviado_en",
            "correo_copia",
            "intentos_envio",
            "ultimo_error",
            "updated_at",
        ])

    def marcar_contestada(self):
        self.estado = self.EstadoEnvio.CONTESTADA
        self.contestado_en = timezone.now()
        self.save(update_fields=["estado", "contestado_en", "updated_at"])

    def marcar_error(self, error):
        self.estado = self.EstadoEnvio.ERROR
        self.ultimo_error = str(error or "")
        self.intentos_envio = (self.intentos_envio or 0) + 1
        self.save(update_fields=["estado", "ultimo_error", "intentos_envio", "updated_at"])

    def marcar_bloqueada(self, motivo="Correo no institucional"):
        self.estado = self.EstadoEnvio.BLOQUEADA
        self.ultimo_error = motivo
        self.save(update_fields=["estado", "ultimo_error", "updated_at"])

    def save(self, *args, **kwargs):
        if self.correo_destino:
            self.correo_destino = self.correo_destino.strip().lower()

        if self.correo_copia:
            self.correo_copia = self.correo_copia.strip().lower()

        if self.correo_destino and not self.correo_institucional_valido:
            self.estado = self.EstadoEnvio.BLOQUEADA
            if not self.ultimo_error:
                self.ultimo_error = "El correo del tutor debe ser institucional y terminar en @unach.mx."

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Encuesta B - {self.inscripcion_id} - {self.semestre.nombre} - {self.get_estado_display()}"

    class Meta:
        ordering = ["semestre", "inscripcion__solicitud_ingreso__apellido_paterno_menor"]
        unique_together = ("semestre", "inscripcion")
        indexes = [
            models.Index(fields=["estado"]),
            models.Index(fields=["token"]),
            models.Index(fields=["correo_destino"]),
            models.Index(fields=["enviado_en"]),
            models.Index(fields=["reenviado_en"]),
            models.Index(fields=["contestado_en"]),
        ]


class MensajeDirectora(models.Model):
    remitente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    asunto = models.CharField(max_length=200)
    contenido = models.TextField()
    fecha_envio = models.DateTimeField(auto_now_add=True)
    leido = models.BooleanField(default=False)

    es_alumno_inscrito = models.BooleanField(default=False, help_text="Si es Falso, es de un aspirante en registro")

    def __str__(self):
        return f"{self.asunto} - {self.remitente.email}"


# =========================================================
# SPRINT 5 - ÉPICA 3: INCIDENCIAS
# Pedagógica, Nutricional, Médica y Psicológica.
# =========================================================
class Incidencia(models.Model):
    class TipoIncidencia(models.TextChoices):
        PEDAGOGICA = "PEDAGOGICA", "Pedagógica"
        NUTRICIONAL = "NUTRICIONAL", "Nutricional"
        MEDICA = "MEDICA", "Médica"
        PSICOLOGICA = "PSICOLOGICA", "Psicológica"

    class EstadoIncidencia(models.TextChoices):
        ABIERTA = "ABIERTA", "Abierta"
        CERRADA = "CERRADA", "Cerrada"

    class NivelChoices(models.TextChoices):
        BAJO = "BAJO", "Bajo / Leve"
        LEVE = "LEVE", "Leve"
        MEDIO = "MEDIO", "Medio"
        ALTO = "ALTO", "Alto"

    class MedioAviso(models.TextChoices):
        NO_APLICA = "NO_APLICA", "No aplica"
        PRESENCIAL = "PRESENCIAL", "Presencial"
        TELEFONO = "TELEFONO", "Teléfono"
        MENSAJE = "MENSAJE", "Mensaje"
        CORREO = "CORREO", "Correo"
        OTRO = "OTRO", "Otro"

    alumno = models.ForeignKey(
        SolicitudInscripcion,
        on_delete=models.CASCADE,
        related_name="incidencias",
        verbose_name="Alumno"
    )
    semestre = models.ForeignKey(
        Semestre,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incidencias",
        verbose_name="Semestre"
    )
    dia_operativo = models.ForeignKey(
        DiaOperativoSemestre,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incidencias",
        verbose_name="Día operativo"
    )
    registro_diario = models.ForeignKey(
        RegistroDiarioAlumno,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incidencias",
        verbose_name="Registro diario del alumno"
    )
    sala_semestre = models.ForeignKey(
        SalaSemestre,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incidencias",
        verbose_name="Sala del semestre"
    )

    tipo = models.CharField(
        max_length=20,
        choices=TipoIncidencia.choices,
        default=TipoIncidencia.MEDICA,
        verbose_name="Tipo de incidencia"
    )
    categoria = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="Categoría principal"
    )
    subtipo = models.CharField(
        max_length=160,
        blank=True,
        default="",
        verbose_name="Subtipo / detalle del tipo"
    )
    descripcion = models.TextField(
        verbose_name="Descripción de la incidencia"
    )
    intervencion_personal = models.TextField(
        blank=True,
        default="",
        verbose_name="Intervención del personal"
    )

    nivel = models.CharField(
        max_length=10,
        choices=NivelChoices.choices,
        default=NivelChoices.LEVE,
        verbose_name="Nivel de riesgo"
    )
    estado = models.CharField(
        max_length=20,
        choices=EstadoIncidencia.choices,
        default=EstadoIncidencia.ABIERTA,
        verbose_name="Estado"
    )

    responsable_informado = models.BooleanField(
        default=False,
        verbose_name="¿Se informó al responsable?"
    )
    medio_aviso_responsable = models.CharField(
        max_length=20,
        choices=MedioAviso.choices,
        default=MedioAviso.NO_APLICA,
        verbose_name="Medio de aviso al responsable"
    )
    responsable_informado_nombre = models.CharField(
        max_length=180,
        blank=True,
        default="",
        verbose_name="Nombre del responsable informado"
    )
    responsable_informado_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha y hora de aviso al responsable"
    )

    resolucion = models.TextField(
        blank=True,
        default="",
        verbose_name="Resolución"
    )

    fecha_reporte = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha y hora de creación"
    )
    registrada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="incidencias_registradas",
        verbose_name="Registrada por"
    )
    cerrada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incidencias_cerradas",
        verbose_name="Cerrada por"
    )
    cerrada_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha y hora de cierre"
    )

    resuelta = models.BooleanField(default=False)
    comentario_cierre = models.TextField(
        blank=True,
        default="",
        verbose_name="Comentario de cierre anterior / compatibilidad"
    )
    datos_extra = models.JSONField(
        null=True,
        blank=True,
        default=dict,
        verbose_name="Datos específicos de la incidencia"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def fecha(self):
        return timezone.localtime(self.fecha_reporte).date() if self.fecha_reporte else None

    @property
    def hora(self):
        return timezone.localtime(self.fecha_reporte).time() if self.fecha_reporte else None

    @property
    def nombre_alumno(self):
        try:
            return self.alumno.solicitud_ingreso.nombre_menor_completo()
        except Exception:
            return "Sin alumno"

    @property
    def nombre_sala(self):
        try:
            return self.sala_semestre.sala.nombre
        except Exception:
            try:
                return self.alumno.sala_semestre_asignada.sala.nombre
            except Exception:
                return "Sin sala"

    @property
    def tiene_seguimiento(self):
        return self.seguimientos.exists()

    @property
    def total_seguimientos(self):
        return self.seguimientos.count()

    @property
    def esta_abierta(self):
        return self.estado == self.EstadoIncidencia.ABIERTA

    @property
    def esta_cerrada(self):
        return self.estado == self.EstadoIncidencia.CERRADA

    def puede_agregar_seguimiento(self, usuario):
        return bool(usuario and self.registrada_por_id == usuario.id and self.esta_abierta)

    def puede_cerrar(self, usuario):
        if not usuario:
            return False

        if self.registrada_por_id == usuario.id:
            return True

        if getattr(usuario, "is_superuser", False) or getattr(usuario, "is_staff", False):
            return True

        try:
            return usuario.groups.filter(name__icontains="admin").exists()
        except Exception:
            return False

    def validar_para_cerrar(self, usuario=None):
        errores = []

        if self.estado == self.EstadoIncidencia.CERRADA:
            errores.append("La incidencia ya está cerrada.")

        if not self.seguimientos.exists():
            errores.append("No se puede cerrar: la incidencia debe tener mínimo un seguimiento.")

        if usuario and not self.puede_cerrar(usuario):
            errores.append("Solo puede cerrar la incidencia quien la creó o el Administrador del Sistema.")

        if self.semestre and self.semestre.estado == Semestre.EstadoSemestre.CERRADO:
            errores.append("No se puede cerrar: el semestre ya está cerrado.")

        return errores

    def cerrar(self, usuario=None, resolucion="", comentario=""):
        errores = self.validar_para_cerrar(usuario=usuario)

        if errores:
            return False, errores

        self.estado = self.EstadoIncidencia.CERRADA
        self.resuelta = True
        self.cerrada_por = usuario
        self.cerrada_en = timezone.now()
        self.resolucion = resolucion or comentario or self.resolucion
        self.comentario_cierre = comentario or resolucion or self.comentario_cierre
        self.save(update_fields=[
            "estado",
            "resuelta",
            "cerrada_por",
            "cerrada_en",
            "resolucion",
            "comentario_cierre",
            "updated_at",
        ])

        return True, []

    def save(self, *args, **kwargs):
        if not self.semestre_id and self.alumno_id:
            self.semestre = getattr(self.alumno, "semestre", None)

        if not self.sala_semestre_id and self.alumno_id:
            self.sala_semestre = getattr(self.alumno, "sala_semestre_asignada", None)

        if not self.dia_operativo_id and self.registro_diario_id:
            self.dia_operativo = self.registro_diario.dia_operativo

        if not self.alumno_id and self.registro_diario_id:
            self.alumno = self.registro_diario.alumno

        if self.estado == self.EstadoIncidencia.CERRADA:
            self.resuelta = True
            if not self.cerrada_en:
                self.cerrada_en = timezone.now()
        elif self.resuelta:
            self.estado = self.EstadoIncidencia.CERRADA
            if not self.cerrada_en:
                self.cerrada_en = timezone.now()

        if self.responsable_informado and not self.responsable_informado_en:
            self.responsable_informado_en = timezone.now()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.nombre_alumno} - {self.get_estado_display()}"

    class Meta:
        ordering = ["-fecha_reporte"]
        indexes = [
            models.Index(fields=["estado"]),
            models.Index(fields=["tipo"]),
            models.Index(fields=["nivel"]),
            models.Index(fields=["fecha_reporte"]),
            models.Index(fields=["semestre"]),
            models.Index(fields=["dia_operativo"]),
            models.Index(fields=["registrada_por"]),
        ]


class IncidenciaArchivo(models.Model):
    incidencia = models.ForeignKey(
        Incidencia,
        on_delete=models.CASCADE,
        related_name="archivos",
        verbose_name="Incidencia"
    )
    archivo = models.FileField(
        upload_to=ruta_archivo_incidencia,
        verbose_name="Archivo adjunto"
    )
    nombre_original = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Nombre original"
    )
    descripcion = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Descripción del archivo"
    )
    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archivos_incidencia_subidos",
        verbose_name="Subido por"
    )
    subido_en = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha y hora de carga"
    )

    def save(self, *args, **kwargs):
        if self.archivo and not self.nombre_original:
            self.nombre_original = self.archivo.name.split("/")[-1]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre_original or f"Archivo incidencia {self.incidencia_id}"

    class Meta:
        ordering = ["-subido_en"]
        indexes = [
            models.Index(fields=["subido_en"]),
        ]


class SeguimientoIncidencia(models.Model):
    incidencia = models.ForeignKey(
        Incidencia,
        on_delete=models.CASCADE,
        related_name="seguimientos",
        verbose_name="Incidencia"
    )
    nota = models.TextField(
        verbose_name="Seguimiento"
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="seguimientos_incidencia_creados",
        verbose_name="Creado por"
    )
    creado_en = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha y hora de seguimiento"
    )

    def __str__(self):
        return f"Seguimiento {self.id} - Incidencia {self.incidencia_id}"

    class Meta:
        ordering = ["-creado_en"]
        indexes = [
            models.Index(fields=["creado_en"]),
            models.Index(fields=["creado_por"]),
        ]


class SeguimientoIncidenciaArchivo(models.Model):
    seguimiento = models.ForeignKey(
        SeguimientoIncidencia,
        on_delete=models.CASCADE,
        related_name="archivos",
        verbose_name="Seguimiento"
    )
    archivo = models.FileField(
        upload_to=ruta_archivo_seguimiento_incidencia,
        verbose_name="Archivo adjunto"
    )
    nombre_original = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Nombre original"
    )
    descripcion = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Descripción del archivo"
    )
    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archivos_seguimiento_incidencia_subidos",
        verbose_name="Subido por"
    )
    subido_en = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha y hora de carga"
    )

    def save(self, *args, **kwargs):
        if self.archivo and not self.nombre_original:
            self.nombre_original = self.archivo.name.split("/")[-1]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre_original or f"Archivo seguimiento {self.seguimiento_id}"

    class Meta:
        ordering = ["-subido_en"]
        indexes = [
            models.Index(fields=["subido_en"]),
        ]


class BitacoraBase(models.Model):
    class EstadoBitacora(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador (Sin enviar)"
        ENVIADO = "ENVIADO", "Enviado a Coordinación"
        APROBADO = "APROBADO", "Aprobado (Palomita)"
        RECHAZADO = "RECHAZADO", "Rechazado (Tacha)"
        EN_DIRECTIVA = "EN_DIRECTIVA", "Enviada a Dirección"

    alumno = models.ForeignKey(SolicitudInscripcion, on_delete=models.CASCADE, related_name="%(class)s_bitacoras")
    maestra = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                related_name="%(class)s_creadas")
    fecha = models.DateField(default=timezone.now)

    estado = models.CharField(max_length=20, choices=EstadoBitacora.choices, default=EstadoBitacora.BORRADOR)
    comentarios_coordinadora = models.TextField(null=True, blank=True, help_text="Espacio en blanco para correcciones")

    archivo_pdf = models.FileField(upload_to=ruta_bitacora_pdf, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class BitacoraLactante(BitacoraBase):
    datos_json = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"Bitácora Lactante - {self.alumno.solicitud_ingreso.nombres_menor} - {self.fecha}"


class BitacoraMaternal(BitacoraBase):
    datos_json = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"Bitácora Maternal - {self.alumno.solicitud_ingreso.nombres_menor} - {self.fecha}"