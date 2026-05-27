from django.shortcuts import render, redirect, get_object_or_404
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    JsonResponse,
    HttpResponseForbidden,
)
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_http_methods
from django.urls import reverse
from django.conf import settings
from django.template.loader import render_to_string
from django.contrib.staticfiles import finders
from xhtml2pdf import pisa

from django.core.mail import send_mail, EmailMessage
from django.core.files import File
from django.contrib.auth import get_user_model
from django.db.models import Q

import os
import re
import csv
import unicodedata

from .forms import (
    CapturaSolicitudForm,
    CrearSolicitudPanelForm,
    DictamenPsicologiaForm,
    DictamenNutricionForm,
    DictamenMedicoForm,
    HistoriaClinicaMedicaForm,

    # Sprint 4 - Configuración de Semestre
    SedeForm,
    SemestreForm,
    DiaFestivoForm,
    SalaForm,
    SalaSemestreForm,
    AsignacionMaestraForm,
    AsignarAlumnoSalaForm,
    DiaOperativoSemestreForm,
    CerrarDiaOperativoForm,
    IncidenciaForm,
    SeguimientoIncidenciaForm,
    CerrarIncidenciaForm,
    EnviarEncuestaSatisfaccionForm,
    IniciarSemestreForm,
    CerrarSemestreForm,
    ClonarSemestreForm,
    GenerarCodigoResponsableForm,
    ConfirmarEntregaCodigoResponsableForm,
    RegistrarComprobantePresencialForm,

    # Sprint 4 - Segunda parte / Operación diaria de maestras
    AbrirDiaOperativoMaestraForm,
    RegistroEntradaAlumnoForm,
    BitacoraEntradaCasaForm,
    BitacoraEstanciaForm,
    RegistroSalidaAlumnoForm,
    CerrarDiaOperacionMaestraForm,
)

from .services import (
    generar_pdf_fo301,
    generar_pdf_dictamen,
    generar_pdf_inscripcion_lleno,
    enviar_correo_dictamen_ingreso,
    generar_pdf_reporte_final_ingreso,
    enviar_correo_reporte_final_ingreso,

    # Reglas generales de semestre / operación del sistema
    obtener_semestre_activo_operativo,
    hay_semestre_activo_operativo,
    contexto_semestre_operativo,
    semestre_esta_cerrado,
    semestre_permite_edicion_admin,
    usuario_es_admin_sistema,
)

from .models import (
    Solicitud,
    LinkCaptura,
    SolicitudInscripcion,
    HistoriaClinicaMedica,
    Carrera,

    # Sprint 4 - Configuración de Semestre
    Sede,
    Semestre,
    DiaFestivo,
    Sala,
    SalaSemestre,
    AsignacionMaestra,
    DiaOperativoSemestre,
    RegistroDiarioAlumno,
    CodigoResponsableAutorizado,
    BitacoraEntradaCasa,
    BitacoraEstancia,
    EncuestaSatisfaccion,
    EnvioEncuestaSatisfaccion,
    Incidencia,
    IncidenciaArchivo,
    SeguimientoIncidencia,
    SeguimientoIncidenciaArchivo,
)


# ===================== AJAX: FILTRAR CARRERAS =====================
def obtener_carreras(request):
    facultad_id = request.GET.get("facultad_id")

    if facultad_id:
        carreras = Carrera.objects.filter(facultad_id=facultad_id).values("id", "nombre")
        return JsonResponse(list(carreras), safe=False)

    return JsonResponse([], safe=False)


# ===================== CALLBACK PARA PDF =====================
def link_callback(uri, rel):
    if uri.startswith(settings.STATIC_URL):
        path = finders.find(uri.replace(settings.STATIC_URL, ""))
        if path:
            return path

    return uri


def verificacion_staff(user):
    return user.is_authenticated and (
        user.is_staff or getattr(user, "tipo_persona", "") == "ADMIN"
    )


def modulo_desactivado(request, mensaje=None):
    """
    Redirección segura para módulos que fueron retirados del flujo actual.
    Evita errores TemplateDoesNotExist cuando ya se borraron los HTML.
    """
    if mensaje:
        messages.info(request, mensaje)
    else:
        messages.info(request, "Este módulo está desactivado en esta versión del sistema.")

    return redirect("/")


# =========================================================
# AUXILIARES SPRINT 2 - PROCESO DE INSCRIPCIÓN
# =========================================================

ESTADOS_INSCRIPCION_EDITABLES = [
    "NUEVA",
    "EN_PROCESO",
    "DEVUELTA",
]

ESTADOS_INSCRIPCION_BLOQUEADOS = [
    "EN_REVISION",
    "FILTROS",
    "REVISION_FINAL_TS",
    "ESPERANDO_DIRECTORA",
    "SALA_EN_REVISION",
    "SALA_RECHAZADA",
    "SALA_APROBADA",
    "ACEPTADO_ESPERANDO_PAGO",
    "FINALIZADA",
    "RECHAZADA",
]

DOCUMENTOS_OBLIGATORIOS_BASE = {
    "doc_menor_certificado_medico": "Certificado médico del menor",
    "doc_menor_cartilla_vacunacion": "Cartilla de vacunación del menor",
    "doc_menor_grupo_sanguineo": "Examen de grupo sanguíneo del menor",
    "doc_menor_acta_nacimiento": "Acta de nacimiento del menor",
    "doc_menor_fotos": "Fotografías del menor",
    "doc_menor_laboratorio": "Estudios de laboratorio del menor",

    "doc_tutor_acta_nacimiento": "Acta de nacimiento del beneficiario",
    "doc_tutor_ine": "INE o pasaporte del beneficiario",
    "doc_tutor_fotos": "Fotografías del beneficiario",
    "doc_tutor_domicilio": "Comprobante de domicilio",
    "doc_tutor_historial": "Historial académico",
    "doc_tutor_horario": "Horario de clases firmado",

    "doc_autorizado_carta": "Carta de autorización de personas autorizadas",
    "doc_autorizado_ine": "INE de personas autorizadas",
    "doc_contacto_1_fotos": "Foto del familiar autorizado 1",

    "reglamento_firmado": "Reglamento interno firmado",
}

CAMPOS_DATOS_OBLIGATORIOS_INSCRIPCION = {
    "avance_academico": "Avance académico",
    "estado_civil_tutor": "Estado civil del beneficiario",
    "parentesco_tutor": "Parentesco con el menor",
    "edad_anios_menor": "Edad del menor en años",
    "edad_meses_menor": "Edad del menor en meses",
    "estado_nacimiento_menor": "Estado de nacimiento del menor",
    "municipio_nacimiento_menor": "Municipio de nacimiento del menor",
    "sexo_menor": "Sexo del menor",
    "tipo_sangre_menor": "Tipo de sangre del menor",
    "contacto_1_nombres": "Nombre del familiar autorizado 1",
    "contacto_1_apellido_paterno": "Apellido paterno del familiar autorizado 1",
    "contacto_1_apellido_materno": "Apellido materno del familiar autorizado 1",
    "contacto_1_parentesco": "Parentesco del familiar autorizado 1",
    "contacto_1_telefono": "Teléfono del familiar autorizado 1",
}


def puede_editar_inscripcion(inscripcion):
    """
    El tutor solo puede editar cuando la inscripción está nueva,
    en proceso o devuelta.
    """
    return inscripcion.estado in ESTADOS_INSCRIPCION_EDITABLES


def obtener_correo_tutor(inscripcion):
    solicitud = inscripcion.solicitud_ingreso

    if getattr(solicitud, "correo", None):
        return solicitud.correo

    if getattr(inscripcion, "usuario_tutor", None) and inscripcion.usuario_tutor.email:
        return inscripcion.usuario_tutor.email

    return None


def enviar_correo_estado_inscripcion(inscripcion, tipo):
    """
    Envía correo al tutor cuando Trabajo Social devuelve o valida expediente.
    En local se imprimirá en consola si usas console.EmailBackend.
    """
    correo = obtener_correo_tutor(inscripcion)

    if not correo:
        return False, "No hay correo registrado para el beneficiario."

    solicitud = inscripcion.solicitud_ingreso
    nombre_tutor = solicitud.nombre_tutor_completo() if hasattr(solicitud, "nombre_tutor_completo") else "Beneficiario"
    folio = solicitud.folio or inscripcion.id

    if tipo == "DEVUELTA":
        asunto = f"Expediente de inscripción devuelto - Folio {folio}"

        observaciones = inscripcion.observaciones or "No se registraron observaciones."

        if "|" in observaciones:
            partes = observaciones.split("|", 1)
            docs = partes[0].strip()
            comentario = partes[1].strip() if len(partes) > 1 else ""
        else:
            docs = ""
            comentario = observaciones

        cuerpo = f"""
Estimado(a) {nombre_tutor}:

Tu expediente de inscripción con folio {folio} fue revisado por Trabajo Social y fue DEVUELTO para corrección.

Documentos observados:
{docs or "No se especificaron documentos particulares."}

Observaciones:
{comentario or "Favor de revisar tu expediente y corregir los documentos solicitados."}

Ingresa nuevamente al portal de inscripción, corrige la información o documentos observados y vuelve a enviar tu expediente.

Atentamente,
Estancia Infantil Universitaria
Universidad Autónoma de Chiapas
"""

    elif tipo == "FILTROS":
        asunto = f"Expediente de inscripción validado - Folio {folio}"
        cuerpo = f"""
Estimado(a) {nombre_tutor}:

Tu expediente de inscripción con folio {folio} fue validado correctamente por Trabajo Social.

A partir de este momento tu expediente pasa a la etapa de filtros institucionales:
- Psicología
- Nutrición
- Médico

Se te notificará cualquier avance o resolución conforme continúe el proceso.

Atentamente,
Estancia Infantil Universitaria
Universidad Autónoma de Chiapas
"""

    elif tipo == "EN_REVISION":
        asunto = f"Expediente enviado a revisión - Folio {folio}"
        cuerpo = f"""
Estimado(a) {nombre_tutor}:

Tu expediente de inscripción con folio {folio} fue enviado correctamente a revisión por Trabajo Social.

Durante esta etapa no podrás modificar la información enviada, salvo que el área responsable devuelva el expediente para correcciones.

Atentamente,
Estancia Infantil Universitaria
Universidad Autónoma de Chiapas
"""

    else:
        return False, "Tipo de correo no válido."

    try:
        send_mail(
            asunto,
            cuerpo,
            settings.DEFAULT_FROM_EMAIL,
            [correo],
            fail_silently=False,
        )
        return True, "Correo enviado correctamente."
    except Exception as e:
        return False, str(e)


def obtener_documentos_obligatorios(inscripcion):
    """
    Documentos obligatorios base + documentos dinámicos.
    """
    documentos = dict(DOCUMENTOS_OBLIGATORIOS_BASE)

    # Si registró pareja/cónyuge, la foto de pareja también es obligatoria.
    if getattr(inscripcion, "nombres_segundo_padre", None):
        documentos["doc_segundo_padre_fotos"] = "Foto de la pareja o segundo tutor"

    # Si agregó familiar 2, su foto también es obligatoria.
    if getattr(inscripcion, "contacto_2_nombres", None):
        documentos["doc_contacto_2_fotos"] = "Foto del familiar autorizado 2"

    # Si agregó familiar 3, su foto también es obligatoria.
    if getattr(inscripcion, "contacto_3_nombres", None):
        documentos["doc_contacto_3_fotos"] = "Foto del familiar autorizado 3"

    return documentos


def validar_expediente_para_envio(inscripcion):
    """
    Validación fuerte de backend.
    Evita que se envíe expediente incompleto aunque manipulen el HTML o JS.
    """
    errores = []

    # Datos obligatorios
    for campo, etiqueta in CAMPOS_DATOS_OBLIGATORIOS_INSCRIPCION.items():
        valor = getattr(inscripcion, campo, None)

        if valor is None or str(valor).strip() == "":
            errores.append(f"Falta completar: {etiqueta}")

    # Reglamento aceptado
    if not inscripcion.acepto_reglamentos:
        errores.append("Debes aceptar los reglamentos y acuerdos.")

    # Documentos obligatorios
    documentos_obligatorios = obtener_documentos_obligatorios(inscripcion)

    for campo, etiqueta in documentos_obligatorios.items():
        archivo = getattr(inscripcion, campo, None)

        if not archivo:
            errores.append(f"Falta documento: {etiqueta}")

    return errores


def construir_observaciones_devolucion(docs_erroneos, comentario):
    docs_erroneos = (docs_erroneos or "").strip()
    comentario = (comentario or "").strip()

    if docs_erroneos and comentario:
        return f"{docs_erroneos}|{comentario}"

    if docs_erroneos:
        return f"{docs_erroneos}|Favor de corregir los documentos marcados."

    if comentario:
        return f"|{comentario}"

    return "|Expediente devuelto para corrección."


def obtener_datos_menor_para_filtro(sol, insc=None):
    """
    Obtiene los datos de identidad del menor de forma segura para
    Psicología, Nutrición y Médico.

    Regla:
    - El nombre del menor NO se captura ni modifica en los filtros.
    - Se toma de Solicitud, que es el expediente base.
    - Se agregan alias para que funcionen los distintos HTML existentes.
    """
    try:
        sol_base = Solicitud.objects.get(pk=sol.pk)
    except Exception:
        sol_base = sol

    nombres = (
        getattr(sol_base, "nombres_menor", None)
        or getattr(sol, "nombres_menor", None)
        or ""
    )

    paterno = (
        getattr(sol_base, "apellido_paterno_menor", None)
        or getattr(sol, "apellido_paterno_menor", None)
        or ""
    )

    materno = (
        getattr(sol_base, "apellido_materno_menor", None)
        or getattr(sol, "apellido_materno_menor", None)
        or ""
    )

    fecha_nacimiento = (
        getattr(sol_base, "fecha_nacimiento_menor", None)
        or getattr(sol, "fecha_nacimiento_menor", None)
    )

    curp = (
        getattr(sol_base, "curp_menor", None)
        or getattr(sol, "curp_menor", None)
        or ""
    )

    nombre_completo = f"{nombres} {paterno} {materno}".strip()

    return {
        "nombre_nino": nombres,
        "paterno_nino": paterno,
        "materno_nino": materno,
        "nombre_menor_completo": nombre_completo,
        "fecha_nacimiento_menor": fecha_nacimiento,
        "curp_menor": curp,

        # Alias extra para HTML anteriores o campos reutilizados.
        "nombres_menor": nombres,
        "apellido_paterno_menor": paterno,
        "apellido_materno_menor": materno,
        "n_menor": nombres,
        "ap_menor": paterno,
        "am_menor": materno,
        "fecha_nacimiento": fecha_nacimiento,
    }


def aplicar_datos_identidad_menor_a_solicitud(sol, datos_menor):
    """
    Restaura los datos de identidad del menor sobre la instancia antes de guardar
    un dictamen, para evitar que Nutrición o Médico los borren si el HTML no los
    envía porque son de solo lectura.
    """
    sol.nombres_menor = datos_menor.get("nombre_nino") or getattr(sol, "nombres_menor", "")
    sol.apellido_paterno_menor = datos_menor.get("paterno_nino") or getattr(sol, "apellido_paterno_menor", "")
    sol.apellido_materno_menor = datos_menor.get("materno_nino") or getattr(sol, "apellido_materno_menor", "")

    if datos_menor.get("fecha_nacimiento_menor"):
        sol.fecha_nacimiento_menor = datos_menor.get("fecha_nacimiento_menor")

    if datos_menor.get("curp_menor"):
        sol.curp_menor = datos_menor.get("curp_menor")

    return sol


# =========================================================
# AUXILIARES SPRINT 3 - FILTROS Y BLOQUEO DE DICTÁMENES
# =========================================================

def normalizar_texto(valor):
    """
    Convierte textos a minúsculas y sin acentos para comparar roles/grupos.
    Ejemplo: Nutrióloga -> nutriologa.
    """
    valor = str(valor or "").strip().lower()
    valor = unicodedata.normalize("NFD", valor)
    valor = "".join(c for c in valor if unicodedata.category(c) != "Mn")
    return valor


def obtener_roles_usuario(user):
    """
    Obtiene grupos y tipo_persona del usuario en formato normalizado.
    """
    roles = []

    if getattr(user, "tipo_persona", None):
        roles.append(normalizar_texto(user.tipo_persona))

    if hasattr(user, "groups"):
        roles.extend([normalizar_texto(g.name) for g in user.groups.all()])

    return roles


def usuario_es_admin(user):
    if not user.is_authenticated:
        return False

    roles = obtener_roles_usuario(user)

    return (
        user.is_superuser
        or "admin" in roles
        or "administrador" in roles
        or "administrador del sistema" in roles
        or normalizar_texto(getattr(user, "tipo_persona", "")) == "admin"
    )



# =========================================================
# AUXILIARES SPRINT 4 - CONFIGURACIÓN DE SEMESTRE
# =========================================================
def usuario_puede_configurar_semestres(user):
    """
    Solo el Administrador del Sistema puede configurar semestres.
    El administrador puede entrar aunque no exista semestre activo,
    porque justamente es quien crea, inicia o cierra semestres.
    """
    return usuario_es_admin_sistema(user)


def usuario_nombre_legible(user):
    if not user:
        return "Sin usuario"

    try:
        nombre = user.get_full_name()
        if nombre:
            return nombre
    except Exception:
        pass

    return getattr(user, "username", "") or getattr(user, "email", "") or str(user)


def obtener_correos_beneficiarios_semestre(semestre):
    """
    Obtiene correos de beneficiarios con inscripción finalizada/asignada al semestre.
    """
    correos = []

    inscripciones = (
        SolicitudInscripcion.objects
        .filter(semestre=semestre)
        .select_related("solicitud_ingreso", "usuario_tutor")
    )

    for inscripcion in inscripciones:
        correo = obtener_correo_tutor(inscripcion)
        if correo and correo not in correos:
            correos.append(correo)

    return correos


def correo_es_institucional_unach(correo):
    """
    Regla de Encuesta B:
    el correo del tutor debe ser institucional @unach.mx.
    """
    correo = (correo or "").strip().lower()
    return bool(correo and correo.endswith("@unach.mx"))


def obtener_inscripciones_encuesta_semestre(semestre):
    """
    Alumnos/tutores que participan en la Encuesta B del semestre.
    Solo se consideran inscripciones finalizadas y asignadas al semestre.
    """
    return (
        SolicitudInscripcion.objects
        .filter(semestre=semestre, estado="FINALIZADA")
        .select_related(
            "solicitud_ingreso",
            "usuario_tutor",
            "sala_semestre_asignada",
            "sala_semestre_asignada__sala",
        )
        .order_by(
            "sala_semestre_asignada__sala__nombre",
            "solicitud_ingreso__apellido_paterno_menor",
            "solicitud_ingreso__nombres_menor",
        )
    )


def asegurar_envios_encuesta_semestre(semestre):
    """
    Crea/actualiza el control individual de envío por alumno/tutor.
    No envía correos; solo prepara los registros para la vista.
    """
    creados = 0
    actualizados = 0

    for inscripcion in obtener_inscripciones_encuesta_semestre(semestre):
        correo = (obtener_correo_tutor(inscripcion) or "").strip().lower()
        tutor = getattr(inscripcion, "usuario_tutor", None)

        envio, created = EnvioEncuestaSatisfaccion.objects.get_or_create(
            semestre=semestre,
            inscripcion=inscripcion,
            defaults={
                "tutor": tutor,
                "correo_destino": correo,
                "correo_copia": semestre.correo_copia_encuesta or "",
            }
        )

        cambios = []

        if envio.tutor_id != getattr(tutor, "id", None):
            envio.tutor = tutor
            cambios.append("tutor")

        if correo and envio.correo_destino != correo:
            envio.correo_destino = correo
            cambios.append("correo_destino")

        if semestre.correo_copia_encuesta and envio.correo_copia != semestre.correo_copia_encuesta:
            envio.correo_copia = semestre.correo_copia_encuesta
            cambios.append("correo_copia")

        if created:
            creados += 1
        elif cambios:
            envio.save(update_fields=cambios + ["updated_at"])
            actualizados += 1

    return creados, actualizados


def obtener_envios_encuesta_semestre(semestre):
    asegurar_envios_encuesta_semestre(semestre)

    return (
        EnvioEncuestaSatisfaccion.objects
        .filter(semestre=semestre)
        .select_related(
            "semestre",
            "inscripcion",
            "inscripcion__solicitud_ingreso",
            "inscripcion__usuario_tutor",
            "inscripcion__sala_semestre_asignada",
            "inscripcion__sala_semestre_asignada__sala",
            "tutor",
        )
        .order_by(
            "inscripcion__sala_semestre_asignada__sala__nombre",
            "inscripcion__solicitud_ingreso__apellido_paterno_menor",
            "inscripcion__solicitud_ingreso__nombres_menor",
        )
    )


def construir_enlace_encuesta_satisfaccion(request, envio):
    """
    Construye el enlace público para que el tutor conteste la Encuesta B.
    """
    try:
        url = reverse("responder_encuesta_satisfaccion", args=[str(envio.token)])
    except Exception:
        # Fallback temporal hasta agregar la ruta en urls.py.
        url = f"/admisiones/encuesta-b/{envio.token}/"

    return request.build_absolute_uri(url)


def enviar_correo_encuesta_individual(request, envio, usuario=None, correo_copia="", es_reenvio=False):
    """
    Envía o reenvía la Encuesta B a un tutor.
    Reglas:
    - Debe existir cuenta de tutor vinculada.
    - El correo debe ser institucional @unach.mx.
    - El mensaje debe ser corto y personalizado.
    """
    if not envio.tutor_id:
        envio.marcar_error("La inscripción no tiene cuenta de tutor vinculada.")
        return False, "La inscripción no tiene cuenta de tutor vinculada."

    if not envio.correo_institucional_valido:
        envio.marcar_bloqueada("El correo del tutor debe ser institucional y terminar en @unach.mx.")
        return False, "Correo no institucional."

    solicitud = envio.inscripcion.solicitud_ingreso
    nombre_tutor = solicitud.nombre_tutor_completo() if hasattr(solicitud, "nombre_tutor_completo") else "Tutor"
    enlace = construir_enlace_encuesta_satisfaccion(request, envio)

    asunto = f"Encuesta de Satisfacción B - {envio.semestre.nombre}"
    cuerpo = f"""Estimado(a) {nombre_tutor}:

Le invitamos a responder la Encuesta de Satisfacción B correspondiente al semestre {envio.semestre.nombre} de la Estancia Infantil UNACH.

Enlace:
{enlace}

Gracias por su participación.

Estancia Infantil UNACH
"""

    try:
        correo = EmailMessage(
            subject=asunto,
            body=cuerpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[envio.correo_destino],
            cc=[correo_copia] if correo_copia else [],
        )
        correo.send(fail_silently=False)

        if es_reenvio:
            envio.marcar_reenviada(usuario=usuario, correo_copia=correo_copia)
        else:
            envio.marcar_enviada(usuario=usuario, correo_copia=correo_copia)

        return True, "Correo enviado correctamente."

    except Exception as e:
        envio.marcar_error(e)
        return False, str(e)


def resumen_envios_encuesta(envios):
    return {
        "total": envios.count(),
        "pendientes": envios.filter(estado=EnvioEncuestaSatisfaccion.EstadoEnvio.PENDIENTE).count(),
        "enviadas": envios.filter(estado=EnvioEncuestaSatisfaccion.EstadoEnvio.ENVIADA).count(),
        "reenviadas": envios.filter(estado=EnvioEncuestaSatisfaccion.EstadoEnvio.REENVIADA).count(),
        "contestadas": envios.filter(estado=EnvioEncuestaSatisfaccion.EstadoEnvio.CONTESTADA).count(),
        "bloqueadas": envios.filter(estado=EnvioEncuestaSatisfaccion.EstadoEnvio.BLOQUEADA).count(),
        "errores": envios.filter(estado=EnvioEncuestaSatisfaccion.EstadoEnvio.ERROR).count(),
    }


def valor_si_no(valor):
    return "Sí" if bool(valor) else "No"


def preguntas_encuesta_satisfaccion(respuesta):
    if not respuesta:
        return []

    return [
        ("¿Recibió información completa de la permanencia diaria?", valor_si_no(respuesta.q1_info_completa)),
        ("¿Considera que su hija y/o hijo se encuentra seguro durante su permanencia?", valor_si_no(respuesta.q2_seguro)),
        ("¿La orientación sobre alimentación fue de utilidad?", valor_si_no(respuesta.q3_orientacion_nutricion)),
        ("¿La orientación médica fue de utilidad?", valor_si_no(respuesta.q4_orientacion_medica)),
        ("¿La orientación pedagógica fue de utilidad?", valor_si_no(respuesta.q5_orientacion_pedagogica)),
        ("¿La orientación psicológica fue de utilidad?", valor_si_no(respuesta.q6_orientacion_psicologica)),
        ("¿El servicio apoyó la continuidad de sus estudios?", valor_si_no(respuesta.q7_apoyo_estudios)),
    ]


def valor_booleano_encuesta(post_data, campo):
    valor = str(post_data.get(campo, "")).strip().lower()
    return valor in ["1", "true", "on", "si", "sí", "yes"]


def construir_resumen_semestre(semestre):
    """
    Resumen para panel/detalle del semestre.

    Regla:
    - dias_operativos cuenta solo días hábiles reales.
    - Sábados, domingos, festivos y suspensiones se reportan como inhábiles
      y no deben bloquear apertura, cierre diario ni cierre de semestre.
    """
    dias_qs = semestre.dias_operativos.all()
    dias_habiles_qs = dias_qs.filter(es_habil=True)
    dias_inhabiles_qs = dias_qs.filter(es_habil=False)

    return {
        "total_salas": semestre.salas_activas.count(),
        "salas_activas": semestre.salas_activas.filter(activa=True).count(),
        "total_maestras": AsignacionMaestra.objects.filter(
            sala_semestre__semestre=semestre,
            activo=True,
        ).values("maestra_id").distinct().count(),
        "total_alumnos": SolicitudInscripcion.objects.filter(semestre=semestre).count(),
        "dias_calendario": dias_qs.count(),
        "dias_operativos": dias_habiles_qs.count(),
        "dias_inhabiles": dias_inhabiles_qs.count(),
        "dias_abiertos": dias_habiles_qs.filter(
            estado=DiaOperativoSemestre.EstadoDia.ABIERTO,
        ).count(),
        "dias_cerrados": dias_habiles_qs.filter(
            estado=DiaOperativoSemestre.EstadoDia.CERRADO,
        ).count(),
        "incidencias_abiertas": semestre.incidencias.filter(
            estado=Incidencia.EstadoIncidencia.ABIERTA,
        ).count(),
    }


def asegurar_sede_inicial():
    """
    Ya no crea sedes automáticamente.

    Regla correcta:
    - Si la base está limpia, no debe existir ninguna sede.
    - El Administrador del Sistema debe crear la sede manualmente desde
      Gestión de Semestres -> Crear sede.
    - Esta función se conserva solo por compatibilidad con llamadas existentes.
    """
    return None

def obtener_origen_sprint4(request):
    """
    Conserva el origen de navegación del Sprint 4.
    origen=ti significa que el usuario entró desde /gobierno-ti/.
    """
    return (request.POST.get("origen") or request.GET.get("origen") or "").strip()


def url_con_origen(url, request):
    origen = obtener_origen_sprint4(request)
    if origen:
        separador = "&" if "?" in url else "?"
        return f"{url}{separador}origen={origen}"
    return url


def redirect_con_origen(request, viewname, *args, **kwargs):
    url = reverse(viewname, args=args, kwargs=kwargs)
    return redirect(url_con_origen(url, request))




def bloquear_si_no_hay_semestre_activo(request, destino="/", mensaje=None):
    """
    Bloquea acciones de escritura/operación si no hay semestre ACTIVO.
    No cierra sesión; solo avisa y redirige.

    La regla base vive en admisiones/services.py.
    Este helper se queda aquí porque usa request, messages y redirect.
    """
    if hay_semestre_activo_operativo():
        return None

    contexto = contexto_semestre_operativo()

    messages.warning(
        request,
        mensaje
        or contexto.get("aviso_semestre_operativo")
        or (
            "No hay semestre activo/iniciado. "
            "Solo puedes consultar información histórica; no se permiten capturas, modificaciones ni operaciones."
        ),
    )

    if isinstance(destino, str) and destino.startswith("/"):
        return redirect(destino)

    return redirect(destino)


def bloquear_si_semestre_no_editable(request, semestre, destino_view="detalle_semestre"):
    """
    Evita modificar semestres cerrados.
    Un semestre cerrado queda en modo solo lectura/histórico.

    La regla base vive en admisiones/services.py.
    Este helper se queda aquí porque usa request, messages y redirect.
    """
    if semestre and not semestre_permite_edicion_admin(semestre):
        messages.warning(
            request,
            "Este semestre está cerrado. Solo se permite consulta; no puedes agregar, modificar o eliminar información."
        )
        return redirect_con_origen(request, destino_view, semestre_id=semestre.id)

    return None





# =========================================================
# AUXILIARES SPRINT 4 - SEGUNDA PARTE
# OPERACIÓN DIARIA DE MAESTRAS
# =========================================================

def usuario_tiene_asignacion_maestra_activa(user, semestre=None):
    """
    Una maestra puede operar solo si está asignada a una sala activa
    del semestre activo.
    """
    if not user or not user.is_authenticated:
        return False

    if semestre is None:
        semestre = obtener_semestre_activo_operativo()

    if not semestre:
        return False

    return AsignacionMaestra.objects.filter(
        maestra=user,
        activo=True,
        sala_semestre__semestre=semestre,
        sala_semestre__activa=True,
    ).exists()


def obtener_asignaciones_maestra_operativas(user, semestre=None):
    """
    Devuelve las asignaciones activas de la maestra en el semestre activo.
    """
    if semestre is None:
        semestre = obtener_semestre_activo_operativo()

    if not semestre:
        return AsignacionMaestra.objects.none()

    return (
        AsignacionMaestra.objects
        .filter(
            maestra=user,
            activo=True,
            sala_semestre__semestre=semestre,
            sala_semestre__activa=True,
        )
        .select_related(
            "sala_semestre",
            "sala_semestre__semestre",
            "sala_semestre__sala",
            "sala_semestre__sala__sede",
        )
        .order_by("sala_semestre__sala__nombre")
    )


def obtener_salas_maestra_operativas(user, semestre=None):
    asignaciones = obtener_asignaciones_maestra_operativas(user, semestre=semestre)
    ids = asignaciones.values_list("sala_semestre_id", flat=True)

    return (
        SalaSemestre.objects
        .filter(id__in=ids)
        .select_related("semestre", "sala", "sala__sede")
        .order_by("sala__nombre")
    )


def obtener_sede_maestra_operativa(user, semestre=None):
    """
    La apertura del día es por sede.
    Se toma la sede del semestre/sala asignada a la maestra.
    """
    salas = obtener_salas_maestra_operativas(user, semestre=semestre)

    sala_semestre = salas.first()
    if sala_semestre and sala_semestre.semestre and sala_semestre.semestre.sede_configurada:
        return sala_semestre.semestre.sede_configurada

    if sala_semestre and sala_semestre.sala:
        return sala_semestre.sala.sede

    return None


def obtener_dia_operativo_actual_maestra(user, semestre=None):
    """
    Obtiene el día operativo de hoy para el semestre activo.
    Si el calendario no existe, intenta generarlo desde el semestre.
    """
    if semestre is None:
        semestre = obtener_semestre_activo_operativo()

    if not semestre:
        return None

    hoy = timezone.localdate()

    if semestre.fecha_inicio and semestre.fecha_fin:
        if hoy < semestre.fecha_inicio or hoy > semestre.fecha_fin:
            return None

    dia = DiaOperativoSemestre.objects.filter(
        semestre=semestre,
        fecha=hoy,
    ).first()

    if not dia:
        semestre.generar_dias_operativos()
        dia = DiaOperativoSemestre.objects.filter(
            semestre=semestre,
            fecha=hoy,
        ).first()

    return dia


def dia_operativo_es_fin_de_semana(dia):
    """
    Regla de operación:
    sábado y domingo son días inhábiles automáticos para la estancia.
    Los usuarios pueden iniciar sesión, pero las maestras no pueden abrir día,
    registrar entrada, salida, bitácoras ni operación diaria de menores.
    """
    return bool(dia and getattr(dia, "fecha", None) and dia.fecha.weekday() in (5, 6))


def dia_operativo_es_laborable(dia):
    """
    True solo cuando el día permite operación diaria real.
    """
    return bool(
        dia
        and getattr(dia, "es_habil", False)
        and not dia_operativo_es_fin_de_semana(dia)
    )


def mensaje_dia_no_operativo(dia):
    """
    Mensaje único para vistas de operación diaria cuando el día no se trabaja.
    """
    if not dia:
        return "No existe día operativo para la fecha actual."

    if dia_operativo_es_fin_de_semana(dia):
        return (
            "Hoy es sábado o domingo. La estancia no opera estos días; "
            "puedes iniciar sesión para consultar información, pero no se permite abrir día, "
            "registrar entrada, salida ni bitácoras."
        )

    if not getattr(dia, "es_habil", False):
        return (
            "Este día está marcado como inhábil por festivo, suspensión o consejo técnico. "
            "No se permite operación diaria de menores."
        )

    return ""


def validar_maestra_puede_operar_dia(request, dia):
    """
    Valida:
    - semestre activo
    - día laborable real
    - sábado y domingo bloqueados para operación diaria
    - maestra asignada a una sala del semestre
    - semestre/día no cerrados
    """
    if not dia:
        messages.error(request, "No existe día operativo para la fecha actual.")
        return False

    if not hay_semestre_activo_operativo():
        messages.warning(
            request,
            "No hay semestre activo/iniciado. La operación diaria queda en modo solo consulta."
        )
        return False

    if dia.semestre.estado != Semestre.EstadoSemestre.ACTIVO:
        messages.warning(request, "El semestre no está activo. No se permite operar el día.")
        return False

    mensaje_no_operativo = mensaje_dia_no_operativo(dia)
    if mensaje_no_operativo:
        messages.warning(request, mensaje_no_operativo)
        return False

    if dia.estado == DiaOperativoSemestre.EstadoDia.CERRADO:
        messages.warning(request, "Este día ya está cerrado. Solo puede consultarse.")
        return False

    if not usuario_tiene_asignacion_maestra_activa(request.user, semestre=dia.semestre):
        messages.error(request, "Solo una maestra asignada a una sala del semestre puede operar este día.")
        return False

    return True


def obtener_registro_diario_para_maestra(request, registro_id):
    """
    Obtiene un registro diario solo si pertenece a una sala asignada a la maestra.
    """
    semestre = obtener_semestre_activo_operativo()
    salas = obtener_salas_maestra_operativas(request.user, semestre=semestre)

    return get_object_or_404(
        RegistroDiarioAlumno.objects
        .select_related(
            "dia_operativo",
            "dia_operativo__semestre",
            "alumno",
            "alumno__solicitud_ingreso",
            "sala_semestre",
            "sala_semestre__sala",
        ),
        pk=registro_id,
        sala_semestre__in=salas,
    )


def asegurar_registros_alumnos_dia(dia, user):
    """
    Crea el registro diario de cada alumno asignado a las salas de la maestra.
    No crea duplicados.

    Regla:
    - No crea registros en sábado, domingo, festivo, suspensión o día cerrado.
    """
    if (
        not dia
        or not dia_operativo_es_laborable(dia)
        or dia.estado != DiaOperativoSemestre.EstadoDia.ABIERTO
    ):
        return 0

    salas = obtener_salas_maestra_operativas(user, semestre=dia.semestre)

    inscripciones = (
        SolicitudInscripcion.objects
        .filter(
            estado="FINALIZADA",
            semestre=dia.semestre,
            sala_semestre_asignada__in=salas,
        )
        .select_related("solicitud_ingreso", "sala_semestre_asignada", "sala_semestre_asignada__sala")
        .order_by("sala_semestre_asignada__sala__nombre", "solicitud_ingreso__apellido_paterno_menor")
    )

    creados = 0

    for inscripcion in inscripciones:
        _, created = RegistroDiarioAlumno.objects.get_or_create(
            dia_operativo=dia,
            alumno=inscripcion,
            defaults={
                "sala_semestre": inscripcion.sala_semestre_asignada,
                "creado_por": user,
            },
        )

        if created:
            creados += 1

    return creados


def obtener_registros_dia_maestra(dia, user):
    if not dia or not dia_operativo_es_laborable(dia):
        return RegistroDiarioAlumno.objects.none()

    salas = obtener_salas_maestra_operativas(user, semestre=dia.semestre if dia else None)

    return (
        RegistroDiarioAlumno.objects
        .filter(dia_operativo=dia, sala_semestre__in=salas)
        .select_related(
            "alumno",
            "alumno__solicitud_ingreso",
            "sala_semestre",
            "sala_semestre__sala",
        )
        .order_by("sala_semestre__sala__nombre", "alumno__solicitud_ingreso__apellido_paterno_menor")
    )


def registro_diario_es_editable(registro):
    return bool(
        registro
        and registro.dia_operativo
        and dia_operativo_es_laborable(registro.dia_operativo)
        and registro.dia_operativo.estado == DiaOperativoSemestre.EstadoDia.ABIERTO
        and registro.dia_operativo.semestre.estado == Semestre.EstadoSemestre.ACTIVO
    )



def usuario_es_directora(user):
    if not user.is_authenticated:
        return False

    roles = obtener_roles_usuario(user)
    return "directora" in roles or normalizar_texto(getattr(user, "tipo_persona", "")) == "directora"


def usuario_es_trabajadora_social(user):
    if not user.is_authenticated:
        return False

    roles = obtener_roles_usuario(user)

    return (
        "trabajadora social" in roles
        or "trabajador social" in roles
        or "trabajo social" in roles
        or normalizar_texto(getattr(user, "tipo_persona", "")) in ["trabajadora_social", "trabajo_social"]
    )


def usuario_puede_reporte_final_ts(user):
    """
    Puede registrar el reporte final de ingreso:
    - Trabajadora Social
    - Administrador del sistema
    """
    return usuario_es_admin(user) or usuario_es_trabajadora_social(user)


def usuario_puede_ver_reporte_final_ts(user):
    """
    Puede ver la bandeja de reporte final:
    - Trabajadora Social
    - Administrador
    - Directora
    """
    return usuario_puede_reporte_final_ts(user) or usuario_es_directora(user)


def usuario_puede_gestionar_pagos(user):
    """
    Puede gestionar comprobantes de pago:
    - Trabajadora Social
    - Administrador del sistema
    """
    return usuario_es_admin(user) or usuario_es_trabajadora_social(user)



def usuario_puede_gestionar_codigo_responsable(user):
    """
    Puede generar/resetear el código de seguridad:
    - Trabajadora Social
    - Administrador del sistema
    """
    return usuario_puede_gestionar_pagos(user)


# =========================================================
# AUXILIARES SPRINT 5 - ÉPICA 3: INCIDENCIAS
# =========================================================

TIPOS_INCIDENCIA_VALIDOS = {
    "PEDAGOGICA": Incidencia.TipoIncidencia.PEDAGOGICA,
    "PEDAGÓGICA": Incidencia.TipoIncidencia.PEDAGOGICA,
    "PEDAGOGICA": Incidencia.TipoIncidencia.PEDAGOGICA,
    "PEDAGOGICA": Incidencia.TipoIncidencia.PEDAGOGICA,
    "NUTRICIONAL": Incidencia.TipoIncidencia.NUTRICIONAL,
    "NUTRICION": Incidencia.TipoIncidencia.NUTRICIONAL,
    "NUTRICIÓN": Incidencia.TipoIncidencia.NUTRICIONAL,
    "MEDICA": Incidencia.TipoIncidencia.MEDICA,
    "MÉDICA": Incidencia.TipoIncidencia.MEDICA,
    "MEDICO": Incidencia.TipoIncidencia.MEDICA,
    "MÉDICO": Incidencia.TipoIncidencia.MEDICA,
    "PSICOLOGICA": Incidencia.TipoIncidencia.PSICOLOGICA,
    "PSICOLÓGICA": Incidencia.TipoIncidencia.PSICOLOGICA,
    "PSICOLOGIA": Incidencia.TipoIncidencia.PSICOLOGICA,
    "PSICOLOGÍA": Incidencia.TipoIncidencia.PSICOLOGICA,
}


def normalizar_tipo_incidencia_param(valor):
    valor = normalizar_texto(valor or "").upper()
    valor = valor.replace(" ", "_").replace("-", "_")
    valor = valor.replace("Ó", "O").replace("É", "E").replace("Í", "I").replace("Á", "A")
    valor = valor.replace("PSICOLOGIA", "PSICOLOGICA")
    valor = valor.replace("NUTRICION", "NUTRICIONAL")
    valor = valor.replace("MEDICO", "MEDICA")

    return TIPOS_INCIDENCIA_VALIDOS.get(valor)


def usuario_es_coordinadora_sala(user):
    if not user or not user.is_authenticated:
        return False

    roles = obtener_roles_usuario(user)
    tipo_persona = normalizar_texto(getattr(user, "tipo_persona", ""))

    return (
        any("coordinador" in rol and "sala" in rol for rol in roles)
        or any("coordinadora" in rol and "sala" in rol for rol in roles)
        or "coordinacion de sala" in roles
        or "coordinacion de salas" in roles
        or tipo_persona in ["coordinadora_sala", "coordinador_sala", "coordinacion_sala"]
    )


def usuario_es_area_nutricion(user):
    if not user or not user.is_authenticated:
        return False

    roles = obtener_roles_usuario(user)
    return any("nutri" in rol for rol in roles)


def usuario_es_area_medica(user):
    if not user or not user.is_authenticated:
        return False

    roles = obtener_roles_usuario(user)
    return any("medic" in rol for rol in roles)


def usuario_es_area_psicologia(user):
    if not user or not user.is_authenticated:
        return False

    roles = obtener_roles_usuario(user)
    return any("psicolog" in rol for rol in roles)


def tipos_incidencia_usuario(user, para_crear=False):
    """
    Define qué tipo de incidencias puede operar el usuario.

    Para crear:
    - Coordinadora de Sala -> Pedagógica
    - Nutrióloga -> Nutricional
    - Médica -> Médica
    - Psicóloga -> Psicológica

    Para consultar:
    - Directora y Administrador ven todas.
    """
    tipos = []

    if usuario_es_coordinadora_sala(user):
        tipos.append(Incidencia.TipoIncidencia.PEDAGOGICA)

    if usuario_es_area_nutricion(user):
        tipos.append(Incidencia.TipoIncidencia.NUTRICIONAL)

    if usuario_es_area_medica(user):
        tipos.append(Incidencia.TipoIncidencia.MEDICA)

    if usuario_es_area_psicologia(user):
        tipos.append(Incidencia.TipoIncidencia.PSICOLOGICA)

    if not para_crear and (usuario_es_admin(user) or usuario_es_directora(user)):
        return [
            Incidencia.TipoIncidencia.PEDAGOGICA,
            Incidencia.TipoIncidencia.NUTRICIONAL,
            Incidencia.TipoIncidencia.MEDICA,
            Incidencia.TipoIncidencia.PSICOLOGICA,
        ]

    return list(dict.fromkeys(tipos))


def usuario_puede_ver_incidencias(user):
    return bool(tipos_incidencia_usuario(user, para_crear=False))


def usuario_puede_crear_tipo_incidencia(user, tipo):
    return tipo in tipos_incidencia_usuario(user, para_crear=True)


def usuario_es_area_operativa_incidencia_unica(user):
    """
    True cuando el usuario pertenece a un área operativa con un solo tipo de
    incidencia permitido. Sirve para fijar el tipo en paneles y formularios.

    Admin y Directora no entran aquí porque su flujo es de consulta/administración.
    """
    if usuario_es_admin(user) or usuario_es_directora(user):
        return False

    return len(tipos_incidencia_usuario(user, para_crear=True)) == 1


def tipo_incidencia_unico_usuario(user):
    tipos = tipos_incidencia_usuario(user, para_crear=True)

    if len(tipos) == 1:
        return tipos[0]

    return None


def url_panel_incidencias_por_tipo(tipo=None):
    url = reverse("panel_incidencias")

    if tipo:
        return f"{url}?tipo={tipo}"

    return url


def usuario_puede_ver_incidencia(user, incidencia):
    if usuario_es_admin(user) or usuario_es_directora(user):
        return True

    return incidencia.tipo in tipos_incidencia_usuario(user, para_crear=False)


def usuario_puede_cerrar_incidencia_sprint5(user, incidencia):
    """
    Regla del Sprint 5:
    - Quien creó la incidencia puede cerrarla.
    - Administrador del sistema puede cerrarla.
    - Directora consulta, pero no cierra.
    """
    if not user or not user.is_authenticated:
        return False

    if incidencia.registrada_por_id == user.id:
        return True

    return usuario_es_admin(user) or usuario_es_admin_sistema(user)


def validar_archivo_incidencia_general(archivo):
    if not archivo:
        return False, "No se recibió archivo."

    extension = os.path.splitext(archivo.name)[1].lower()
    extensiones_permitidas = [".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx"]

    if extension not in extensiones_permitidas:
        return False, "Formato no permitido. Usa PDF, imagen JPG/PNG o documento Word."

    if archivo.size > 10 * 1024 * 1024:
        return False, "El archivo supera el tamaño máximo permitido de 10 MB."

    return True, "Archivo válido."


def guardar_archivos_incidencia(incidencia, archivos, usuario):
    guardados = 0
    errores = []

    for archivo in archivos:
        valido, mensaje = validar_archivo_incidencia_general(archivo)

        if not valido:
            errores.append(f"{archivo.name}: {mensaje}")
            continue

        IncidenciaArchivo.objects.create(
            incidencia=incidencia,
            archivo=archivo,
            nombre_original=archivo.name,
            subido_por=usuario,
        )
        guardados += 1

    return guardados, errores


def guardar_archivos_seguimiento_incidencia(seguimiento, archivos, usuario):
    guardados = 0
    errores = []

    for archivo in archivos:
        valido, mensaje = validar_archivo_incidencia_general(archivo)

        if not valido:
            errores.append(f"{archivo.name}: {mensaje}")
            continue

        SeguimientoIncidenciaArchivo.objects.create(
            seguimiento=seguimiento,
            archivo=archivo,
            nombre_original=archivo.name,
            subido_por=usuario,
        )
        guardados += 1

    return guardados, errores


def obtener_incidencias_visibles_para_usuario(user):
    incidencias = (
        Incidencia.objects
        .select_related(
            "alumno",
            "alumno__solicitud_ingreso",
            "semestre",
            "dia_operativo",
            "registro_diario",
            "sala_semestre",
            "sala_semestre__sala",
            "registrada_por",
            "cerrada_por",
        )
        .prefetch_related("seguimientos", "archivos")
    )

    if usuario_es_admin(user) or usuario_es_directora(user):
        return incidencias

    tipos = tipos_incidencia_usuario(user, para_crear=False)

    if not tipos:
        return Incidencia.objects.none()

    return incidencias.filter(tipo__in=tipos)


def pago_validado_inscripcion(inscripcion):
    """
    Compatibilidad para validar pago según los campos existentes del proyecto.
    Algunas versiones usan estado_pago='VALIDADO', otras pago_validado o pago_validado_en.
    """
    if not inscripcion:
        return False

    if getattr(inscripcion, "pago_validado", False):
        return True

    if getattr(inscripcion, "estado_pago", "") == "VALIDADO":
        return True

    if getattr(inscripcion, "pago_validado_en", None):
        return True

    return False


def preparar_inscripcion_para_form_codigo(inscripcion):
    """
    El formulario GenerarCodigoResponsableForm espera alumno.pago_validado.
    Si el modelo no tiene ese campo, se agrega temporalmente en memoria.
    """
    try:
        setattr(inscripcion, "pago_validado", pago_validado_inscripcion(inscripcion))
    except Exception:
        pass

    return inscripcion


def sincronizar_codigos_responsables_inscripcion(inscripcion):
    """
    Sincroniza los responsables autorizados del expediente con la tabla de códigos.

    Regla actual:
    - El código ya no es único por alumno.
    - Cada tutor o familiar autorizado tiene su propio código.
    - Se crean/actualizan responsables desde los datos del expediente sin borrar códigos existentes.
    """
    if not inscripcion:
        return []

    try:
        return CodigoResponsableAutorizado.sincronizar_desde_inscripcion(inscripcion)
    except Exception:
        return list(
            CodigoResponsableAutorizado.objects
            .filter(inscripcion=inscripcion, activo=True)
            .order_by("tipo_responsable", "nombre_completo")
        )


def obtener_responsables_codigo_inscripcion(inscripcion, solo_activos=True):
    """
    Devuelve los responsables autorizados de un alumno/inscripción.
    """
    sincronizar_codigos_responsables_inscripcion(inscripcion)

    qs = CodigoResponsableAutorizado.objects.filter(inscripcion=inscripcion)

    if solo_activos:
        qs = qs.filter(activo=True)

    return qs.order_by("tipo_responsable", "nombre_completo")


def preparar_resumen_codigos_inscripcion(inscripcion):
    """
    Agrega atributos temporales para que el template pueda mostrar el avance
    de códigos por tutor/familiar autorizado.
    """
    responsables = list(obtener_responsables_codigo_inscripcion(inscripcion))

    inscripcion.responsables_codigo = responsables
    inscripcion.total_responsables_codigo = len(responsables)
    inscripcion.total_codigos_generados = sum(1 for r in responsables if r.tiene_codigo)
    inscripcion.total_codigos_entregados = sum(1 for r in responsables if r.codigo_entregado)
    inscripcion.tiene_codigo_responsable_personal = inscripcion.total_codigos_generados > 0

    return inscripcion


def inscripcion_tiene_codigo_responsable(inscripcion):
    """
    Compatibilidad: ahora revisa si existe al menos un responsable autorizado
    con código generado. Si no existe el nuevo modelo, conserva la validación anterior.
    """
    try:
        return CodigoResponsableAutorizado.objects.filter(
            inscripcion=inscripcion,
            codigo_hash__gt="",
        ).exists()
    except Exception:
        return bool(getattr(inscripcion, "codigo_responsable_hash", ""))


def obtener_responsable_codigo_desde_request(request, inscripcion):
    """
    Obtiene el responsable seleccionado para generar/resetear/entregar código.
    Acepta varios nombres de campo para ser compatible con los HTML anteriores
    y los nuevos diseños.
    """
    responsable_id = (
        request.POST.get("responsable_codigo_id")
        or request.POST.get("responsable_autorizado_id")
        or request.POST.get("codigo_responsable_id")
        or request.POST.get("responsable_id")
        or request.GET.get("responsable_codigo_id")
        or request.GET.get("responsable_autorizado_id")
        or request.GET.get("codigo_responsable_id")
        or request.GET.get("responsable_id")
    )

    responsables = obtener_responsables_codigo_inscripcion(inscripcion)

    if responsable_id:
        return get_object_or_404(responsables, pk=responsable_id)

    # Si solo hay una persona autorizada, se puede usar automáticamente.
    if responsables.count() == 1:
        return responsables.first()

    return None


def guardar_codigo_responsable_en_inscripcion(
    inscripcion,
    codigo,
    usuario,
    motivo="",
    es_reset=False,
    responsable_autorizado=None,
):
    """
    Guarda el código sin texto plano.

    Nuevo flujo:
    - Si se recibe responsable_autorizado, el código se guarda en
      CodigoResponsableAutorizado.

    Compatibilidad:
    - Si no se recibe responsable, conserva el guardado antiguo por alumno
      para no romper pantallas que todavía no fueron actualizadas.
    """
    motivo = (motivo or "").strip()

    if responsable_autorizado:
        try:
            responsable_autorizado.set_codigo(
                codigo,
                usuario=usuario,
                motivo_reset=motivo if es_reset else "",
                observaciones=motivo if not es_reset else "",
            )
            responsable_autorizado.save()
            return True, "Código guardado correctamente para el responsable autorizado."
        except Exception as exc:
            return False, str(exc)

    if not hasattr(inscripcion, "set_codigo_responsable"):
        return False, (
            "Falta seleccionar el tutor o familiar autorizado para generar el código."
        )

    inscripcion.set_codigo_responsable(codigo)

    ahora = timezone.now()

    campos_a_actualizar = {
        "codigo_responsable_generado_por": usuario,
        "codigo_responsable_generado_en": ahora,
        "codigo_responsable_observaciones": motivo,
    }

    if es_reset:
        campos_a_actualizar.update({
            "codigo_responsable_reset_por": usuario,
            "codigo_responsable_reset_en": ahora,
            "codigo_responsable_reset_motivo": motivo,
        })

    if hasattr(inscripcion, "codigo_responsable_entregado"):
        campos_a_actualizar["codigo_responsable_entregado"] = False

    for campo, valor in campos_a_actualizar.items():
        if hasattr(inscripcion, campo):
            setattr(inscripcion, campo, valor)

    inscripcion.save()

    return True, "Código guardado correctamente."


def registrar_entrega_codigo_en_inscripcion(inscripcion, form, usuario, responsable_autorizado=None):
    """
    Registra evidencia de entrega de credencial/código.

    Nuevo flujo:
    - Marca entregado el código de una persona autorizada específica.

    Compatibilidad:
    - Si no se recibe responsable, usa los campos antiguos de SolicitudInscripcion.
    """
    observaciones = ""
    if hasattr(form, "cleaned_data"):
        observaciones = form.cleaned_data.get("observaciones", "") or form.cleaned_data.get("motivo", "") or ""

    if responsable_autorizado:
        responsable_autorizado.marcar_entregado(
            usuario=usuario,
            observaciones=observaciones,
            credencial=True,
        )
        return True

    ahora = timezone.now()

    campos_a_actualizar = {
        "codigo_responsable_entregado": True,
        "codigo_responsable_entregado_por": usuario,
        "codigo_responsable_entregado_en": ahora,
        "codigo_responsable_entregado_a": form.cleaned_data.get("responsable_recibe", ""),
        "codigo_responsable_entregado_parentesco": form.cleaned_data.get("parentesco", ""),
        "codigo_responsable_entrega_observaciones": form.cleaned_data.get("observaciones", ""),
        "credencial_entregada": True,
        "credencial_entregada_por": usuario,
        "credencial_entregada_en": ahora,
    }

    cambio = False

    for campo, valor in campos_a_actualizar.items():
        if hasattr(inscripcion, campo):
            setattr(inscripcion, campo, valor)
            cambio = True

    if cambio:
        inscripcion.save()

    return cambio


def _post_bool(post_data, campo):
    valor = str(post_data.get(campo, "")).strip().lower()
    return valor in ["1", "true", "on", "si", "sí", "yes"]


def _post_valor(post_data, *campos):
    for campo in campos:
        valor = post_data.get(campo)
        if valor not in [None, ""]:
            return valor
    return ""


def obtener_responsable_operacion_desde_post(registro, post_data, prefijo="entrada"):
    """
    Valida el código capturado por la maestra contra la persona autorizada.

    El HTML nuevo debe enviar responsable_codigo_id y codigo_responsable.
    Se aceptan alias para no romper nombres de campos anteriores.
    """
    errores = []

    inscripcion = registro.alumno
    responsables = obtener_responsables_codigo_inscripcion(inscripcion)

    responsable_id = _post_valor(
        post_data,
        "responsable_codigo_id",
        "responsable_autorizado_id",
        "codigo_responsable_id",
        f"responsable_{prefijo}_codigo_id",
        f"responsable_{prefijo}_autorizado_id",
        "responsable_id",
    )

    codigo = str(_post_valor(
        post_data,
        "codigo_responsable",
        "codigo_seguridad",
        f"codigo_{prefijo}",
        f"codigo_responsable_{prefijo}",
    ) or "").strip()

    responsable = None

    if responsable_id:
        responsable = responsables.filter(pk=responsable_id).first()
        if not responsable:
            errores.append("El responsable seleccionado no pertenece a este alumno o no está activo.")
    elif responsables.count() == 1:
        responsable = responsables.first()
    else:
        errores.append("Selecciona el tutor o familiar autorizado que entrega/recoge al menor.")

    if not codigo:
        errores.append("Captura el código de seguridad de 4 dígitos del responsable.")
    elif not re.fullmatch(r"\d{4}", codigo):
        errores.append("El código de seguridad debe tener exactamente 4 dígitos.")

    if responsable:
        if not responsable.tiene_codigo:
            errores.append("Este responsable todavía no tiene código generado por Trabajo Social.")
        elif not responsable.codigo_entregado:
            errores.append("El código de este responsable aún no está marcado como entregado.")
        elif codigo and not responsable.validar_codigo(codigo):
            errores.append("El código de seguridad no coincide con el responsable seleccionado.")

    return responsable, errores


def errores_form_sin_codigo(form):
    """
    Permite que la vista use la validación nueva por responsable aunque el
    formulario anterior todavía tenga validación del código por alumno.
    """
    errores = dict(getattr(form, "errors", {}) or {})

    for campo in [
        "codigo_responsable",
        "codigo_seguridad",
        "codigo_entrada",
        "codigo_salida",
        "responsable_codigo_id",
        "responsable_autorizado_id",
        "codigo_responsable_id",
        "responsable_id",
    ]:
        errores.pop(campo, None)

    return errores


def datos_entrada_desde_form_o_post(form, post_data, responsable_autorizado=None):
    cleaned = getattr(form, "cleaned_data", {}) or {}

    return {
        "responsable_nombre": (
            cleaned.get("responsable_entrada_nombre")
            or _post_valor(post_data, "responsable_entrada_nombre")
            or getattr(responsable_autorizado, "nombre_completo", "")
        ),
        "responsable_parentesco": (
            cleaned.get("responsable_entrada_parentesco")
            or _post_valor(post_data, "responsable_entrada_parentesco")
            or getattr(responsable_autorizado, "parentesco", "")
        ),
        "responsable_telefono": (
            cleaned.get("responsable_entrada_telefono")
            or _post_valor(post_data, "responsable_entrada_telefono")
            or getattr(responsable_autorizado, "telefono", "")
        ),
        "credencial_validada": (
            cleaned.get("credencial_entrada_validada")
            if "credencial_entrada_validada" in cleaned
            else _post_bool(post_data, "credencial_entrada_validada")
        ),
        "temperatura": cleaned.get("temperatura_entrada") or _post_valor(post_data, "temperatura_entrada") or None,
    }


def datos_salida_desde_form_o_post(form, post_data, responsable_autorizado=None):
    cleaned = getattr(form, "cleaned_data", {}) or {}

    return {
        "responsable_nombre": (
            cleaned.get("responsable_salida_nombre")
            or _post_valor(post_data, "responsable_salida_nombre")
            or getattr(responsable_autorizado, "nombre_completo", "")
        ),
        "responsable_parentesco": (
            cleaned.get("responsable_salida_parentesco")
            or _post_valor(post_data, "responsable_salida_parentesco")
            or getattr(responsable_autorizado, "parentesco", "")
        ),
        "responsable_telefono": (
            cleaned.get("responsable_salida_telefono")
            or _post_valor(post_data, "responsable_salida_telefono")
            or getattr(responsable_autorizado, "telefono", "")
        ),
        "credencial_validada": (
            cleaned.get("credencial_salida_validada")
            if "credencial_salida_validada" in cleaned
            else _post_bool(post_data, "credencial_salida_validada")
        ),
        "tipo_salida": cleaned.get("tipo_salida") or _post_valor(post_data, "tipo_salida"),
        "motivo_salida": cleaned.get("motivo_salida") or _post_valor(post_data, "motivo_salida"),
        "observacion_salida": cleaned.get("observacion_salida") or _post_valor(post_data, "observacion_salida"),
    }


def validar_archivo_comprobante_pago(archivo):
    """
    Valida comprobante de pago subido por el beneficiario.
    Permitidos: PDF, JPG, JPEG, PNG.
    Tamaño máximo: 5 MB.
    """
    if not archivo:
        return False, "Debes seleccionar un archivo de comprobante de pago."

    extension = os.path.splitext(archivo.name)[1].lower()
    extensiones_permitidas = [".pdf", ".jpg", ".jpeg", ".png"]

    if extension not in extensiones_permitidas:
        return False, "Formato no permitido. Sube un archivo PDF, JPG o PNG."

    if archivo.size > 5 * 1024 * 1024:
        return False, "El comprobante supera el tamaño máximo permitido de 5 MB."

    return True, "Archivo válido."


def nombre_archivo_comprobante_pago(inscripcion, archivo):
    """
    Construye un nombre controlado para el comprobante de pago.

    Formato requerido:
    comprobante_de_pago_MATRICULA.pdf
    comprobante_de_pago_MATRICULA.jpg
    comprobante_de_pago_MATRICULA.png
    """
    matricula = getattr(inscripcion.solicitud_ingreso, "matricula", "") or "SIN_MATRICULA"
    matricula = str(matricula).strip().replace(" ", "_").replace("/", "_").replace("\\", "_")
    extension = os.path.splitext(archivo.name)[1].lower()
    return f"comprobante_de_pago_{matricula}{extension}"




def preparar_archivo_comprobante_presencial(request, inscripcion):
    """
    Compatibilidad para el modal de pago presencial.

    Acepta el archivo con nombre nuevo comprobante_pago o con el nombre
    anterior doc_tutor_pago. Además arma un nombre controlado para guardarlo
    en el FileField doc_tutor_pago.
    """
    post_data = request.POST.copy()
    files_data = request.FILES.copy()

    observaciones = (
        post_data.get("observaciones")
        or post_data.get("pago_observaciones")
        or post_data.get("motivo_rechazo")
        or ""
    ).strip()

    if observaciones and not post_data.get("observaciones"):
        post_data["observaciones"] = observaciones

    # El botón Presencial del modal funciona como confirmación.
    post_data.setdefault("confirmar", "on")

    if "comprobante_pago" not in files_data and "doc_tutor_pago" in files_data:
        files_data["comprobante_pago"] = files_data["doc_tutor_pago"]

    archivo = files_data.get("comprobante_pago")

    if archivo:
        archivo.name = nombre_archivo_comprobante_pago(inscripcion, archivo)

    return post_data, files_data

def usuario_es_editor_especial_filtros(user):
    """
    Roles que pueden corregir un filtro incluso después de dictaminar.
    Por acuerdo del flujo: Administrador del sistema y Directora.
    """
    return usuario_es_admin(user) or usuario_es_directora(user)


def usuario_tiene_permiso_area_filtro(user, area):
    """
    Permisos normales por área.
    Admin y Directora pueden acceder a todas las áreas.
    """
    if usuario_es_editor_especial_filtros(user):
        return True

    roles = obtener_roles_usuario(user)

    if area == "psicologia":
        return any("psicolog" in rol for rol in roles)

    if area == "nutricion":
        return any("nutriolog" in rol or "nutricion" in rol for rol in roles)

    if area == "medico":
        return any("medic" in rol for rol in roles)

    return False


def filtro_ya_dictaminado(sol, area):
    if area == "psicologia":
        return getattr(sol, "estado_psicologia", "PENDIENTE") != "PENDIENTE"

    if area == "nutricion":
        return getattr(sol, "estado_nutricion", "PENDIENTE") != "PENDIENTE"

    if area == "medico":
        return getattr(sol, "estado_medico", "PENDIENTE") != "PENDIENTE"

    return False


def puede_editar_filtro(user, sol, area):
    """
    Regla principal del Sprint 3 - Paso 1:
    - Admin y Directora pueden corregir aunque ya esté dictaminado.
    - El área correspondiente solo puede editar mientras el filtro esté PENDIENTE.
    """
    if usuario_es_editor_especial_filtros(user):
        return True

    if not usuario_tiene_permiso_area_filtro(user, area):
        return False

    return not filtro_ya_dictaminado(sol, area)


def filtros_terminados(sol):
    """
    Verifica si Psicología, Nutrición y Médico ya emitieron dictamen final.
    """
    estados = [
        getattr(sol, "estado_psicologia", "PENDIENTE"),
        getattr(sol, "estado_nutricion", "PENDIENTE"),
        getattr(sol, "estado_medico", "PENDIENTE"),
    ]

    return all(estado != "PENDIENTE" for estado in estados)


def obtener_areas_rechazadas_filtros(sol):
    """
    Devuelve las áreas que rechazaron el expediente.
    """
    rechazadas = []

    if getattr(sol, "estado_psicologia", "PENDIENTE") == "RECHAZADO":
        rechazadas.append("Psicología")

    if getattr(sol, "estado_nutricion", "PENDIENTE") == "RECHAZADO":
        rechazadas.append("Nutrición")

    if getattr(sol, "estado_medico", "PENDIENTE") == "RECHAZADO":
        rechazadas.append("Médico")

    return rechazadas


def guardar_pdf_reporte_final_en_inscripcion(inscripcion):
    """
    Genera el PDF FO-301-02-18 y lo guarda en el campo reporte_final_pdf.

    El archivo físico queda en:
    media/inscripciones/<matricula>/reportes_finales/

    El FileField permite descargarlo desde el portal o adjuntarlo por correo.
    """
    pdf_path = generar_pdf_reporte_final_ingreso(inscripcion)

    if not pdf_path or not os.path.exists(pdf_path):
        return False, "No se pudo generar el PDF del Reporte Final de Ingreso."

    nombre_archivo = os.path.basename(pdf_path)

    try:
        with open(pdf_path, "rb") as archivo_pdf:
            inscripcion.reporte_final_pdf.save(
                nombre_archivo,
                File(archivo_pdf),
                save=True,
            )

        return True, "PDF del Reporte Final generado correctamente."

    except Exception as e:
        return False, f"No se pudo guardar el PDF del Reporte Final: {e}"


def revisar_cierre_filtros(sol):
    """
    Sprint 3 - cierre correcto del flujo de filtros.

    Cada vez que Psicología, Nutrición o Médico guarda dictamen, se revisa
    si los tres filtros ya terminaron.

    Flujo correcto según el Sprint 3:
    - Si todavía falta algún filtro: la inscripción permanece en FILTROS.
    - Si los tres filtros terminaron: la inscripción pasa a REVISION_FINAL_TS.
    - Trabajo Social registra el Reporte Final de Ingreso.
    - Después, si Trabajo Social acepta, pasa a ESPERANDO_DIRECTORA.
    - Si Trabajo Social rechaza, pasa a RECHAZADA.
    """
    inscripcion = SolicitudInscripcion.objects.filter(solicitud_ingreso=sol).first()

    if not inscripcion:
        return False, None, "No existe inscripción vinculada."

    if inscripcion.estado != "FILTROS":
        return False, inscripcion.estado, "La inscripción no está en etapa de filtros."

    if not filtros_terminados(sol):
        return False, inscripcion.estado, "Aún faltan filtros por dictaminar."

    rechazadas = obtener_areas_rechazadas_filtros(sol)

    inscripcion.estado = "REVISION_FINAL_TS"

    if rechazadas:
        inscripcion.observaciones = (
            "Los tres filtros finalizaron. Existen dictámenes desfavorables en: "
            + ", ".join(rechazadas)
            + ". Trabajo Social debe registrar el Reporte Final de Ingreso."
        )
        mensaje = (
            "Los tres filtros finalizaron con observaciones. "
            "El expediente pasó a Trabajo Social para Reporte Final. "
            "Áreas con rechazo: " + ", ".join(rechazadas) + "."
        )
    else:
        inscripcion.observaciones = (
            "Los tres filtros fueron aprobados. Trabajo Social debe registrar el Reporte Final de Ingreso."
        )
        mensaje = (
            "Los tres filtros fueron aprobados. "
            "El expediente pasó a Trabajo Social para Reporte Final de Ingreso."
        )

    inscripcion.save(update_fields=["estado", "observaciones"])

    return True, inscripcion.estado, mensaje



def limpiar_texto_persona(valor):
    """
    Limpia espacios dobles y aplica formato título.
    No cambia letras acentuadas.
    """
    valor = (valor or "").strip()
    valor = re.sub(r"\s+", " ", valor)
    return valor.title()


def solicitud_tiene_identidad_menor(solicitud):
    """
    Verifica si la Solicitud tiene los datos mínimos del menor.
    Estos datos son los que se muestran después en Psicología, Nutrición y Médico.
    """
    return all([
        (getattr(solicitud, "nombres_menor", "") or "").strip(),
        (getattr(solicitud, "apellido_paterno_menor", "") or "").strip(),
        (getattr(solicitud, "apellido_materno_menor", "") or "").strip(),
        getattr(solicitud, "fecha_nacimiento_menor", None),
        (getattr(solicitud, "curp_menor", "") or "").strip(),
    ])


def guardar_identidad_menor_desde_formulario(solicitud, form):
    """
    Guarda explícitamente los datos del menor desde cleaned_data.

    Esto evita que por algún ajuste de HTML/JS el nombre del menor no quede
    persistido en Solicitud. La fecha y CURP ya estaban guardando, pero nombre
    y apellidos podían quedar vacíos en algunos folios.
    """
    solicitud.nombres_menor = limpiar_texto_persona(form.cleaned_data.get("nombres_menor"))
    solicitud.apellido_paterno_menor = limpiar_texto_persona(form.cleaned_data.get("apellido_paterno_menor"))
    solicitud.apellido_materno_menor = limpiar_texto_persona(form.cleaned_data.get("apellido_materno_menor"))
    solicitud.fecha_nacimiento_menor = form.cleaned_data.get("fecha_nacimiento_menor")
    solicitud.curp_menor = (form.cleaned_data.get("curp_menor") or "").strip().upper()

    return solicitud


# ===================== CAPTURA POR TOKEN — PADRES =====================
def captura_por_token(request, token):
    link = get_object_or_404(LinkCaptura, token=token)

    if not link.vigente():
        raise Http404("Este enlace ya no es válido.")

    solicitud = link.solicitud

    if request.method == "POST":
        form = CapturaSolicitudForm(request.POST, instance=solicitud)

        if form.is_valid():
            # Guardado controlado para asegurar que la identidad del menor
            # quede persistida en Solicitud antes de generar PDF o marcar link usado.
            solicitud = form.save(commit=False)
            solicitud = guardar_identidad_menor_desde_formulario(solicitud, form)

            if not solicitud_tiene_identidad_menor(solicitud):
                messages.error(
                    request,
                    "Faltan datos del menor. Captura nombre, apellidos, fecha de nacimiento y CURP antes de enviar."
                )
                return render(request, "admisiones/captura.html", {"form": form})

            solicitud.estado = Solicitud.Estado.RECIBIDA
            solicitud.save()

            # Recargar desde BD para comprobar que realmente se guardó.
            solicitud.refresh_from_db()

            if not solicitud_tiene_identidad_menor(solicitud):
                messages.error(
                    request,
                    "No se pudieron guardar los datos del menor. Intenta nuevamente o avisa a Trabajo Social."
                )
                return render(request, "admisiones/captura.html", {"form": form})

            link.usado = True
            link.usado_en = timezone.now()
            link.save(update_fields=["usado", "usado_en"])

            try:
                pdf_path = generar_pdf_fo301(solicitud)

                if pdf_path and os.path.exists(pdf_path):
                    with open(pdf_path, "rb") as f:
                        solicitud.pdf.save(
                            f"FO301_{solicitud.folio}.pdf",
                            File(f),
                            save=True,
                        )

            except Exception as e:
                print("Error al generar PDF:", e)

            return render(
                request,
                "admisiones/gracias.html",
                {"folio": solicitud.folio},
            )

        messages.error(
            request,
            "No se pudo guardar la solicitud. Revisa los campos marcados en rojo."
        )

    else:
        form = CapturaSolicitudForm(instance=solicitud)

    return render(request, "admisiones/captura.html", {"form": form})


# ===================== PANEL DE ADMISIÓN / TRABAJO SOCIAL =====================
@login_required
def panel_admisiones(request):
    orden = "-created_at"
    sort_param = request.GET.get("sort")

    if sort_param == "apellidos":
        orden = "apellido_paterno_tutor"
    elif sort_param == "folio_asc":
        orden = "id"
    elif sort_param == "folio_desc":
        orden = "-id"

    solicitudes = Solicitud.objects.order_by(orden)
    form_crear = CrearSolicitudPanelForm()

    context = {
        "solicitudes": solicitudes,
        "form_crear": form_crear,
        **contexto_semestre_operativo(),
    }

    return render(
        request,
        "admisiones/panel.html",
        context,
    )


@require_http_methods(["POST"])
@login_required
def crear_solicitud_y_link(request):
    bloqueo = bloquear_si_no_hay_semestre_activo(request, "panel_admisiones")
    if bloqueo:
        return bloqueo

    form = CrearSolicitudPanelForm(request.POST)

    if form.is_valid():
        unidad = form.cleaned_data.get("unidad_academica")

        if unidad == "Otra":
            unidad = form.cleaned_data.get("unidad_academica_otra")

        solicitud = Solicitud.objects.create(
            estado=Solicitud.Estado.CAPTURA,
            nombres_tutor=form.cleaned_data.get("nombres_tutor", ""),
            apellido_paterno_tutor=form.cleaned_data.get("apellido_paterno_tutor", ""),
            apellido_materno_tutor=form.cleaned_data.get("apellido_materno_tutor", ""),
            matricula=form.cleaned_data.get("matricula", ""),
            correo=form.cleaned_data.get("correo", ""),
            unidad_academica=unidad,
        )

        LinkCaptura.objects.create(solicitud=solicitud)
        messages.success(request, f"Solicitud creada. Folio: {solicitud.folio}")

    return redirect("panel_admisiones")


@login_required
def editar_solicitud(request, solicitud_id):
    s = get_object_or_404(Solicitud, id=solicitud_id)

    if request.method == "POST":
        bloqueo = bloquear_si_no_hay_semestre_activo(request, "panel_admisiones")
        if bloqueo:
            return bloqueo

        s.nombres_tutor = (request.POST.get("nombres_tutor") or "").strip()
        s.apellido_paterno_tutor = (
            request.POST.get("apellido_paterno_tutor") or ""
        ).strip()
        s.save()

        messages.success(request, f"Datos de {s.folio} actualizados.")
        return redirect("panel_admisiones")

    return render(request, "admisiones/editar.html", {"solicitud": s})


@login_required
def enviar_link_por_correo(request, solicitud_id):
    solicitud = get_object_or_404(Solicitud, id=solicitud_id)
    link = LinkCaptura.objects.filter(solicitud=solicitud, usado=False).last()

    if link and solicitud.correo:
        url = request.build_absolute_uri(reverse("captura_por_token", args=[link.token]))
        asunto = f"Link de Captura - Folio {solicitud.folio}"
        cuerpo = f"Hola {solicitud.nombres_tutor},\n\nCompleta tu solicitud aquí: {url}"

        try:
            send_mail(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, [solicitud.correo])
            messages.success(request, "Correo enviado.")
        except Exception as e:
            messages.error(request, f"Fallo al enviar: {e}")

    return redirect("panel_admisiones")


@user_passes_test(verificacion_staff, login_url="/")
def eliminar_solicitud(request, pk):
    bloqueo = bloquear_si_no_hay_semestre_activo(request, "panel_admisiones")
    if bloqueo:
        return bloqueo

    s = get_object_or_404(Solicitud, pk=pk)
    s.delete()

    messages.success(request, "Solicitud eliminada.")
    return redirect("panel_admisiones")


@user_passes_test(verificacion_staff, login_url="/")
def eliminar_todas_solicitudes(request):
    if request.method == "POST":
        bloqueo = bloquear_si_no_hay_semestre_activo(request, "panel_admisiones")
        if bloqueo:
            return bloqueo

        Solicitud.objects.all().delete()
        messages.success(request, "Todas eliminadas.")

    return redirect("panel_admisiones")


# ===================== DESCARGA DIRECTA DE EXPEDIENTE =====================
@login_required
def descargar_archivo_expediente(request, inscripcion_id, campo):
    user = request.user
    grupo = user.groups.first().name.strip().lower() if user.groups.exists() else ""

    if getattr(user, "tipo_persona", "") != "ADMIN" and "trabajadora social" not in grupo:
        return redirect("/")

    insc = get_object_or_404(SolicitudInscripcion, id=inscripcion_id)
    archivo_field = getattr(insc, campo, None)

    if not archivo_field:
        raise Http404("El archivo no existe.")

    mapeo_nombres = {
        "doc_menor_certificado_medico": "Certificado_Medico_Menor",
        "doc_menor_cartilla_vacunacion": "Cartilla_Vacunacion_Menor",
        "doc_menor_grupo_sanguineo": "Grupo_Sanguineo_Menor",
        "doc_menor_acta_nacimiento": "Acta_de_Nacimiento_Menor",
        "doc_menor_fotos": "Fotografia_del_Menor",
        "doc_menor_laboratorio": "Estudios_de_Laboratorio_Menor",
        "doc_tutor_acta_nacimiento": "Acta_de_Nacimiento_Beneficiario",
        "doc_tutor_ine": "INE_del_Beneficiario",
        "doc_tutor_fotos": "Fotografia_del_Beneficiario",
        "doc_segundo_padre_fotos": "Fotografia_Pareja",
        "doc_tutor_domicilio": "Comprobante_de_Domicilio_Beneficiario",
        "doc_tutor_historial": "Historial_Academico",
        "doc_tutor_horario": "Horario_de_Clases",
        "doc_autorizado_carta": "Carta_de_Autorizacion",
        "doc_autorizado_ine": "INE_del_Autorizado",
        "doc_contacto_1_fotos": "Fotografia_Autorizado_1",
        "doc_contacto_2_fotos": "Fotografia_Autorizado_2",
        "doc_contacto_3_fotos": "Fotografia_Autorizado_3",
        "reglamento_firmado": "Reglamento_Interno_Firmado",
        "doc_tutor_pago": "Comprobante_Pago",
    }

    nombre_archivo = mapeo_nombres.get(campo, "Documento")
    matricula = insc.solicitud_ingreso.matricula or "SIN_MATRICULA"
    ext = os.path.splitext(archivo_field.name)[1]

    return FileResponse(
        archivo_field.open("rb"),
        as_attachment=True,
        filename=f"{nombre_archivo}_{matricula}{ext}",
    )


# ===================== REVISIÓN DE SOLICITUD =====================
@login_required
def revisar_solicitud(request, pk):
    s = get_object_or_404(Solicitud, pk=pk)
    inscripcion = SolicitudInscripcion.objects.filter(solicitud_ingreso=s).first()

    if request.method == "POST" and "accion_inscripcion" in request.POST:
        bloqueo = bloquear_si_no_hay_semestre_activo(request, "/")
        if bloqueo:
            return redirect("revisar_solicitud", pk=pk)

        accion = request.POST.get("accion_inscripcion")

        if not inscripcion:
            messages.error(request, "No existe solicitud de inscripción vinculada.")
            return redirect("revisar_solicitud", pk=pk)

        if inscripcion.estado != "EN_REVISION":
            messages.warning(
                request,
                "Este expediente no está en revisión. No se puede dictaminar en esta etapa."
            )
            return redirect("revisar_solicitud", pk=pk)

        if accion == "DEVOLVER":
            docs_erroneos = request.POST.get("docs_erroneos", "")
            comentario = request.POST.get("comentario_inscripcion", "")

            if not comentario.strip():
                messages.error(
                    request,
                    "Para devolver el expediente debes escribir una observación clara para el tutor."
                )
                return redirect("revisar_solicitud", pk=pk)

            inscripcion.estado = "DEVUELTA"
            inscripcion.observaciones = construir_observaciones_devolucion(
                docs_erroneos,
                comentario,
            )
            inscripcion.comentario_tutor = ""
            inscripcion.save()

            enviado, mensaje_correo = enviar_correo_estado_inscripcion(
                inscripcion,
                "DEVUELTA",
            )

            if enviado:
                messages.warning(
                    request,
                    "Expediente devuelto. Se enviaron las observaciones al tutor por correo."
                )
            else:
                messages.warning(
                    request,
                    f"Expediente devuelto, pero no se pudo enviar el correo: {mensaje_correo}"
                )

        elif accion == "APROBAR":
            inscripcion.estado = "FILTROS"
            inscripcion.observaciones = ""
            inscripcion.comentario_tutor = ""
            inscripcion.save()

            enviado, mensaje_correo = enviar_correo_estado_inscripcion(
                inscripcion,
                "FILTROS",
            )

            if enviado:
                messages.success(
                    request,
                    "Expediente validado. Se envió correo al tutor y pasó a filtros."
                )
            else:
                messages.success(
                    request,
                    "Expediente validado y enviado a filtros."
                )
                messages.warning(
                    request,
                    f"No se pudo enviar el correo: {mensaje_correo}"
                )

        else:
            messages.error(request, "Acción de revisión no válida.")

        return redirect("revisar_solicitud", pk=pk)

    return render(
        request,
        "admisiones/revisar_solicitud.html",
        {
            "s": s,
            "inscripcion": inscripcion,
        },
    )


@login_required
def dictaminar_solicitud(request, pk):
    s = get_object_or_404(Solicitud, pk=pk)
    User = get_user_model()

    if request.method == "POST":
        bloqueo = bloquear_si_no_hay_semestre_activo(request, "panel_admisiones")
        if bloqueo:
            return bloqueo

        accion = request.POST.get("accion")

        if accion == "APROBAR":
            s.estado = Solicitud.Estado.APROBADA
            s.comentario_respuesta = (
                request.POST.get("comentario_respuesta")
                or "Solicitud aceptada para continuar con el proceso de inscripción."
            )

            if hasattr(s, "dictaminado_por"):
                s.dictaminado_por = request.user

            if hasattr(s, "dictaminado_en"):
                s.dictaminado_en = timezone.now()

            s.save()

            if not s.correo:
                messages.warning(
                    request,
                    "La solicitud fue aprobada, pero no tiene correo registrado. "
                    "No se pudo crear acceso ni enviar correo."
                )
                return redirect("panel_admisiones")

            user, creado = User.objects.get_or_create(
                email=s.correo,
                defaults={
                    "username": s.correo,
                    "tipo_persona": "BENEFICIARIO",
                    "is_active": True,
                },
            )

            user.tipo_persona = "BENEFICIARIO"
            user.is_active = True

            if not user.username:
                user.username = s.correo

            # Contraseña temporal para pruebas locales.
            # Después conviene cambiarlo por enlace de restablecimiento.
            user.set_password("Unach2026")
            user.save()

            SolicitudInscripcion.objects.get_or_create(
                solicitud_ingreso=s,
                defaults={"usuario_tutor": user},
            )

            pdf_path = None

            try:
                pdf_path = generar_pdf_dictamen(s)
            except Exception as e:
                messages.warning(
                    request,
                    f"Solicitud aprobada, pero no se pudo generar el PDF de aceptación: {e}"
                )

            try:
                enviado, mensaje_correo = enviar_correo_dictamen_ingreso(s, pdf_path)

                if enviado:
                    messages.success(
                        request,
                        "Solicitud aprobada. Se creó la inscripción, se generó el PDF y se envió el correo."
                    )
                else:
                    messages.warning(
                        request,
                        f"Solicitud aprobada y PDF generado, pero no se envió el correo: {mensaje_correo}"
                    )

            except Exception as e:
                messages.warning(
                    request,
                    f"Solicitud aprobada y PDF generado, pero ocurrió un error al enviar el correo: {e}"
                )

        elif accion == "RECHAZAR":
            motivo = (
                request.POST.get("motivo_rechazo")
                or request.POST.get("comentario_respuesta")
                or request.POST.get("comentario")
                or request.POST.get("motivo")
                or ""
            ).strip()

            if not motivo:
                motivo = "No se especificó un motivo adicional."

            s.estado = Solicitud.Estado.RECHAZADA
            s.comentario_respuesta = motivo

            if hasattr(s, "dictaminado_por"):
                s.dictaminado_por = request.user

            if hasattr(s, "dictaminado_en"):
                s.dictaminado_en = timezone.now()

            s.save()

            pdf_path = None

            try:
                pdf_path = generar_pdf_dictamen(s)
            except Exception as e:
                messages.warning(
                    request,
                    f"Solicitud rechazada, pero no se pudo generar el PDF de rechazo: {e}"
                )

            try:
                enviado, mensaje_correo = enviar_correo_dictamen_ingreso(s, pdf_path)

                if enviado:
                    messages.warning(
                        request,
                        "Solicitud rechazada. Se generó el PDF y se envió el correo al tutor."
                    )
                else:
                    messages.warning(
                        request,
                        f"Solicitud rechazada y PDF generado, pero no se envió el correo: {mensaje_correo}"
                    )

            except Exception as e:
                messages.warning(
                    request,
                    f"Solicitud rechazada y PDF generado, pero ocurrió un error al enviar el correo: {e}"
                )

        else:
            messages.error(request, "Acción no válida.")

        return redirect("panel_admisiones")

    return redirect("revisar_solicitud", pk=pk)


# ===================== PORTAL DE PADRES =====================
@login_required
def portal_inscripcion(request):
    inscripcion = SolicitudInscripcion.objects.filter(usuario_tutor=request.user).first()

    if not inscripcion:
        return redirect("/")

    if request.method == "POST":
        bloqueo = bloquear_si_no_hay_semestre_activo(request, "portal_inscripcion")
        if bloqueo:
            return bloqueo

        # =========================================================
        # SUBIR COMPROBANTE DE PAGO POR BENEFICIARIO
        # Permitido únicamente cuando Dirección ya aceptó la inscripción.
        # No desbloquea el resto del expediente.
        # =========================================================
        if request.POST.get("subir_comprobante_pago") == "1":
            if inscripcion.estado != "ACEPTADO_ESPERANDO_PAGO":
                messages.warning(
                    request,
                    "El comprobante de pago solo puede subirse cuando la inscripción ya fue aceptada por Dirección."
                )
                return redirect("portal_inscripcion")

            archivo_pago = request.FILES.get("doc_tutor_pago")
            es_valido, mensaje_validacion = validar_archivo_comprobante_pago(archivo_pago)

            if not es_valido:
                messages.error(request, mensaje_validacion)
                return redirect("portal_inscripcion")

            archivo_pago.name = nombre_archivo_comprobante_pago(inscripcion, archivo_pago)
            inscripcion.doc_tutor_pago = archivo_pago
            inscripcion.estado_pago = "SUBIDO_BENEFICIARIO"
            inscripcion.pago_subido_por_beneficiario = True
            inscripcion.pago_entregado_presencial = False
            inscripcion.pago_recibido_presencial_por = None
            inscripcion.pago_recibido_presencial_en = None
            inscripcion.pago_rechazado_por = None
            inscripcion.pago_rechazado_en = None
            inscripcion.pago_observaciones = request.POST.get("pago_observaciones", "").strip()
            inscripcion.save()

            messages.success(
                request,
                "Comprobante enviado correctamente. Trabajo Social lo revisará para finalizar tu inscripción."
            )
            return redirect("portal_inscripcion")

        if not puede_editar_inscripcion(inscripcion):
            messages.warning(
                request,
                "Tu expediente ya fue enviado o se encuentra en una etapa donde no puede modificarse."
            )
            return redirect("portal_inscripcion")

        mapeo_nombres = {
            "doc_menor_certificado_medico": "Certificado_Medico_Menor",
            "doc_menor_cartilla_vacunacion": "Cartilla_Vacunacion_Menor",
            "doc_menor_grupo_sanguineo": "Grupo_Sanguineo_Menor",
            "doc_menor_acta_nacimiento": "Acta_de_Nacimiento_Menor",
            "doc_menor_fotos": "Fotografia_del_Menor",
            "doc_menor_laboratorio": "Estudios_de_Laboratorio_Menor",
            "doc_tutor_acta_nacimiento": "Acta_de_Nacimiento_Beneficiario",
            "doc_tutor_ine": "INE_del_Beneficiario",
            "doc_tutor_fotos": "Fotografia_del_Beneficiario",
            "doc_segundo_padre_fotos": "Fotografia_Pareja",
            "doc_tutor_domicilio": "Comprobante_de_Domicilio_Beneficiario",
            "doc_tutor_historial": "Historial_Academico",
            "doc_tutor_horario": "Horario_de_Clases",
            "doc_autorizado_carta": "Carta_de_Autorizacion",
            "doc_autorizado_ine": "INE_del_Autorizado",
            "doc_contacto_1_fotos": "Fotografia_Autorizado_1",
            "doc_contacto_2_fotos": "Fotografia_Autorizado_2",
            "doc_contacto_3_fotos": "Fotografia_Autorizado_3",
            "reglamento_firmado": "Reglamento_Interno_Firmado",
            "doc_tutor_pago": "Comprobante_de_Pago",
        }

        campos_fotos = [
            "doc_menor_fotos",
            "doc_tutor_fotos",
            "doc_segundo_padre_fotos",
            "doc_contacto_1_fotos",
            "doc_contacto_2_fotos",
            "doc_contacto_3_fotos",
        ]

        matricula = inscripcion.solicitud_ingreso.matricula or "SIN_MATRICULA"

        # Guardar archivos
        for campo, nombre_legible in mapeo_nombres.items():
            if campo in request.FILES:
                archivo = request.FILES[campo]
                ext = os.path.splitext(archivo.name)[1].lower()

                if campo in campos_fotos:
                    if ext == ".pdf":
                        messages.error(
                            request,
                            f"Error: El campo '{nombre_legible}' no acepta PDFs. "
                            "Por favor sube una imagen .jpg o .png.",
                        )
                        return redirect("portal_inscripcion")

                    if archivo.size > 5 * 1024 * 1024:
                        messages.error(
                            request,
                            f"Error: El archivo de '{nombre_legible}' supera el tamaño máximo de 5MB."
                        )
                        return redirect("portal_inscripcion")

                archivo.name = f"{nombre_legible}_{matricula}{ext}"
                setattr(inscripcion, campo, archivo)

        campos_intocables = [
            "nombres_menor",
            "apellido_paterno_menor",
            "apellido_materno_menor",
            "nombres_tutor",
            "apellido_paterno_tutor",
            "apellido_materno_tutor",
            "curp_menor",
            "fecha_nacimiento_menor",
            "matricula",
            "correo",
        ]

        # Guardar datos generales
        for key, value in request.POST.items():
            if key not in ["csrfmiddlewaretoken", "enviar_revision", "guardar_avance"] and key not in campos_intocables:
                if hasattr(inscripcion, key):
                    setattr(inscripcion, key, value)
                elif hasattr(inscripcion.solicitud_ingreso, key):
                    setattr(inscripcion.solicitud_ingreso, key, value)

        # Checkbox de reglamento
        inscripcion.acepto_reglamentos = request.POST.get("acepto_reglamentos") == "True"

        if request.POST.get("enviar_revision") == "1":
            if not solicitud_tiene_identidad_menor(inscripcion.solicitud_ingreso):
                messages.error(
                    request,
                    "⚠️ Error grave: Faltan datos de identidad del menor. Debe existir nombre, apellidos, fecha de nacimiento y CURP."
                )
                return redirect("portal_inscripcion")

            errores = validar_expediente_para_envio(inscripcion)

            if errores:
                messages.error(
                    request,
                    "No se pudo enviar el expediente. Revisa los campos y documentos obligatorios."
                )

                for error in errores[:10]:
                    messages.error(request, error)

                if len(errores) > 10:
                    messages.error(
                        request,
                        f"Además hay {len(errores) - 10} pendientes adicionales."
                    )

                return redirect("portal_inscripcion")

            inscripcion.estado = "EN_REVISION"
            inscripcion.observaciones = ""
            inscripcion.comentario_tutor = request.POST.get("comentario_tutor", "").strip()

            inscripcion.solicitud_ingreso.save()
            inscripcion.save()

            enviado, mensaje_correo = enviar_correo_estado_inscripcion(
                inscripcion,
                "EN_REVISION",
            )

            if enviado:
                messages.success(
                    request,
                    "Expediente enviado a revisión. Se envió confirmación a tu correo."
                )
            else:
                messages.success(
                    request,
                    "Expediente enviado a revisión correctamente."
                )
                messages.warning(
                    request,
                    f"No se pudo enviar el correo de confirmación: {mensaje_correo}"
                )

        else:
            if inscripcion.estado == "NUEVA":
                inscripcion.estado = "EN_PROCESO"

            inscripcion.solicitud_ingreso.save()
            inscripcion.save()

            messages.success(request, "Avance guardado exitosamente.")

        return redirect("portal_inscripcion")

    return render(
        request,
        "admisiones/portal_inscripcion.html",
        {
            "inscripcion": inscripcion,
            "inscripcion_bloqueada": not puede_editar_inscripcion(inscripcion) or not hay_semestre_activo_operativo(),
            **contexto_semestre_operativo(),
        },
    )


# ===================== PSICOLOGÍA =====================
@login_required
def psicologia_pendientes(request):
    if not usuario_tiene_permiso_area_filtro(request.user, "psicologia"):
        messages.error(request, "No tienes permiso para entrar al filtro de Psicología.")
        return redirect("/")

    if not hay_semestre_activo_operativo():
        messages.warning(request, "No hay semestre activo. Psicología queda en modo solo consulta; no hay dictámenes pendientes para operar.")
        qs = Solicitud.objects.none()
    else:
        folios = SolicitudInscripcion.objects.filter(estado="FILTROS").values_list(
            "solicitud_ingreso_id",
            flat=True,
        )

        qs = Solicitud.objects.filter(
            id__in=folios,
            estado_psicologia="PENDIENTE",
        ).order_by("-created_at")

    return render(
        request,
        "admisiones/psicologia_pendientes.html",
        {"solicitudes": qs, **contexto_semestre_operativo()},
    )


@login_required
def psicologia_dictaminar(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    insc = SolicitudInscripcion.objects.filter(solicitud_ingreso=sol).first()
    datos_menor = obtener_datos_menor_para_filtro(sol, insc)
    sol = aplicar_datos_identidad_menor_a_solicitud(sol, datos_menor)

    if not usuario_tiene_permiso_area_filtro(request.user, "psicologia"):
        messages.error(request, "No tienes permiso para dictaminar Psicología.")
        return redirect("/")

    bloqueado = not puede_editar_filtro(request.user, sol, "psicologia")

    if request.method == "POST":
        bloqueo_semestre = bloquear_si_no_hay_semestre_activo(request, "psicologia_pendientes")
        if bloqueo_semestre:
            return bloqueo_semestre

        if bloqueado:
            messages.warning(
                request,
                "El dictamen de Psicología ya fue enviado y no puede modificarse. Solo Administrador o Directora pueden corregirlo."
            )
            return redirect("psicologia_pendientes")

        estado_decision = request.POST.get("estado_psicologia")

        if not estado_decision or estado_decision == "PENDIENTE":
            form = DictamenPsicologiaForm(request.POST, instance=sol)
            messages.error(request, "Debes seleccionar un dictamen final de Psicología: Aprobado o Rechazado.")
        else:
            form = DictamenPsicologiaForm(request.POST, instance=sol)

            if form.is_valid():
                sol = form.save(commit=False)

                # Proteger identidad del menor: el filtro no debe modificarla.
                sol = aplicar_datos_identidad_menor_a_solicitud(sol, datos_menor)

                sol.estado_psicologia = estado_decision
                sol.psicologia_por = request.user
                sol.psicologia_en = timezone.now()
                sol.save()

                messages.success(request, "Dictamen de psicología guardado exitosamente.")

                cierre_realizado, estado_inscripcion, mensaje_cierre = revisar_cierre_filtros(sol)
                if cierre_realizado:
                    messages.info(request, mensaje_cierre)

                return redirect("psicologia_pendientes")

        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"Te faltó este campo ({field}): {error}")

        messages.warning(
            request,
            "⚠️ No se guardó el dictamen. Revisa los mensajes rojos de arriba.",
        )

    else:
        form = DictamenPsicologiaForm(instance=sol)

    return render(
        request,
        "admisiones/psicologia_dictaminar.html",
        {
            "sol": sol,
            "insc": insc,
            "form": form,
            "bloqueado": bloqueado,
            **datos_menor,
            **contexto_semestre_operativo(),
        },
    )


@login_required
def psicologia_registro(request):
    aprobados = Solicitud.objects.filter(
        estado_psicologia="APROBADO",
    ).order_by("-psicologia_en")

    rechazados = Solicitud.objects.filter(
        estado_psicologia="RECHAZADO",
    ).order_by("-psicologia_en")

    return render(
        request,
        "admisiones/psicologia_registro.html",
        {
            "aprobados": aprobados,
            "rechazados": rechazados,
        },
    )


# ===================== NUTRICIÓN =====================
@login_required
def nutricion_pendientes(request):
    if not usuario_tiene_permiso_area_filtro(request.user, "nutricion"):
        messages.error(request, "No tienes permiso para entrar al filtro de Nutrición.")
        return redirect("/")

    if not hay_semestre_activo_operativo():
        messages.warning(request, "No hay semestre activo. Nutrición queda en modo solo consulta; no hay dictámenes pendientes para operar.")
        qs = Solicitud.objects.none()
    else:
        folios = SolicitudInscripcion.objects.filter(estado="FILTROS").values_list(
            "solicitud_ingreso_id",
            flat=True,
        )

        qs = Solicitud.objects.filter(
            id__in=folios,
            estado_nutricion="PENDIENTE",
        ).order_by("-created_at")

    return render(
        request,
        "admisiones/nutricion_pendientes.html",
        {"solicitudes": qs, **contexto_semestre_operativo()},
    )


@login_required
def nutricion_dictaminar(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    insc = SolicitudInscripcion.objects.filter(solicitud_ingreso=sol).first()
    datos_menor = obtener_datos_menor_para_filtro(sol, insc)
    sol = aplicar_datos_identidad_menor_a_solicitud(sol, datos_menor)

    if not usuario_tiene_permiso_area_filtro(request.user, "nutricion"):
        messages.error(request, "No tienes permiso para dictaminar Nutrición.")
        return redirect("/")

    bloqueado = not puede_editar_filtro(request.user, sol, "nutricion")

    n_menor = datos_menor["nombre_nino"]
    ap_menor = datos_menor["paterno_nino"]
    am_menor = datos_menor["materno_nino"]

    if request.method == "POST":
        bloqueo_semestre = bloquear_si_no_hay_semestre_activo(request, "nutricion_pendientes")
        if bloqueo_semestre:
            return bloqueo_semestre

        if bloqueado:
            messages.warning(
                request,
                "El dictamen de Nutrición ya fue enviado y no puede modificarse. Solo Administrador o Directora pueden corregirlo."
            )
            return redirect("nutricion_pendientes")

        estado_decision = request.POST.get("estado_nutricion")

        if not estado_decision or estado_decision == "PENDIENTE":
            form = DictamenNutricionForm(request.POST, instance=sol)
            messages.error(request, "Debes seleccionar un dictamen final de Nutrición: Aprobado o Rechazado.")
        else:
            form = DictamenNutricionForm(request.POST, instance=sol)

            if form.is_valid():
                sol = form.save(commit=False)

                # Proteger identidad del menor: Nutrición no debe modificarla.
                sol = aplicar_datos_identidad_menor_a_solicitud(sol, datos_menor)

                sol.estado_nutricion = estado_decision
                sol.nutricion_por = request.user
                sol.nutricion_en = timezone.now()
                sol.save()

                messages.success(request, "Dictamen de nutrición guardado exitosamente.")

                cierre_realizado, estado_inscripcion, mensaje_cierre = revisar_cierre_filtros(sol)
                if cierre_realizado:
                    messages.info(request, mensaje_cierre)

                return redirect("nutricion_pendientes")

        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"Te faltó este campo ({field}): {error}")

        messages.warning(
            request,
            "⚠️ No se guardó el dictamen. Revisa los mensajes rojos de arriba.",
        )

    else:
        form = DictamenNutricionForm(
            instance=sol,
            initial={
                "nombres_menor": n_menor,
                "apellido_paterno_menor": ap_menor,
                "apellido_materno_menor": am_menor,
                "fecha_nacimiento_menor": datos_menor.get("fecha_nacimiento_menor"),
                "curp_menor": datos_menor.get("curp_menor"),
            },
        )

    contexto = {
        "sol": sol,
        "insc": insc,
        "form": form,
        "bloqueado": bloqueado,
        **datos_menor,
        **contexto_semestre_operativo(),
    }

    return render(request, "admisiones/nutricion_dictaminar.html", contexto)


@login_required
def nutricion_registro(request):
    aprobados = Solicitud.objects.filter(
        estado_nutricion="APROBADO",
    ).order_by("-nutricion_en")

    rechazados = Solicitud.objects.filter(
        estado_nutricion="RECHAZADO",
    ).order_by("-nutricion_en")

    return render(
        request,
        "admisiones/nutricion_registro.html",
        {
            "aprobados": aprobados,
            "rechazados": rechazados,
        },
    )


# ===================== MÉDICO =====================
@login_required
def medico_pendientes(request):
    if not usuario_tiene_permiso_area_filtro(request.user, "medico"):
        messages.error(request, "No tienes permiso para entrar al filtro Médico.")
        return redirect("/")

    if not hay_semestre_activo_operativo():
        messages.warning(request, "No hay semestre activo. Médico queda en modo solo consulta; no hay dictámenes pendientes para operar.")
        qs = Solicitud.objects.none()
    else:
        folios = SolicitudInscripcion.objects.filter(estado="FILTROS").values_list(
            "solicitud_ingreso_id",
            flat=True,
        )

        qs = Solicitud.objects.filter(
            id__in=folios,
            estado_medico="PENDIENTE",
        ).order_by("-created_at")

    return render(
        request,
        "admisiones/medico_pendientes.html",
        {"solicitudes": qs, **contexto_semestre_operativo()},
    )


@login_required
def medico_dictaminar(request, pk):
    sol = get_object_or_404(Solicitud, id=pk)
    insc = get_object_or_404(SolicitudInscripcion, solicitud_ingreso=sol)

    if not usuario_tiene_permiso_area_filtro(request.user, "medico"):
        messages.error(request, "No tienes permiso para dictaminar Médico.")
        return redirect("/")

    bloqueado = not puede_editar_filtro(request.user, sol, "medico")

    historia, created = HistoriaClinicaMedica.objects.get_or_create(inscripcion=insc)
    datos_menor = obtener_datos_menor_para_filtro(sol, insc)
    sol = aplicar_datos_identidad_menor_a_solicitud(sol, datos_menor)

    n_menor = datos_menor["nombre_nino"]
    ap_menor = datos_menor["paterno_nino"]
    am_menor = datos_menor["materno_nino"]

    h_initial = {
        "nombres_paciente": n_menor,
        "apellido_paterno_paciente": ap_menor,
        "apellido_materno_paciente": am_menor,
        "nombre_paciente": datos_menor.get("nombre_menor_completo", ""),
        "fecha_nacimiento": datos_menor.get("fecha_nacimiento_menor"),
    }

    anios = insc.edad_anios_menor or 0
    meses = insc.edad_meses_menor or 0
    h_initial["edad"] = historia.edad or f"{anios} años, {meses} meses"

    sexo_bd = insc.sexo_menor or getattr(sol, "sexo_nutricion", "")

    if sexo_bd in ["M", "MASCULINO"]:
        h_initial["sexo"] = "Masculino"
    elif sexo_bd in ["F", "FEMENINO"]:
        h_initial["sexo"] = "Femenino"
    else:
        h_initial["sexo"] = historia.sexo

    if sol.fecha_nacimiento_menor and not historia.fecha_nacimiento:
        h_initial["fecha_nacimiento"] = sol.fecha_nacimiento_menor

    h_initial["quien_cuida_menor"] = (
        historia.quien_cuida_menor
        or sol.persona_aparte_padres_cuidado_psicologia
        or "Padres"
    )

    nombres_padre = ""
    paterno_padre = ""
    materno_padre = ""

    if sol.nombre_padre_psicologia:
        parts = sol.nombre_padre_psicologia.split()

        if len(parts) >= 3:
            nombres_padre = " ".join(parts[:-2])
            paterno_padre = parts[-2]
            materno_padre = parts[-1]
        elif len(parts) == 2:
            nombres_padre = parts[0]
            paterno_padre = parts[1]
        else:
            nombres_padre = sol.nombre_padre_psicologia

    elif sol.parentesco == "PADRE":
        nombres_padre = sol.nombres_tutor
        paterno_padre = sol.apellido_paterno_tutor
        materno_padre = sol.apellido_materno_tutor

    h_initial["nombres_padre"] = nombres_padre
    h_initial["apellido_paterno_padre"] = paterno_padre
    h_initial["apellido_materno_padre"] = materno_padre
    h_initial["edad_padre"] = historia.edad_padre or sol.edad_padre_psicologia

    nombres_madre = ""
    paterno_madre = ""
    materno_madre = ""

    if sol.nombre_madre_psicologia:
        parts = sol.nombre_madre_psicologia.split()

        if len(parts) >= 3:
            nombres_madre = " ".join(parts[:-2])
            paterno_madre = parts[-2]
            materno_madre = parts[-1]
        elif len(parts) == 2:
            nombres_madre = parts[0]
            paterno_madre = parts[1]
        else:
            nombres_madre = sol.nombre_madre_psicologia

    elif sol.parentesco == "MADRE":
        nombres_madre = sol.nombres_tutor
        paterno_madre = sol.apellido_paterno_tutor
        materno_madre = sol.apellido_materno_tutor

    h_initial["nombres_madre"] = nombres_madre
    h_initial["apellido_paterno_madre"] = paterno_madre
    h_initial["apellido_materno_madre"] = materno_madre
    h_initial["edad_madre"] = historia.edad_madre or sol.edad_madre_psicologia

    g_raw = historia.numero_gestas or sol.numero_gesta_psicologia or ""

    if "1" in g_raw:
        g_raw = "1"
    elif "2" in g_raw:
        g_raw = "2"
    elif "3" in g_raw:
        g_raw = "3"
    elif "4" in g_raw:
        g_raw = "4 o mas"

    h_initial["numero_gestas"] = g_raw[:10]

    s_raw = historia.semanas_gestacion or sol.semanas_gestacion_psicologia or ""

    if "Menos" in s_raw:
        s_raw = "< 37 sem"
    elif "37" in s_raw:
        s_raw = "37 a 41 sem"
    elif "42" in s_raw:
        s_raw = "> 42 sem"
    elif "Desconoce" in s_raw:
        s_raw = "Desconoce"

    h_initial["semanas_gestacion"] = s_raw[:20]

    h_initial["peso_actual"] = (
        historia.peso_actual or sol.peso_actual or sol.peso_al_nacer_psicologia
    )
    h_initial["talla"] = (
        historia.talla or sol.talla_actual or sol.talla_al_nacer_psicologia
    )

    parto = (sol.tipo_nacimiento_psicologia or "").upper()
    tipo_parto = historia.tipo_parto

    if not tipo_parto:
        if "CESAREA" in parto:
            tipo_parto = "Cesárea"
        elif "PARTO" in parto:
            tipo_parto = "Eutócico"

    h_initial["tipo_parto"] = tipo_parto

    if historia.nombre_paciente:
        parts = historia.nombre_paciente.split()

        if len(parts) >= 3:
            h_initial["nombres_paciente"] = " ".join(parts[:-2])
            h_initial["apellido_paterno_paciente"] = parts[-2]
            h_initial["apellido_materno_paciente"] = parts[-1]
        elif len(parts) == 2:
            h_initial["nombres_paciente"] = parts[0]
            h_initial["apellido_paterno_paciente"] = parts[1]
            h_initial["apellido_materno_paciente"] = ""
        else:
            h_initial["nombres_paciente"] = historia.nombre_paciente

    if historia.nombre_padre:
        parts = historia.nombre_padre.split()

        if len(parts) >= 3:
            h_initial["nombres_padre"] = " ".join(parts[:-2])
            h_initial["apellido_paterno_padre"] = parts[-2]
            h_initial["apellido_materno_padre"] = parts[-1]
        elif len(parts) == 2:
            h_initial["nombres_padre"] = parts[0]
            h_initial["apellido_paterno_padre"] = parts[1]
            h_initial["apellido_materno_padre"] = ""
        else:
            h_initial["nombres_padre"] = historia.nombre_padre

    if historia.nombre_madre:
        parts = historia.nombre_madre.split()

        if len(parts) >= 3:
            h_initial["nombres_madre"] = " ".join(parts[:-2])
            h_initial["apellido_paterno_madre"] = parts[-2]
            h_initial["apellido_materno_madre"] = parts[-1]
        elif len(parts) == 2:
            h_initial["nombres_madre"] = parts[0]
            h_initial["apellido_paterno_madre"] = parts[1]
            h_initial["apellido_materno_madre"] = ""
        else:
            h_initial["nombres_madre"] = historia.nombre_madre

    if request.method == "POST":
        bloqueo_semestre = bloquear_si_no_hay_semestre_activo(request, "medico_pendientes")
        if bloqueo_semestre:
            return bloqueo_semestre

        if bloqueado:
            messages.warning(
                request,
                "El dictamen Médico ya fue enviado y no puede modificarse. Solo Administrador o Directora pueden corregirlo."
            )
            return redirect("medico_pendientes")

        post_data = request.POST.copy()

        if "numero_gestas" in post_data:
            g_val = post_data["numero_gestas"]

            if "1" in g_val:
                g_val = "1"
            elif "2" in g_val:
                g_val = "2"
            elif "3" in g_val:
                g_val = "3"
            elif "4" in g_val:
                g_val = "4 o mas"

            post_data["numero_gestas"] = g_val[:10]

        if "semanas_gestacion" in post_data:
            s_val = post_data["semanas_gestacion"]

            if "Menos" in s_val:
                s_val = "< 37 sem"
            elif "37" in s_val:
                s_val = "37 a 41 sem"
            elif "42" in s_val:
                s_val = "> 42 sem"
            elif "Desconoce" in s_val:
                s_val = "Desconoce"

            post_data["semanas_gestacion"] = s_val[:20]

        estado_decision = post_data.get("estado_medico")

        if not estado_decision or estado_decision == "PENDIENTE":
            messages.error(
                request,
                "⚠️ ERROR: Debes seleccionar un Veredicto Final: Aprobado o Rechazado.",
            )

            form = DictamenMedicoForm(post_data, request.FILES, instance=sol)
            h_form = HistoriaClinicaMedicaForm(
                post_data,
                instance=historia,
                initial=h_initial,
                historia_nueva=created,
            )

        else:
            form = DictamenMedicoForm(post_data, request.FILES, instance=sol)
            h_form = HistoriaClinicaMedicaForm(
                post_data,
                instance=historia,
                initial=h_initial,
                historia_nueva=created,
            )

            if form.is_valid() and h_form.is_valid():
                sol = form.save(commit=False)

                # Proteger identidad del menor: Médico no debe modificarla.
                sol = aplicar_datos_identidad_menor_a_solicitud(sol, datos_menor)

                sol.estado_medico = estado_decision
                sol.medico_por = request.user
                sol.medico_en = timezone.now()
                sol.save()

                h_form.save()

                messages.success(request, "Dictamen médico guardado.")

                cierre_realizado, estado_inscripcion, mensaje_cierre = revisar_cierre_filtros(sol)
                if cierre_realizado:
                    messages.info(request, mensaje_cierre)

                return redirect("medico_pendientes")

            if not form.is_valid():
                for f, errs in form.errors.items():
                    for e in errs:
                        messages.error(request, f"Error Médico ({f}): {e}")

            if not h_form.is_valid():
                for f, errs in h_form.errors.items():
                    for e in errs:
                        messages.error(request, f"Error Historia Clínica ({f}): {e}")

            messages.warning(
                request,
                "⚠️ Hay campos obligatorios en blanco, no se pudo guardar.",
            )

    else:
        form = DictamenMedicoForm(instance=sol)
        h_form = HistoriaClinicaMedicaForm(
            instance=historia,
            initial=h_initial,
            historia_nueva=created,
        )

    return render(
        request,
        "admisiones/medico_dictaminar.html",
        {
            "sol": sol,
            "insc": insc,
            "form": form,
            "historia_form": h_form,
            "bloqueado": bloqueado,
            "mama_previo": bool(h_initial["nombres_madre"]),
            "papa_previo": bool(h_initial["nombres_padre"]),
            **datos_menor,
            **contexto_semestre_operativo(),
        },
    )


@login_required
def medico_registro(request):
    aprobados = Solicitud.objects.filter(
        estado_medico="APROBADO",
    ).order_by("-medico_en")

    rechazados = Solicitud.objects.filter(
        estado_medico="RECHAZADO",
    ).order_by("-medico_en")

    return render(
        request,
        "admisiones/medico_registro.html",
        {
            "aprobados": aprobados,
            "rechazados": rechazados,
        },
    )


# ===================== PDFs ACTIVOS =====================
@login_required
def descargar_pdf_solicitud(request, solicitud_id):
    sol = get_object_or_404(Solicitud, id=solicitud_id)
    matricula = sol.matricula or "S_M"
    nombre_archivo = f"Expediente_Inscripcion_{matricula}.pdf"

    if hasattr(sol, "inscripcion_oficial"):
        ruta = generar_pdf_inscripcion_lleno(sol.inscripcion_oficial)

        if ruta and os.path.exists(ruta):
            return FileResponse(
                open(ruta, "rb"),
                as_attachment=True,
                filename=nombre_archivo,
            )

    if sol.pdf:
        return FileResponse(
            sol.pdf.open("rb"),
            as_attachment=True,
            filename=nombre_archivo,
        )

    raise Http404("PDF no disponible.")


@login_required
def psicologia_pdf(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    insc = SolicitudInscripcion.objects.filter(solicitud_ingreso=sol).first()

    context = {
        "sol": sol,
        "insc": insc,
    }

    html = render_to_string("admisiones/psicologia_pdf.html", context, request=request)

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="Dictamen_Psicologia.pdf"'

    pisa.CreatePDF(html, dest=response, link_callback=link_callback)

    return response


@login_required
def nutricion_pdf(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    insc = SolicitudInscripcion.objects.filter(solicitud_ingreso=sol).first()
    datos_menor = obtener_datos_menor_para_filtro(sol, insc)

    context = {
        "sol": sol,
        "insc": insc,
        **datos_menor,
    }

    html = render_to_string("admisiones/nutricion_pdf.html", context, request=request)

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="Dictamen_Nutricion.pdf"'

    pisa.CreatePDF(html, dest=response, link_callback=link_callback)

    return response


@login_required
def medico_pdf(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    insc = SolicitudInscripcion.objects.filter(solicitud_ingreso=sol).first()
    datos_menor = obtener_datos_menor_para_filtro(sol, insc)

    context = {
        "sol": sol,
        "insc": insc,
        **datos_menor,
    }

    html = render_to_string("admisiones/medico_pdf.html", context, request=request)

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="Dictamen_Medico.pdf"'

    pisa.CreatePDF(html, dest=response, link_callback=link_callback)

    return response


@login_required
def descargar_reporte_final_padre(request, inscripcion_id):
    inscripcion = get_object_or_404(SolicitudInscripcion, id=inscripcion_id)

    # El tutor solo puede descargar su propio reporte.
    if not usuario_es_admin(request.user) and not usuario_es_directora(request.user):
        if getattr(inscripcion, "usuario_tutor_id", None) != request.user.id:
            return redirect("/")

    if not getattr(inscripcion, "reporte_final_pdf", None):
        raise Http404("El Reporte Final de Ingreso todavía no está disponible.")

    return FileResponse(
        inscripcion.reporte_final_pdf.open("rb"),
        as_attachment=True,
        filename=f"Reporte_Final_Ingreso_{inscripcion.solicitud_ingreso.folio}.pdf",
    )


# ===================== PÚBLICO =====================
def solicitud_publica_nueva(request):
    return render(request, "admisiones/publico_nuevo_ingreso.html")


# =========================================================
# MÓDULOS DESACTIVADOS
# Estas vistas permanecen para evitar errores si algún enlace viejo
# todavía intenta entrar, pero ya no renderizan templates eliminados.
# =========================================================

@login_required
def validacion_pagos_pendientes(request):
    """
    Bandeja de Trabajo Social para comprobantes de pago.

    Muestra expedientes aceptados por Dirección y en espera de pago.
    Permite:
    - Ver comprobante subido por beneficiario.
    - Registrar comprobante presencial adjuntando foto o PDF.
    - Validar pago.
    - Rechazar comprobante.
    - Consultar beneficiarios que ya tienen comprobante o pago validado.
    """
    if not usuario_puede_gestionar_pagos(request.user):
        messages.error(request, "No tienes permiso para validar comprobantes de pago.")
        return redirect("/")

    pagos_registrados = SolicitudInscripcion.objects.none()

    if not hay_semestre_activo_operativo():
        messages.warning(request, "No hay semestre activo. Validación de pagos queda en modo solo consulta.")
        inscripciones = SolicitudInscripcion.objects.none()
    else:
        inscripciones = (
            SolicitudInscripcion.objects
            .filter(estado="ACEPTADO_ESPERANDO_PAGO")
            .select_related("solicitud_ingreso", "usuario_tutor")
            .order_by("-updated_at")
        )

        pagos_registrados = (
            SolicitudInscripcion.objects
            .filter(
                Q(estado_pago="SUBIDO_BENEFICIARIO")
                | Q(estado_pago="ENTREGADO_PRESENCIAL")
                | Q(estado_pago="VALIDADO")
                | Q(pago_entregado_presencial=True)
                | Q(pago_validado_en__isnull=False)
                | (Q(doc_tutor_pago__isnull=False) & ~Q(doc_tutor_pago=""))
            )
            .select_related(
                "solicitud_ingreso",
                "usuario_tutor",
                "pago_recibido_presencial_por",
                "pago_validado_por",
            )
            .order_by("-pago_validado_en", "-pago_recibido_presencial_en", "-updated_at")
        )

    resumen_pagos = {
        "pendientes": inscripciones.count(),
        "con_comprobante": pagos_registrados.exclude(estado_pago="VALIDADO").count(),
        "validados": pagos_registrados.filter(estado_pago="VALIDADO").count(),
        "presenciales": pagos_registrados.filter(pago_entregado_presencial=True).count(),
    }

    return render(
        request,
        "admisiones/validacion_pagos_pendientes.html",
        {
            "inscripciones": inscripciones,
            "pagos_registrados": pagos_registrados,
            "pagos_con_comprobante": pagos_registrados,
            "resumen_pagos": resumen_pagos,
            **contexto_semestre_operativo(),
        },
    )


@login_required
def registrar_pago_valido(request, pk):
    """
    Gestión del comprobante de pago por Trabajo Social.

    Acciones esperadas por POST:
    - PRESENCIAL: marca que el beneficiario entregó ticket/comprobante físico.
    - VALIDAR: valida archivo digital o entrega presencial y finaliza inscripción.
    - RECHAZAR: rechaza el comprobante digital y solicita corrección.
    """
    if not usuario_puede_gestionar_pagos(request.user):
        messages.error(request, "No tienes permiso para registrar comprobantes de pago.")
        return redirect("/")

    bloqueo = bloquear_si_no_hay_semestre_activo(request, "validacion_pagos_pendientes")
    if bloqueo:
        return bloqueo

    inscripcion = get_object_or_404(
        SolicitudInscripcion.objects.select_related("solicitud_ingreso", "usuario_tutor"),
        pk=pk,
    )

    if inscripcion.estado != "ACEPTADO_ESPERANDO_PAGO":
        messages.warning(
            request,
            "Este expediente no está en etapa de espera de comprobante de pago."
        )
        return redirect("validacion_pagos_pendientes")

    if request.method != "POST":
        return redirect("validacion_pagos_pendientes")

    accion = (request.POST.get("accion_pago") or request.POST.get("accion") or "").strip().upper()
    observaciones = (
        request.POST.get("pago_observaciones")
        or request.POST.get("observaciones")
        or request.POST.get("motivo_rechazo")
        or ""
    ).strip()

    if accion == "PRESENCIAL":
        post_data, files_data = preparar_archivo_comprobante_presencial(request, inscripcion)

        form_presencial = RegistrarComprobantePresencialForm(
            post_data,
            files_data,
            inscripcion=inscripcion,
            usuario=request.user,
        )

        if form_presencial.is_valid():
            form_presencial.registrar()

            messages.success(
                request,
                "Comprobante presencial registrado con archivo adjunto. Ahora puedes validar el pago."
            )
        else:
            messages.error(
                request,
                "No se pudo registrar el comprobante presencial. Adjunta foto o PDF del comprobante."
            )
            for campo, errores in form_presencial.errors.items():
                for error in errores:
                    messages.error(request, f"{campo}: {error}")

            return redirect("validacion_pagos_pendientes")

    elif accion == "VALIDAR":
        if not inscripcion.doc_tutor_pago and not inscripcion.pago_entregado_presencial:
            messages.error(
                request,
                "No se puede validar: no hay archivo de comprobante ni entrega presencial registrada."
            )
            return redirect("validacion_pagos_pendientes")

        inscripcion.estado_pago = "VALIDADO"
        inscripcion.pago_validado_por = request.user
        inscripcion.pago_validado_en = timezone.now()
        inscripcion.pago_observaciones = observaciones or inscripcion.pago_observaciones
        inscripcion.estado = "FINALIZADA"
        inscripcion.save()

        messages.success(
            request,
            "Pago validado correctamente. La inscripción quedó FINALIZADA."
        )

        if not inscripcion_tiene_codigo_responsable(inscripcion):
            messages.info(
                request,
                "Siguiente paso: genera el código de seguridad de 4 dígitos y entrégalo junto con la credencial."
            )

    elif accion == "RECHAZAR":
        if not observaciones:
            messages.error(
                request,
                "Para rechazar el comprobante debes escribir el motivo u observaciones."
            )
            return redirect("validacion_pagos_pendientes")

        inscripcion.estado_pago = "RECHAZADO"
        inscripcion.pago_rechazado_por = request.user
        inscripcion.pago_rechazado_en = timezone.now()
        inscripcion.pago_validado_por = None
        inscripcion.pago_validado_en = None
        inscripcion.pago_observaciones = observaciones
        inscripcion.pago_entregado_presencial = False
        inscripcion.pago_recibido_presencial_por = None
        inscripcion.pago_recibido_presencial_en = None

        # Conservamos el archivo para auditoría/consulta, pero el beneficiario puede subir otro
        # porque el expediente permanece en ACEPTADO_ESPERANDO_PAGO.
        inscripcion.estado = "ACEPTADO_ESPERANDO_PAGO"
        inscripcion.save()

        messages.warning(
            request,
            "Comprobante rechazado. El beneficiario podrá subir un nuevo comprobante."
        )

    else:
        messages.error(request, "Acción de pago no válida.")

    return redirect("validacion_pagos_pendientes")



@login_required
def codigos_responsable_pendientes(request):
    """
    Bandeja de Trabajo Social para generar/resetear códigos de seguridad.

    Nuevo flujo:
    - Se muestran alumnos con inscripción FINALIZADA y pago validado.
    - Cada alumno puede tener varios responsables autorizados.
    - Cada responsable tiene su propio código.
    """
    if not usuario_puede_gestionar_codigo_responsable(request.user):
        messages.error(request, "No tienes permiso para generar códigos de seguridad.")
        return redirect("/")

    semestre = obtener_semestre_activo_operativo()

    if not semestre:
        messages.warning(
            request,
            "No hay semestre activo. La generación de códigos queda bloqueada; solo se permite consulta histórica."
        )
        inscripciones = []
    else:
        inscripciones_qs = (
            SolicitudInscripcion.objects
            .filter(
                estado="FINALIZADA",
                semestre=semestre,
            )
            .select_related(
                "solicitud_ingreso",
                "usuario_tutor",
                "semestre",
                "sala_semestre_asignada",
                "sala_semestre_asignada__sala",
            )
            .prefetch_related("codigos_responsables_autorizados")
            .order_by(
                "sala_semestre_asignada__sala__nombre",
                "solicitud_ingreso__apellido_paterno_menor",
                "solicitud_ingreso__nombres_menor",
            )
        )

        try:
            inscripciones_qs = inscripciones_qs.filter(
                Q(estado_pago="VALIDADO") | Q(pago_validado_en__isnull=False) | Q(pago_validado=True)
            ).distinct()
        except Exception:
            try:
                inscripciones_qs = inscripciones_qs.filter(
                    Q(estado_pago="VALIDADO") | Q(pago_validado_en__isnull=False)
                ).distinct()
            except Exception:
                pass

        inscripciones = [
            preparar_resumen_codigos_inscripcion(inscripcion)
            for inscripcion in inscripciones_qs
        ]

    return render(
        request,
        "admisiones/codigos_responsable_pendientes.html",
        {
            "inscripciones": inscripciones,
            "semestre": semestre,
            **contexto_semestre_operativo(),
        },
    )


@login_required
def generar_codigo_responsable(request, inscripcion_id):
    """
    Trabajo Social genera o resetea el código de 4 dígitos de una persona autorizada.
    El código visible solo se muestra una vez en esta pantalla.
    """
    if not usuario_puede_gestionar_codigo_responsable(request.user):
        messages.error(request, "No tienes permiso para generar códigos de seguridad.")
        return redirect("/")

    bloqueo = bloquear_si_no_hay_semestre_activo(request, "codigos_responsable_pendientes")
    if bloqueo:
        return bloqueo

    inscripcion = get_object_or_404(
        SolicitudInscripcion.objects.select_related(
            "solicitud_ingreso",
            "usuario_tutor",
            "semestre",
            "sala_semestre_asignada",
            "sala_semestre_asignada__sala",
        ),
        pk=inscripcion_id,
    )

    preparar_inscripcion_para_form_codigo(inscripcion)
    responsables_codigo = obtener_responsables_codigo_inscripcion(inscripcion)
    responsable_codigo = obtener_responsable_codigo_desde_request(request, inscripcion)

    codigo_generado = None
    es_reset = bool(responsable_codigo and responsable_codigo.tiene_codigo)

    if request.method == "POST":
        if not responsable_codigo:
            messages.error(
                request,
                "Selecciona el tutor o familiar autorizado al que se le generará el código."
            )
            form = GenerarCodigoResponsableForm(
                request.POST,
                alumno=inscripcion,
                es_reset=False,
            )
        else:
            form = GenerarCodigoResponsableForm(
                request.POST,
                alumno=inscripcion,
                es_reset=es_reset,
            )

            if form.is_valid():
                if hasattr(form, "generar_codigo"):
                    codigo_generado = form.generar_codigo()
                else:
                    codigo_generado = CodigoResponsableAutorizado.generar_codigo_plano()

                ok, mensaje = guardar_codigo_responsable_en_inscripcion(
                    inscripcion=inscripcion,
                    codigo=codigo_generado,
                    usuario=request.user,
                    motivo=form.cleaned_data.get("motivo", ""),
                    es_reset=es_reset,
                    responsable_autorizado=responsable_codigo,
                )

                if ok:
                    if es_reset:
                        messages.success(
                            request,
                            f"Código reseteado correctamente para {responsable_codigo.nombre_completo}."
                        )
                    else:
                        messages.success(
                            request,
                            f"Código generado correctamente para {responsable_codigo.nombre_completo}."
                        )

                    responsable_codigo.refresh_from_db()
                    responsables_codigo = obtener_responsables_codigo_inscripcion(inscripcion)

                    return render(
                        request,
                        "admisiones/generar_codigo_responsable.html",
                        {
                            "form": form,
                            "inscripcion": inscripcion,
                            "responsables_codigo": responsables_codigo,
                            "responsable_codigo": responsable_codigo,
                            "codigo_generado": codigo_generado,
                            "es_reset": es_reset,
                            **contexto_semestre_operativo(),
                        },
                    )

                messages.error(request, mensaje)

            else:
                messages.error(request, "No se pudo generar el código. Revisa las validaciones.")
    else:
        form = GenerarCodigoResponsableForm(
            alumno=inscripcion,
            es_reset=es_reset,
        )

    return render(
        request,
        "admisiones/generar_codigo_responsable.html",
        {
            "form": form,
            "inscripcion": inscripcion,
            "responsables_codigo": responsables_codigo,
            "responsable_codigo": responsable_codigo,
            "codigo_generado": codigo_generado,
            "es_reset": es_reset,
            **contexto_semestre_operativo(),
        },
    )


@login_required
def confirmar_entrega_codigo_responsable(request, inscripcion_id):
    """
    Registra que Trabajo Social entregó credencial y código a una persona autorizada.
    Esta vista no muestra el código; solo confirma evidencia de entrega.
    """
    if not usuario_puede_gestionar_codigo_responsable(request.user):
        messages.error(request, "No tienes permiso para confirmar entrega de códigos.")
        return redirect("/")

    inscripcion = get_object_or_404(
        SolicitudInscripcion.objects.select_related(
            "solicitud_ingreso",
            "usuario_tutor",
            "semestre",
            "sala_semestre_asignada",
            "sala_semestre_asignada__sala",
        ),
        pk=inscripcion_id,
    )

    responsables_codigo = obtener_responsables_codigo_inscripcion(inscripcion)
    responsable_codigo = obtener_responsable_codigo_desde_request(request, inscripcion)

    if not responsable_codigo:
        messages.warning(
            request,
            "Selecciona el tutor o familiar autorizado al que se le entregó el código."
        )
        return redirect("generar_codigo_responsable", inscripcion_id=inscripcion.id)

    if not responsable_codigo.tiene_codigo:
        messages.warning(
            request,
            "Primero debes generar el código de seguridad de este responsable antes de confirmar su entrega."
        )
        return redirect(
            f"{reverse('generar_codigo_responsable', kwargs={'inscripcion_id': inscripcion.id})}?responsable_codigo_id={responsable_codigo.id}"
        )

    if request.method == "POST":
        form = ConfirmarEntregaCodigoResponsableForm(request.POST)

        if form.is_valid():
            cambio = registrar_entrega_codigo_en_inscripcion(
                inscripcion,
                form,
                request.user,
                responsable_autorizado=responsable_codigo,
            )

            if cambio:
                messages.success(
                    request,
                    f"Entrega de código y credencial registrada para {responsable_codigo.nombre_completo}."
                )
            else:
                messages.warning(
                    request,
                    "El formulario es válido, pero no se pudo guardar la entrega."
                )

            return redirect("codigos_responsable_pendientes")

        messages.error(request, "No se pudo confirmar la entrega. Revisa los campos.")

    else:
        form = ConfirmarEntregaCodigoResponsableForm()

    return render(
        request,
        "admisiones/confirmar_entrega_codigo_responsable.html",
        {
            "form": form,
            "inscripcion": inscripcion,
            "responsables_codigo": responsables_codigo,
            "responsable_codigo": responsable_codigo,
            **contexto_semestre_operativo(),
        },
    )


@login_required
def lista_semestres(request):
    """
    Sprint 4 / Épica 3:
    Panel principal de configuración de semestres para Administrador del Sistema.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede configurar semestres.")
        return redirect("/")

    # No se crea sede automática. Si no hay sedes, la tabla aparecerá vacía
    # y el Administrador deberá usar el botón "Crear sede".
    asegurar_sede_inicial()

    semestres = (
        Semestre.objects
        .select_related(
            "sede_configurada",
            "medico_asignado",
            "nutriologa_asignada",
            "psicologa_asignada",
        )
        .order_by("-fecha_inicio", "-created_at")
    )

    sedes = Sede.objects.order_by("nombre")
    semestre_activo = semestres.filter(estado=Semestre.EstadoSemestre.ACTIVO).first()
    ultimo_semestre_cerrado = semestres.filter(
        estado=Semestre.EstadoSemestre.CERRADO
    ).first()

    puede_clonar_semestre = bool(ultimo_semestre_cerrado and not semestre_activo)

    if semestre_activo:
        motivo_bloqueo_clonar = "Cierra el semestre activo para poder clonar uno anterior."
    elif not ultimo_semestre_cerrado:
        motivo_bloqueo_clonar = "Todavía no hay un semestre cerrado para clonar."
    else:
        motivo_bloqueo_clonar = ""

    return render(
        request,
        "admisiones/semestres/lista_semestres.html",
        {
            "semestres": semestres,
            "sedes": sedes,
            "semestre_activo": semestre_activo,
            "ultimo_semestre_cerrado": ultimo_semestre_cerrado,
            "puede_clonar_semestre": puede_clonar_semestre,
            "motivo_bloqueo_clonar": motivo_bloqueo_clonar,
            **contexto_semestre_operativo(),
        },
    )

@login_required
def crear_sede(request):
    """
    Crea una sede para operar de forma segmentada.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede crear sedes.")
        return redirect("/")

    if request.method == "POST":
        form = SedeForm(request.POST)

        if form.is_valid():
            form.save()
            messages.success(request, "Sede creada correctamente.")
            return redirect_con_origen(request, "lista_semestres")

        messages.error(request, "No se pudo crear la sede. Revisa los campos.")

    else:
        form = SedeForm()

    return render(
        request,
        "admisiones/semestres/form_sede.html",
        {
            "form": form,
            "titulo": "Crear sede",
            "origen": obtener_origen_sprint4(request),
        },
    )


@login_required
def editar_sede(request, sede_id):
    """
    Modifica una sede existente.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede modificar sedes.")
        return redirect("/")

    sede = get_object_or_404(Sede, pk=sede_id)

    if request.method == "POST":
        form = SedeForm(request.POST, instance=sede)

        if form.is_valid():
            form.save()
            messages.success(request, "Sede actualizada correctamente.")
            return redirect_con_origen(request, "lista_semestres")

        messages.error(request, "No se pudo actualizar la sede. Revisa los campos.")

    else:
        form = SedeForm(instance=sede)

    return render(
        request,
        "admisiones/semestres/form_sede.html",
        {
            "form": form,
            "sede": sede,
            "titulo": "Editar sede",
            "origen": obtener_origen_sprint4(request),
        },
    )


@login_required
def crear_semestre(request):
    """
    Crea un semestre en estado CONFIGURACION/BORRADOR.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede crear semestres.")
        return redirect("/")

    if not Sede.objects.exists():
        messages.warning(
            request,
            "Primero debes crear una sede antes de registrar un semestre."
        )
        return redirect_con_origen(request, "crear_sede")

    if request.method == "POST":
        form = SemestreForm(request.POST)

        if form.is_valid():
            semestre = form.save(commit=False)

            # Mantener compatibilidad con campo antiguo sede.
            if semestre.sede_configurada:
                semestre.sede = semestre.sede_configurada.clave

            semestre.estado = Semestre.EstadoSemestre.CONFIGURACION
            semestre.save()

            messages.success(request, "Semestre creado correctamente. Ahora configura salas, días y maestras.")
            return redirect_con_origen(request, "detalle_semestre", semestre_id=semestre.id)

        messages.error(request, "No se pudo crear el semestre. Revisa los campos.")

    else:
        form = SemestreForm()

    return render(
        request,
        "admisiones/semestres/form_semestre.html",
        {
            "form": form,
            "titulo": "Crear semestre",
        },
    )


@login_required
def clonar_semestre(request, semestre_id):
    """
    Crea un nuevo semestre copiando la configuración operativa de un semestre cerrado.

    Reglas:
    - Solo Administrador del Sistema.
    - Solo se puede clonar un semestre CERRADO.
    - No se puede clonar mientras exista un semestre ACTIVO.
    - Se copian sede, personal institucional, salas, cupos, horarios y maestras.
    - No se copian alumnos, encuestas, respuestas, incidencias, bitácoras ni calendario operativo.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede clonar semestres.")
        return redirect("/")

    semestre_origen = get_object_or_404(
        Semestre.objects.select_related(
            "sede_configurada",
            "medico_asignado",
            "nutriologa_asignada",
            "psicologa_asignada",
        ),
        pk=semestre_id,
    )

    if semestre_origen.estado != Semestre.EstadoSemestre.CERRADO:
        messages.warning(
            request,
            "Solo se puede clonar un semestre cerrado. Primero cierra el semestre actual."
        )
        return redirect_con_origen(request, "lista_semestres")

    semestre_activo = Semestre.objects.filter(
        estado=Semestre.EstadoSemestre.ACTIVO
    ).first()

    if semestre_activo:
        messages.warning(
            request,
            "No se puede clonar mientras exista un semestre activo. Primero cierra el semestre activo."
        )
        return redirect_con_origen(request, "lista_semestres")

    if request.method == "POST":
        post_data = request.POST.copy()

        # Compatibilidad visual:
        # si el template usado no muestra el checkbox confirmar,
        # el botón de guardar funciona como confirmación.
        post_data.setdefault("confirmar", "on")

        form = ClonarSemestreForm(
            post_data,
            semestre_origen=semestre_origen,
        )

        if form.is_valid():
            try:
                nuevo_semestre = form.crear_semestre_clonado(usuario=request.user)
            except Exception as exc:
                messages.error(
                    request,
                    f"No se pudo clonar el semestre: {exc}"
                )
            else:
                messages.success(
                    request,
                    "Semestre clonado correctamente. Revisa fechas, horarios y personal antes de iniciarlo."
                )
                return redirect_con_origen(
                    request,
                    "detalle_semestre",
                    semestre_id=nuevo_semestre.id,
                )

        else:
            messages.error(request, "No se pudo clonar el semestre. Revisa los campos.")
            for campo, errores in form.errors.items():
                for error in errores:
                    messages.error(request, f"{campo}: {error}")

    else:
        form = ClonarSemestreForm(semestre_origen=semestre_origen)

    return render(
        request,
        "admisiones/semestres/form_semestre.html",
        {
            "form": form,
            "semestre": semestre_origen,
            "semestre_origen": semestre_origen,
            "titulo": "Clonar semestre",
            "modo_clonar": True,
            "origen": obtener_origen_sprint4(request),
        },
    )

@login_required
def editar_semestre(request, semestre_id):
    """
    Modifica la configuración principal del semestre.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede modificar semestres.")
        return redirect("/")

    semestre = get_object_or_404(Semestre, pk=semestre_id)

    if semestre_esta_cerrado(semestre):
        messages.warning(request, "No se puede modificar un semestre cerrado.")
        return redirect_con_origen(request, "detalle_semestre", semestre_id=semestre.id)

    if request.method == "POST":
        form = SemestreForm(request.POST, instance=semestre)

        if form.is_valid():
            semestre = form.save(commit=False)

            if semestre.sede_configurada:
                semestre.sede = semestre.sede_configurada.clave

            semestre.save()
            messages.success(request, "Semestre actualizado correctamente.")
            return redirect_con_origen(request, "detalle_semestre", semestre_id=semestre.id)

        messages.error(request, "No se pudo actualizar el semestre. Revisa los campos.")

    else:
        form = SemestreForm(instance=semestre)

    return render(
        request,
        "admisiones/semestres/form_semestre.html",
        {
            "form": form,
            "semestre": semestre,
            "titulo": "Modificar semestre",
        },
    )


@login_required
def detalle_semestre(request, semestre_id):
    """
    Vista centralizada del semestre:
    - datos principales
    - días festivos/suspensiones
    - salas
    - maestras
    - horarios
    - alumnos asignados
    - incidencias
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede consultar la configuración de semestres.")
        return redirect("/")

    semestre = get_object_or_404(
        Semestre.objects.select_related(
            "sede_configurada",
            "medico_asignado",
            "nutriologa_asignada",
            "psicologa_asignada",
            "iniciado_por",
            "cerrado_por",
        ),
        pk=semestre_id,
    )

    dias_festivos = semestre.dias_festivos.order_by("fecha")
    salas_semestre = (
        semestre.salas_activas
        .select_related("sala", "sala__sede")
        .prefetch_related("maestras_asignadas", "maestras_asignadas__maestra")
        .order_by("sala__nombre")
    )
    dias_operativos_qs = semestre.dias_operativos.order_by("fecha")
    dias_operativos_habiles_qs = dias_operativos_qs.filter(es_habil=True)
    dias_inhabiles_qs = dias_operativos_qs.filter(es_habil=False)

    total_dias_calendario = dias_operativos_qs.count()
    total_dias_operativos = dias_operativos_habiles_qs.count()
    dias_inhabiles = dias_inhabiles_qs.count()
    dias_fin_semana = sum(1 for dia in dias_operativos_qs if dia_operativo_es_fin_de_semana(dia))

    dias_operativos_abiertos = dias_operativos_habiles_qs.filter(
        estado=DiaOperativoSemestre.EstadoDia.ABIERTO,
    ).count()
    dias_operativos_cerrados = dias_operativos_habiles_qs.filter(
        estado=DiaOperativoSemestre.EstadoDia.CERRADO,
    ).count()
    calendario_operativo_generado = total_dias_calendario > 0
    dias_operativos = dias_operativos_qs[:15]

    alumnos = (
        SolicitudInscripcion.objects
        .filter(semestre=semestre)
        .select_related("solicitud_ingreso", "sala_semestre_asignada", "sala_semestre_asignada__sala")
        .order_by("sala_semestre_asignada__sala__nombre", "solicitud_ingreso__apellido_paterno_menor")
    )
    incidencias_abiertas = semestre.incidencias.filter(
        estado=Incidencia.EstadoIncidencia.ABIERTA
    ).select_related("alumno", "alumno__solicitud_ingreso")

    return render(
        request,
        "admisiones/semestres/detalle_semestre.html",
        {
            "semestre": semestre,
            "dias_festivos": dias_festivos,
            "salas_semestre": salas_semestre,
            "dias_operativos": dias_operativos,
            "total_dias_calendario": total_dias_calendario,
            "total_dias_operativos": total_dias_operativos,
            "dias_inhabiles": dias_inhabiles,
            "dias_fin_semana": dias_fin_semana,
            "dias_operativos_abiertos": dias_operativos_abiertos,
            "dias_operativos_cerrados": dias_operativos_cerrados,
            "calendario_operativo_generado": calendario_operativo_generado,
            "alumnos": alumnos,
            "incidencias_abiertas": incidencias_abiertas,
            "resumen": construir_resumen_semestre(semestre),
            "errores_inicio": semestre.validar_para_iniciar(),
            "errores_cierre": semestre.validar_para_cerrar() if semestre_esta_cerrado(semestre) is False and semestre.estado == Semestre.EstadoSemestre.ACTIVO else [],
            "semestre_solo_lectura": not semestre_permite_edicion_admin(semestre),
            **contexto_semestre_operativo(),
        },
    )


@login_required
def agregar_dia_festivo(request, semestre_id):
    """
    Agrega día festivo o suspensión al semestre.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede configurar días del semestre.")
        return redirect("/")

    semestre = get_object_or_404(Semestre, pk=semestre_id)

    bloqueo_cerrado = bloquear_si_semestre_no_editable(request, semestre)
    if bloqueo_cerrado:
        return bloqueo_cerrado

    if request.method == "POST":
        form = DiaFestivoForm(request.POST, semestre=semestre)

        if form.is_valid():
            form.save()

            # Si el calendario ya existe, se actualiza para que el día capturado
            # quede como inhábil y no bloquee el cierre del semestre.
            if semestre.dias_operativos.exists():
                semestre.generar_dias_operativos()

            messages.success(request, "Día festivo/suspensión agregado correctamente.")
            return redirect_con_origen(request, "detalle_semestre", semestre_id=semestre.id)

        messages.error(request, "No se pudo agregar el día. Revisa los campos.")

    else:
        form = DiaFestivoForm(semestre=semestre)

    return render(
        request,
        "admisiones/semestres/form_dia_festivo.html",
        {
            "form": form,
            "semestre": semestre,
            "titulo": "Agregar día festivo o suspensión",
        },
    )


@login_required
def eliminar_dia_festivo(request, dia_id):
    """
    Elimina un día festivo/suspensión.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede eliminar días del semestre.")
        return redirect("/")

    dia = get_object_or_404(DiaFestivo.objects.select_related("semestre"), pk=dia_id)
    semestre_id = dia.semestre_id

    bloqueo_cerrado = bloquear_si_semestre_no_editable(request, dia.semestre)
    if bloqueo_cerrado:
        return bloqueo_cerrado

    if request.method == "POST":
        semestre = dia.semestre
        dia.delete()

        # Recalcula el calendario si ya estaba generado.
        # Sábados y domingos siguen siendo inhábiles automáticos.
        if semestre.dias_operativos.exists():
            semestre.generar_dias_operativos()

        messages.success(request, "Día eliminado correctamente.")

    return redirect_con_origen(request, "detalle_semestre", semestre_id=semestre_id)


@login_required
def crear_sala(request):
    """
    Crea una sala base del catálogo.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede crear salas.")
        return redirect("/")

    if not Sede.objects.exists():
        messages.warning(
            request,
            "Primero debes crear una sede antes de registrar salas."
        )
        return redirect_con_origen(request, "crear_sede")

    if request.method == "POST":
        form = SalaForm(request.POST)

        if form.is_valid():
            form.save()
            messages.success(request, "Sala creada correctamente.")
            return redirect_con_origen(request, "lista_semestres")

        messages.error(request, "No se pudo crear la sala. Revisa los campos.")

    else:
        form = SalaForm()

    return render(
        request,
        "admisiones/semestres/form_sala.html",
        {
            "form": form,
            "titulo": "Crear sala",
        },
    )


@login_required
def editar_sala(request, sala_id):
    """
    Modifica sala base del catálogo.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede modificar salas.")
        return redirect("/")

    sala = get_object_or_404(Sala, pk=sala_id)

    if request.method == "POST":
        form = SalaForm(request.POST, instance=sala)

        if form.is_valid():
            form.save()
            messages.success(request, "Sala actualizada correctamente.")
            return redirect_con_origen(request, "lista_semestres")

        messages.error(request, "No se pudo actualizar la sala. Revisa los campos.")

    else:
        form = SalaForm(instance=sala)

    return render(
        request,
        "admisiones/semestres/form_sala.html",
        {
            "form": form,
            "sala": sala,
            "titulo": "Editar sala",
        },
    )


@login_required
def agregar_sala_semestre(request, semestre_id):
    """
    Agrega una sala al semestre y captura sus horarios por sala.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede configurar salas de semestre.")
        return redirect("/")

    semestre = get_object_or_404(Semestre, pk=semestre_id)

    if semestre_esta_cerrado(semestre):
        messages.warning(request, "No se puede modificar un semestre cerrado.")
        return redirect_con_origen(request, "detalle_semestre", semestre_id=semestre.id)

    if request.method == "POST":
        form = SalaSemestreForm(request.POST, semestre=semestre)

        if form.is_valid():
            sala_semestre = form.save()

            messages.success(request, "Sala agregada/configurada correctamente.")
            return redirect_con_origen(request, "detalle_semestre", semestre_id=sala_semestre.semestre_id)

        messages.error(request, "No se pudo configurar la sala. Revisa los campos.")

    else:
        form = SalaSemestreForm(semestre=semestre)

    return render(
        request,
        "admisiones/semestres/form_sala_semestre.html",
        {
            "form": form,
            "semestre": semestre,
            "titulo": "Agregar sala al semestre",
        },
    )


@login_required
def editar_sala_semestre(request, sala_semestre_id):
    """
    Edita horarios/cupo de una sala dentro del semestre.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede modificar salas de semestre.")
        return redirect("/")

    sala_semestre = get_object_or_404(
        SalaSemestre.objects.select_related("semestre", "sala"),
        pk=sala_semestre_id,
    )
    semestre = sala_semestre.semestre

    if semestre_esta_cerrado(semestre):
        messages.warning(request, "No se puede modificar un semestre cerrado.")
        return redirect_con_origen(request, "detalle_semestre", semestre_id=semestre.id)

    if request.method == "POST":
        form = SalaSemestreForm(request.POST, instance=sala_semestre, semestre=semestre)

        if form.is_valid():
            form.save()
            messages.success(request, "Sala del semestre actualizada correctamente.")
            return redirect_con_origen(request, "detalle_semestre", semestre_id=semestre.id)

        messages.error(request, "No se pudo actualizar la sala. Revisa los campos.")

    else:
        form = SalaSemestreForm(instance=sala_semestre, semestre=semestre)

    return render(
        request,
        "admisiones/semestres/form_sala_semestre.html",
        {
            "form": form,
            "semestre": semestre,
            "sala_semestre": sala_semestre,
            "titulo": "Editar sala del semestre",
        },
    )


@login_required
def asignar_maestra_sala(request, sala_semestre_id):
    """
    Asigna maestra a sala.
    Una maestra puede estar en más de una sala.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede asignar maestras.")
        return redirect("/")

    sala_semestre = get_object_or_404(
        SalaSemestre.objects.select_related("semestre", "sala"),
        pk=sala_semestre_id,
    )

    if semestre_esta_cerrado(sala_semestre.semestre):
        messages.warning(request, "No se puede modificar un semestre cerrado.")
        return redirect_con_origen(request, "detalle_semestre", semestre_id=sala_semestre.semestre_id)

    if request.method == "POST":
        form = AsignacionMaestraForm(request.POST, sala_semestre=sala_semestre)

        if form.is_valid():
            form.save()
            messages.success(request, "Maestra asignada correctamente.")
            return redirect_con_origen(request, "detalle_semestre", semestre_id=sala_semestre.semestre_id)

        messages.error(request, "No se pudo asignar la maestra. Revisa los campos.")

    else:
        form = AsignacionMaestraForm(sala_semestre=sala_semestre)

    return render(
        request,
        "admisiones/semestres/form_asignacion_maestra.html",
        {
            "form": form,
            "sala_semestre": sala_semestre,
            "semestre": sala_semestre.semestre,
            "titulo": "Asignar maestra a sala",
        },
    )


@login_required
def editar_asignacion_maestra(request, asignacion_id):
    """
    Edita horario/rol de una maestra asignada.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede modificar maestras asignadas.")
        return redirect("/")

    asignacion = get_object_or_404(
        AsignacionMaestra.objects.select_related("sala_semestre", "sala_semestre__semestre", "sala_semestre__sala"),
        pk=asignacion_id,
    )
    sala_semestre = asignacion.sala_semestre

    if semestre_esta_cerrado(sala_semestre.semestre):
        messages.warning(request, "No se puede modificar un semestre cerrado.")
        return redirect_con_origen(request, "detalle_semestre", semestre_id=sala_semestre.semestre_id)

    if request.method == "POST":
        form = AsignacionMaestraForm(
            request.POST,
            instance=asignacion,
            sala_semestre=sala_semestre,
        )

        if form.is_valid():
            form.save()
            messages.success(request, "Asignación de maestra actualizada correctamente.")
            return redirect_con_origen(request, "detalle_semestre", semestre_id=sala_semestre.semestre_id)

        messages.error(request, "No se pudo actualizar la asignación. Revisa los campos.")

    else:
        form = AsignacionMaestraForm(instance=asignacion, sala_semestre=sala_semestre)

    return render(
        request,
        "admisiones/semestres/form_asignacion_maestra.html",
        {
            "form": form,
            "asignacion": asignacion,
            "sala_semestre": sala_semestre,
            "semestre": sala_semestre.semestre,
            "titulo": "Editar asignación de maestra",
        },
    )


@login_required
def eliminar_asignacion_maestra(request, asignacion_id):
    """
    Elimina una asignación de maestra.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede eliminar asignaciones.")
        return redirect("/")

    asignacion = get_object_or_404(
        AsignacionMaestra.objects.select_related("sala_semestre", "sala_semestre__semestre"),
        pk=asignacion_id,
    )
    semestre_id = asignacion.sala_semestre.semestre_id

    bloqueo_cerrado = bloquear_si_semestre_no_editable(request, asignacion.sala_semestre.semestre)
    if bloqueo_cerrado:
        return bloqueo_cerrado

    if request.method == "POST":
        asignacion.delete()
        messages.success(request, "Asignación eliminada correctamente.")

    return redirect_con_origen(request, "detalle_semestre", semestre_id=semestre_id)


@login_required
def iniciar_semestre(request, semestre_id):
    """
    Inicia semestre con validaciones:
    - todas las salas con maestra
    - todas las maestras activas asignadas
    - sede, fechas y personal de filtros asignado
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede iniciar semestres.")
        return redirect("/")

    semestre = get_object_or_404(Semestre, pk=semestre_id)

    if request.method != "POST":
        return redirect_con_origen(request, "detalle_semestre", semestre_id=semestre.id)

    form = IniciarSemestreForm(request.POST)

    if not form.is_valid():
        messages.error(request, "Debes confirmar el inicio del semestre.")
        return redirect_con_origen(request, "detalle_semestre", semestre_id=semestre.id)

    ok, errores = semestre.iniciar(usuario=request.user)

    if ok:
        messages.success(request, "Semestre iniciado correctamente. Se generaron los días operativos.")
    else:
        messages.error(request, "No se pudo iniciar el semestre.")
        for error in errores:
            messages.error(request, error)

    return redirect_con_origen(request, "detalle_semestre", semestre_id=semestre.id)


@login_required
def cerrar_semestre(request, semestre_id):
    """
    Cierra semestre si:
    - todos los días hábiles están cerrados
    - todas las incidencias están cerradas
    - la fecha fin ya venció
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede cerrar semestres.")
        return redirect("/")

    semestre = get_object_or_404(Semestre, pk=semestre_id)

    if request.method != "POST":
        return redirect_con_origen(request, "detalle_semestre", semestre_id=semestre.id)

    form = CerrarSemestreForm(request.POST)

    if not form.is_valid():
        messages.error(request, "Debes confirmar el cierre del semestre.")
        return redirect_con_origen(request, "detalle_semestre", semestre_id=semestre.id)

    observaciones = form.cleaned_data.get("observaciones", "").strip()

    if observaciones:
        semestre.observaciones = observaciones
        semestre.save(update_fields=["observaciones", "updated_at"])

    ok, errores = semestre.cerrar(usuario=request.user)

    if ok:
        messages.success(request, "Semestre cerrado correctamente.")
    else:
        messages.error(request, "No se pudo cerrar el semestre.")
        for error in errores:
            messages.error(request, error)

    return redirect_con_origen(request, "detalle_semestre", semestre_id=semestre.id)


@login_required
def generar_dias_operativos_semestre(request, semestre_id):
    """
    Genera o actualiza el calendario operativo del semestre.

    Días operativos = días hábiles/laborales dentro del periodo del semestre.
    Sirven para controlar asistencia, bitácoras, incidencias y cierre del semestre.

    Si ya existen, no se duplican. Por eso puede regresar total=0.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede generar el calendario operativo.")
        return redirect("/")

    semestre = get_object_or_404(Semestre, pk=semestre_id)

    bloqueo_cerrado = bloquear_si_semestre_no_editable(request, semestre)
    if bloqueo_cerrado:
        return bloqueo_cerrado

    if request.method != "POST":
        messages.info(
            request,
            "El calendario operativo se genera desde el botón del detalle del semestre."
        )
        return redirect_con_origen(request, "detalle_semestre", semestre_id=semestre.id)

    total_nuevos = semestre.generar_dias_operativos()
    dias_despues = semestre.dias_operativos.count()

    if total_nuevos > 0:
        messages.success(
            request,
            (
                f"Calendario operativo generado correctamente. Nuevos días creados: {total_nuevos}. "
                "Sábados, domingos y días inhábiles quedan cerrados automáticamente y no bloquean el cierre."
            )
        )
    elif dias_despues > 0:
        messages.info(
            request,
            "El calendario operativo ya estaba actualizado. No se crearon días nuevos."
        )
    else:
        messages.warning(
            request,
            "No se generaron días operativos. Revisa que el semestre tenga fecha de inicio, fecha fin "
            "y que el periodo incluya días hábiles."
        )

    return redirect_con_origen(request, "detalle_semestre", semestre_id=semestre.id)


@login_required
def cerrar_dia_operativo(request, dia_id):
    """
    Cierra un día operativo individual.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede cerrar días operativos.")
        return redirect("/")

    dia = get_object_or_404(DiaOperativoSemestre.objects.select_related("semestre"), pk=dia_id)

    bloqueo_cerrado = bloquear_si_semestre_no_editable(request, dia.semestre)
    if bloqueo_cerrado:
        return bloqueo_cerrado

    if request.method == "POST":
        if not dia_operativo_es_laborable(dia):
            messages.info(
                request,
                mensaje_dia_no_operativo(dia)
                or "Este día no es laborable y queda cerrado automáticamente; no requiere cierre manual."
            )
            return redirect_con_origen(request, "detalle_semestre", semestre_id=dia.semestre_id)

        form = CerrarDiaOperativoForm(request.POST, instance=dia)

        if form.is_valid():
            observaciones = form.cleaned_data.get("observaciones", "")

            incidencias_abiertas_dia = Incidencia.objects.filter(
                dia_operativo=dia,
                estado=Incidencia.EstadoIncidencia.ABIERTA,
            ).count()

            if incidencias_abiertas_dia:
                messages.warning(
                    request,
                    f"Este día tiene {incidencias_abiertas_dia} incidencia(s) abierta(s). "
                    "El cierre del día puede continuar, pero deberán cerrarse antes del cierre del semestre."
                )

            ok, errores = dia.cerrar(usuario=request.user, observaciones=observaciones)

            if ok:
                messages.success(request, "Día operativo cerrado correctamente.")
            else:
                messages.error(request, "No se pudo cerrar el día operativo.")
                for error in errores:
                    messages.error(request, error)
        else:
            messages.error(request, "No se pudo cerrar el día operativo.")

    return redirect_con_origen(request, "detalle_semestre", semestre_id=dia.semestre_id)


@login_required
def enviar_encuesta_satisfaccion(request, semestre_id):
    """
    Vista de Encuesta de Satisfacción B.

    Funciones:
    - Preparar envíos por alumno/tutor.
    - Enviar encuesta al correo institucional del tutor.
    - Mostrar estado por alumno.
    - Permitir ver respuestas individuales.
    - Preparar descarga CSV semestral desde otra vista.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede gestionar encuestas.")
        return redirect("/")

    semestre = get_object_or_404(Semestre, pk=semestre_id)
    asegurar_envios_encuesta_semestre(semestre)

    if request.method == "POST":
        form = EnviarEncuestaSatisfaccionForm(request.POST, semestre=semestre)

        if form.is_valid():
            correo_copia = (form.cleaned_data.get("correo_copia") or "").strip().lower()
            envios = obtener_envios_encuesta_semestre(semestre)

            if not envios.exists():
                messages.warning(
                    request,
                    "No hay alumnos finalizados/asignados a este semestre para enviar la encuesta."
                )
                return redirect_con_origen(request, "enviar_encuesta_satisfaccion", semestre_id=semestre.id)

            enviados = 0
            bloqueados = 0
            errores = []

            for envio in envios:
                if envio.estado == EnvioEncuestaSatisfaccion.EstadoEnvio.CONTESTADA:
                    continue

                ok, mensaje = enviar_correo_encuesta_individual(
                    request,
                    envio,
                    usuario=request.user,
                    correo_copia=correo_copia,
                    es_reenvio=envio.estado in [
                        EnvioEncuestaSatisfaccion.EstadoEnvio.ENVIADA,
                        EnvioEncuestaSatisfaccion.EstadoEnvio.REENVIADA,
                        EnvioEncuestaSatisfaccion.EstadoEnvio.ERROR,
                    ],
                )

                if ok:
                    enviados += 1
                else:
                    if envio.estado == EnvioEncuestaSatisfaccion.EstadoEnvio.BLOQUEADA:
                        bloqueados += 1
                    errores.append(f"{envio.correo_destino or 'Sin correo'}: {mensaje}")

            semestre.encuesta_enviada = enviados > 0 or semestre.encuesta_enviada
            if enviados:
                semestre.fecha_envio_encuesta = timezone.now()
            semestre.correo_copia_encuesta = correo_copia
            semestre.save(update_fields=[
                "encuesta_enviada",
                "fecha_envio_encuesta",
                "correo_copia_encuesta",
                "updated_at",
            ])

            if enviados:
                messages.success(request, f"Encuesta enviada correctamente a {enviados} tutor(es).")

            if bloqueados:
                messages.warning(
                    request,
                    f"{bloqueados} envío(s) quedaron bloqueados porque el correo del tutor no es @unach.mx."
                )

            for error in errores[:5]:
                messages.warning(request, f"No se pudo enviar: {error}")

            if len(errores) > 5:
                messages.warning(request, f"Hubo {len(errores) - 5} errores adicionales.")

            return redirect_con_origen(request, "enviar_encuesta_satisfaccion", semestre_id=semestre.id)

        messages.error(request, "No se pudo enviar la encuesta. Revisa los campos.")

    else:
        form = EnviarEncuestaSatisfaccionForm(semestre=semestre)

    envios = obtener_envios_encuesta_semestre(semestre)

    return render(
        request,
        "admisiones/semestres/enviar_encuesta.html",
        {
            "form": form,
            "semestre": semestre,
            "envios_encuesta": envios,
            "resumen_encuesta": resumen_envios_encuesta(envios),
            "titulo": "Encuesta de Satisfacción B",
        },
    )


@login_required
def reenviar_encuesta_satisfaccion(request, envio_id):
    """
    Reenvía la Encuesta B a un tutor específico.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede reenviar encuestas.")
        return redirect("/")

    envio = get_object_or_404(
        EnvioEncuestaSatisfaccion.objects.select_related(
            "semestre",
            "inscripcion",
            "inscripcion__solicitud_ingreso",
            "tutor",
        ),
        pk=envio_id,
    )

    if request.method != "POST":
        return redirect_con_origen(request, "enviar_encuesta_satisfaccion", semestre_id=envio.semestre_id)

    correo_copia = envio.semestre.correo_copia_encuesta or envio.correo_copia or ""

    ok, mensaje = enviar_correo_encuesta_individual(
        request,
        envio,
        usuario=request.user,
        correo_copia=correo_copia,
        es_reenvio=True,
    )

    if ok:
        messages.success(request, "Encuesta reenviada correctamente.")
    else:
        messages.error(request, f"No se pudo reenviar la encuesta: {mensaje}")

    return redirect_con_origen(request, "enviar_encuesta_satisfaccion", semestre_id=envio.semestre_id)


@login_required
def ver_respuesta_encuesta_satisfaccion(request, envio_id):
    """
    Muestra las respuestas individuales de un alumno/tutor.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede consultar respuestas.")
        return redirect("/")

    envio = get_object_or_404(
        EnvioEncuestaSatisfaccion.objects.select_related(
            "semestre",
            "inscripcion",
            "inscripcion__solicitud_ingreso",
            "tutor",
        ),
        pk=envio_id,
    )

    respuesta = envio.respuesta

    return render(
        request,
        "admisiones/semestres/ver_respuesta_encuesta.html",
        {
            "envio": envio,
            "semestre": envio.semestre,
            "respuesta": respuesta,
            "preguntas": preguntas_encuesta_satisfaccion(respuesta),
            "titulo": "Respuestas de Encuesta B",
        },
    )


def responder_encuesta_satisfaccion(request, token):
    """
    Formulario público para que el tutor responda la Encuesta B desde el enlace del correo.
    """
    envio = get_object_or_404(
        EnvioEncuestaSatisfaccion.objects.select_related(
            "semestre",
            "inscripcion",
            "inscripcion__solicitud_ingreso",
            "tutor",
        ),
        token=token,
    )

    if not envio.correo_institucional_valido:
        return render(
            request,
            "admisiones/semestres/responder_encuesta.html",
            {
                "envio": envio,
                "semestre": envio.semestre,
                "bloqueada": True,
                "mensaje_error": "El correo del tutor no es institucional. Comuníquese con la Estancia Infantil UNACH.",
            },
        )

    if not envio.tutor_id:
        return render(
            request,
            "admisiones/semestres/responder_encuesta.html",
            {
                "envio": envio,
                "semestre": envio.semestre,
                "bloqueada": True,
                "mensaje_error": "No existe una cuenta de tutor vinculada a esta inscripción.",
            },
        )

    respuesta_existente = envio.respuesta

    if request.method == "POST":
        defaults = {
            "tutor": envio.tutor,
            "q1_info_completa": valor_booleano_encuesta(request.POST, "q1_info_completa"),
            "q2_seguro": valor_booleano_encuesta(request.POST, "q2_seguro"),
            "q3_orientacion_nutricion": valor_booleano_encuesta(request.POST, "q3_orientacion_nutricion"),
            "q4_orientacion_medica": valor_booleano_encuesta(request.POST, "q4_orientacion_medica"),
            "q5_orientacion_pedagogica": valor_booleano_encuesta(request.POST, "q5_orientacion_pedagogica"),
            "q6_orientacion_psicologica": valor_booleano_encuesta(request.POST, "q6_orientacion_psicologica"),
            "q7_apoyo_estudios": valor_booleano_encuesta(request.POST, "q7_apoyo_estudios"),
            "comentarios": (request.POST.get("comentarios") or "").strip(),
        }

        respuesta, _ = EncuestaSatisfaccion.objects.update_or_create(
            semestre=envio.semestre,
            inscripcion=envio.inscripcion,
            defaults=defaults,
        )

        envio.marcar_contestada()

        return render(
            request,
            "admisiones/semestres/responder_encuesta.html",
            {
                "envio": envio,
                "semestre": envio.semestre,
                "respuesta": respuesta,
                "contestada": True,
            },
        )

    return render(
        request,
        "admisiones/semestres/responder_encuesta.html",
        {
            "envio": envio,
            "semestre": envio.semestre,
            "respuesta": respuesta_existente,
        },
    )


@login_required
def descargar_csv_encuesta_satisfaccion(request, semestre_id):
    """
    Descarga el archivo plano CSV semestral con todas las respuestas de Encuesta B.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede descargar respuestas.")
        return redirect("/")

    semestre = get_object_or_404(Semestre, pk=semestre_id)
    envios = obtener_envios_encuesta_semestre(semestre)

    nombre_archivo = f"encuesta_b_{semestre.id}_{semestre.nombre}".replace(" ", "_").replace("/", "-")

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{nombre_archivo}.csv"'
    response.write("\ufeff")

    writer = csv.writer(response)
    writer.writerow([
        "Semestre",
        "Sede",
        "Folio",
        "Alumno",
        "Tutor",
        "Correo institucional",
        "Sala",
        "Estado envío",
        "Fecha envío",
        "Fecha reenvío",
        "Fecha respuesta",
        "Puntaje",
        "Nivel satisfacción",
        "Pregunta 1",
        "Respuesta 1",
        "Pregunta 2",
        "Respuesta 2",
        "Pregunta 3",
        "Respuesta 3",
        "Pregunta 4",
        "Respuesta 4",
        "Pregunta 5",
        "Respuesta 5",
        "Pregunta 6",
        "Respuesta 6",
        "Pregunta 7",
        "Respuesta 7",
        "Comentarios",
        "Último error",
    ])

    for envio in envios:
        inscripcion = envio.inscripcion
        solicitud = inscripcion.solicitud_ingreso
        respuesta = envio.respuesta
        preguntas = preguntas_encuesta_satisfaccion(respuesta)
        sala = ""

        if inscripcion.sala_semestre_asignada and inscripcion.sala_semestre_asignada.sala:
            sala = inscripcion.sala_semestre_asignada.sala.nombre

        fila = [
            semestre.nombre,
            semestre.sede_nombre,
            solicitud.folio or "",
            solicitud.nombre_menor_completo() if hasattr(solicitud, "nombre_menor_completo") else "",
            solicitud.nombre_tutor_completo() if hasattr(solicitud, "nombre_tutor_completo") else "",
            envio.correo_destino,
            sala,
            envio.get_estado_display(),
            timezone.localtime(envio.enviado_en).strftime("%d/%m/%Y %H:%M") if envio.enviado_en else "",
            timezone.localtime(envio.reenviado_en).strftime("%d/%m/%Y %H:%M") if envio.reenviado_en else "",
            timezone.localtime(respuesta.fecha_respuesta).strftime("%d/%m/%Y %H:%M") if respuesta else "",
            respuesta.puntaje_total if respuesta else "",
            respuesta.nivel_satisfaccion() if respuesta else "",
        ]

        for idx in range(7):
            if idx < len(preguntas):
                fila.extend([preguntas[idx][0], preguntas[idx][1]])
            else:
                fila.extend(["", ""])

        fila.extend([
            respuesta.comentarios if respuesta else "",
            envio.ultimo_error or "",
        ])

        writer.writerow(fila)

    return response


@login_required
def lista_asignacion_salas(request):
    """
    Lista alumnos FINALIZADOS pendientes o disponibles para asignar a semestre/sala.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede asignar salas.")
        return redirect("/")

    semestre_id = request.GET.get("semestre")
    semestre = None

    semestres = Semestre.objects.exclude(
        estado=Semestre.EstadoSemestre.CERRADO
    ).order_by("-fecha_inicio")

    if semestre_id:
        semestre = get_object_or_404(Semestre, pk=semestre_id)
    else:
        semestre = Semestre.obtener_activo() or semestres.first()

    inscripciones = (
        SolicitudInscripcion.objects
        .filter(estado="FINALIZADA")
        .select_related(
            "solicitud_ingreso",
            "semestre",
            "sala_semestre_asignada",
            "sala_semestre_asignada__sala",
        )
        .order_by("solicitud_ingreso__apellido_paterno_menor", "solicitud_ingreso__nombres_menor")
    )

    if semestre:
        # Mostrar alumnos de ese semestre y alumnos sin semestre para poder asignarlos.
        inscripciones = inscripciones.filter(Q(semestre=semestre) | Q(semestre__isnull=True))

    return render(
        request,
        "admisiones/semestres/lista_asignacion_salas.html",
        {
            "inscripciones": inscripciones,
            "semestres": semestres,
            "semestre": semestre,
        },
    )


@login_required
def asignar_sala_definitiva(request, inscripcion_id):
    """
    Asigna semestre/sala definitiva a alumno finalizado.
    """
    if not usuario_puede_configurar_semestres(request.user):
        messages.error(request, "Solo el Administrador del Sistema puede asignar sala definitiva.")
        return redirect("/")

    inscripcion = get_object_or_404(
        SolicitudInscripcion.objects.select_related(
            "solicitud_ingreso",
            "semestre",
            "sala_semestre_asignada",
        ),
        pk=inscripcion_id,
    )

    if inscripcion.estado != "FINALIZADA":
        messages.warning(request, "Solo se puede asignar sala a inscripciones finalizadas.")
        return redirect_con_origen(request, "lista_asignacion_salas")

    semestre_id = request.GET.get("semestre") or request.POST.get("semestre")
    semestre = None

    if semestre_id:
        semestre = get_object_or_404(Semestre, pk=semestre_id)

    if semestre and semestre.estado == Semestre.EstadoSemestre.CERRADO:
        messages.warning(request, "No se puede asignar alumnos a un semestre cerrado.")
        return redirect_con_origen(request, "lista_asignacion_salas")

    if request.method == "POST":
        form = AsignarAlumnoSalaForm(request.POST, instance=inscripcion, semestre=semestre)

        if form.is_valid():
            inscripcion = form.save(commit=False)
            inscripcion.sala_asignada_por = request.user
            inscripcion.sala_asignada_en = timezone.now()
            inscripcion.save()

            messages.success(request, "Sala definitiva asignada correctamente.")
            return redirect_con_origen(request, "lista_asignacion_salas")

        messages.error(request, "No se pudo asignar la sala. Revisa los campos.")

    else:
        form = AsignarAlumnoSalaForm(instance=inscripcion, semestre=semestre)

    return render(
        request,
        "admisiones/semestres/asignar_sala_definitiva.html",
        {
            "form": form,
            "inscripcion": inscripcion,
            "semestre": semestre,
            "titulo": "Asignar sala definitiva",
        },
    )


@login_required
def panel_incidencias(request):
    """
    Sprint 5 / Épica 3:
    Panel general de incidencias.

    Reglas:
    - Coordinadora ve/crea Pedagógicas.
    - Nutrióloga ve/crea Nutricionales.
    - Médica ve/crea Médicas.
    - Psicóloga ve/crea Psicológicas.
    - Directora y Administrador ven todas.
    - Si el usuario pertenece a un área operativa única, el tipo queda fijo
      aunque intenten cambiarlo desde la URL.
    """
    if not usuario_puede_ver_incidencias(request.user):
        messages.error(request, "No tienes permiso para consultar incidencias.")
        return redirect("/")

    tipos_visibles = tipos_incidencia_usuario(request.user, para_crear=False)
    tipos_creables = tipos_incidencia_usuario(request.user, para_crear=True)
    es_admin_actual = usuario_es_admin(request.user)
    es_directora_actual = usuario_es_directora(request.user)
    tipo_unico_operativo = tipo_incidencia_unico_usuario(request.user)

    incidencias = obtener_incidencias_visibles_para_usuario(request.user)

    estado = (request.GET.get("estado") or "").strip().upper()
    tipo_solicitado = normalizar_tipo_incidencia_param(request.GET.get("tipo"))
    nivel = (request.GET.get("nivel") or "").strip().upper()
    q = (request.GET.get("q") or "").strip()
    semestre_id = request.GET.get("semestre")

    # Si el usuario es de una sola área operativa, el tipo siempre se fija
    # por backend. Así no puede consultar otro tipo cambiando el parámetro URL.
    if usuario_es_area_operativa_incidencia_unica(request.user):
        tipo = tipo_unico_operativo
    else:
        tipo = tipo_solicitado

        if tipo and tipo not in tipos_visibles:
            messages.warning(
                request,
                "El tipo de incidencia solicitado no corresponde a tus permisos. Se omitió ese filtro."
            )
            tipo = None

    if estado in ["ABIERTA", "CERRADA"]:
        incidencias = incidencias.filter(estado=estado)

    if tipo:
        incidencias = incidencias.filter(tipo=tipo)

    if nivel in ["LEVE", "MEDIO", "ALTO", "BAJO"]:
        incidencias = incidencias.filter(nivel=nivel)

    if semestre_id:
        incidencias = incidencias.filter(semestre_id=semestre_id)

    if q:
        incidencias = incidencias.filter(
            Q(descripcion__icontains=q)
            | Q(intervencion_personal__icontains=q)
            | Q(resolucion__icontains=q)
            | Q(alumno__solicitud_ingreso__nombres_menor__icontains=q)
            | Q(alumno__solicitud_ingreso__apellido_paterno_menor__icontains=q)
            | Q(alumno__solicitud_ingreso__apellido_materno_menor__icontains=q)
            | Q(sala_semestre__sala__nombre__icontains=q)
        )

    resumen = {
        "total": incidencias.count(),
        "abiertas": incidencias.filter(estado=Incidencia.EstadoIncidencia.ABIERTA).count(),
        "cerradas": incidencias.filter(estado=Incidencia.EstadoIncidencia.CERRADA).count(),
        "alto": incidencias.filter(nivel=Incidencia.NivelChoices.ALTO).count(),
        "sin_seguimiento": incidencias.filter(seguimientos__isnull=True).distinct().count(),
    }

    return render(
        request,
        "admisiones/incidencias/panel_incidencias.html",
        {
            "incidencias": incidencias.order_by("-fecha_reporte"),
            "resumen": resumen,
            "tipos_creables": tipos_creables,
            "tipos_visibles": tipos_visibles,
            "tipo_unico_operativo": tipo_unico_operativo,
            "semestres": Semestre.objects.order_by("-fecha_inicio"),
            "filtros": {
                "estado": estado,
                "tipo": tipo or "",
                "nivel": nivel,
                "q": q,
                "semestre": semestre_id or "",
            },
            "puede_crear_alguna": bool(tipos_creables),
            "es_directora": es_directora_actual,
            "es_admin": es_admin_actual,
            **contexto_semestre_operativo(),
        },
    )


@login_required
def crear_incidencia(request, tipo=None):
    """
    Crea incidencia por tipo.

    Seguridad:
    - El tipo se fija por el rol/área del usuario.
    - Si alguien intenta cambiar el tipo por URL o manipulando el HTML,
      el backend lo rechaza o lo vuelve a fijar antes de guardar.
    """
    tipos_creables = tipos_incidencia_usuario(request.user, para_crear=True)

    if not tipos_creables:
        messages.error(request, "No tienes permiso para crear incidencias.")
        return redirect("panel_incidencias")

    tipo_solicitado = normalizar_tipo_incidencia_param(tipo or request.GET.get("tipo"))
    tipo_unico_operativo = tipo_incidencia_unico_usuario(request.user)

    if tipo_solicitado:
        if tipo_solicitado not in tipos_creables:
            messages.error(
                request,
                "No tienes permiso para crear ese tipo de incidencia. Tu área solo puede registrar incidencias autorizadas."
            )
            return redirect(url_panel_incidencias_por_tipo(tipo_unico_operativo))

        tipo_forzado = tipo_solicitado

    elif tipo_unico_operativo:
        tipo_forzado = tipo_unico_operativo

    else:
        messages.error(request, "Selecciona un tipo de incidencia válido.")
        return redirect("panel_incidencias")

    bloqueo = bloquear_si_no_hay_semestre_activo(
        request,
        url_panel_incidencias_por_tipo(tipo_forzado),
    )
    if bloqueo:
        return bloqueo

    semestre = obtener_semestre_activo_operativo()
    registro_diario = None
    registro_id = request.GET.get("registro_id") or request.POST.get("registro_diario_inicial")

    if registro_id:
        registro_diario = get_object_or_404(
            RegistroDiarioAlumno.objects.select_related(
                "alumno",
                "alumno__solicitud_ingreso",
                "dia_operativo",
                "dia_operativo__semestre",
                "sala_semestre",
                "sala_semestre__sala",
            ),
            pk=registro_id,
        )

        if semestre and registro_diario.dia_operativo and registro_diario.dia_operativo.semestre_id != semestre.id:
            messages.error(
                request,
                "El registro diario seleccionado no pertenece al semestre activo."
            )
            return redirect(url_panel_incidencias_por_tipo(tipo_forzado))

        if getattr(registro_diario.alumno, "estado", "") != "FINALIZADA":
            messages.error(
                request,
                "Solo se pueden registrar incidencias de niñas y niños con inscripción finalizada."
            )
            return redirect(url_panel_incidencias_por_tipo(tipo_forzado))

        if registro_diario.dia_operativo and not dia_operativo_es_laborable(registro_diario.dia_operativo):
            messages.warning(
                request,
                mensaje_dia_no_operativo(registro_diario.dia_operativo)
                or "No se pueden registrar incidencias operativas de menores en días inhábiles."
            )
            return redirect(url_panel_incidencias_por_tipo(tipo_forzado))

    if request.method == "POST":
        post_data = request.POST.copy()

        # Seguridad: se ignora cualquier valor manipulado desde el navegador.
        post_data["tipo"] = tipo_forzado

        if registro_diario:
            post_data["alumno"] = str(registro_diario.alumno_id)
            post_data["registro_diario"] = str(registro_diario.id)

        form = IncidenciaForm(
            post_data,
            request.FILES,
            semestre=semestre,
            usuario=request.user,
            tipo_forzado=tipo_forzado,
            registro_diario=registro_diario,
        )

        if form.is_valid():
            incidencia = form.save(commit=False)

            # Seguridad final antes de guardar.
            incidencia.tipo = tipo_forzado
            incidencia.registrada_por = request.user
            incidencia.estado = Incidencia.EstadoIncidencia.ABIERTA

            if semestre and not getattr(incidencia, "semestre_id", None):
                incidencia.semestre = semestre

            if registro_diario:
                incidencia.registro_diario = registro_diario
                incidencia.alumno = registro_diario.alumno
                incidencia.dia_operativo = registro_diario.dia_operativo
                incidencia.sala_semestre = registro_diario.sala_semestre
                incidencia.semestre = registro_diario.dia_operativo.semestre if registro_diario.dia_operativo else semestre

            elif getattr(incidencia, "registro_diario_id", None):
                # Si el formulario trae registro diario, sincroniza datos relacionados.
                try:
                    incidencia.registro_diario.refresh_from_db()
                    incidencia.alumno = incidencia.registro_diario.alumno
                    incidencia.dia_operativo = incidencia.registro_diario.dia_operativo
                    incidencia.sala_semestre = incidencia.registro_diario.sala_semestre
                    incidencia.semestre = (
                        incidencia.registro_diario.dia_operativo.semestre
                        if incidencia.registro_diario.dia_operativo
                        else semestre
                    )
                except Exception:
                    pass

            incidencia.save()

            if hasattr(form, "save_m2m"):
                form.save_m2m()

            archivos = request.FILES.getlist("archivos")
            guardados, errores_archivos = guardar_archivos_incidencia(
                incidencia,
                archivos,
                request.user,
            )

            if guardados:
                messages.success(request, f"Se adjuntaron {guardados} archivo(s) a la incidencia.")

            for error in errores_archivos[:5]:
                messages.warning(request, error)

            messages.success(request, "Incidencia registrada correctamente.")
            return redirect("detalle_incidencia", incidencia_id=incidencia.id)

        messages.error(request, "No se pudo crear la incidencia. Revisa los campos marcados.")

        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{field}: {error}")

    else:
        form = IncidenciaForm(
            semestre=semestre,
            usuario=request.user,
            tipo_forzado=tipo_forzado,
            registro_diario=registro_diario,
        )

    return render(
        request,
        "admisiones/incidencias/crear_incidencia.html",
        {
            "form": form,
            "tipo_forzado": tipo_forzado,
            "registro_diario": registro_diario,
            "semestre": semestre,
            "titulo": f"Crear incidencia {dict(Incidencia.TipoIncidencia.choices).get(tipo_forzado, '')}",
            **contexto_semestre_operativo(),
        },
    )


@login_required
def detalle_incidencia(request, incidencia_id):
    incidencia = get_object_or_404(
        Incidencia.objects
        .select_related(
            "alumno",
            "alumno__solicitud_ingreso",
            "semestre",
            "dia_operativo",
            "registro_diario",
            "sala_semestre",
            "sala_semestre__sala",
            "registrada_por",
            "cerrada_por",
        )
        .prefetch_related(
            "archivos",
            "seguimientos",
            "seguimientos__archivos",
        ),
        pk=incidencia_id,
    )

    if not usuario_puede_ver_incidencia(request.user, incidencia):
        messages.error(request, "No tienes permiso para consultar esta incidencia.")
        return redirect("panel_incidencias")

    return render(
        request,
        "admisiones/incidencias/detalle_incidencia.html",
        {
            "incidencia": incidencia,
            "seguimientos": incidencia.seguimientos.select_related("creado_por").prefetch_related("archivos"),
            "archivos": incidencia.archivos.select_related("subido_por"),
            "puede_agregar_seguimiento": incidencia.puede_agregar_seguimiento(request.user),
            "puede_cerrar": usuario_puede_cerrar_incidencia_sprint5(request.user, incidencia),
            "es_directora": usuario_es_directora(request.user),
            "es_admin": usuario_es_admin(request.user),
            **contexto_semestre_operativo(),
        },
    )


@login_required
def registrar_seguimiento_incidencia(request, incidencia_id):
    incidencia = get_object_or_404(
        Incidencia.objects.select_related(
            "alumno",
            "alumno__solicitud_ingreso",
            "semestre",
            "registrada_por",
        ),
        pk=incidencia_id,
    )

    if not usuario_puede_ver_incidencia(request.user, incidencia):
        messages.error(request, "No tienes permiso para consultar esta incidencia.")
        return redirect("panel_incidencias")

    bloqueo = bloquear_si_no_hay_semestre_activo(request, "panel_incidencias")
    if bloqueo:
        return bloqueo

    if not incidencia.puede_agregar_seguimiento(request.user):
        messages.error(request, "Solo la persona que creó la incidencia puede registrar seguimiento.")
        return redirect("detalle_incidencia", incidencia_id=incidencia.id)

    if request.method == "POST":
        form = SeguimientoIncidenciaForm(
            request.POST,
            request.FILES,
            incidencia=incidencia,
            usuario=request.user,
        )

        if form.is_valid():
            seguimiento = form.save()

            archivos = request.FILES.getlist("archivos")
            guardados, errores_archivos = guardar_archivos_seguimiento_incidencia(
                seguimiento,
                archivos,
                request.user,
            )

            if guardados:
                messages.success(request, f"Se adjuntaron {guardados} archivo(s) al seguimiento.")

            for error in errores_archivos[:5]:
                messages.warning(request, error)

            messages.success(request, "Seguimiento registrado correctamente.")
            return redirect("detalle_incidencia", incidencia_id=incidencia.id)

        messages.error(request, "No se pudo registrar el seguimiento. Revisa los campos.")

        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{field}: {error}")

    else:
        form = SeguimientoIncidenciaForm(
            incidencia=incidencia,
            usuario=request.user,
        )

    return render(
        request,
        "admisiones/incidencias/registrar_seguimiento.html",
        {
            "form": form,
            "incidencia": incidencia,
            **contexto_semestre_operativo(),
        },
    )


@login_required
def cerrar_incidencia(request, incidencia_id):
    """
    Cierre de incidencia Sprint 5.

    Validaciones:
    - Debe tener mínimo un seguimiento.
    - Puede cerrarse después del día de creación y antes del cierre del semestre.
    - Solo quien la creó o el Administrador del Sistema puede cerrarla.
    """
    incidencia = get_object_or_404(
        Incidencia.objects.select_related(
            "alumno",
            "alumno__solicitud_ingreso",
            "semestre",
            "registrada_por",
            "cerrada_por",
        ),
        pk=incidencia_id,
    )

    if not usuario_puede_ver_incidencia(request.user, incidencia):
        messages.error(request, "No tienes permiso para consultar esta incidencia.")
        return redirect("panel_incidencias")

    bloqueo = bloquear_si_no_hay_semestre_activo(request, "panel_incidencias")
    if bloqueo:
        return bloqueo

    if not usuario_puede_cerrar_incidencia_sprint5(request.user, incidencia):
        messages.error(request, "Solo puede cerrar la incidencia quien la creó o el Administrador del Sistema.")
        return redirect("detalle_incidencia", incidencia_id=incidencia.id)

    errores_cierre = incidencia.validar_para_cerrar(usuario=request.user)

    if request.method == "POST":
        form = CerrarIncidenciaForm(
            request.POST,
            instance=incidencia,
            incidencia=incidencia,
            usuario=request.user,
        )

        if form.is_valid():
            incidencia = form.save(commit=False)
            incidencia.cerrada_por = request.user
            incidencia.cerrada_en = timezone.now()
            incidencia.estado = Incidencia.EstadoIncidencia.CERRADA
            incidencia.resuelta = True
            incidencia.comentario_cierre = incidencia.resolucion
            incidencia.save()

            messages.success(request, "Incidencia cerrada correctamente.")
            return redirect("detalle_incidencia", incidencia_id=incidencia.id)

        messages.error(request, "No se pudo cerrar la incidencia.")

        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{field}: {error}")

        errores_cierre = incidencia.validar_para_cerrar(usuario=request.user)

    else:
        form = CerrarIncidenciaForm(
            instance=incidencia,
            incidencia=incidencia,
            usuario=request.user,
        )

    return render(
        request,
        "admisiones/incidencias/cerrar_incidencia.html",
        {
            "form": form,
            "incidencia": incidencia,
            "errores_cierre": errores_cierre,
            **contexto_semestre_operativo(),
        },
    )


@login_required
def crear_incidencia_semestre(request, semestre_id):
    """
    Compatibilidad con enlaces anteriores del detalle de semestre.
    Redirige al panel del nuevo módulo de incidencias filtrado por semestre.
    """
    if not usuario_puede_ver_incidencias(request.user):
        messages.error(request, "No tienes permiso para consultar incidencias.")
        return redirect("/")

    semestre = get_object_or_404(Semestre, pk=semestre_id)
    return redirect(f"{reverse('panel_incidencias')}?semestre={semestre.id}")



@login_required
def reporte_final_pendientes(request):
    if not usuario_puede_ver_reporte_final_ts(request.user):
        messages.error(request, "No tienes permiso para revisar reportes finales de ingreso.")
        return redirect("/")

    if not hay_semestre_activo_operativo():
        messages.warning(request, "No hay semestre activo. Reportes finales quedan en modo solo consulta.")
        inscripciones = SolicitudInscripcion.objects.none()
    else:
        inscripciones = (
            SolicitudInscripcion.objects
            .filter(estado="REVISION_FINAL_TS")
            .select_related("solicitud_ingreso", "usuario_tutor")
            .order_by("-updated_at")
        )

    return render(
        request,
        "admisiones/reporte_final_pendientes.html",
        {
            "inscripciones": inscripciones,
            **contexto_semestre_operativo(),
        },
    )


@login_required
def dictaminar_reporte_final(request, pk):
    if not usuario_puede_reporte_final_ts(request.user):
        messages.error(request, "No tienes permiso para registrar el Reporte Final de Ingreso.")
        return redirect("/")

    bloqueo = bloquear_si_no_hay_semestre_activo(request, "reporte_final_pendientes")
    if bloqueo:
        return bloqueo

    inscripcion = get_object_or_404(
        SolicitudInscripcion.objects.select_related("solicitud_ingreso", "usuario_tutor"),
        pk=pk,
    )
    solicitud = inscripcion.solicitud_ingreso

    if inscripcion.estado != "REVISION_FINAL_TS":
        messages.warning(
            request,
            "Este expediente no está en revisión final de Trabajo Social."
        )
        return redirect("reporte_final_pendientes")

    if request.method == "POST":
        accion = (
            request.POST.get("accion_reporte_final")
            or request.POST.get("accion")
            or ""
        ).strip().upper()

        motivos = (
            request.POST.get("reporte_final_motivos")
            or request.POST.get("motivos")
            or request.POST.get("observaciones")
            or ""
        ).strip()

        if accion in ["ACEPTAR", "APROBAR", "APROBADO"]:
            inscripcion.reporte_final_aprobado = True
            inscripcion.reporte_final_motivos = motivos
            inscripcion.reporte_final_por = request.user
            inscripcion.reporte_final_en = timezone.now()
            inscripcion.estado = "ESPERANDO_DIRECTORA"
            inscripcion.observaciones = (
                "Trabajo Social autorizó la inscripción y registró el Reporte Final de Ingreso. "
                "Pendiente resolución final de Dirección."
            )
            inscripcion.save()

            pdf_generado, mensaje_pdf = guardar_pdf_reporte_final_en_inscripcion(inscripcion)

            if pdf_generado:
                messages.success(
                    request,
                    "Reporte Final registrado como ACEPTADO. Se generó el PDF FO-301-02-18 y el expediente pasó a Dirección."
                )
            else:
                messages.warning(
                    request,
                    f"Reporte Final registrado como ACEPTADO y pasó a Dirección, pero ocurrió un problema con el PDF: {mensaje_pdf}"
                )

            return redirect("reporte_final_pendientes")

        elif accion in ["RECHAZAR", "RECHAZADO"]:
            if not motivos:
                messages.error(
                    request,
                    "Para rechazar la inscripción debes escribir los motivos del Reporte Final."
                )
                return redirect("dictaminar_reporte_final", pk=pk)

            inscripcion.reporte_final_aprobado = False
            inscripcion.reporte_final_motivos = motivos
            inscripcion.reporte_final_por = request.user
            inscripcion.reporte_final_en = timezone.now()
            inscripcion.estado = "RECHAZADA"
            inscripcion.observaciones = (
                "Trabajo Social no autorizó la inscripción en el Reporte Final de Ingreso."
            )
            inscripcion.save()

            pdf_generado, mensaje_pdf = guardar_pdf_reporte_final_en_inscripcion(inscripcion)

            if pdf_generado:
                messages.warning(
                    request,
                    "Reporte Final registrado como RECHAZADO. Se generó el PDF FO-301-02-18 y el expediente quedó rechazado."
                )
            else:
                messages.warning(
                    request,
                    f"Reporte Final registrado como RECHAZADO, pero ocurrió un problema con el PDF: {mensaje_pdf}"
                )

            return redirect("reporte_final_pendientes")

        messages.error(request, "Acción no válida para el Reporte Final.")

    return render(
        request,
        "admisiones/dictaminar_reporte_final.html",
        {
            "inscripcion": inscripcion,
            "solicitud": solicitud,
        },
    )


@login_required
def lista_asignacion_salas_legacy_desactivada(request):
    return modulo_desactivado(
        request,
        "La asignación de salas está desactivada en esta versión.",
    )


@login_required
def asignar_sala_definitiva_legacy_desactivada(request, inscripcion_id):
    return modulo_desactivado(
        request,
        "La asignación definitiva de sala está desactivada en esta versión.",
    )


@login_required
def dashboard_maestra(request):
    """
    Panel principal de operación diaria para maestras.

    Flujo:
    - Validar semestre activo.
    - Validar que la maestra tenga sala asignada.
    - Mostrar día operativo actual.
    - Permitir abrir día, registrar alumnos y cerrar día.
    """
    semestre = obtener_semestre_activo_operativo()
    asignaciones = obtener_asignaciones_maestra_operativas(request.user, semestre=semestre)

    dia_actual = None
    registros = RegistroDiarioAlumno.objects.none()
    salas = SalaSemestre.objects.none()

    if not semestre:
        messages.warning(
            request,
            "No hay semestre activo/iniciado. Puedes consultar información histórica, pero no operar."
        )
    elif not asignaciones.exists():
        messages.error(
            request,
            "No tienes salas asignadas en el semestre activo. Pide al Administrador que te asigne a una sala."
        )
    else:
        salas = obtener_salas_maestra_operativas(request.user, semestre=semestre)
        dia_actual = obtener_dia_operativo_actual_maestra(request.user, semestre=semestre)

        if dia_actual and dia_actual.estado == DiaOperativoSemestre.EstadoDia.ABIERTO and dia_operativo_es_laborable(dia_actual):
            asegurar_registros_alumnos_dia(dia_actual, request.user)

        if dia_actual and dia_operativo_es_laborable(dia_actual):
            registros = obtener_registros_dia_maestra(dia_actual, request.user)

    resumen_dia = {
        "total": registros.count() if dia_actual else 0,
        "sin_entrada": registros.filter(entrada_en__isnull=True).count() if dia_actual else 0,
        "en_estancia": registros.filter(entrada_en__isnull=False, salida_en__isnull=True).count() if dia_actual else 0,
        "con_salida": registros.filter(salida_en__isnull=False).count() if dia_actual else 0,
        "completos": registros.filter(estado=RegistroDiarioAlumno.EstadoRegistro.COMPLETO).count() if dia_actual else 0,
    }

    return render(
        request,
        "admisiones/operacion_diaria/panel_maestra.html",
        {
            "semestre": semestre,
            "asignaciones": asignaciones,
            "salas": salas,
            "dia_actual": dia_actual,
            "registros": registros,
            "resumen_dia": resumen_dia,
            "dia_no_operativo": bool(dia_actual and not dia_operativo_es_laborable(dia_actual)),
            "mensaje_dia_no_operativo": mensaje_dia_no_operativo(dia_actual) if dia_actual else "",
            **contexto_semestre_operativo(),
        },
    )


@login_required
def abrir_dia_maestra(request, dia_id):
    """
    Cualquier maestra asignada a sala puede abrir la operación del día de la sede.
    """
    dia = get_object_or_404(
        DiaOperativoSemestre.objects.select_related("semestre", "semestre__sede_configurada"),
        pk=dia_id,
    )

    if not validar_maestra_puede_operar_dia(request, dia):
        return redirect("dashboard_maestra")

    if request.method == "POST":
        form = AbrirDiaOperativoMaestraForm(request.POST)

        if form.is_valid():
            observaciones = form.cleaned_data.get("observaciones", "")
            ok, errores = dia.abrir(usuario=request.user, observaciones=observaciones)

            if ok:
                creados = asegurar_registros_alumnos_dia(dia, request.user)

                if dia.abierto_por_id == request.user.id:
                    messages.success(
                        request,
                        f"Día abierto correctamente. Registros de alumnos preparados: {creados}."
                    )
                else:
                    messages.info(
                        request,
                        "El día ya estaba abierto. Puedes continuar con la operación diaria."
                    )

                return redirect("lista_alumnos_dia_maestra", dia_id=dia.id)

            messages.error(request, "No se pudo abrir el día.")
            for error in errores:
                messages.error(request, error)
        else:
            messages.error(request, "Debes confirmar la apertura del día.")
    else:
        form = AbrirDiaOperativoMaestraForm()

    return render(
        request,
        "admisiones/operacion_diaria/abrir_dia.html",
        {
            "form": form,
            "dia": dia,
            "semestre": dia.semestre,
        },
    )


@login_required
def lista_alumnos_dia_maestra(request, dia_id):
    """
    Lista diaria de alumnos de las salas asignadas a la maestra.
    """
    dia = get_object_or_404(
        DiaOperativoSemestre.objects.select_related("semestre", "semestre__sede_configurada"),
        pk=dia_id,
    )

    if not usuario_tiene_asignacion_maestra_activa(request.user, semestre=dia.semestre):
        messages.error(request, "No tienes permiso para consultar este día operativo.")
        return redirect("dashboard_maestra")

    if not dia_operativo_es_laborable(dia):
        messages.info(
            request,
            mensaje_dia_no_operativo(dia)
            or "Este día no permite operación diaria de menores."
        )
        registros = RegistroDiarioAlumno.objects.none()
    else:
        if dia.estado == DiaOperativoSemestre.EstadoDia.ABIERTO:
            asegurar_registros_alumnos_dia(dia, request.user)

        registros = obtener_registros_dia_maestra(dia, request.user)

    return render(
        request,
        "admisiones/operacion_diaria/lista_alumnos_dia.html",
        {
            "dia": dia,
            "semestre": dia.semestre,
            "registros": registros,
            "dia_solo_lectura": dia.estado != DiaOperativoSemestre.EstadoDia.ABIERTO or not dia_operativo_es_laborable(dia),
            "dia_no_operativo": not dia_operativo_es_laborable(dia),
            "mensaje_dia_no_operativo": mensaje_dia_no_operativo(dia),
        },
    )


@login_required
def registrar_entrada_alumno(request, registro_id):
    registro = obtener_registro_diario_para_maestra(request, registro_id)
    responsables_codigo = obtener_responsables_codigo_inscripcion(registro.alumno)

    if not registro_diario_es_editable(registro):
        messages.warning(
            request,
            mensaje_dia_no_operativo(registro.dia_operativo)
            or "No se puede registrar entrada porque el día no está abierto."
        )
        return redirect("lista_alumnos_dia_maestra", dia_id=registro.dia_operativo_id)

    if registro.entrada_en:
        messages.info(request, "Este alumno ya tiene entrada registrada.")
        return redirect("lista_alumnos_dia_maestra", dia_id=registro.dia_operativo_id)

    if request.method == "POST":
        form = RegistroEntradaAlumnoForm(request.POST, instance=registro, registro_diario=registro)
        form_valido = form.is_valid()
        responsable_autorizado, errores_codigo = obtener_responsable_operacion_desde_post(
            registro,
            request.POST,
            prefijo="entrada",
        )

        errores_no_codigo = errores_form_sin_codigo(form)

        if form_valido or (not errores_no_codigo and not errores_codigo):
            if errores_codigo:
                for error in errores_codigo:
                    messages.error(request, error)
            else:
                datos = datos_entrada_desde_form_o_post(
                    form,
                    request.POST,
                    responsable_autorizado=responsable_autorizado,
                )

                ok, errores = registro.registrar_entrada(
                    usuario=request.user,
                    responsable_nombre=datos["responsable_nombre"],
                    responsable_parentesco=datos["responsable_parentesco"],
                    responsable_telefono=datos["responsable_telefono"],
                    responsable_autorizado=responsable_autorizado,
                    credencial_validada=datos["credencial_validada"],
                    codigo_validado=True,
                    temperatura=datos["temperatura"],
                )

                if ok:
                    BitacoraEntradaCasa.objects.get_or_create(registro_diario=registro)
                    messages.success(request, "Entrada registrada correctamente. Ahora captura la bitácora en casa.")
                    return redirect("bitacora_entrada_casa_maestra", registro_id=registro.id)

                messages.error(request, "No se pudo registrar la entrada.")
                for error in errores:
                    messages.error(request, error)
        else:
            messages.error(request, "No se pudo registrar la entrada. Revisa los campos.")
            for error in errores_codigo:
                messages.error(request, error)
    else:
        form = RegistroEntradaAlumnoForm(instance=registro, registro_diario=registro)

    return render(
        request,
        "admisiones/operacion_diaria/registrar_entrada.html",
        {
            "form": form,
            "registro": registro,
            "responsables_codigo": responsables_codigo,
            "tipo_formulario": registro.formulario_bitacora,
            "dia": registro.dia_operativo,
        },
    )


@login_required
def bitacora_entrada_casa_maestra(request, registro_id):
    registro = obtener_registro_diario_para_maestra(request, registro_id)

    if not registro.entrada_en:
        messages.warning(request, "Primero debes registrar la entrada del menor.")
        return redirect("lista_alumnos_dia_maestra", dia_id=registro.dia_operativo_id)

    bitacora, _ = BitacoraEntradaCasa.objects.get_or_create(registro_diario=registro)

    if request.method == "POST":
        if not registro_diario_es_editable(registro):
            messages.warning(
                request,
                mensaje_dia_no_operativo(registro.dia_operativo)
                or "El día está cerrado o no está activo. Solo consulta."
            )
            return redirect("lista_alumnos_dia_maestra", dia_id=registro.dia_operativo_id)

        form = BitacoraEntradaCasaForm(
            request.POST,
            instance=bitacora,
            registro_diario=registro,
            tipo_formulario=registro.formulario_bitacora,
        )

        if form.is_valid():
            obj = form.save(commit=False)
            obj.capturada_por = request.user

            if form.cleaned_data.get("marcar_completa"):
                obj.completa = True
                obj.capturada_en = timezone.now()

            obj.save()
            registro.marcar_completo_si_corresponde()

            messages.success(request, "Bitácora en casa guardada correctamente.")
            return redirect("lista_alumnos_dia_maestra", dia_id=registro.dia_operativo_id)

        messages.error(request, "No se pudo guardar la bitácora en casa. Revisa los campos.")
    else:
        form = BitacoraEntradaCasaForm(
            instance=bitacora,
            registro_diario=registro,
            tipo_formulario=registro.formulario_bitacora,
        )

    return render(
        request,
        "admisiones/operacion_diaria/bitacora_en_casa.html",
        {
            "form": form,
            "registro": registro,
            "bitacora": bitacora,
            "tipo_formulario": registro.formulario_bitacora,
            "dia": registro.dia_operativo,
            "solo_lectura": not registro_diario_es_editable(registro),
            "incidencias_dia": registro.incidencias.select_related("registrada_por").order_by("-fecha_reporte"),
        },
    )


@login_required
def bitacora_estancia_maestra(request, registro_id):
    registro = obtener_registro_diario_para_maestra(request, registro_id)

    if not registro.entrada_en:
        messages.warning(request, "Primero debes registrar la entrada del menor.")
        return redirect("lista_alumnos_dia_maestra", dia_id=registro.dia_operativo_id)

    bitacora, _ = BitacoraEstancia.objects.get_or_create(registro_diario=registro)

    if request.method == "POST":
        if not registro_diario_es_editable(registro):
            messages.warning(
                request,
                mensaje_dia_no_operativo(registro.dia_operativo)
                or "El día está cerrado o no está activo. Solo consulta."
            )
            return redirect("lista_alumnos_dia_maestra", dia_id=registro.dia_operativo_id)

        form = BitacoraEstanciaForm(
            request.POST,
            instance=bitacora,
            registro_diario=registro,
            tipo_formulario=registro.formulario_bitacora,
        )

        if form.is_valid():
            obj = form.save(commit=False)
            obj.capturada_por = request.user

            if form.cleaned_data.get("marcar_completa"):
                obj.completa = True
                obj.capturada_en = timezone.now()

            obj.save()
            registro.marcar_completo_si_corresponde()

            messages.success(request, "Bitácora durante estancia guardada correctamente.")
            return redirect("lista_alumnos_dia_maestra", dia_id=registro.dia_operativo_id)

        messages.error(request, "No se pudo guardar la bitácora durante estancia. Revisa los campos.")
    else:
        form = BitacoraEstanciaForm(
            instance=bitacora,
            registro_diario=registro,
            tipo_formulario=registro.formulario_bitacora,
        )

    return render(
        request,
        "admisiones/operacion_diaria/bitacora_estancia.html",
        {
            "form": form,
            "registro": registro,
            "bitacora": bitacora,
            "tipo_formulario": registro.formulario_bitacora,
            "dia": registro.dia_operativo,
            "solo_lectura": not registro_diario_es_editable(registro),
            "incidencias_dia": registro.incidencias.select_related("registrada_por").order_by("-fecha_reporte"),
        },
    )


@login_required
def registrar_salida_alumno(request, registro_id):
    registro = obtener_registro_diario_para_maestra(request, registro_id)
    responsables_codigo = obtener_responsables_codigo_inscripcion(registro.alumno)

    if not registro_diario_es_editable(registro):
        messages.warning(
            request,
            mensaje_dia_no_operativo(registro.dia_operativo)
            or "No se puede registrar salida porque el día no está abierto."
        )
        return redirect("lista_alumnos_dia_maestra", dia_id=registro.dia_operativo_id)

    if not registro.entrada_en:
        messages.warning(request, "No se puede registrar salida sin entrada.")
        return redirect("lista_alumnos_dia_maestra", dia_id=registro.dia_operativo_id)

    if registro.salida_en:
        messages.info(request, "Este alumno ya tiene salida registrada.")
        return redirect("lista_alumnos_dia_maestra", dia_id=registro.dia_operativo_id)

    if request.method == "POST":
        form = RegistroSalidaAlumnoForm(request.POST, instance=registro, registro_diario=registro)
        form_valido = form.is_valid()
        responsable_autorizado, errores_codigo = obtener_responsable_operacion_desde_post(
            registro,
            request.POST,
            prefijo="salida",
        )

        errores_no_codigo = errores_form_sin_codigo(form)

        if form_valido or (not errores_no_codigo and not errores_codigo):
            if errores_codigo:
                for error in errores_codigo:
                    messages.error(request, error)
            else:
                datos = datos_salida_desde_form_o_post(
                    form,
                    request.POST,
                    responsable_autorizado=responsable_autorizado,
                )

                ok, errores = registro.registrar_salida(
                    usuario=request.user,
                    responsable_nombre=datos["responsable_nombre"],
                    responsable_parentesco=datos["responsable_parentesco"],
                    responsable_telefono=datos["responsable_telefono"],
                    responsable_autorizado=responsable_autorizado,
                    credencial_validada=datos["credencial_validada"],
                    codigo_validado=True,
                    tipo_salida=datos["tipo_salida"],
                    motivo_salida=datos["motivo_salida"],
                    observacion_salida=datos["observacion_salida"],
                )

                if ok:
                    registro.marcar_completo_si_corresponde()
                    messages.success(request, "Salida registrada correctamente.")
                    return redirect("lista_alumnos_dia_maestra", dia_id=registro.dia_operativo_id)

                messages.error(request, "No se pudo registrar la salida.")
                for error in errores:
                    messages.error(request, error)
        else:
            messages.error(request, "No se pudo registrar la salida. Revisa los campos.")
            for error in errores_codigo:
                messages.error(request, error)
    else:
        form = RegistroSalidaAlumnoForm(instance=registro, registro_diario=registro)

    return render(
        request,
        "admisiones/operacion_diaria/registrar_salida.html",
        {
            "form": form,
            "registro": registro,
            "responsables_codigo": responsables_codigo,
            "tipo_formulario": registro.formulario_bitacora,
            "dia": registro.dia_operativo,
        },
    )


@login_required
def cerrar_dia_maestra(request, dia_id):
    """
    Cierre operativo del día por maestra.
    No mezcla incidencias todavía.
    """
    dia = get_object_or_404(
        DiaOperativoSemestre.objects.select_related("semestre", "semestre__sede_configurada"),
        pk=dia_id,
    )

    if not usuario_tiene_asignacion_maestra_activa(request.user, semestre=dia.semestre):
        messages.error(request, "No tienes permiso para cerrar este día.")
        return redirect("dashboard_maestra")

    registros = obtener_registros_dia_maestra(dia, request.user)
    errores_cierre = dia.puede_cerrarse() if dia.estado == DiaOperativoSemestre.EstadoDia.ABIERTO else []

    if request.method == "POST":
        form = CerrarDiaOperacionMaestraForm(request.POST)

        if form.is_valid():
            observaciones = form.cleaned_data.get("observaciones", "")
            ok, errores = dia.cerrar(usuario=request.user, observaciones=observaciones)

            if ok:
                messages.success(request, "Día cerrado correctamente. A partir de ahora queda solo en consulta.")
                return redirect("dashboard_maestra")

            messages.error(request, "No se puede cerrar el día todavía.")
            for error in errores:
                messages.error(request, error)

            errores_cierre = errores
        else:
            messages.error(request, "Debes confirmar el cierre del día.")
    else:
        form = CerrarDiaOperacionMaestraForm()

    return render(
        request,
        "admisiones/operacion_diaria/cerrar_dia.html",
        {
            "form": form,
            "dia": dia,
            "semestre": dia.semestre,
            "registros": registros,
            "errores_cierre": errores_cierre,
            "incidencias_abiertas": Incidencia.objects.filter(
                dia_operativo=dia,
                estado=Incidencia.EstadoIncidencia.ABIERTA,
            ).select_related("alumno", "alumno__solicitud_ingreso", "registrada_por"),
        },
    )


@login_required
def historial_alumno_maestra(request, alumno_id):
    """
    Historial diario del alumno.
    La maestra solo puede verlo si el alumno pertenece a una de sus salas asignadas
    en el semestre activo.
    """
    semestre = obtener_semestre_activo_operativo()
    salas = obtener_salas_maestra_operativas(request.user, semestre=semestre)

    alumno = get_object_or_404(
        SolicitudInscripcion.objects.select_related("solicitud_ingreso", "sala_semestre_asignada", "semestre"),
        pk=alumno_id,
        sala_semestre_asignada__in=salas,
    )

    registros = (
        RegistroDiarioAlumno.objects
        .filter(alumno=alumno)
        .select_related("dia_operativo", "sala_semestre", "sala_semestre__sala")
        .order_by("-dia_operativo__fecha")
    )

    return render(
        request,
        "admisiones/operacion_diaria/historial_alumno.html",
        {
            "alumno": alumno,
            "registros": registros,
            "semestre": semestre,
            "incidencias": Incidencia.objects.filter(alumno=alumno).select_related(
                "dia_operativo",
                "sala_semestre",
                "sala_semestre__sala",
                "registrada_por",
            ).order_by("-fecha_reporte"),
        },
    )



# =========================================================
# SPRINT 5 - PDF DE BITÁCORA DIARIA
# Orden:
# datos del menor -> entrada -> en casa -> estancia -> incidencias -> salida -> firmas
# =========================================================

def _valor_pdf_legible(valor, campo=None):
    """
    Convierte valores de modelos a texto legible para el PDF diario.
    Evita depender de nombres exactos de campos de bitácora.
    """
    if valor is None or valor == "":
        return ""

    if isinstance(valor, bool):
        return "Sí" if valor else "No"

    if isinstance(valor, (list, tuple, set)):
        return ", ".join(str(v) for v in valor if str(v).strip())

    if isinstance(valor, dict):
        partes = []
        for k, v in valor.items():
            if v not in [None, "", [], {}]:
                partes.append(f"{k}: {v}")
        return "; ".join(partes)

    if campo is not None:
        tipo_campo = campo.get_internal_type()

        # Si el campo tiene choices, usa la etiqueta visible.
        try:
            display = getattr(campo.model, f"get_{campo.name}_display", None)
            if display:
                return str(display())
        except Exception:
            pass

        if tipo_campo == "DateTimeField":
            try:
                return timezone.localtime(valor).strftime("%d/%m/%Y %H:%M")
            except Exception:
                return str(valor)

        if tipo_campo == "DateField":
            try:
                return valor.strftime("%d/%m/%Y")
            except Exception:
                return str(valor)

        if tipo_campo == "TimeField":
            try:
                return valor.strftime("%H:%M")
            except Exception:
                return str(valor)

    return str(valor)


def serializar_modelo_para_pdf(obj, excluir=None):
    """
    Devuelve campos llenos de un modelo como lista:
    [{"etiqueta": "...", "valor": "..."}]

    Esto permite que el PDF funcione aunque cambien los campos
    de BitacoraEntradaCasa o BitacoraEstancia.
    """
    if not obj:
        return []

    excluir_base = {
        "id",
        "registro_diario",
        "created_at",
        "updated_at",
    }

    if excluir:
        excluir_base.update(excluir)

    filas = []

    for campo in obj._meta.fields:
        if campo.name in excluir_base:
            continue

        valor = getattr(obj, campo.name, None)

        if valor in [None, "", [], {}]:
            continue

        # Evitar mostrar rutas de archivos pesadas o relaciones técnicas no necesarias.
        tipo_campo = campo.get_internal_type()
        if tipo_campo in ["FileField", "ImageField"]:
            continue

        texto = _valor_pdf_legible(valor, campo=campo)
        if not texto:
            continue

        filas.append({
            "etiqueta": str(getattr(campo, "verbose_name", campo.name)).title(),
            "valor": texto,
        })

    return filas


def _dato_registro_pdf(registro, etiqueta, campo):
    valor = getattr(registro, campo, None)

    if valor in [None, ""]:
        return None

    try:
        if hasattr(valor, "strftime"):
            if "en" in campo or "hora" in campo:
                valor = timezone.localtime(valor).strftime("%d/%m/%Y %H:%M")
            else:
                valor = valor.strftime("%d/%m/%Y")
    except Exception:
        pass

    if isinstance(valor, bool):
        valor = "Sí" if valor else "No"

    return {"etiqueta": etiqueta, "valor": valor}


def construir_datos_entrada_salida_pdf(registro):
    campos_entrada = [
        ("Hora de entrada", "entrada_en"),
        ("Responsable que deja al menor", "responsable_entrada_nombre"),
        ("Parentesco", "responsable_entrada_parentesco"),
        ("Teléfono", "responsable_entrada_telefono"),
        ("Credencial validada", "credencial_entrada_validada"),
        ("Código validado", "codigo_entrada_validado"),
        ("Temperatura de entrada", "temperatura_entrada"),
    ]

    campos_salida = [
        ("Hora de salida", "salida_en"),
        ("Responsable que recoge al menor", "responsable_salida_nombre"),
        ("Parentesco", "responsable_salida_parentesco"),
        ("Teléfono", "responsable_salida_telefono"),
        ("Credencial validada", "credencial_salida_validada"),
        ("Código validado", "codigo_salida_validado"),
        ("Tipo de salida", "tipo_salida"),
        ("Motivo de salida", "motivo_salida"),
        ("Observación de salida", "observacion_salida"),
    ]

    datos_entrada = []
    datos_salida = []

    for etiqueta, campo in campos_entrada:
        dato = _dato_registro_pdf(registro, etiqueta, campo)
        if dato:
            datos_entrada.append(dato)

    for etiqueta, campo in campos_salida:
        dato = _dato_registro_pdf(registro, etiqueta, campo)
        if dato:
            datos_salida.append(dato)

    return datos_entrada, datos_salida


def limpiar_nombre_archivo_pdf(valor):
    valor = str(valor or "").strip()
    valor = re.sub(r"\s+", "_", valor)
    valor = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9_.-]", "", valor)
    return valor or "bitacora"


def usuario_puede_descargar_bitacora_diaria(user, registro):
    """
    Permisos para descargar PDF diario:
    - Administrador del Sistema
    - Directora
    - Coordinadora de Sala
    - Maestra asignada a la sala del registro
    - Beneficiario/tutor del menor, si se habilita desde portal
    """
    if not user or not user.is_authenticated:
        return False

    if usuario_es_admin(user) or usuario_es_directora(user) or usuario_es_coordinadora_sala(user):
        return True

    if getattr(registro.alumno, "usuario_tutor_id", None) == user.id:
        return True

    try:
        semestre = registro.dia_operativo.semestre
        salas = obtener_salas_maestra_operativas(user, semestre=semestre)
        return salas.filter(id=registro.sala_semestre_id).exists()
    except Exception:
        return False

@login_required
def dashboard_coordinadora(request):
    """
    Panel de Coordinadora de Sala.

    Función:
    - Crear incidencias pedagógicas.
    - Ver incidencias pedagógicas abiertas/cerradas.
    - Supervisar incidencias de alto riesgo.
    - Consultar estado del semestre.
    """
    if not (
        usuario_es_coordinadora_sala(request.user)
        or usuario_es_admin(request.user)
        or usuario_es_directora(request.user)
    ):
        messages.error(request, "No tienes permiso para entrar al panel de Coordinadora de Sala.")
        return redirect("/")

    semestre = obtener_semestre_activo_operativo()
    modo_solo_consulta = not hay_semestre_activo_operativo()

    incidencias_pedagogicas = (
        Incidencia.objects
        .filter(tipo=Incidencia.TipoIncidencia.PEDAGOGICA)
        .select_related(
            "alumno",
            "alumno__solicitud_ingreso",
            "semestre",
            "dia_operativo",
            "sala_semestre",
            "sala_semestre__sala",
            "registrada_por",
        )
        .order_by("-fecha_reporte")
    )

    if semestre:
        incidencias_semestre = incidencias_pedagogicas.filter(semestre=semestre)
    else:
        incidencias_semestre = incidencias_pedagogicas

    resumen_incidencias = {
        "total": incidencias_semestre.count(),
        "abiertas": incidencias_semestre.filter(estado=Incidencia.EstadoIncidencia.ABIERTA).count(),
        "cerradas": incidencias_semestre.filter(estado=Incidencia.EstadoIncidencia.CERRADA).count(),
        "alto": incidencias_semestre.filter(nivel=Incidencia.NivelChoices.ALTO).count(),
    }

    return render(
        request,
        "admisiones/dashboard_coordinadora.html",
        {
            "semestre": semestre,
            "semestre_activo_operativo": semestre,
            "modo_solo_consulta": modo_solo_consulta,
            "incidencias_pedagogicas": incidencias_semestre[:10],
            "incidencias_abiertas": incidencias_semestre.filter(
                estado=Incidencia.EstadoIncidencia.ABIERTA
            )[:10],
            "incidencias_alto": incidencias_semestre.filter(
                nivel=Incidencia.NivelChoices.ALTO
            )[:10],
            "resumen_incidencias": resumen_incidencias,
            **contexto_semestre_operativo(),
        },
    )

@login_required
def expediente_bitacoras(request, alumno_id):
    """
    Compatibilidad con enlaces anteriores:
    redirige al historial diario del alumno para maestras.
    """
    return historial_alumno_maestra(request, alumno_id)


@login_required
def crear_bitacora(request, alumno_id):
    return modulo_desactivado(
        request,
        "La creación de bitácoras está desactivada en esta versión.",
    )


@login_required
def enviar_bitacora_coordinadora(request, bitacora_id, tipo):
    return modulo_desactivado(
        request,
        "El envío de bitácora a coordinación está desactivado en esta versión.",
    )


@login_required
def aprobar_bitacora_coordinadora(request, bitacora_id, tipo):
    return modulo_desactivado(
        request,
        "La aprobación de bitácoras está desactivada en esta versión.",
    )


@login_required
def corregir_bitacora_coordinadora(request, bitacora_id, tipo):
    return modulo_desactivado(
        request,
        "La corrección de bitácoras está desactivada en esta versión.",
    )


@login_required
def enviar_bitacora_directora(request, bitacora_id, tipo):
    return modulo_desactivado(
        request,
        "El envío de bitácora a dirección está desactivado en esta versión.",
    )


@login_required
def descargar_pdf_bitacora(request, bitacora_id, tipo):
    """
    Descarga PDF del registro diario del menor.

    En este flujo nuevo, bitacora_id se interpreta como el ID de RegistroDiarioAlumno.
    La URL conserva <str:tipo> por compatibilidad, pero el contenido se genera desde:
    - RegistroDiarioAlumno
    - BitacoraEntradaCasa
    - BitacoraEstancia
    - Incidencias del día
    - Salida del menor
    """
    registro = get_object_or_404(
        RegistroDiarioAlumno.objects.select_related(
            "dia_operativo",
            "dia_operativo__semestre",
            "alumno",
            "alumno__solicitud_ingreso",
            "sala_semestre",
            "sala_semestre__sala",
            "entrada_por",
            "salida_por",
            "creado_por",
        ),
        pk=bitacora_id,
    )

    if not usuario_puede_descargar_bitacora_diaria(request.user, registro):
        messages.error(request, "No tienes permiso para descargar esta bitácora.")
        return redirect("/")

    bitacora_casa = BitacoraEntradaCasa.objects.filter(registro_diario=registro).first()
    bitacora_estancia = BitacoraEstancia.objects.filter(registro_diario=registro).first()

    incidencias = (
        registro.incidencias
        .select_related(
            "registrada_por",
            "cerrada_por",
            "alumno",
            "alumno__solicitud_ingreso",
            "sala_semestre",
            "sala_semestre__sala",
        )
        .prefetch_related("seguimientos", "seguimientos__archivos", "archivos")
        .order_by("fecha_reporte")
    )

    datos_entrada, datos_salida = construir_datos_entrada_salida_pdf(registro)

    solicitud = registro.alumno.solicitud_ingreso
    nombre_menor = registro.alumno.solicitud_ingreso.nombre_menor_completo()
    sala_nombre = registro.sala_semestre.sala.nombre if registro.sala_semestre and registro.sala_semestre.sala else "Sin sala"

    nombre_base = limpiar_nombre_archivo_pdf(
        f"Bitacora_Diaria_{nombre_menor}_{registro.dia_operativo.fecha if registro.dia_operativo else ''}"
    )

    context = {
        "registro": registro,
        "alumno": registro.alumno,
        "sol": solicitud,
        "nombre_menor": nombre_menor,
        "sala_nombre": sala_nombre,
        "bitacora_casa": bitacora_casa,
        "bitacora_estancia": bitacora_estancia,
        "campos_casa": serializar_modelo_para_pdf(bitacora_casa),
        "campos_estancia": serializar_modelo_para_pdf(bitacora_estancia),
        "datos_entrada": datos_entrada,
        "datos_salida": datos_salida,
        "incidencias": incidencias,
        "tipo": tipo,
        "fecha_generacion": timezone.now(),
    }

    html = render_to_string(
        "admisiones/operacion_diaria/bitacora_diaria_pdf.html",
        context,
        request=request,
    )

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{nombre_base}.pdf"'

    pdf = pisa.CreatePDF(html, dest=response, link_callback=link_callback)

    if pdf.err:
        return HttpResponse(
            "No se pudo generar el PDF de la bitácora diaria.",
            status=500,
        )

    return response
