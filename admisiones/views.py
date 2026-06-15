from django.shortcuts import render, redirect, get_object_or_404
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    JsonResponse,
    HttpResponseForbidden,
)
from django.utils import timezone
from django.utils.html import escape
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_http_methods
from django.urls import reverse
from django.conf import settings
from django.template.loader import render_to_string
from django.contrib.staticfiles import finders
from xhtml2pdf import pisa

from django.core.mail import send_mail, EmailMessage
from django.core.exceptions import ValidationError
from django.core.files import File
from django.contrib.auth import get_user_model, logout
from django.db import transaction
from django.db.models import Q, Count

import os
import re
import csv
import unicodedata
from datetime import datetime
from urllib.parse import urlencode

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

    # Suplencias / pase de lista del personal operativo
    PaseListaPersonalForm,
    AsistenciaPersonalForm,
    AutorizacionSuplenciaForm,
    CancelarSuplenciaForm,
    RevisionMovimientoSuplenciaForm,
    FiltroBitacoraSuplenciaForm,
    RevisarIncidenciaSuplenciaForm,
    RevisarTrabajoSocialSuplenciaForm,
    personal_operativo_pase_lista_queryset,
    personal_suplente_queryset,
    inferir_area_operativa_usuario,
    nombre_area_operativa_usuario,

    # Sprint 4 - Segunda parte / Operación diaria de maestras
    AbrirDiaOperativoMaestraForm,
    RegistroEntradaAlumnoForm,
    SolicitarAutorizacionEntradaForm,
    AutorizarEntradaResponsableForm,
    RechazarAutorizacionEntradaForm,
    SolicitarAutorizacionSalidaForm,
    AutorizarSalidaResponsableForm,
    RechazarAutorizacionSalidaForm,
    BitacoraEntradaCasaForm,
    BitacoraEstanciaForm,
    RegistroSalidaAlumnoForm,
    CerrarDiaOperacionMaestraForm,
    ApoyoSalaMaestraForm,
    FinalizarApoyoSalaMaestraForm,
)

from .services import (
    generar_pdf_fo301,
    generar_pdf_dictamen,
    generar_pdf_inscripcion_lleno,
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
    DatoCompartidoFiltro,
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
    AutorizacionEntrada,
    AutorizacionSalida,
    es_correo_institucional,
    BitacoraEntradaCasa,
    BitacoraEstancia,
    EncuestaSatisfaccion,
    EnvioEncuestaSatisfaccion,
    Incidencia,
    IncidenciaArchivo,
    SeguimientoIncidencia,
    SeguimientoIncidenciaArchivo,

    # Suplencias / pase de lista del personal operativo
    AsistenciaPersonal,
    AutorizacionSuplencia,
    MovimientoSuplencia,
    ApoyoSalaMaestra,
    BloqueoEdicionTemporal,
)


# ===================== AJAX: FILTRAR CARRERAS =====================
def obtener_carreras(request):
    facultad_id = request.GET.get("facultad_id")

    if facultad_id:
        carreras = Carrera.objects.filter(facultad_id=facultad_id).values("id", "nombre")
        return JsonResponse(list(carreras), safe=False)

    return JsonResponse([], safe=False)


def obtener_programas_educativos_catalogo():
    """
    Catálogo para el combo de Programa educativo en editar solicitud.

    Fuente principal:
    - Modelo Carrera, porque el proyecto ya lo usa para cargar carreras
      por facultad en obtener_carreras().

    Si la tabla todavía está vacía, se devuelve lista vacía y el HTML usa
    su respaldo visual sin romper la pantalla.
    """
    programas = []

    try:
        programas = list(
            Carrera.objects
            .exclude(nombre__isnull=True)
            .exclude(nombre__exact="")
            .order_by("nombre")
            .values_list("nombre", flat=True)
            .distinct()
        )
    except Exception:
        programas = []

    return programas


def obtener_unidades_academicas_catalogo():
    """
    Catálogo para el combo de Unidad académica en editar solicitud.

    Fuente:
    - CrearSolicitudPanelForm.UNIDADES_CHOICES, donde ya están definidas
      las facultades/unidades usadas al crear solicitudes desde el panel.
    """
    unidades = []

    try:
        for valor, etiqueta in getattr(CrearSolicitudPanelForm, "UNIDADES_CHOICES", []):
            valor = str(valor or "").strip()
            etiqueta = str(etiqueta or "").strip()

            if not valor:
                continue

            if valor.lower() in ["otra", "otro"]:
                continue

            unidades.append(etiqueta or valor)
    except Exception:
        unidades = []

    # Quita duplicados conservando el orden.
    resultado = []
    vistos = set()

    for unidad in unidades:
        clave = normalizar_texto(unidad)
        if clave and clave not in vistos:
            resultado.append(unidad)
            vistos.add(clave)

    return resultado


def contexto_catalogos_editar_solicitud():
    """
    Contexto reutilizable para editar_solicitud.html.
    Mantiene los nombres simples que el HTML usa en JavaScript.
    """
    return {
        "programas_educativos": obtener_programas_educativos_catalogo(),
        "unidades_academicas": obtener_unidades_academicas_catalogo(),
    }


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


def acceso_denegado_login(request, mensaje="No tienes permiso para entrar a este módulo. Se cerró la sesión por seguridad."):
    """
    Política de seguridad solicitada:
    - Si un usuario autenticado intenta entrar a un panel ajeno, no se muestra información.
    - Se cierra su sesión y se redirige al login.

    Nota: las suplencias autorizadas por Dirección y el apoyo temporal de sala
    se validan antes de llamar a este helper.
    """
    try:
        messages.error(request, mensaje)
    except Exception:
        pass

    try:
        logout(request)
    except Exception:
        pass

    return redirect("login")


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

# Límite de carga para expedientes de inscripción.
# Este límite se aplica en backend para evitar archivos demasiado pesados
# aunque el usuario modifique o desactive la validación del navegador.
MAX_TAMANO_ARCHIVO_EXPEDIENTE_MB = 5
MAX_TAMANO_ARCHIVO_EXPEDIENTE_BYTES = MAX_TAMANO_ARCHIVO_EXPEDIENTE_MB * 1024 * 1024

EXTENSIONES_EXPEDIENTE_PERMITIDAS = {".pdf", ".jpg", ".jpeg", ".png"}
EXTENSIONES_IMAGEN_PERMITIDAS = {".jpg", ".jpeg", ".png"}

CAMPOS_SOLO_IMAGEN_EXPEDIENTE = {
    "doc_menor_fotos",
    "doc_tutor_fotos",
    "doc_segundo_padre_fotos",
    "doc_contacto_1_fotos",
    "doc_contacto_2_fotos",
    "doc_contacto_3_fotos",
}

CAMPOS_SOLO_PDF_EXPEDIENTE = {
    "reglamento_firmado",
}


def validar_archivo_expediente_inscripcion(campo, archivo, nombre_legible="archivo"):
    """
    Valida archivos del portal de inscripción antes de guardarlos.

    Reglas:
    - Documentos generales: PDF, JPG, JPEG o PNG.
    - Fotografías: solo JPG, JPEG o PNG.
    - Reglamento firmado: solo PDF.
    - Tamaño máximo por archivo: 5 MB.
    """
    nombre_legible = nombre_legible or campo or "archivo"

    if not archivo:
        return False, f"Debes seleccionar el archivo de '{nombre_legible}'."

    extension = os.path.splitext(archivo.name)[1].lower()

    if campo in CAMPOS_SOLO_PDF_EXPEDIENTE:
        extensiones_permitidas = {".pdf"}
        mensaje_formato = f"El campo '{nombre_legible}' solo acepta PDF."
    elif campo in CAMPOS_SOLO_IMAGEN_EXPEDIENTE:
        extensiones_permitidas = EXTENSIONES_IMAGEN_PERMITIDAS
        mensaje_formato = (
            f"El campo '{nombre_legible}' no acepta PDF. "
            "Sube una imagen JPG, JPEG o PNG."
        )
    else:
        extensiones_permitidas = EXTENSIONES_EXPEDIENTE_PERMITIDAS
        mensaje_formato = (
            f"Formato no permitido en '{nombre_legible}'. "
            "Sube un archivo PDF, JPG, JPEG o PNG."
        )

    if extension not in extensiones_permitidas:
        return False, mensaje_formato

    if archivo.size > MAX_TAMANO_ARCHIVO_EXPEDIENTE_BYTES:
        peso_mb = round(archivo.size / (1024 * 1024), 2)
        return (
            False,
            (
                f"El archivo de '{nombre_legible}' pesa {peso_mb} MB y supera "
                f"el límite permitido de {MAX_TAMANO_ARCHIVO_EXPEDIENTE_MB} MB. "
                "Comprime el archivo o sube una versión más ligera."
            ),
        )

    if archivo.size <= 0:
        return False, f"El archivo de '{nombre_legible}' está vacío. Selecciona un archivo válido."

    return True, "Archivo válido."



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

def obtener_dominio_correos_institucionales():
    """
    Devuelve los dominios institucionales permitidos para envío de correos.
    Regla solicitada: solo se consideran válidos los correos que terminan en @unach.mx,
    salvo que en settings.py se agreguen dominios adicionales en
    UNACH_CORREOS_INSTITUCIONALES.
    """
    dominios = getattr(settings, "UNACH_CORREOS_INSTITUCIONALES", ["@unach.mx"])

    if isinstance(dominios, str):
        dominios = [dominios]

    dominios_limpios = []
    for dominio in dominios or ["@unach.mx"]:
        dominio = str(dominio or "").strip().lower()
        if dominio:
            dominios_limpios.append(dominio)

    return dominios_limpios or ["@unach.mx"]


def es_correo_institucional_unach_views(correo):
    """
    Valida correos institucionales para las vistas de admisiones.
    Se usa en los envíos para impedir correos que no sean @unach.mx.
    """
    correo = (correo or "").strip().lower()

    if not correo:
        return False

    return any(
        correo.endswith(dominio)
        for dominio in obtener_dominio_correos_institucionales()
    )


def extraer_correo_desde_cabecera(cabecera):
    """
    Obtiene el correo real desde textos como:
    Estancia Infantil UNACH <correo@unach.mx>
    """
    cabecera = (cabecera or "").strip()

    if not cabecera:
        return ""

    coincidencia = re.search(r"<([^>]+)>", cabecera)

    if coincidencia:
        return coincidencia.group(1).strip().lower()

    return cabecera.strip().lower()


def limpiar_nombre_para_correo(nombre):
    """
    Evita saltos de línea o caracteres inválidos en el nombre visible del remitente.
    """
    nombre = str(nombre or "").strip()
    nombre = re.sub(r"[\r\n<>]+", " ", nombre)
    nombre = re.sub(r"\s+", " ", nombre).strip()
    return nombre or "Estancia Infantil UNACH"


def obtener_correo_institucional_usuario(user):
    """
    Toma dinámicamente el correo del usuario que inició sesión.
    No se deja fijo ningún correo de trabajadora social.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return ""

    correo = (getattr(user, "email", "") or "").strip().lower()

    if es_correo_institucional_unach_views(correo):
        return correo

    return ""


def construir_from_email_usuario(user):
    """
    Construye el remitente visible usando el correo institucional del usuario actual.
    Ejemplo:
    Nombre Trabajadora Social <nombre@unach.mx>
    """
    correo = obtener_correo_institucional_usuario(user)

    if not correo:
        return ""

    nombre = limpiar_nombre_para_correo(usuario_nombre_legible(user))
    return f"{nombre} <{correo}>"


def normalizar_lista_correos(correos):
    """
    Acepta un correo o lista/tupla de correos y devuelve lista limpia.
    """
    if not correos:
        return []

    if isinstance(correos, str):
        correos = [correos]

    lista = []
    for correo in correos:
        correo = (correo or "").strip().lower()
        if correo and correo not in lista:
            lista.append(correo)

    return lista


def validar_correos_destino_institucionales(correos):
    """
    Valida que todos los destinatarios terminen en @unach.mx.
    """
    correos = normalizar_lista_correos(correos)

    if not correos:
        return False, "No hay correo destino registrado.", []

    invalidos = [
        correo
        for correo in correos
        if not es_correo_institucional_unach_views(correo)
    ]

    if invalidos:
        return (
            False,
            "Solo se permite enviar a correos institucionales @unach.mx. "
            f"Correo no válido: {', '.join(invalidos)}",
            correos,
        )

    return True, "Correos válidos.", correos


def adjuntar_archivos_a_correo(correo, adjuntos):
    """
    Adjunta archivos de forma segura.
    Acepta:
    - rutas de archivo,
    - FileField con .path,
    - tuplas compatibles con EmailMessage.attach().
    """
    for adjunto in adjuntos or []:
        if not adjunto:
            continue

        try:
            if isinstance(adjunto, tuple):
                correo.attach(*adjunto)
                continue

            ruta = None

            if isinstance(adjunto, str):
                ruta = adjunto
            elif hasattr(adjunto, "path"):
                ruta = adjunto.path

            if ruta and os.path.exists(ruta):
                correo.attach_file(ruta)

        except Exception:
            # Si un adjunto falla, no rompemos la aprobación;
            # el error real se controlará al enviar o se omitirá ese adjunto.
            continue


def enviar_correo_institucional_unach(
    asunto,
    cuerpo,
    destinatarios,
    usuario_emisor=None,
    adjuntos=None,
    cc=None,
    bcc=None,
):
    """
    Envío centralizado de correos institucionales.

    Reglas:
    - El destinatario debe ser @unach.mx.
    - Si se indica usuario_emisor, ese usuario debe tener correo @unach.mx.
    - No se deja fijo el correo de la trabajadora social.
    - El remitente visible se toma del usuario que inició sesión.
    """
    ok_destinos, mensaje_destinos, destinatarios = validar_correos_destino_institucionales(destinatarios)

    if not ok_destinos:
        return False, mensaje_destinos

    cc = normalizar_lista_correos(cc)
    bcc = normalizar_lista_correos(bcc)

    ok_cc, mensaje_cc, cc = validar_correos_destino_institucionales(cc) if cc else (True, "", [])
    if not ok_cc:
        return False, f"CC inválido. {mensaje_cc}"

    ok_bcc, mensaje_bcc, bcc = validar_correos_destino_institucionales(bcc) if bcc else (True, "", [])
    if not ok_bcc:
        return False, f"BCC inválido. {mensaje_bcc}"

    correo_emisor_usuario = ""

    if usuario_emisor is not None:
        correo_emisor_usuario = obtener_correo_institucional_usuario(usuario_emisor)

        if not correo_emisor_usuario:
            return (
                False,
                "El usuario que envía debe tener registrado un correo institucional @unach.mx."
            )

    from_email = construir_from_email_usuario(usuario_emisor) if usuario_emisor is not None else ""
    if not from_email:
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or getattr(settings, "EMAIL_HOST_USER", "")

    correo_from_real = extraer_correo_desde_cabecera(from_email)

    if not es_correo_institucional_unach_views(correo_from_real):
        return (
            False,
            "El correo emisor configurado debe ser institucional @unach.mx. "
            f"Correo actual: {correo_from_real or 'sin configurar'}"
        )

    try:
        correo = EmailMessage(
            subject=asunto,
            body=cuerpo,
            from_email=from_email,
            to=destinatarios,
            cc=cc,
            bcc=bcc,
            reply_to=[correo_emisor_usuario] if correo_emisor_usuario else None,
        )

        adjuntar_archivos_a_correo(correo, adjuntos)
        correo.send(fail_silently=False)

        return True, "Correo enviado correctamente."

    except Exception as e:
        return False, f"No se pudo enviar el correo: {e}"


def enviar_correo_dictamen_ingreso(solicitud, pdf_path=None, usuario_emisor=None):
    """
    Envía el dictamen de ingreso al correo destino de la solicitud.

    Cambio solicitado:
    - No usa correo fijo de Gmail.
    - El remitente visible se toma de la trabajadora social que inició sesión,
      siempre que su correo sea @unach.mx.
    - El destinatario también debe ser @unach.mx.
    """
    correo_destino = (getattr(solicitud, "correo", "") or "").strip().lower()

    if not correo_destino:
        return False, "La solicitud no tiene correo destino registrado."

    if not es_correo_institucional_unach_views(correo_destino):
        return (
            False,
            "No se envió el correo porque el destinatario no tiene correo institucional @unach.mx."
        )

    folio = getattr(solicitud, "folio", "") or solicitud.id
    nombre_tutor = (
        solicitud.nombre_tutor_completo()
        if hasattr(solicitud, "nombre_tutor_completo")
        else (
            f"{getattr(solicitud, 'nombres_tutor', '')} "
            f"{getattr(solicitud, 'apellido_paterno_tutor', '')} "
            f"{getattr(solicitud, 'apellido_materno_tutor', '')}"
        ).strip() or "Beneficiario"
    )

    estado_aprobada = getattr(Solicitud.Estado, "APROBADA", "APROBADA")
    estado_rechazada = getattr(Solicitud.Estado, "RECHAZADA", "RECHAZADA")
    estado_actual = getattr(solicitud, "estado", "")

    if estado_actual == estado_aprobada:
        asunto = f"Solicitud aprobada - Folio {folio}"
        cuerpo = f"""Estimado(a) {nombre_tutor}:

Tu solicitud de ingreso a la Estancia Infantil UNACH con folio {folio} fue APROBADA.

Puedes continuar con el proceso de inscripción en el sistema.

Datos de acceso temporal:
Usuario: {correo_destino}
Contraseña temporal: Unach2026

Por seguridad, cambia tu contraseña después de ingresar.

Se adjunta el PDF de dictamen correspondiente.

Atentamente,
Estancia Infantil UNACH
"""
    elif estado_actual == estado_rechazada:
        motivo = (
            getattr(solicitud, "comentario_respuesta", "")
            or "No se especificó un motivo adicional."
        )
        asunto = f"Solicitud rechazada - Folio {folio}"
        cuerpo = f"""Estimado(a) {nombre_tutor}:

Tu solicitud de ingreso a la Estancia Infantil UNACH con folio {folio} fue RECHAZADA.

Motivo:
{motivo}

Se adjunta el PDF de dictamen correspondiente.

Atentamente,
Estancia Infantil UNACH
"""
    else:
        asunto = f"Dictamen de solicitud - Folio {folio}"
        cuerpo = f"""Estimado(a) {nombre_tutor}:

Se generó el dictamen de tu solicitud de ingreso con folio {folio}.

Se adjunta el PDF correspondiente.

Atentamente,
Estancia Infantil UNACH
"""

    adjuntos = []
    if pdf_path and os.path.exists(pdf_path):
        adjuntos.append(pdf_path)

    return enviar_correo_institucional_unach(
        asunto=asunto,
        cuerpo=cuerpo,
        destinatarios=[correo_destino],
        usuario_emisor=usuario_emisor,
        adjuntos=adjuntos,
    )


def enviar_correo_estado_inscripcion(inscripcion, tipo, usuario_emisor=None):
    """
    Envía correo al tutor cuando Trabajo Social devuelve o valida expediente.

    Cambio solicitado:
    - Solo envía a correos @unach.mx.
    - El remitente visible se toma dinámicamente del usuario de Trabajo Social
      que inició sesión, sin dejar fijo un correo como trabajadora@unach.mx.
    """
    correo = obtener_correo_tutor(inscripcion)

    if not correo:
        return False, "No hay correo registrado para el beneficiario."

    correo = correo.strip().lower()

    if not es_correo_institucional_unach_views(correo):
        return False, "El correo destino del beneficiario debe ser institucional @unach.mx."

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

    return enviar_correo_institucional_unach(
        asunto=asunto,
        cuerpo=cuerpo,
        destinatarios=[correo],
        usuario_emisor=usuario_emisor,
    )


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
# AUXILIARES - DATOS COMPARTIDOS ENTRE FILTROS
# Psicología, Nutrición y Médico pueden atender en cualquier orden.
# Si un dato compartido ya existe, se muestra como referencia y se protege;
# si todavía no existe, el área actual puede capturarlo.
# =========================================================
AREA_FILTRO_PSICOLOGIA = "PSICOLOGIA"
AREA_FILTRO_NUTRICION = "NUTRICION"
AREA_FILTRO_MEDICO = "MEDICO"

DATOS_COMPARTIDOS_FILTROS = {
    "edad_menor": {
        "etiqueta": "Edad del menor",
        "campos": {
            AREA_FILTRO_PSICOLOGIA: ["edad_psicologia"],
            AREA_FILTRO_NUTRICION: ["edad_nutricion"],
            AREA_FILTRO_MEDICO: ["edad"],
        },
    },
    "sexo_menor": {
        "etiqueta": "Sexo del menor",
        "campos": {
            AREA_FILTRO_NUTRICION: ["sexo_nutricion"],
            AREA_FILTRO_MEDICO: ["sexo"],
        },
    },
    "fecha_nacimiento_menor": {
        "etiqueta": "Fecha de nacimiento del menor",
        "campos": {
            AREA_FILTRO_NUTRICION: ["fecha_nacimiento_nutricion"],
            AREA_FILTRO_MEDICO: ["fecha_nacimiento"],
        },
    },
    "peso_nacer": {
        "etiqueta": "Peso al nacer",
        "campos": {
            AREA_FILTRO_PSICOLOGIA: ["peso_al_nacer_psicologia"],
            AREA_FILTRO_NUTRICION: ["peso_nacer"],
        },
    },
    "talla_nacer": {
        "etiqueta": "Talla al nacer",
        "campos": {
            AREA_FILTRO_PSICOLOGIA: ["talla_al_nacer_psicologia"],
            AREA_FILTRO_NUTRICION: ["talla_nacer"],
        },
    },
    "peso_actual": {
        "etiqueta": "Peso actual",
        "campos": {
            AREA_FILTRO_NUTRICION: ["peso_actual"],
            AREA_FILTRO_MEDICO: ["peso_actual"],
        },
    },
    "talla_actual": {
        "etiqueta": "Talla actual",
        "campos": {
            AREA_FILTRO_NUTRICION: ["talla_actual"],
            AREA_FILTRO_MEDICO: ["talla"],
        },
    },
    "semanas_gestacion": {
        "etiqueta": "Semanas de gestación",
        "campos": {
            AREA_FILTRO_PSICOLOGIA: ["semanas_gestacion_psicologia"],
            AREA_FILTRO_MEDICO: ["semanas_gestacion"],
        },
    },
    "tipo_nacimiento": {
        "etiqueta": "Tipo de nacimiento / parto",
        "campos": {
            AREA_FILTRO_PSICOLOGIA: ["tipo_nacimiento_psicologia"],
            AREA_FILTRO_MEDICO: ["tipo_parto"],
        },
    },
    "numero_gestas": {
        "etiqueta": "Número de gestas",
        "campos": {
            AREA_FILTRO_PSICOLOGIA: ["numero_gesta_psicologia"],
            AREA_FILTRO_MEDICO: ["numero_gestas"],
        },
    },
    "complicaciones_embarazo": {
        "etiqueta": "Complicaciones durante el embarazo",
        "campos": {
            AREA_FILTRO_PSICOLOGIA: ["dificultad_embarazo_psicologia"],
            AREA_FILTRO_MEDICO: ["complicaciones_embarazo"],
        },
    },
    "tipo_alimentacion_inicio": {
        "etiqueta": "Tipo de alimentación inicial",
        "campos": {
            AREA_FILTRO_PSICOLOGIA: ["metodo_alimentacion_inicio_psicologia"],
            AREA_FILTRO_NUTRICION: ["tipo_alimentacion_lactante"],
        },
    },
    "seno_materno": {
        "etiqueta": "Seno materno",
        "campos": {
            AREA_FILTRO_NUTRICION: ["seno_materno"],
        },
    },
    "tiempo_seno_materno": {
        "etiqueta": "Tiempo con seno materno",
        "campos": {
            AREA_FILTRO_NUTRICION: ["tiempo_seno_materno"],
        },
    },
    "formula_infantil": {
        "etiqueta": "Fórmula infantil",
        "campos": {
            AREA_FILTRO_NUTRICION: ["formula_infantil", "cual_formula"],
        },
    },
    "alergia_alimentos": {
        "etiqueta": "Alergia a alimentos",
        "campos": {
            AREA_FILTRO_NUTRICION: ["alergia_alimentos", "cual_alergia"],
            AREA_FILTRO_MEDICO: ["alergia_alimentos"],
        },
    },
    "alergia_medicamentos": {
        "etiqueta": "Alergia a medicamentos",
        "campos": {
            AREA_FILTRO_MEDICO: ["alergia_medicamentos"],
        },
    },
    "enfermedades_actuales": {
        "etiqueta": "Enfermedades actuales",
        "campos": {
            AREA_FILTRO_MEDICO: ["enfermedades_actuales"],
        },
    },
    "estado_nutricional": {
        "etiqueta": "Estado nutricional",
        "campos": {
            AREA_FILTRO_MEDICO: ["estado_nutricional"],
        },
    },
}


def area_filtro_valor(area):
    """Devuelve el valor compatible con DatoCompartidoFiltro.AreaFiltro."""
    return str(area or "").strip().upper()


def normalizar_valor_compartido(valor):
    if valor is None:
        return ""

    if isinstance(valor, (list, tuple, set)):
        return ", ".join(str(v).strip() for v in valor if str(v or "").strip())

    if hasattr(valor, "strftime"):
        try:
            return valor.strftime("%Y-%m-%d")
        except Exception:
            return str(valor or "").strip()

    return str(valor or "").strip()


def obtener_campos_compartidos_area(clave, area):
    config = DATOS_COMPARTIDOS_FILTROS.get(clave, {})
    campos = config.get("campos", {})
    return list(campos.get(area_filtro_valor(area), []))


def obtener_datos_compartidos_bd(sol):
    if not sol:
        return {}

    try:
        return sol.datos_compartidos_por_clave()
    except Exception:
        try:
            return {
                dato.clave: dato
                for dato in sol.datos_compartidos_filtros.all()
            }
        except Exception:
            return {}


def obtener_valor_post_compartido(post_data, clave, area):
    if not post_data:
        return ""

    nombres_posibles = [
        f"dato_compartido_{clave}",
        f"dc_{clave}",
        f"shared_{clave}",
    ] + obtener_campos_compartidos_area(clave, area)

    for nombre in nombres_posibles:
        if not nombre:
            continue

        if hasattr(post_data, "getlist"):
            valores = [
                normalizar_valor_compartido(v)
                for v in post_data.getlist(nombre)
                if normalizar_valor_compartido(v)
            ]
            if len(valores) > 1:
                return ", ".join(valores)

        valor = normalizar_valor_compartido(post_data.get(nombre, ""))
        if valor:
            return valor

    return ""


def obtener_valor_objetos_compartido(clave, area, sol=None, historia=None, insc=None):
    campos = obtener_campos_compartidos_area(clave, area)

    # En Médico, varios campos viven en HistoriaClinicaMedica.
    objetos = []
    if historia is not None:
        objetos.append(historia)
    if sol is not None:
        objetos.append(sol)
    if insc is not None:
        objetos.append(insc)

    for campo in campos:
        for obj in objetos:
            if hasattr(obj, campo):
                valor = normalizar_valor_compartido(getattr(obj, campo, ""))
                if valor:
                    return valor

    return ""


def preparar_post_con_datos_compartidos(post_data, sol, area):
    """
    Protege datos compartidos antes de construir los formularios:
    - Si otro filtro ya capturó el dato, se inyecta el valor correcto en el POST.
    - Si el dato existe y el campo viene vacío, se rellena para evitar "Sin datos".
    - Si el dato no existe, el área actual puede capturarlo normalmente.
    """
    data = post_data.copy()
    area = area_filtro_valor(area)
    datos_bd = obtener_datos_compartidos_bd(sol)

    for clave, config in DATOS_COMPARTIDOS_FILTROS.items():
        dato = datos_bd.get(clave)
        if not dato or not getattr(dato, "tiene_valor", False):
            continue

        valor = normalizar_valor_compartido(getattr(dato, "valor", ""))
        if not valor:
            continue

        editable = False
        try:
            editable = dato.puede_ser_editado_por_area(area)
        except Exception:
            editable = False

        for campo in obtener_campos_compartidos_area(clave, area):
            if not campo:
                continue

            valor_actual = normalizar_valor_compartido(data.get(campo, ""))

            if not editable:
                data[campo] = valor
            elif not valor_actual:
                data[campo] = valor

    return data


def obtener_initial_datos_compartidos_para_area(sol, area):
    area = area_filtro_valor(area)
    initial = {}
    datos_bd = obtener_datos_compartidos_bd(sol)

    for clave, dato in datos_bd.items():
        if clave not in DATOS_COMPARTIDOS_FILTROS:
            continue

        valor = normalizar_valor_compartido(getattr(dato, "valor", ""))
        if not valor:
            continue

        for campo in obtener_campos_compartidos_area(clave, area):
            initial[campo] = valor

    return initial


def aplicar_initial_datos_compartidos(initial, sol, area, sobrescribir_vacios=True):
    initial = dict(initial or {})
    extra = obtener_initial_datos_compartidos_para_area(sol, area)

    for campo, valor in extra.items():
        if sobrescribir_vacios:
            if not normalizar_valor_compartido(initial.get(campo, "")):
                initial[campo] = valor
        else:
            initial[campo] = valor

    return initial


def guardar_datos_compartidos_desde_fuentes(sol, area, usuario=None, post_data=None, historia=None, insc=None):
    """
    Guarda datos compartidos después de validar el formulario del área.
    No sobrescribe información de otra área si ya está bloqueada.
    """
    if not sol:
        return []

    area = area_filtro_valor(area)
    errores = []
    datos_bd = obtener_datos_compartidos_bd(sol)

    for clave, config in DATOS_COMPARTIDOS_FILTROS.items():
        valor = obtener_valor_post_compartido(post_data, clave, area)

        if not valor:
            valor = obtener_valor_objetos_compartido(
                clave,
                area,
                sol=sol,
                historia=historia,
                insc=insc,
            )

        valor = normalizar_valor_compartido(valor)
        if not valor:
            continue

        dato_actual = datos_bd.get(clave)
        if dato_actual and getattr(dato_actual, "tiene_valor", False):
            try:
                if not dato_actual.puede_ser_editado_por_area(area):
                    continue
            except Exception:
                continue

        observacion = ""
        if post_data:
            observacion = normalizar_valor_compartido(
                post_data.get(f"dato_compartido_observacion_{clave}", "")
                or post_data.get(f"dc_observacion_{clave}", "")
            )

        try:
            sol.registrar_dato_compartido(
                clave=clave,
                valor=valor,
                area=area,
                usuario=usuario,
                etiqueta=config.get("etiqueta", ""),
                observacion=observacion,
                fuente=f"formulario_{area.lower()}",
            )
        except ValidationError as exc:
            errores.append(str(exc))
        except Exception as exc:
            errores.append(f"No se pudo guardar el dato compartido '{config.get('etiqueta', clave)}': {exc}")

    return errores


def contexto_datos_compartidos_filtro(sol, area):
    area = area_filtro_valor(area)
    datos_bd = obtener_datos_compartidos_bd(sol)
    lista = []
    por_clave = {}

    for clave, config in DATOS_COMPARTIDOS_FILTROS.items():
        dato = datos_bd.get(clave)
        valor = normalizar_valor_compartido(getattr(dato, "valor", "")) if dato else ""

        editable = True
        nota = "Dato no capturado todavía. Este filtro puede registrarlo si lo necesita."
        area_origen = ""
        capturado_por = ""
        capturado_en = None
        bloqueado_por_otra_area = False

        if dato:
            try:
                editable = dato.puede_ser_editado_por_area(area)
            except Exception:
                editable = not valor

            nota = getattr(dato, "nota_origen", "") or nota
            area_origen = getattr(dato, "area_origen", "") or ""
            capturado_por = getattr(dato, "capturado_por_nombre", "") or ""
            capturado_en = getattr(dato, "capturado_en", None)
            bloqueado_por_otra_area = bool(valor and not editable)

        item = {
            "clave": clave,
            "etiqueta": config.get("etiqueta", clave.replace("_", " ").capitalize()),
            "valor": valor,
            "tiene_valor": bool(valor),
            "editable": editable,
            "solo_lectura": not editable,
            "bloqueado_por_otra_area": bloqueado_por_otra_area,
            "area_origen": area_origen,
            "capturado_por": capturado_por,
            "capturado_en": capturado_en,
            "nota": nota,
            "input_name": f"dato_compartido_{clave}",
            "observacion_name": f"dato_compartido_observacion_{clave}",
            "campos_area": obtener_campos_compartidos_area(clave, area),
            "obj": dato,
        }
        lista.append(item)
        por_clave[clave] = item

    return {
        "datos_compartidos_lista": lista,
        "datos_compartidos_por_clave": por_clave,
        "datos_compartidos_config": DATOS_COMPARTIDOS_FILTROS,
        "area_filtro_actual": area,
    }


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



def obtener_next_seguro(request, default=""):
    """
    Devuelve una URL interna segura para regresar al punto exacto desde donde entró la maestra.
    Acepta rutas con ancla como /admisiones/dashboard-maestra/#historial-alumnos.
    """
    next_url = (
        request.POST.get("next")
        or request.GET.get("next")
        or ""
    ).strip()

    if next_url.startswith("/") and not next_url.startswith("//"):
        return next_url

    return default or ""


def obtener_campo_foto_perfil_usuario(user):
    """
    Detecta si el modelo de usuario tiene un campo de imagen/foto de perfil.
    Se usan varios nombres comunes para no obligar a cambiar el HTML si el campo ya existe.
    """
    if not user:
        return ""

    posibles = [
        "foto_perfil",
        "foto",
        "avatar",
        "imagen_perfil",
        "foto_usuario",
        "imagen",
    ]

    for campo in posibles:
        try:
            field = user._meta.get_field(campo)
            internal_type = field.get_internal_type()
            if internal_type in ["ImageField", "FileField"]:
                return campo
        except Exception:
            continue

    return ""


def obtener_foto_perfil_usuario(user):
    """
    Devuelve la URL de la foto de perfil de la maestra si existe.
    Si el modelo todavía no tiene campo de foto, devuelve cadena vacía.
    """
    campo = obtener_campo_foto_perfil_usuario(user)

    if not campo:
        return ""

    archivo = getattr(user, campo, None)

    if not archivo:
        return ""

    try:
        return archivo.url
    except Exception:
        return ""




def contexto_perfil_maestra(user):
    """
    Contexto reutilizable para mostrar la foto/nombre de la maestra en todas
    las pantallas de operación diaria. La foto pertenece al usuario autenticado,
    por eso no se mezcla con otras maestras.
    """
    return {
        "foto_perfil_maestra_url": obtener_foto_perfil_usuario(user),
        "perfil_maestra_soporta_foto": bool(obtener_campo_foto_perfil_usuario(user)),
    }

def procesar_foto_perfil_maestra(request):
    """
    Actualiza o elimina la foto de perfil de la maestra desde el dashboard.
    Para funcionar, el modelo de usuario debe tener un campo ImageField/FileField,
    por ejemplo: foto_perfil = models.ImageField(upload_to='usuarios/fotos_perfil/', blank=True, null=True)
    """
    destino = obtener_next_seguro(request, reverse("dashboard_maestra") + "#inicio")
    accion = (request.POST.get("accion_perfil_maestra") or "").strip()
    campo_foto = obtener_campo_foto_perfil_usuario(request.user)

    if not campo_foto:
        messages.warning(
            request,
            "El modelo de usuario todavía no tiene un campo para foto de perfil. "
            "Agrega un ImageField en usuarios/models.py o pásame ese archivo para prepararlo."
        )
        return redirect(destino)

    if accion == "eliminar_foto":
        archivo_actual = getattr(request.user, campo_foto, None)

        try:
            if archivo_actual:
                archivo_actual.delete(save=False)
        except Exception:
            pass

        setattr(request.user, campo_foto, None)
        try:
            request.user.save(update_fields=[campo_foto])
        except Exception:
            request.user.save()

        messages.success(request, "Foto de perfil eliminada correctamente.")
        return redirect(destino)

    if accion == "actualizar_foto":
        archivo = request.FILES.get("foto_perfil_maestra")

        if not archivo:
            messages.error(request, "Selecciona una imagen para actualizar tu foto de perfil.")
            return redirect(destino)

        extension = os.path.splitext(archivo.name)[1].lower()
        if extension not in [".jpg", ".jpeg", ".png", ".webp"]:
            messages.error(request, "Formato no permitido. Usa JPG, PNG o WEBP.")
            return redirect(destino)

        max_bytes = 3 * 1024 * 1024
        if getattr(archivo, "size", 0) > max_bytes:
            messages.error(request, "La foto no debe superar 3 MB.")
            return redirect(destino)

        setattr(request.user, campo_foto, archivo)
        try:
            request.user.save(update_fields=[campo_foto])
        except Exception:
            request.user.save()

        messages.success(request, "Foto de perfil actualizada correctamente.")
        return redirect(destino)

    messages.warning(request, "Acción de perfil no válida.")
    return redirect(destino)


def procesar_foto_perfil_area(
    request,
    destino_url,
    campo_archivo="foto_perfil",
    action_actualizar="actualizar_foto",
    action_eliminar="eliminar_foto",
    nombre_area="perfil",
):
    """
    Actualiza o elimina la foto de perfil del usuario autenticado para paneles por área.

    Usa el mismo campo real del modelo de usuario detectado por
    obtener_campo_foto_perfil_usuario(), por eso la foto puede mostrarse después
    en otros paneles del mismo usuario.

    Reglas:
    - JPG, JPEG, PNG o WEBP.
    - Máximo 3 MB.
    - Si el usuario está cubriendo una suplencia, el HTML puede mostrar icono de
      cobertura, pero la foto guardada pertenece siempre al usuario autenticado.
    """
    accion = (request.POST.get("action_type") or "").strip()

    if accion not in [action_actualizar, action_eliminar]:
        return None

    campo_foto = obtener_campo_foto_perfil_usuario(request.user)

    if not campo_foto:
        messages.warning(
            request,
            "El modelo de usuario todavía no tiene un campo para foto de perfil. "
            "Agrega un ImageField/FileField en usuarios/models.py, por ejemplo foto_perfil."
        )
        return redirect(destino_url)

    if accion == action_eliminar:
        archivo_actual = getattr(request.user, campo_foto, None)

        try:
            if archivo_actual:
                archivo_actual.delete(save=False)
        except Exception:
            pass

        setattr(request.user, campo_foto, None)

        try:
            request.user.save(update_fields=[campo_foto])
        except Exception:
            request.user.save()

        messages.success(request, f"Foto de perfil de {nombre_area} eliminada correctamente.")
        return redirect(destino_url)

    archivo = request.FILES.get(campo_archivo) or request.FILES.get("foto_perfil")

    if not archivo:
        messages.error(request, "Selecciona una imagen para actualizar tu foto de perfil.")
        return redirect(destino_url)

    extension = os.path.splitext(getattr(archivo, "name", ""))[1].lower()
    extensiones_permitidas = [".jpg", ".jpeg", ".png", ".webp"]

    if extension not in extensiones_permitidas:
        messages.error(request, "Formato no permitido. Usa JPG, JPEG, PNG o WEBP.")
        return redirect(destino_url)

    max_bytes = 3 * 1024 * 1024

    if getattr(archivo, "size", 0) <= 0:
        messages.error(request, "La imagen seleccionada está vacía. Elige un archivo válido.")
        return redirect(destino_url)

    if getattr(archivo, "size", 0) > max_bytes:
        messages.error(request, "La foto no debe superar 3 MB.")
        return redirect(destino_url)

    archivo_actual = getattr(request.user, campo_foto, None)

    try:
        if archivo_actual:
            archivo_actual.delete(save=False)
    except Exception:
        pass

    setattr(request.user, campo_foto, archivo)

    try:
        request.user.save(update_fields=[campo_foto])
    except Exception:
        request.user.save()

    messages.success(request, f"Foto de perfil de {nombre_area} actualizada correctamente.")
    return redirect(destino_url)


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
    - El emisor visible se toma del usuario que envía la encuesta.
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

    enviado, mensaje = enviar_correo_institucional_unach(
        asunto=asunto,
        cuerpo=cuerpo,
        destinatarios=[envio.correo_destino],
        usuario_emisor=usuario,
        cc=[correo_copia] if correo_copia else [],
    )

    if enviado:
        if es_reenvio:
            envio.marcar_reenviada(usuario=usuario, correo_copia=correo_copia)
        else:
            envio.marcar_enviada(usuario=usuario, correo_copia=correo_copia)

        return True, "Correo enviado correctamente."

    envio.marcar_error(mensaje)
    return False, mensaje


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

def obtener_apoyo_sala_activo_usuario(user):
    """
    Devuelve el apoyo temporal activo de una maestra, si existe.

    Este flujo es independiente de las suplencias de filtros. No requiere
    autorización de Dirección; se registra como apoyo temporal de sala para
    auditoría y consulta de Supervisora/Dirección.
    """
    try:
        return ApoyoSalaMaestra.apoyo_activo_para_maestra(user)
    except Exception:
        return None


def usuario_es_maestra_o_asistente(user):
    """Identifica maestras/asistentes usando area_operativa y grupos antiguos."""
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if str(getattr(user, "area_operativa", "") or "").upper() == "MAESTRA":
        return True

    roles = obtener_roles_usuario(user)
    return any("maestra" in rol or "asistente" in rol or "sala" in rol for rol in roles)


def obtener_sala_origen_maestra(user, semestre=None):
    """
    Devuelve la primera sala asignada a la maestra.
    Se usa como sala original cuando inicia apoyo temporal en otra sala.
    """
    asignacion = obtener_asignaciones_maestra_operativas(user, semestre=semestre).first()
    return asignacion.sala_semestre if asignacion else None


def obtener_maestra_titular_sala(sala_semestre, excluir_usuario=None):
    """
    Devuelve la maestra titular/asignada de una sala.

    Sirve para conservar la responsabilidad principal de la sala apoyada:
    la persona que apoya puede capturar, pero la sala sigue perteneciendo
    a su titular/asignación original.
    """
    if not sala_semestre:
        return None

    qs = (
        AsignacionMaestra.objects
        .filter(sala_semestre=sala_semestre, activo=True)
        .select_related("maestra")
        .order_by("rol", "id")
    )

    if excluir_usuario is not None:
        qs = qs.exclude(maestra_id=getattr(excluir_usuario, "id", None))

    asignacion = qs.first()
    return asignacion.maestra if asignacion else None


def obtener_salas_disponibles_para_apoyo(user, dia=None, semestre=None):
    """Salas activas que una maestra puede seleccionar para apoyo temporal."""
    if semestre is None:
        semestre = getattr(dia, "semestre", None) or obtener_semestre_activo_operativo()

    if not semestre:
        return SalaSemestre.objects.none()

    return (
        SalaSemestre.objects
        .filter(semestre=semestre, activa=True)
        .select_related("semestre", "sala", "sala__sede")
        .order_by("sala__nombre")
    )


def contexto_apoyo_sala_maestra(user, dia=None):
    """
    Contexto común para mostrar en los HTML de maestra:
    - botón Apoyar otra sala,
    - aviso de apoyo activo,
    - botón Finalizar apoyo,
    - bloqueo del botón cuando el día aún no está abierto.

    Regla:
    El apoyo temporal de sala solo puede iniciarse con día operativo ABIERTO.
    """
    apoyo = obtener_apoyo_sala_activo_usuario(user)
    sala_apoyada = getattr(apoyo, "sala_apoyada", None) if apoyo else None
    titular = getattr(apoyo, "maestra_titular_sala", None) if apoyo else None

    dia_abierto_para_apoyo = dia_operativo_permite_apoyo_sala(dia)
    puede_iniciar_apoyo = bool(not apoyo and dia_abierto_para_apoyo)
    mensaje_bloqueo = ""

    if not apoyo and not puede_iniciar_apoyo:
        mensaje_bloqueo = mensaje_apoyo_sala_no_disponible(dia)

    return {
        "apoyo_sala_activo": apoyo,
        "apoyo_temporal_sala_activo": apoyo,
        "tiene_apoyo_sala_activo": bool(apoyo),
        "sala_apoyada_actual": sala_apoyada,
        "maestra_titular_sala_apoyada": titular,
        "puede_iniciar_apoyo_sala": puede_iniciar_apoyo,
        "dia_abierto_para_apoyo_sala": dia_abierto_para_apoyo,
        "apoyo_sala_bloqueado_mensaje": mensaje_bloqueo,
        "mensaje_apoyo_sala_activo": (
            f"Estás apoyando temporalmente {sala_apoyada}. No olvides finalizar el apoyo y regresar a tu sala original."
            if apoyo and sala_apoyada else ""
        ),
    }


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


def obtener_salas_propias_maestra(user, semestre=None):
    """
    Salas asignadas directamente a la maestra en el semestre activo.
    Esta lista se usa para el apartado "Mis salas" y NO incluye apoyos temporales.
    """
    if semestre is None:
        semestre = obtener_semestre_activo_operativo()

    if not semestre:
        return SalaSemestre.objects.none()

    ids = obtener_asignaciones_maestra_operativas(user, semestre=semestre).values_list(
        "sala_semestre_id",
        flat=True,
    )

    return (
        SalaSemestre.objects
        .filter(id__in=ids, semestre=semestre, activa=True)
        .select_related("semestre", "sala", "sala__sede")
        .order_by("sala__nombre")
    )


def anotar_total_alumnos_asignados_salas(salas, semestre=None):
    """
    Agrega a cada SalaSemestre el atributo total_alumnos_asignados.
    Cuenta alumnos FINALIZADOS asignados a esa sala, aunque el día esté cerrado
    o aunque el menor ya tenga salida. Esto evita que "Mis salas" marque 0
    cuando sí hay alumnos asignados.
    """
    salas_lista = list(salas or [])

    if not salas_lista:
        return salas_lista

    if semestre is None:
        semestre = getattr(salas_lista[0], "semestre", None)

    sala_ids = [s.id for s in salas_lista if getattr(s, "id", None)]

    conteos = {
        item["sala_semestre_asignada_id"]: item["total"]
        for item in (
            SolicitudInscripcion.objects
            .filter(
                estado="FINALIZADA",
                sala_semestre_asignada_id__in=sala_ids,
                semestre=semestre,
            )
            .values("sala_semestre_asignada_id")
            .annotate(total=Count("id"))
        )
    }

    for sala in salas_lista:
        sala.total_alumnos_asignados = conteos.get(getattr(sala, "id", None), 0)

    return salas_lista


def obtener_alumnos_asignados_a_salas(salas, semestre=None):
    """
    Devuelve los alumnos FINALIZADOS asignados a las salas indicadas.

    Se usa para secciones que NO deben depender de que el día esté abierto
    ni de que ya existan registros diarios, por ejemplo:
    - Mis salas / conteo de asignados.
    - Alumnos del día cuando todavía está pendiente la apertura.
    - Historial de alumnos, disponible como consulta permanente.

    Si la maestra está apoyando otra sala, la vista debe enviar aquí solo la sala
    apoyada para evitar mezclar alumnos de su sala principal con la sala cubierta.
    """
    salas_lista = list(salas or [])

    if not salas_lista:
        return SolicitudInscripcion.objects.none()

    if semestre is None:
        semestre = getattr(salas_lista[0], "semestre", None)

    sala_ids = [s.id for s in salas_lista if getattr(s, "id", None)]

    if not sala_ids:
        return SolicitudInscripcion.objects.none()

    qs = (
        SolicitudInscripcion.objects
        .filter(
            estado="FINALIZADA",
            sala_semestre_asignada_id__in=sala_ids,
        )
        .select_related(
            "solicitud_ingreso",
            "sala_semestre_asignada",
            "sala_semestre_asignada__sala",
            "semestre",
        )
        .order_by(
            "sala_semestre_asignada__sala__nombre",
            "solicitud_ingreso__apellido_paterno_menor",
            "solicitud_ingreso__apellido_materno_menor",
            "solicitud_ingreso__nombres_menor",
        )
    )

    if semestre is not None:
        qs = qs.filter(semestre=semestre)

    return qs


def agregar_alumnos_asignados_a_salas(salas, semestre=None):
    """
    Agrega a cada SalaSemestre una lista alumnos_asignados_lista para que
    el HTML pueda desplegar los menores pertenecientes a cada sala.

    Esta lista se calcula por sala y por semestre, no por registro diario;
    por eso funciona aunque el día esté programado, cerrado o aún no existan
    registros del día.
    """
    salas_lista = list(salas or [])

    if not salas_lista:
        return salas_lista

    if semestre is None:
        semestre = getattr(salas_lista[0], "semestre", None)

    sala_ids = [s.id for s in salas_lista if getattr(s, "id", None)]

    alumnos = list(obtener_alumnos_asignados_a_salas(salas_lista, semestre=semestre))

    alumnos_por_sala = {sala_id: [] for sala_id in sala_ids}
    for alumno in alumnos:
        sala_id = getattr(alumno, "sala_semestre_asignada_id", None)
        alumnos_por_sala.setdefault(sala_id, []).append(alumno)

    for sala in salas_lista:
        lista = alumnos_por_sala.get(getattr(sala, "id", None), [])
        try:
            sala.alumnos_asignados_lista = lista
            sala.total_alumnos_asignados = len(lista)
        except Exception:
            pass

    return salas_lista



def obtener_salas_maestra_operativas(user, semestre=None):
    """
    Salas que la maestra está operando en este momento.

    Regla importante:
    - Si NO hay apoyo temporal activo, opera sus salas asignadas.
    - Si SÍ hay apoyo temporal activo, opera SOLO la sala apoyada.

    Esto evita mezclar alumnos de la sala principal con alumnos de la sala que
    está cubriendo temporalmente.
    """
    if semestre is None:
        semestre = obtener_semestre_activo_operativo()

    if not semestre:
        return SalaSemestre.objects.none()

    apoyo = obtener_apoyo_sala_activo_usuario(user)
    if apoyo and getattr(apoyo, "sala_apoyada_id", None):
        try:
            if apoyo.sala_apoyada.semestre_id == semestre.id:
                return (
                    SalaSemestre.objects
                    .filter(id=apoyo.sala_apoyada_id, semestre=semestre, activa=True)
                    .select_related("semestre", "sala", "sala__sede")
                    .order_by("sala__nombre")
                )
        except Exception:
            return (
                SalaSemestre.objects
                .filter(id=apoyo.sala_apoyada_id, activa=True)
                .select_related("semestre", "sala", "sala__sede")
                .order_by("sala__nombre")
            )

    return obtener_salas_propias_maestra(user, semestre=semestre)


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



def dia_operativo_permite_apoyo_sala(dia):
    """
    Regla específica para el botón "Apoyar otra sala".

    El apoyo temporal de maestras solo puede iniciar cuando:
    - existe día operativo,
    - el día es laborable,
    - el día ya fue abierto.

    Esto evita que una maestra seleccione otra sala antes de iniciar la jornada.
    """
    return bool(
        dia
        and dia_operativo_es_laborable(dia)
        and getattr(dia, "estado", "") == DiaOperativoSemestre.EstadoDia.ABIERTO
    )


def mensaje_apoyo_sala_no_disponible(dia):
    """
    Mensaje seguro para explicar por qué no se permite iniciar apoyo de sala.
    """
    mensaje_no_operativo = mensaje_dia_no_operativo(dia)
    if mensaje_no_operativo:
        return mensaje_no_operativo

    if not dia:
        return "No existe día operativo para hoy. No se puede apoyar otra sala."

    estado = getattr(dia, "estado", "")

    if estado == DiaOperativoSemestre.EstadoDia.PROGRAMADO:
        return "Primero debes iniciar el día operativo para poder apoyar otra sala."

    if estado == DiaOperativoSemestre.EstadoDia.CERRADO:
        return "El día operativo ya está cerrado. No se puede iniciar apoyo temporal."

    if estado != DiaOperativoSemestre.EstadoDia.ABIERTO:
        return "El apoyo temporal solo está disponible cuando el día operativo está abierto."

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
    Crea el registro diario de cada alumno de las salas que puede operar la maestra.

    Si la maestra está apoyando otra sala, también prepara los alumnos de esa sala.
    En ese caso, el registro conserva como creador preferente a la titular/asignada
    de la sala apoyada; la persona que apoya queda identificada en las acciones
    específicas como entrada_por, salida_por o capturada_por.
    """
    if (
        not dia
        or not dia_operativo_es_laborable(dia)
        or dia.estado != DiaOperativoSemestre.EstadoDia.ABIERTO
    ):
        return 0

    salas = obtener_salas_maestra_operativas(user, semestre=dia.semestre)
    apoyo = obtener_apoyo_sala_activo_usuario(user)

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
        sala = inscripcion.sala_semestre_asignada
        creador = user

        if apoyo and sala and sala.id == getattr(apoyo, "sala_apoyada_id", None):
            creador = (
                getattr(apoyo, "maestra_titular_sala", None)
                or obtener_maestra_titular_sala(sala, excluir_usuario=user)
                or user
            )

        _, created = RegistroDiarioAlumno.objects.get_or_create(
            dia_operativo=dia,
            alumno=inscripcion,
            defaults={
                "sala_semestre": sala,
                "creado_por": creador,
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
    """
    Dirección se identifica por area_operativa=DIRECCION y, por compatibilidad,
    también por grupos antiguos que contengan directora/dirección.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    area = str(getattr(user, "area_operativa", "") or "").upper()
    if area == "DIRECCION":
        return True

    roles = obtener_roles_usuario(user)
    tipo = normalizar_texto(getattr(user, "tipo_persona", ""))

    return (
        "directora" in roles
        or "direccion" in roles
        or "dirección" in roles
        or tipo in ["directora", "direccion", "dirección"]
    )


def usuario_es_trabajadora_social(user):
    """
    Trabajo Social se identifica por area_operativa=TRABAJO_SOCIAL y por grupos
    anteriores. La cobertura por suplencia se valida aparte para no cambiar
    el rol real de la persona.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    area = str(getattr(user, "area_operativa", "") or "").upper()
    if area == "TRABAJO_SOCIAL":
        return True

    roles = obtener_roles_usuario(user)
    tipo = normalizar_texto(getattr(user, "tipo_persona", ""))

    return (
        "trabajadora social" in roles
        or "trabajador social" in roles
        or "trabajo social" in roles
        or tipo in ["trabajadora_social", "trabajo_social"]
    )


def usuario_puede_reporte_final_ts(user):
    """
    Puede registrar el reporte final de ingreso:
    - Trabajadora Social
    - Administrador del sistema
    - Persona con cobertura temporal autorizada para Trabajo Social
    """
    return (
        usuario_es_admin(user)
        or usuario_es_trabajadora_social(user)
        or usuario_tiene_cobertura_trabajo_social(user)
    )


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
    - Persona con cobertura temporal autorizada para Trabajo Social
    """
    return (
        usuario_es_admin(user)
        or usuario_es_trabajadora_social(user)
        or usuario_tiene_cobertura_trabajo_social(user)
    )



def usuario_puede_gestionar_codigo_responsable(user):
    """
    Puede generar/resetear el código de seguridad:
    - Trabajadora Social
    - Administrador del sistema
    - Persona con cobertura temporal autorizada para Trabajo Social
    """
    return usuario_puede_gestionar_pagos(user)



# =========================================================
# AUXILIARES - SUPLENCIAS Y AUTORIZACIONES TEMPORALES
# Dirección registra pase de lista, autoriza suplencias y cada suplente
# conserva su panel normal. La viñeta "Cubriendo temporalmente" se muestra
# por contexto, sin cambiar el rol real del usuario.
# =========================================================

AREA_CUBIERTA_A_TIPO_INCIDENCIA = {
    "MEDICA": lambda: Incidencia.TipoIncidencia.MEDICA,
    "NUTRICION": lambda: Incidencia.TipoIncidencia.NUTRICIONAL,
    "PSICOLOGIA": lambda: Incidencia.TipoIncidencia.PSICOLOGICA,
    "PEDAGOGICA": lambda: Incidencia.TipoIncidencia.PEDAGOGICA,
}

AREA_FILTRO_A_AREA_CUBIERTA = {
    "psicologia": "PSICOLOGIA",
    "nutricion": "NUTRICION",
    "medico": "MEDICA",
}

PREFIJO_DICTAMEN_SUPLENCIA = {
    "psicologia": "psicologia",
    "nutricion": "nutricion",
    "medico": "medico",
}


def area_operativa_usuario(user):
    """
    Área operativa del usuario.
    Usa area_operativa si ya está capturada y, como respaldo, la infiere
    desde grupos/correo/nombre para usuarios existentes.
    """
    try:
        return inferir_area_operativa_usuario(user)
    except Exception:
        return str(getattr(user, "area_operativa", "") or "").upper()


def usuario_tiene_area_operativa(user, *areas):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    areas = [str(area or "").upper() for area in areas]
    return area_operativa_usuario(user) in areas


def tipo_incidencia_para_area_cubierta(area_cubierta):
    factory = AREA_CUBIERTA_A_TIPO_INCIDENCIA.get(str(area_cubierta or "").upper())
    return factory() if factory else None


def area_cubierta_para_tipo_incidencia(tipo):
    tipo = str(tipo or "").upper()
    for area, factory in AREA_CUBIERTA_A_TIPO_INCIDENCIA.items():
        try:
            if factory() == tipo:
                return area
        except Exception:
            continue
    return ""


def obtener_suplencias_activas_usuario(user, fecha=None):
    if not user or not getattr(user, "is_authenticated", False):
        return AutorizacionSuplencia.objects.none()

    fecha = fecha or timezone.localdate()

    try:
        return (
            AutorizacionSuplencia.activas_para_usuario(user, fecha=fecha)
            .select_related("titular_ausente", "suplente", "autorizada_por", "asistencia_personal")
            .order_by("area_cubierta", "-created_at")
        )
    except Exception:
        return AutorizacionSuplencia.objects.none()


def obtener_suplencia_activa_usuario_area(user, area_cubierta, accion=None):
    area_cubierta = str(area_cubierta or "").upper()

    if not area_cubierta:
        return None

    qs = obtener_suplencias_activas_usuario(user).filter(area_cubierta=area_cubierta)

    for autorizacion in qs:
        try:
            if accion is None or autorizacion.permite_accion(accion):
                return autorizacion
        except Exception:
            if accion is None:
                return autorizacion

    return None


def obtener_suplencia_activa_para_filtro(user, area_filtro):
    area_cubierta = AREA_FILTRO_A_AREA_CUBIERTA.get(str(area_filtro or "").lower())
    return obtener_suplencia_activa_usuario_area(user, area_cubierta, accion="DICTAMEN")


def obtener_suplencia_activa_para_tipo_incidencia(user, tipo_incidencia):
    area_cubierta = area_cubierta_para_tipo_incidencia(tipo_incidencia)
    return obtener_suplencia_activa_usuario_area(user, area_cubierta, accion="INCIDENCIA")


def usuario_tiene_suplencia_para_filtro(user, area_filtro):
    return bool(obtener_suplencia_activa_para_filtro(user, area_filtro))


def usuario_tiene_suplencia_para_tipo_incidencia(user, tipo_incidencia):
    return bool(obtener_suplencia_activa_para_tipo_incidencia(user, tipo_incidencia))


def usuario_tiene_cobertura_trabajo_social(user):
    """
    Cobertura especial para Trabajo Social.

    No cambia el rol real de la persona. Solo permite continuar el proceso social
    cuando Dirección autorizó suplencia porque la titular está ausente.
    """
    return bool(
        obtener_suplencia_activa_usuario_area(
            user,
            AutorizacionSuplencia.AreaCubierta.TRABAJO_SOCIAL,
            accion="PROCESO_SOCIAL",
        )
    )


def descripcion_autorizacion_suplencia(autorizacion):
    if not autorizacion:
        return ""

    try:
        area = autorizacion.get_area_cubierta_display()
    except Exception:
        area = getattr(autorizacion, "area_cubierta", "")

    try:
        tipo = autorizacion.get_tipo_cobertura_display()
    except Exception:
        tipo = getattr(autorizacion, "tipo_cobertura", "")

    return f"Cubriendo temporalmente: {area} — {tipo}"


def reverse_seguro_suplencia(nombre_url, *args, fallback="/"):
    """
    Resuelve una URL de forma segura para las acciones de suplencia.

    No rompe el sistema si en urls.py todavía existe un nombre anterior o si
    una ruta se renombró durante el desarrollo.
    """
    if not nombre_url:
        return fallback

    try:
        return reverse(nombre_url, args=args)
    except Exception:
        return fallback


def agregar_query_suplencia(url, **params):
    """
    Agrega parámetros a una URL conservando anchors como #vista-pendientes.
    """
    url = url or "/"
    anchor = ""

    if "#" in url:
        url, anchor = url.split("#", 1)
        anchor = f"#{anchor}"

    params_limpios = {
        key: value
        for key, value in params.items()
        if value not in [None, "", False]
    }

    if params_limpios:
        separador = "&" if "?" in url else "?"
        url = f"{url}{separador}{urlencode(params_limpios)}"

    return f"{url}{anchor}"


def construir_accion_suplencia(autorizacion):
    """
    Construye las acciones reales de una suplencia según el área cubierta.

    Regla clave:
    - El panel real del usuario NO cambia.
    - La viñeta de "Cubriendo temporalmente" debe mandar al área cubierta,
      no al panel donde el usuario inició sesión.

    Ejemplo:
    Si una psicóloga cubre Nutrición, la acción principal debe ir a
    nutricion_pendientes y la incidencia debe ser tipo NUTRICIONAL.
    """
    if not autorizacion:
        return None

    area = str(getattr(autorizacion, "area_cubierta", "") or "").upper()
    autorizacion_id = getattr(autorizacion, "pk", None) or getattr(autorizacion, "id", None)

    meta_por_area = {
        "MEDICA": {
            "area_display": "Médica",
            "panel_view": "medico_pendientes",
            "panel_fallback": "/admisiones/medico/",
            "dictamen_label": "Ir a dictámenes médicos",
            "dictamen_corto": "Dictaminar médica",
            "incidencia_tipo": "MEDICA",
            "incidencia_label": "Incidencia médica",
            "icono": "bi-heart-pulse-fill",
            "es_filtro": True,
        },
        "NUTRICION": {
            "area_display": "Nutrición",
            "panel_view": "nutricion_pendientes",
            "panel_fallback": "/admisiones/nutricion/",
            "dictamen_label": "Ir a dictámenes de Nutrición",
            "dictamen_corto": "Dictaminar nutrición",
            "incidencia_tipo": "NUTRICIONAL",
            "incidencia_label": "Incidencia nutricional",
            "icono": "bi-egg-fried",
            "es_filtro": True,
        },
        "PSICOLOGIA": {
            "area_display": "Psicología",
            "panel_view": "psicologia_pendientes",
            "panel_fallback": "/admisiones/psicologia/",
            "dictamen_label": "Ir a dictámenes de Psicología",
            "dictamen_corto": "Dictaminar psicología",
            "incidencia_tipo": "PSICOLOGICA",
            "incidencia_label": "Incidencia psicológica",
            "icono": "bi-person-heart",
            "es_filtro": True,
        },
        "PEDAGOGICA": {
            "area_display": "Pedagógica",
            "panel_view": "dashboard_coordinadora",
            "panel_fallback": "/admisiones/coordinadora/",
            "dictamen_label": "Ir al panel pedagógico",
            "dictamen_corto": "Panel pedagógico",
            "incidencia_tipo": "PEDAGOGICA",
            "incidencia_label": "Incidencia pedagógica",
            "icono": "bi-journal-check",
            "es_filtro": False,
        },
        "TRABAJO_SOCIAL": {
            "area_display": "Trabajo Social",
            "panel_view": "panel_admisiones",
            "panel_fallback": "/admisiones/",
            "dictamen_label": "Ir a Trabajo Social",
            "dictamen_corto": "Trabajo Social",
            "incidencia_tipo": "",
            "incidencia_label": "",
            "icono": "bi-person-check-fill",
            "es_filtro": False,
        },
    }

    meta = meta_por_area.get(area, {
        "area_display": area or "Área no definida",
        "panel_view": "",
        "panel_fallback": "/",
        "dictamen_label": "Ir al módulo correspondiente",
        "dictamen_corto": "Ir al módulo",
        "incidencia_tipo": "",
        "incidencia_label": "",
        "icono": "bi-person-badge-fill",
        "es_filtro": False,
    })

    panel_base_url = reverse_seguro_suplencia(
        meta.get("panel_view"),
        fallback=meta.get("panel_fallback", "/"),
    )

    panel_url = agregar_query_suplencia(
        panel_base_url,
        suplencia=autorizacion_id,
        area_suplencia=area,
    )

    if area in ["MEDICA", "NUTRICION", "PSICOLOGIA"]:
        dictamen_url = agregar_query_suplencia(
            f"{panel_base_url}#vista-pendientes",
            suplencia=autorizacion_id,
            area_suplencia=area,
        )
    else:
        dictamen_url = panel_url

    incidencia_tipo = meta.get("incidencia_tipo") or ""
    incidencia_url = ""

    if incidencia_tipo:
        incidencia_base_url = reverse_seguro_suplencia(
            "crear_incidencia_tipo",
            incidencia_tipo,
            fallback="/admisiones/incidencias/crear/",
        )
        incidencia_url = agregar_query_suplencia(
            incidencia_base_url,
            tipo=incidencia_tipo,
            suplencia=autorizacion_id,
            area_suplencia=area,
            next=panel_base_url,
        )

    # Acciones especiales de Trabajo Social, porque no es un solo dictamen.
    trabajo_social_urls = {}
    if area == "TRABAJO_SOCIAL":
        trabajo_social_urls = {
            "solicitudes_url": agregar_query_suplencia(
                reverse_seguro_suplencia("panel_admisiones", fallback="/admisiones/"),
                suplencia=autorizacion_id,
                area_suplencia=area,
            ),
            "reporte_final_url": agregar_query_suplencia(
                reverse_seguro_suplencia("reporte_final_pendientes", fallback="/admisiones/reporte-final/"),
                suplencia=autorizacion_id,
                area_suplencia=area,
            ),
            "pagos_url": agregar_query_suplencia(
                reverse_seguro_suplencia("validacion_pagos_pendientes", fallback="/admisiones/pagos/"),
                suplencia=autorizacion_id,
                area_suplencia=area,
            ),
            "codigos_url": agregar_query_suplencia(
                reverse_seguro_suplencia("codigos_responsable_pendientes", fallback="/admisiones/codigos-responsable/"),
                suplencia=autorizacion_id,
                area_suplencia=area,
            ),
        }

    accion = {
        "id": autorizacion_id,
        "autorizacion": autorizacion,
        "area": area,
        "area_cubierta": area,
        "area_display": meta.get("area_display"),
        "icono": meta.get("icono"),
        "panel_url": panel_url,
        "panel_base_url": panel_base_url,
        "dictamen_url": dictamen_url,
        "dictamen_label": meta.get("dictamen_label"),
        "dictamen_corto": meta.get("dictamen_corto"),
        "incidencia_url": incidencia_url,
        "incidencia_tipo": incidencia_tipo,
        "incidencia_label": meta.get("incidencia_label"),
        "tiene_incidencia": bool(incidencia_url),
        "es_filtro": bool(meta.get("es_filtro")),
        "es_trabajo_social": area == "TRABAJO_SOCIAL",
        **trabajo_social_urls,
    }

    # Atributos temporales para que los HTML puedan usar sup.panel_url,
    # sup.dictamen_url, sup.incidencia_url, etc., sin crear modelos nuevos.
    for clave, valor in accion.items():
        if clave != "autorizacion":
            try:
                setattr(autorizacion, clave, valor)
            except Exception:
                pass

    try:
        autorizacion.accion_suplencia = accion
        autorizacion.acciones_suplencia = accion
        autorizacion.url_panel_area = panel_url
        autorizacion.url_dictaminar_suplencia = dictamen_url
        autorizacion.url_incidencia_suplencia = incidencia_url
        autorizacion.label_dictaminar_suplencia = meta.get("dictamen_label")
        autorizacion.label_incidencia_suplencia = meta.get("incidencia_label")
    except Exception:
        pass

    return accion


def contexto_suplencias_usuario(user):
    """
    Contexto genérico para mostrar la viñeta "Cubriendo temporalmente" en
    los paneles existentes sin crear nuevos HTML.

    Ahora las acciones salen según el área cubierta:
    - Si cubre Nutrición, manda a Nutrición.
    - Si cubre Médica, manda a Médica.
    - Si cubre Psicología, manda a Psicología.
    - Si cubre Pedagógica, manda al panel pedagógico.
    - Si cubre Trabajo Social, manda al proceso social.
    """
    suplencias = list(obtener_suplencias_activas_usuario(user))
    acciones = []

    for suplencia in suplencias:
        accion = construir_accion_suplencia(suplencia)
        if accion:
            acciones.append(accion)

    suplencias_por_area = {}
    for suplencia in suplencias:
        area = str(getattr(suplencia, "area_cubierta", "") or "").upper()
        if area:
            suplencias_por_area.setdefault(area, []).append(suplencia)

    acciones_por_area = {}
    for accion in acciones:
        area = accion.get("area")
        if area:
            acciones_por_area.setdefault(area, []).append(accion)

    return {
        "suplencias_activas_usuario": suplencias,
        "suplencias_activas": suplencias,
        "suplencias_usuario": suplencias,
        "suplencias_acciones_usuario": acciones,
        "acciones_suplencia_usuario": acciones,
        "suplencias_por_area_usuario": suplencias_por_area,
        "acciones_suplencia_por_area": acciones_por_area,
        "tiene_suplencia_activa": bool(suplencias),
        "texto_suplencia_activa": "; ".join(descripcion_autorizacion_suplencia(s) for s in suplencias),
        "tiene_suplencia_medica": bool(suplencias_por_area.get("MEDICA")),
        "tiene_suplencia_nutricion": bool(suplencias_por_area.get("NUTRICION")),
        "tiene_suplencia_psicologia": bool(suplencias_por_area.get("PSICOLOGIA")),
        "tiene_suplencia_pedagogica": bool(suplencias_por_area.get("PEDAGOGICA")),
        "tiene_suplencia_trabajo_social": bool(suplencias_por_area.get("TRABAJO_SOCIAL")),
    }


def estado_pase_lista_dia(fecha=None):
    """
    Devuelve estado de asistencia del personal operativo para Dirección.
    Si no hay registros, se devuelve como NO_REGISTRADO para que el sistema
    no autorice suplencias sin pase de lista.
    """
    fecha = fecha or timezone.localdate()
    personal = list(personal_operativo_pase_lista_queryset())
    registros = {
        asistencia.trabajador_id: asistencia
        for asistencia in AsistenciaPersonal.objects.filter(fecha=fecha).select_related(
            "trabajador",
            "registrado_por",
            "actualizado_por",
        )
    }

    filas = []
    total_presentes = 0
    total_ausentes = 0
    total_no_registrado = 0

    for trabajador in personal:
        asistencia = registros.get(trabajador.id)
        estado = getattr(asistencia, "estado", AsistenciaPersonal.EstadoAsistencia.NO_REGISTRADO)
        area_operativa = inferir_area_operativa_usuario(trabajador)
        area_display = nombre_area_operativa_usuario(trabajador)
        area_pendiente = not bool(area_operativa)

        if asistencia and not getattr(asistencia, "area_operativa", "") and area_operativa:
            asistencia.area_operativa = area_operativa
            try:
                asistencia.save(update_fields=["area_operativa"])
            except Exception:
                pass

        if estado == AsistenciaPersonal.EstadoAsistencia.PRESENTE:
            total_presentes += 1
        elif estado in [
            AsistenciaPersonal.EstadoAsistencia.AUSENTE,
            AsistenciaPersonal.EstadoAsistencia.PERMISO,
            AsistenciaPersonal.EstadoAsistencia.INCAPACIDAD,
        ]:
            total_ausentes += 1
        elif estado == AsistenciaPersonal.EstadoAsistencia.NO_REGISTRADO:
            total_no_registrado += 1

        filas.append({
            "trabajador": trabajador,
            "asistencia": asistencia,
            "estado": estado,
            "estado_display": asistencia.get_estado_display() if asistencia else "No registrado",
            "permite_suplencia": bool(asistencia and asistencia.permite_suplencia),
            "esta_presente": estado == AsistenciaPersonal.EstadoAsistencia.PRESENTE,
            "sin_registrar": estado == AsistenciaPersonal.EstadoAsistencia.NO_REGISTRADO,
            "area_operativa": area_operativa,
            "area_display": area_display,
            "area_pendiente": area_pendiente,
        })

    total_personal = len(personal)
    pase_lista_completo = bool(total_personal and total_no_registrado == 0)
    todo_personal_presente = bool(pase_lista_completo and total_ausentes == 0)

    return {
        "fecha_pase_lista": fecha,
        "personal_pase_lista": personal,
        "asistencias_pase_lista": filas,
        "pase_lista_completo": pase_lista_completo,
        "todo_personal_presente": todo_personal_presente,
        "total_personal_pase_lista": total_personal,
        "total_personal_presente": total_presentes,
        "total_personal_ausente": total_ausentes,
        "total_personal_no_registrado": total_no_registrado,
        "ausencias_para_suplencia": [fila for fila in filas if fila["permite_suplencia"]],
    }


def contexto_suplencias_direccion(user=None, fecha=None, request=None):
    fecha = fecha or timezone.localdate()
    semestre = obtener_semestre_activo_operativo()
    estado = estado_pase_lista_dia(fecha=fecha)
    personal = estado["personal_pase_lista"]

    post_data = None
    if request is not None and request.method == "POST":
        post_data = request.POST

    pase_lista_form = PaseListaPersonalForm(
        post_data if post_data and post_data.get("accion_directiva") == "guardar_pase_lista" else None,
        usuario=user,
        semestre=semestre,
        fecha=fecha,
        personal=personal,
    )

    suplencia_form = AutorizacionSuplenciaForm(
        post_data if post_data and post_data.get("accion_directiva") == "crear_suplencia" else None,
        usuario=user,
        semestre=semestre,
        fecha=fecha,
    )

    suplencias_activas = (
        AutorizacionSuplencia.objects
        .filter(fecha=fecha, estado=AutorizacionSuplencia.EstadoAutorizacion.ACTIVA)
        .select_related("titular_ausente", "suplente", "autorizada_por", "asistencia_personal")
        .order_by("area_cubierta", "-created_at")
    )

    movimientos = (
        MovimientoSuplencia.objects
        .select_related(
            "autorizacion",
            "usuario",
            "titular_area",
            "solicitud",
            "inscripcion",
            "incidencia",
            "revisado_por",
        )
        .order_by("-creado_en")[:50]
    )

    contexto = {
        **estado,
        "pase_lista_form": pase_lista_form,
        "suplencia_form": suplencia_form,
        "suplencias_activas_dia": suplencias_activas,
        "movimientos_suplencia_recientes": movimientos,
        "bitacora_suplencias": movimientos,
    }

    return contexto


def registrar_movimiento_suplencia(
    autorizacion,
    usuario,
    accion,
    descripcion,
    solicitud=None,
    inscripcion=None,
    incidencia=None,
    objeto=None,
    estado=None,
):
    """
    Crea una bitácora visible para Dirección y Supervisora.

    Se usa desde incidencias, dictámenes y procesos de Trabajo Social.
    """
    if not autorizacion:
        return None

    try:
        objeto_modelo = ""
        objeto_id = None

        if objeto is not None:
            try:
                objeto_modelo = objeto._meta.label
            except Exception:
                objeto_modelo = objeto.__class__.__name__
            objeto_id = getattr(objeto, "pk", None)

        return MovimientoSuplencia.objects.create(
            autorizacion=autorizacion,
            usuario=usuario,
            titular_area=autorizacion.titular_ausente,
            area_cubierta=autorizacion.area_cubierta,
            accion=accion,
            descripcion=descripcion,
            solicitud=solicitud,
            inscripcion=inscripcion,
            incidencia=incidencia,
            objeto_modelo=objeto_modelo,
            objeto_id=objeto_id,
            estado=estado or MovimientoSuplencia.EstadoMovimiento.PENDIENTE,
        )
    except Exception:
        return None


# =========================================================
# AUXILIARES - BLOQUEO TEMPORAL DE EDICIÓN POR EXPEDIENTE
# =========================================================
def contexto_bloqueos_edicion_area(area=None, limite=50):
    """
    Contexto ligero para que los paneles puedan mostrar quién está editando
    un expediente o registro en ese momento.
    """
    try:
        qs = BloqueoEdicionTemporal.activos().select_related(
            "usuario",
            "solicitud",
            "inscripcion",
            "incidencia",
            "autorizacion_suplencia",
        )
        if area:
            qs = qs.filter(area=str(area or "").upper())
        bloqueos = list(qs[:limite])
    except Exception:
        bloqueos = []

    por_solicitud = {}
    por_inscripcion = {}
    por_incidencia = {}
    por_objeto = {}

    for bloqueo in bloqueos:
        if getattr(bloqueo, "solicitud_id", None):
            por_solicitud[bloqueo.solicitud_id] = bloqueo
        if getattr(bloqueo, "inscripcion_id", None):
            por_inscripcion[bloqueo.inscripcion_id] = bloqueo
        if getattr(bloqueo, "incidencia_id", None):
            por_incidencia[bloqueo.incidencia_id] = bloqueo
        try:
            por_objeto[(bloqueo.modelo, bloqueo.objeto_id)] = bloqueo
        except Exception:
            pass

    return {
        "bloqueos_edicion_activos": bloqueos,
        "bloqueos_edicion_por_solicitud": por_solicitud,
        "bloqueos_edicion_por_inscripcion": por_inscripcion,
        "bloqueos_edicion_por_incidencia": por_incidencia,
        "bloqueos_edicion_por_objeto": por_objeto,
    }


def mensaje_bloqueo_edicion(conflicto):
    if not conflicto:
        return "Este expediente está siendo atendido por otra persona."
    usuario = getattr(conflicto, "usuario_nombre", "Otra persona")
    area = getattr(conflicto, "area", "") or "este módulo"
    objeto = getattr(conflicto, "descripcion_objeto", "este expediente")
    return (
        f"{objeto} está siendo atendido por {usuario} en {area}. "
        "Puedes avanzar con otros expedientes; este queda bloqueado temporalmente para evitar duplicidad."
    )


def iniciar_bloqueo_edicion_temporal(request, objeto, area="", autorizacion_suplencia=None, retorno="/", motivo=""):
    """
    Crea o refresca el bloqueo del objeto actual.
    Devuelve (bloqueo, respuesta_redirect). Si hay conflicto, respuesta_redirect
    contiene la redirección segura al panel indicado.
    """
    try:
        bloqueo, creado, conflicto = BloqueoEdicionTemporal.intentar_bloquear(
            usuario=request.user,
            objeto=objeto,
            area=area,
            autorizacion_suplencia=autorizacion_suplencia,
            motivo=motivo,
        )
    except Exception:
        return None, None

    if conflicto:
        messages.warning(request, mensaje_bloqueo_edicion(conflicto))
        try:
            return None, redirect(retorno)
        except Exception:
            return None, redirect("/")

    return bloqueo, None


def liberar_bloqueo_edicion_temporal(request, objeto, observaciones=""):
    try:
        return BloqueoEdicionTemporal.liberar_para_objeto(
            usuario=request.user,
            objeto=objeto,
            observaciones=observaciones,
        )
    except Exception:
        return 0


@login_required
@require_http_methods(["POST"])
def ping_bloqueo_edicion(request):
    """Refresca un bloqueo desde AJAX si luego se agrega JS en los HTML."""
    bloqueo_id = request.POST.get("bloqueo_id")
    bloqueo = get_object_or_404(BloqueoEdicionTemporal, pk=bloqueo_id, usuario=request.user)
    bloqueo.tocar(usuario=request.user)
    return JsonResponse({"ok": True, "ultimo_ping": bloqueo.ultimo_ping.isoformat()})


@login_required
@require_http_methods(["POST"])
def liberar_bloqueo_edicion(request, bloqueo_id):
    """Libera un bloqueo temporal propio; Dirección/Admin también puede liberarlo."""
    bloqueo = get_object_or_404(BloqueoEdicionTemporal, pk=bloqueo_id)
    es_duenio = bloqueo.usuario_id == request.user.id
    es_autorizado = usuario_es_directora(request.user) or usuario_es_admin(request.user) or getattr(request.user, "is_superuser", False)
    if not (es_duenio or es_autorizado):
        return acceso_denegado_login(request, "No tienes permiso para liberar este bloqueo.")

    observaciones = request.POST.get("observaciones") or "Bloqueo liberado manualmente."
    bloqueo.liberar(usuario=request.user, observaciones=observaciones)
    siguiente = request.POST.get("next") or request.META.get("HTTP_REFERER") or "/"
    if siguiente.startswith("/") and not siguiente.startswith("//"):
        return redirect(siguiente)
    return redirect("/")


def aplicar_dictamen_suplencia(sol, area_filtro, autorizacion, usuario=None):
    """
    Marca un dictamen como preliminar por suplencia.
    El área titular lo revisa después en su panel.
    """
    prefijo = PREFIJO_DICTAMEN_SUPLENCIA.get(str(area_filtro or "").lower())

    if not sol or not prefijo or not autorizacion:
        return sol

    campos = {
        f"{prefijo}_es_suplencia": True,
        f"{prefijo}_autorizacion_suplencia": autorizacion,
        f"{prefijo}_pendiente_revision_titular": True,
    }

    for campo, valor in campos.items():
        if hasattr(sol, campo):
            setattr(sol, campo, valor)

    return sol


def registrar_movimiento_dictamen_suplencia(sol, insc, area_filtro, autorizacion, usuario):
    if not autorizacion:
        return None

    area_legible = {
        "psicologia": "Psicología",
        "nutricion": "Nutrición",
        "medico": "Médica",
    }.get(str(area_filtro or "").lower(), area_filtro)

    return registrar_movimiento_suplencia(
        autorizacion=autorizacion,
        usuario=usuario,
        accion=MovimientoSuplencia.TipoAccion.DICTAMEN_PRELIMINAR,
        descripcion=f"Dictamen preliminar de {area_legible} registrado por suplencia.",
        solicitud=sol,
        inscripcion=insc,
        objeto=sol,
    )


def aplicar_suplencia_a_incidencia(incidencia, autorizacion):
    if not incidencia or not autorizacion:
        return incidencia

    if hasattr(incidencia, "es_suplencia"):
        incidencia.es_suplencia = True

    if hasattr(incidencia, "autorizacion_suplencia"):
        incidencia.autorizacion_suplencia = autorizacion

    if hasattr(incidencia, "area_original_suplencia"):
        incidencia.area_original_suplencia = incidencia.tipo

    if hasattr(incidencia, "pendiente_revision_titular"):
        incidencia.pendiente_revision_titular = True

    return incidencia


def registrar_movimiento_incidencia_suplencia(incidencia, autorizacion, usuario, accion=None, descripcion=None):
    if not incidencia or not autorizacion:
        return None

    inscripcion = getattr(incidencia, "alumno", None)
    solicitud = getattr(inscripcion, "solicitud_ingreso", None) if inscripcion else None

    return registrar_movimiento_suplencia(
        autorizacion=autorizacion,
        usuario=usuario,
        accion=accion or MovimientoSuplencia.TipoAccion.CREACION_INCIDENCIA,
        descripcion=descripcion or f"Incidencia {getattr(incidencia, 'tipo', '')} registrada por suplencia.",
        solicitud=solicitud,
        inscripcion=inscripcion,
        incidencia=incidencia,
        objeto=incidencia,
    )


def marcar_trabajo_social_por_suplencia(inscripcion=None, solicitud=None, usuario=None, accion=None, descripcion=""):
    """
    Marca expediente o solicitud cuando una persona autorizada cubre el proceso
    especial de Trabajo Social.
    """
    autorizacion = obtener_suplencia_activa_usuario_area(
        usuario,
        AutorizacionSuplencia.AreaCubierta.TRABAJO_SOCIAL,
        accion="PROCESO_SOCIAL",
    )

    if not autorizacion:
        return None

    if inscripcion is not None:
        campos_update = []

        if hasattr(inscripcion, "trabajo_social_es_suplencia"):
            inscripcion.trabajo_social_es_suplencia = True
            campos_update.append("trabajo_social_es_suplencia")

        if hasattr(inscripcion, "trabajo_social_autorizacion_suplencia"):
            inscripcion.trabajo_social_autorizacion_suplencia = autorizacion
            campos_update.append("trabajo_social_autorizacion_suplencia")

        if hasattr(inscripcion, "trabajo_social_pendiente_revision_titular"):
            inscripcion.trabajo_social_pendiente_revision_titular = True
            campos_update.append("trabajo_social_pendiente_revision_titular")

        if campos_update:
            campos_update.append("updated_at") if hasattr(inscripcion, "updated_at") else None
            try:
                inscripcion.save(update_fields=list(dict.fromkeys(campos_update)))
            except Exception:
                inscripcion.save()

    return registrar_movimiento_suplencia(
        autorizacion=autorizacion,
        usuario=usuario,
        accion=accion or MovimientoSuplencia.TipoAccion.PROCESO_TRABAJO_SOCIAL,
        descripcion=descripcion or "Movimiento de Trabajo Social realizado por suplencia.",
        solicitud=solicitud,
        inscripcion=inscripcion,
        objeto=inscripcion or solicitud,
    )


def movimientos_suplencia_queryset():
    return (
        MovimientoSuplencia.objects
        .select_related(
            "autorizacion",
            "autorizacion__titular_ausente",
            "autorizacion__suplente",
            "autorizacion__autorizada_por",
            "usuario",
            "titular_area",
            "solicitud",
            "inscripcion",
            "incidencia",
            "revisado_por",
        )
        .order_by("-creado_en")
    )


def filtrar_movimientos_suplencia(request, qs=None):
    qs = qs or movimientos_suplencia_queryset()
    form = FiltroBitacoraSuplenciaForm(request.GET or None)

    if form.is_valid():
        fecha_inicio = form.cleaned_data.get("fecha_inicio")
        fecha_fin = form.cleaned_data.get("fecha_fin")
        area_cubierta = form.cleaned_data.get("area_cubierta")
        estado = form.cleaned_data.get("estado")
        usuario = form.cleaned_data.get("usuario")

        if fecha_inicio:
            qs = qs.filter(creado_en__date__gte=fecha_inicio)
        if fecha_fin:
            qs = qs.filter(creado_en__date__lte=fecha_fin)
        if area_cubierta:
            qs = qs.filter(area_cubierta=area_cubierta)
        if estado:
            qs = qs.filter(estado=estado)
        if usuario:
            qs = qs.filter(usuario=usuario)

    return form, qs


def contexto_bitacora_suplencias(request, limite=100):
    form, qs = filtrar_movimientos_suplencia(request)
    return {
        "filtro_bitacora_suplencia_form": form,
        "movimientos_suplencia": qs[:limite],
        "total_movimientos_suplencia": qs.count(),
    }


def _valor_estado_autorizacion_suplencia(nombre, fallback):
    """
    Obtiene un valor de estado de AutorizacionSuplencia sin romper si el modelo
    cambia el nombre interno del enum.
    """
    try:
        return getattr(AutorizacionSuplencia.EstadoAutorizacion, nombre)
    except Exception:
        return fallback


def _valor_estado_movimiento_suplencia(nombre, fallback):
    """
    Obtiene un valor de estado de MovimientoSuplencia sin romper si el modelo
    cambia el nombre interno del enum.
    """
    try:
        return getattr(MovimientoSuplencia.EstadoMovimiento, nombre)
    except Exception:
        return fallback


def autorizaciones_suplencia_supervisor_queryset(request=None, fecha=None, limite=None):
    """
    Autorizaciones visibles para Supervisora.

    Importante:
    - Una autorización de suplencia debe mostrarse aunque todavía no exista
      MovimientoSuplencia.
    - Por eso esta consulta lee directamente AutorizacionSuplencia y no depende
      de que la suplente ya haya dictaminado, registrado incidencia o hecho un
      proceso de Trabajo Social.
    """
    qs = (
        AutorizacionSuplencia.objects
        .select_related(
            "titular_ausente",
            "suplente",
            "autorizada_por",
            "asistencia_personal",
        )
        .order_by("-fecha", "-inicio", "-created_at", "-id")
    )

    if fecha:
        qs = qs.filter(fecha=fecha)

    if request is not None:
        fecha_inicio = request.GET.get("fecha_inicio") or request.GET.get("desde")
        fecha_fin = request.GET.get("fecha_fin") or request.GET.get("hasta")
        area_cubierta = request.GET.get("area_cubierta") or request.GET.get("area")
        estado = request.GET.get("estado")

        if fecha_inicio:
            qs = qs.filter(fecha__gte=fecha_inicio)
        if fecha_fin:
            qs = qs.filter(fecha__lte=fecha_fin)
        if area_cubierta:
            qs = qs.filter(area_cubierta=area_cubierta)
        if estado:
            qs = qs.filter(estado=estado)

    if limite:
        return qs[:limite]

    return qs


def preparar_autorizacion_suplencia_para_supervisor(autorizacion):
    """
    Prepara una AutorizacionSuplencia para que el HTML de Supervisora pueda
    pintarla en la misma tabla donde se muestran los movimientos.

    El template ya espera campos como fecha_hora, accion, usuario,
    autorizado_por, alumno y descripcion. Se agregan solo como atributos en
    memoria; no se modifica la base de datos.
    """
    if not autorizacion:
        return autorizacion

    try:
        estado_display = autorizacion.get_estado_display()
    except Exception:
        estado_display = getattr(autorizacion, "estado", "Autorizada") or "Autorizada"

    try:
        tipo_display = autorizacion.get_tipo_cobertura_display()
    except Exception:
        tipo_display = getattr(autorizacion, "tipo_cobertura", "Cobertura temporal") or "Cobertura temporal"

    try:
        area_display = autorizacion.get_area_cubierta_display()
    except Exception:
        area_display = getattr(autorizacion, "area_cubierta", "Área cubierta") or "Área cubierta"

    motivo = (getattr(autorizacion, "motivo", "") or "").strip()
    inicio = getattr(autorizacion, "inicio", None)
    fin = getattr(autorizacion, "fin", None)

    vigencia = ""
    if inicio and fin:
        try:
            vigencia = f"Vigencia: {timezone.localtime(inicio).strftime('%d/%m/%Y %H:%M')} - {timezone.localtime(fin).strftime('%d/%m/%Y %H:%M')}"
        except Exception:
            vigencia = f"Vigencia: {inicio} - {fin}"
    elif inicio:
        try:
            vigencia = f"Inicio: {timezone.localtime(inicio).strftime('%d/%m/%Y %H:%M')}"
        except Exception:
            vigencia = f"Inicio: {inicio}"

    descripcion = f"Autorización de suplencia {estado_display.lower()} para cubrir {area_display}."
    if motivo:
        descripcion = f"{descripcion} Motivo: {motivo}."
    if vigencia:
        descripcion = f"{descripcion} {vigencia}."

    atributos = {
        "fecha_hora": inicio or getattr(autorizacion, "created_at", None) or getattr(autorizacion, "fecha", None),
        "accion": f"Autorización de suplencia - {tipo_display}",
        "tipo_accion": "AUTORIZACION_SUPLENCIA",
        "proceso": "Autorización de suplencia",
        "usuario": getattr(autorizacion, "suplente", None),
        "usuario_movimiento": getattr(autorizacion, "suplente", None),
        "realizado_por": getattr(autorizacion, "suplente", None),
        "suplente": getattr(autorizacion, "suplente", None),
        "autorizado_por": getattr(autorizacion, "autorizada_por", None),
        "autorizada_por": getattr(autorizacion, "autorizada_por", None),
        "titular_area": getattr(autorizacion, "titular_ausente", None),
        "alumno": "Autorización sin movimiento todavía",
        "expediente": "Pendiente de acción",
        "descripcion": descripcion,
        "observaciones": descripcion,
        "es_autorizacion_suplencia": True,
    }

    for campo, valor in atributos.items():
        try:
            setattr(autorizacion, campo, valor)
        except Exception:
            pass

    return autorizacion


def contexto_suplencias_supervisor(request, limite=100):
    """
    Contexto completo para la sección de suplencias del panel supervisor.

    Soluciona el caso detectado: Dirección crea una suplencia activa, pero la
    Supervisora no la ve porque aún no existe MovimientoSuplencia. Ahora se
    muestran tanto las autorizaciones como los movimientos reales.
    """
    hoy = timezone.localdate()
    estado_activa = _valor_estado_autorizacion_suplencia("ACTIVA", "ACTIVA")
    estado_cancelada = _valor_estado_autorizacion_suplencia("CANCELADA", "CANCELADA")
    estado_finalizada = _valor_estado_autorizacion_suplencia("FINALIZADA", "FINALIZADA")

    autorizaciones_qs = autorizaciones_suplencia_supervisor_queryset(request=request)
    autorizaciones_hoy_qs = autorizaciones_suplencia_supervisor_queryset(fecha=hoy)
    autorizaciones_activas_qs = autorizaciones_qs.filter(estado=estado_activa)

    movimientos_qs = movimientos_suplencia_queryset()
    filtro_form, movimientos_filtrados_qs = filtrar_movimientos_suplencia(request, movimientos_qs)

    estado_pendiente = _valor_estado_movimiento_suplencia("PENDIENTE", "PENDIENTE")
    estado_pendiente_revision = _valor_estado_movimiento_suplencia("PENDIENTE_REVISION", "PENDIENTE_REVISION")
    estado_validado = _valor_estado_movimiento_suplencia("VALIDADO", "VALIDADO")
    estado_revisado = _valor_estado_movimiento_suplencia("REVISADO", "REVISADO")
    estado_ajustado = _valor_estado_movimiento_suplencia("AJUSTADO", "AJUSTADO")

    movimientos_pendientes_qs = movimientos_qs.filter(
        estado__in=[estado_pendiente, estado_pendiente_revision]
    )
    movimientos_validados_qs = movimientos_qs.filter(
        estado__in=[estado_validado, estado_revisado, estado_ajustado]
    )

    autorizaciones_rows = [
        preparar_autorizacion_suplencia_para_supervisor(autorizacion)
        for autorizacion in autorizaciones_qs[:limite]
    ]
    movimientos_rows = list(movimientos_filtrados_qs[:limite])

    # La tabla del HTML se llama "movimientos_suplencia", pero para Supervisora
    # debe incluir también autorizaciones sin movimiento. Se ordena por la fecha
    # más representativa para que lo más reciente quede arriba.
    bitacora_completa = list(autorizaciones_rows) + movimientos_rows

    def fecha_orden(item):
        valor = (
            getattr(item, "fecha_hora", None)
            or getattr(item, "creado_en", None)
            or getattr(item, "inicio", None)
            or getattr(item, "fecha", None)
            or ""
        )
        try:
            return valor.isoformat()
        except Exception:
            return str(valor or "")

    try:
        bitacora_completa = sorted(bitacora_completa, key=fecha_orden, reverse=True)[:limite]
    except Exception:
        bitacora_completa = bitacora_completa[:limite]

    return {
        "filtro_bitacora_suplencia_form": filtro_form,

        # Autorizaciones de suplencia, aunque todavía no tengan acciones.
        "autorizaciones_suplencia": autorizaciones_qs[:limite],
        "autorizaciones_suplencia_hoy": autorizaciones_hoy_qs,
        "autorizaciones_suplencia_activas": autorizaciones_activas_qs,
        "suplencias_activas": autorizaciones_activas_qs,
        "suplencias_activas_dia": autorizaciones_activas_qs.filter(fecha=hoy),
        "suplencias_canceladas_dia": autorizaciones_hoy_qs.filter(estado=estado_cancelada),
        "suplencias_finalizadas_dia": autorizaciones_hoy_qs.filter(estado=estado_finalizada),

        # KPIs esperados por el HTML de Supervisora.
        "suplencias_hoy": autorizaciones_hoy_qs.count(),
        "total_suplencias_hoy": autorizaciones_hoy_qs.count(),
        "total_suplencias_activas": autorizaciones_activas_qs.count(),
        "suplencias_pendientes_revision": movimientos_pendientes_qs.count(),
        "suplencias_validadas": movimientos_validados_qs.count(),
        "total_movimientos_suplencia": movimientos_qs.count(),

        # Tabla principal del HTML: autorizaciones + movimientos.
        "movimientos_suplencia": bitacora_completa,
        "movimientos_suplencia_recientes": bitacora_completa,
        "bitacora_suplencias": bitacora_completa,

        # Si necesitas consultar solo acciones reales, quedan disponibles aparte.
        "movimientos_suplencia_reales": movimientos_filtrados_qs[:limite],
        "total_movimientos_suplencia_reales": movimientos_qs.count(),
    }


def contexto_apoyos_sala_supervisor(request=None, limite=100):
    """
    Apoyos temporales de maestras visibles para Supervisora y Dirección.
    La Supervisora solo observa; no crea, edita ni cancela apoyos.
    """
    qs = (
        ApoyoSalaMaestra.objects
        .select_related(
            "dia_operativo",
            "sala_origen",
            "sala_origen__sala",
            "sala_apoyada",
            "sala_apoyada__sala",
            "maestra_apoyo",
            "maestra_titular_sala",
            "cerrado_por",
        )
        .order_by("-inicio", "-id")
    )

    hoy = timezone.localdate()
    apoyos_hoy = qs.filter(fecha=hoy)
    apoyos_activos = qs.filter(estado=ApoyoSalaMaestra.Estado.ACTIVO, fin__isnull=True)

    return {
        "apoyos_sala_maestras": qs[:limite],
        "apoyos_sala_hoy": apoyos_hoy,
        "apoyos_sala_activos": apoyos_activos,
        "total_apoyos_sala_hoy": apoyos_hoy.count(),
        "total_apoyos_sala_activos": apoyos_activos.count(),
    }


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
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if usuario_tiene_area_operativa(user, "PEDAGOGICA"):
        return True

    roles = obtener_roles_usuario(user)
    tipo_persona = normalizar_texto(getattr(user, "tipo_persona", ""))

    return (
        any("coordinador" in rol and "sala" in rol for rol in roles)
        or any("coordinadora" in rol and "sala" in rol for rol in roles)
        or any("pedagog" in rol for rol in roles)
        or any("pedagóg" in rol for rol in roles)
        or "coordinacion de sala" in roles
        or "coordinacion de salas" in roles
        or tipo_persona in ["coordinadora_sala", "coordinador_sala", "coordinacion_sala", "pedagogica"]
    )


def usuario_es_area_nutricion(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if usuario_tiene_area_operativa(user, "NUTRICION"):
        return True

    roles = obtener_roles_usuario(user)
    return any("nutri" in rol for rol in roles)


def usuario_es_area_medica(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if usuario_tiene_area_operativa(user, "MEDICA"):
        return True

    roles = obtener_roles_usuario(user)
    return any("medic" in rol or "médic" in rol for rol in roles)


def usuario_es_area_psicologia(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if usuario_tiene_area_operativa(user, "PSICOLOGIA"):
        return True

    roles = obtener_roles_usuario(user)
    return any("psicolog" in rol or "psicólog" in rol for rol in roles)


def tipos_incidencia_usuario(user, para_crear=False):
    """
    Define qué tipo de incidencias puede operar el usuario.

    Para crear:
    - Pedagógica -> Pedagógica
    - Nutrióloga -> Nutricional
    - Médica -> Médica
    - Psicóloga -> Psicológica
    - Suplente autorizado -> solo el tipo cubierto temporalmente

    Para consultar:
    - Directora y Administrador ven todas.
    - Personal operativo ve su área y, si tiene suplencia activa, el área cubierta.
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

    # Suplencias activas: no cambian el rol real; solo agregan el tipo cubierto.
    for autorizacion in obtener_suplencias_activas_usuario(user):
        try:
            if autorizacion.permite_accion("INCIDENCIA"):
                tipo_suplencia = tipo_incidencia_para_area_cubierta(autorizacion.area_cubierta)
                if tipo_suplencia:
                    tipos.append(tipo_suplencia)
        except Exception:
            continue

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



# Límites de adjuntos para incidencias. Se validan también en backend para evitar
# archivos pesados aunque el usuario modifique el HTML o desactive JavaScript.
MAX_ARCHIVO_INCIDENCIA_MB = 10
MAX_TOTAL_ARCHIVOS_INCIDENCIA_MB = 20
MAX_ARCHIVO_INCIDENCIA_BYTES = MAX_ARCHIVO_INCIDENCIA_MB * 1024 * 1024
MAX_TOTAL_ARCHIVOS_INCIDENCIA_BYTES = MAX_TOTAL_ARCHIVOS_INCIDENCIA_MB * 1024 * 1024
EXTENSIONES_INCIDENCIA_PERMITIDAS = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx"}


def validar_archivo_incidencia_general(archivo):
    if not archivo:
        return False, "No se recibió archivo."

    extension = os.path.splitext(getattr(archivo, "name", ""))[1].lower()

    if extension not in EXTENSIONES_INCIDENCIA_PERMITIDAS:
        return False, "Formato no permitido. Usa PDF, imagen JPG/PNG o documento Word."

    if getattr(archivo, "size", 0) <= 0:
        return False, "El archivo está vacío. Selecciona un archivo válido."

    if archivo.size > MAX_ARCHIVO_INCIDENCIA_BYTES:
        return False, f"El archivo supera el tamaño máximo permitido de {MAX_ARCHIVO_INCIDENCIA_MB} MB."

    return True, "Archivo válido."


def validar_total_archivos_incidencia(archivos):
    archivos = list(archivos or [])
    total = sum(getattr(archivo, "size", 0) or 0 for archivo in archivos)

    if total > MAX_TOTAL_ARCHIVOS_INCIDENCIA_BYTES:
        peso_mb = round(total / (1024 * 1024), 2)
        return False, (
            f"El total de archivos adjuntos pesa {peso_mb} MB y supera "
            f"el límite permitido de {MAX_TOTAL_ARCHIVOS_INCIDENCIA_MB} MB."
        )

    return True, "Total válido."


def guardar_archivos_incidencia(incidencia, archivos, usuario):
    guardados = 0
    errores = []
    archivos = list(archivos or [])

    total_valido, mensaje_total = validar_total_archivos_incidencia(archivos)
    if not total_valido:
        return 0, [mensaje_total]

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
    archivos = list(archivos or [])

    total_valido, mensaje_total = validar_total_archivos_incidencia(archivos)
    if not total_valido:
        return 0, [mensaje_total]

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


def nombre_menor_desde_inscripcion(inscripcion):
    """
    Devuelve el nombre real del menor para vistas y respuestas AJAX.
    Evita mostrar textos genéricos del modelo SolicitudInscripcion.
    """
    solicitud = getattr(inscripcion, "solicitud_ingreso", None)

    if solicitud:
        for attr in ("nombre_menor_completo", "nombre_completo_menor", "menor_nombre_completo"):
            valor = getattr(solicitud, attr, None)
            if callable(valor):
                try:
                    valor = valor()
                except Exception:
                    valor = ""
            if valor:
                return str(valor).strip().title()

        partes = [
            getattr(solicitud, "nombres_menor", "") or "",
            getattr(solicitud, "apellido_paterno_menor", "") or "",
            getattr(solicitud, "apellido_materno_menor", "") or "",
        ]
        nombre = " ".join(p.strip() for p in partes if p and str(p).strip()).strip()
        if nombre:
            return nombre.title()

    return str(inscripcion)


def obtener_dia_operativo_actual_incidencias(semestre=None):
    """
    Día operativo usado por incidencias al crear registros desde coordinación o áreas.
    Devuelve None si no hay semestre activo o si hoy no existe en calendario.
    """
    if semestre is None:
        semestre = obtener_semestre_activo_operativo()

    if not semestre:
        return None

    hoy = timezone.localdate()

    try:
        return DiaOperativoSemestre.objects.select_related("semestre").filter(
            semestre=semestre,
            fecha=hoy,
        ).first()
    except Exception:
        return None


def obtener_registro_diario_actual_para_alumno(alumno, semestre=None):
    """
    Busca automáticamente el registro diario del alumno para la fecha actual.
    Si no existe, la incidencia se puede guardar con alumno, semestre y sala.
    """
    if not alumno:
        return None

    if semestre is None:
        semestre = getattr(alumno, "semestre", None) or obtener_semestre_activo_operativo()

    qs = RegistroDiarioAlumno.objects.select_related(
        "alumno",
        "alumno__solicitud_ingreso",
        "dia_operativo",
        "dia_operativo__semestre",
        "sala_semestre",
        "sala_semestre__sala",
    ).filter(
        alumno=alumno,
        dia_operativo__fecha=timezone.localdate(),
    )

    if semestre:
        qs = qs.filter(dia_operativo__semestre=semestre)

    try:
        qs = qs.filter(dia_operativo__es_habil=True).exclude(dia_operativo__fecha__week_day__in=[1, 7])
    except Exception:
        pass

    return qs.order_by("-id").first()


def serializar_registro_diario_incidencia(registro):
    if not registro:
        return None

    dia = getattr(registro, "dia_operativo", None)
    sala_semestre = getattr(registro, "sala_semestre", None)
    sala = getattr(sala_semestre, "sala", None)

    return {
        "id": registro.id,
        "fecha": dia.fecha.isoformat() if dia and getattr(dia, "fecha", None) else "",
        "fecha_display": dia.fecha.strftime("%d/%m/%Y") if dia and getattr(dia, "fecha", None) else "",
        "estado_dia": getattr(dia, "estado", "") if dia else "",
        "es_habil": bool(getattr(dia, "es_habil", False)) if dia else False,
        "sala": getattr(sala, "nombre", "") or "",
        "alumno_id": getattr(registro, "alumno_id", None),
        "alumno": nombre_menor_desde_inscripcion(registro.alumno) if getattr(registro, "alumno", None) else "",
    }


def incidencias_pedagogicas_base_coordinadora(semestre=None):
    qs = (
        Incidencia.objects
        .filter(tipo=Incidencia.TipoIncidencia.PEDAGOGICA)
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

    if semestre:
        qs = qs.filter(semestre=semestre)

    return qs


def resumen_incidencias_pedagogicas(qs):
    total = qs.count()
    abiertas = qs.filter(estado=Incidencia.EstadoIncidencia.ABIERTA).count()
    cerradas = qs.filter(estado=Incidencia.EstadoIncidencia.CERRADA).count()
    riesgo_alto = qs.filter(nivel=Incidencia.NivelChoices.ALTO).count()
    sin_seguimiento = qs.filter(seguimientos__isnull=True).distinct().count()

    return {
        "total": total,
        "abiertas": abiertas,
        "cerradas": cerradas,
        "alto": riesgo_alto,
        "riesgo_alto": riesgo_alto,
        "sin_seguimiento": sin_seguimiento,
        "porcentaje_abiertas": porcentaje_panel(abiertas, total),
        "porcentaje_cerradas": porcentaje_panel(cerradas, total),
        "porcentaje_riesgo_alto": porcentaje_panel(riesgo_alto, total),
        "porcentaje_sin_seguimiento": porcentaje_panel(sin_seguimiento, total),
    }


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
        "responsable_autorizado",
        "responsable_autorizado_id",
        "codigo_responsable_id",
        f"responsable_{prefijo}_codigo_id",
        f"responsable_{prefijo}_autorizado",
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
        "responsable_autorizado",
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

    if archivo.size > MAX_TAMANO_ARCHIVO_EXPEDIENTE_BYTES:
        return False, f"El comprobante supera el tamaño máximo permitido de {MAX_TAMANO_ARCHIVO_EXPEDIENTE_MB} MB."

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
    Permisos normales por área más suplencia temporal para dictámenes.

    Admin y Directora pueden acceder a todas las áreas.
    La suplente solo entra al área cubierta y la captura queda marcada como
    preliminar por suplencia.
    """
    if usuario_es_editor_especial_filtros(user):
        return True

    area = str(area or "").lower()
    roles = obtener_roles_usuario(user)

    if area == "psicologia":
        return (
            usuario_es_area_psicologia(user)
            or any("psicolog" in rol for rol in roles)
            or usuario_tiene_suplencia_para_filtro(user, "psicologia")
        )

    if area == "nutricion":
        return (
            usuario_es_area_nutricion(user)
            or any("nutriolog" in rol or "nutricion" in rol for rol in roles)
            or usuario_tiene_suplencia_para_filtro(user, "nutricion")
        )

    if area == "medico":
        return (
            usuario_es_area_medica(user)
            or any("medic" in rol for rol in roles)
            or usuario_tiene_suplencia_para_filtro(user, "medico")
        )

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

    semestre_activo = obtener_semestre_activo_operativo()
    inscripcion.estado = "REVISION_FINAL_TS"
    if semestre_activo and not getattr(inscripcion, "semestre_id", None):
        inscripcion.semestre = semestre_activo

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

    campos_update = ["estado", "observaciones"]
    if semestre_activo and getattr(inscripcion, "semestre_id", None) == getattr(semestre_activo, "id", None):
        campos_update.append("semestre")

    inscripcion.save(update_fields=list(dict.fromkeys(campos_update)))

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
        **contexto_bloqueos_edicion_area("TRABAJO_SOCIAL"),
        **contexto_suplencias_usuario(request.user),
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
        marcar_trabajo_social_por_suplencia(
            solicitud=solicitud,
            usuario=request.user,
            accion=MovimientoSuplencia.TipoAccion.PROCESO_TRABAJO_SOCIAL,
            descripcion="Solicitud inicial creada durante cobertura temporal de Trabajo Social.",
        )
        messages.success(request, f"Solicitud creada. Folio: {solicitud.folio}")

    return redirect("panel_admisiones")


@login_required
def editar_solicitud(request, solicitud_id):
    """
    Edita solo los datos básicos de la solicitud desde Trabajo Social.

    No edita PDFs, documentos cargados, CURP, fecha de nacimiento ni datos
    clínicos/filtros. Esos datos se conservan intactos.
    """
    s = get_object_or_404(Solicitud, id=solicitud_id)

    if request.method == "POST":
        bloqueo = bloquear_si_no_hay_semestre_activo(request, "panel_admisiones")
        if bloqueo:
            return bloqueo

        correo_anterior = (getattr(s, "correo", "") or "").strip().lower()

        def post_limpio(nombre_campo, default=""):
            return (request.POST.get(nombre_campo, default) or "").strip()

        # Datos básicos del beneficiario/tutor.
        datos_texto_persona = {
            "nombres_tutor": limpiar_texto_persona(post_limpio("nombres_tutor")),
            "apellido_paterno_tutor": limpiar_texto_persona(post_limpio("apellido_paterno_tutor")),
            "apellido_materno_tutor": limpiar_texto_persona(post_limpio("apellido_materno_tutor")),
            "estado_domicilio": limpiar_texto_persona(post_limpio("estado_domicilio")),
            "ciudad": limpiar_texto_persona(post_limpio("ciudad")),
        }

        for campo, valor in datos_texto_persona.items():
            if hasattr(s, campo):
                setattr(s, campo, valor)

        if hasattr(s, "parentesco"):
            s.parentesco = post_limpio("parentesco").upper()

        if hasattr(s, "parentesco_otro"):
            parentesco = getattr(s, "parentesco", "")
            if parentesco == "OTRO":
                s.parentesco_otro = limpiar_texto_persona(post_limpio("parentesco_otro"))
            else:
                s.parentesco_otro = ""

        if hasattr(s, "matricula"):
            s.matricula = post_limpio("matricula").upper()

        if hasattr(s, "correo"):
            s.correo = post_limpio("correo").lower()

        if hasattr(s, "celular"):
            s.celular = re.sub(r"\D", "", post_limpio("celular"))[:10]

        # Datos académicos y domicilio básico.
        campos_basicos = [
            "programa_educativo",
            "unidad_academica",
            "calle",
            "numero_exterior",
            "domicilio",
        ]

        for campo in campos_basicos:
            if hasattr(s, campo):
                setattr(s, campo, post_limpio(campo))

        s.save()

        marcar_trabajo_social_por_suplencia(
            solicitud=s,
            usuario=request.user,
            accion=MovimientoSuplencia.TipoAccion.PROCESO_TRABAJO_SOCIAL,
            descripcion=f"Datos básicos de la solicitud {getattr(s, 'folio', s.id)} editados durante cobertura temporal de Trabajo Social.",
        )

        # Si la solicitud ya tiene cuenta de tutor creada, sincroniza el correo
        # para que el beneficiario pueda seguir entrando con el correo actualizado.
        correo_nuevo = (getattr(s, "correo", "") or "").strip().lower()

        if correo_nuevo and correo_nuevo != correo_anterior:
            inscripcion = (
                SolicitudInscripcion.objects
                .filter(solicitud_ingreso=s)
                .select_related("usuario_tutor")
                .first()
            )

            if inscripcion and getattr(inscripcion, "usuario_tutor", None):
                User = get_user_model()
                tutor = inscripcion.usuario_tutor

                correo_ocupado = (
                    User.objects
                    .filter(Q(email__iexact=correo_nuevo) | Q(username__iexact=correo_nuevo))
                    .exclude(pk=tutor.pk)
                    .exists()
                )

                if correo_ocupado:
                    messages.warning(
                        request,
                        "La solicitud se actualizó, pero no se cambió el correo de acceso "
                        "porque ese correo ya pertenece a otro usuario."
                    )
                else:
                    tutor.email = correo_nuevo
                    tutor.username = correo_nuevo

                    try:
                        tutor.save(update_fields=["email", "username"])
                    except Exception:
                        tutor.save()

        messages.success(request, f"Datos básicos del folio {s.folio} actualizados correctamente.")

        siguiente = post_limpio("next")

        if siguiente and siguiente.startswith("/") and not siguiente.startswith("//"):
            return redirect(siguiente)

        return redirect("panel_admisiones")

    return render(
        request,
        "admisiones/editar.html",
        {
            "solicitud": s,
            **contexto_catalogos_editar_solicitud(),
            **contexto_suplencias_usuario(request.user),
            **contexto_semestre_operativo(),
        },
    )


@login_required
def enviar_link_por_correo(request, solicitud_id):
    solicitud = get_object_or_404(Solicitud, id=solicitud_id)
    link = LinkCaptura.objects.filter(solicitud=solicitud, usado=False).last()

    if link and solicitud.correo:
        url = request.build_absolute_uri(reverse("captura_por_token", args=[link.token]))
        asunto = f"Link de Captura - Folio {solicitud.folio}"
        cuerpo = f"Hola {solicitud.nombres_tutor},\n\nCompleta tu solicitud aquí: {url}"

        enviado, mensaje_correo = enviar_correo_institucional_unach(
            asunto=asunto,
            cuerpo=cuerpo,
            destinatarios=[solicitud.correo],
            usuario_emisor=request.user,
        )

        if enviado:
            messages.success(request, "Correo enviado.")
        else:
            messages.error(request, f"Fallo al enviar: {mensaje_correo}")

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
    autorizacion_suplencia_actual = obtener_suplencia_activa_usuario_area(
        request.user,
        AutorizacionSuplencia.AreaCubierta.TRABAJO_SOCIAL,
        accion="PROCESO_SOCIAL",
    )
    bloqueo_edicion_temporal, respuesta_bloqueo = iniciar_bloqueo_edicion_temporal(
        request,
        inscripcion or s,
        area="TRABAJO_SOCIAL",
        autorizacion_suplencia=autorizacion_suplencia_actual,
        retorno="panel_admisiones",
        motivo="Revisión documental de Trabajo Social",
    )
    if respuesta_bloqueo:
        return respuesta_bloqueo

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

            marcar_trabajo_social_por_suplencia(
                inscripcion=inscripcion,
                solicitud=s,
                usuario=request.user,
                accion=MovimientoSuplencia.TipoAccion.REVISION_DOCUMENTOS,
                descripcion="Expediente devuelto por cobertura temporal de Trabajo Social.",
            )

            enviado, mensaje_correo = enviar_correo_estado_inscripcion(
                inscripcion,
                "DEVUELTA",
                usuario_emisor=request.user,
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
            semestre_activo = obtener_semestre_activo_operativo()
            inscripcion.estado = "FILTROS"
            inscripcion.observaciones = ""
            inscripcion.comentario_tutor = ""

            campos_actualizar_inscripcion = ["estado", "observaciones", "comentario_tutor"]
            if semestre_activo and not getattr(inscripcion, "semestre_id", None):
                inscripcion.semestre = semestre_activo
                campos_actualizar_inscripcion.append("semestre")

            campos_actualizar_inscripcion.append("updated_at")
            inscripcion.save(update_fields=campos_actualizar_inscripcion)

            marcar_trabajo_social_por_suplencia(
                inscripcion=inscripcion,
                solicitud=s,
                usuario=request.user,
                accion=MovimientoSuplencia.TipoAccion.REVISION_DOCUMENTOS,
                descripcion="Expediente validado y enviado a filtros por cobertura temporal de Trabajo Social.",
            )

            enviado, mensaje_correo = enviar_correo_estado_inscripcion(
                inscripcion,
                "FILTROS",
                usuario_emisor=request.user,
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

        liberar_bloqueo_edicion_temporal(
            request,
            inscripcion or s,
            observaciones="Revisión documental de Trabajo Social finalizada.",
        )
        return redirect("revisar_solicitud", pk=pk)

    return render(
        request,
        "admisiones/revisar_solicitud.html",
        {
            "s": s,
            "inscripcion": inscripcion,
            "bloqueo_edicion_temporal": bloqueo_edicion_temporal,
            **contexto_suplencias_usuario(request.user),
            **contexto_semestre_operativo(),
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

            semestre_activo = obtener_semestre_activo_operativo()
            inscripcion, _ = SolicitudInscripcion.objects.get_or_create(
                solicitud_ingreso=s,
                defaults={
                    "usuario_tutor": user,
                    "semestre": semestre_activo,
                },
            )

            campos_actualizar_inscripcion = []
            if not getattr(inscripcion, "usuario_tutor_id", None):
                inscripcion.usuario_tutor = user
                campos_actualizar_inscripcion.append("usuario_tutor")
            if semestre_activo and not getattr(inscripcion, "semestre_id", None):
                inscripcion.semestre = semestre_activo
                campos_actualizar_inscripcion.append("semestre")
            if campos_actualizar_inscripcion:
                campos_actualizar_inscripcion.append("updated_at")
                inscripcion.save(update_fields=campos_actualizar_inscripcion)

            pdf_path = None

            try:
                pdf_path = generar_pdf_dictamen(s)
            except Exception as e:
                messages.warning(
                    request,
                    f"Solicitud aprobada, pero no se pudo generar el PDF de aceptación: {e}"
                )

            try:
                enviado, mensaje_correo = enviar_correo_dictamen_ingreso(s, pdf_path, usuario_emisor=request.user)

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
                enviado, mensaje_correo = enviar_correo_dictamen_ingreso(s, pdf_path, usuario_emisor=request.user)

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

        # Guardar archivos con validación fuerte en backend.
        # Esto evita que un archivo demasiado pesado llegue a guardarse aunque
        # el usuario modifique el HTML o desactive el JavaScript.
        for campo, nombre_legible in mapeo_nombres.items():
            if campo in request.FILES:
                archivo = request.FILES[campo]

                es_valido, mensaje_validacion = validar_archivo_expediente_inscripcion(
                    campo,
                    archivo,
                    nombre_legible,
                )

                if not es_valido:
                    messages.error(request, mensaje_validacion)
                    return redirect("portal_inscripcion")

                ext = os.path.splitext(archivo.name)[1].lower()
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
                usuario_emisor=request.user,
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

            # Foto de perfil del beneficiario.
            # Se muestra en mi-inscripcion.html únicamente si el usuario ya la subió
            # desde el Portal de Padres. Si no existe, el HTML conserva el icono normal.
            "foto_perfil_beneficiario_url": obtener_foto_perfil_usuario(request.user),
            "perfil_beneficiario_soporta_foto": bool(obtener_campo_foto_perfil_usuario(request.user)),

            **contexto_semestre_operativo(),
        },
    )


# ===================== PSICOLOGÍA =====================
@login_required
def psicologia_pendientes(request):
    if not usuario_tiene_permiso_area_filtro(request.user, "psicologia"):
        return acceso_denegado_login(request, "No tienes permiso para entrar al filtro de Psicología.")

    # Foto de perfil desde el panel principal de Psicología.
    # El HTML envía action_type=actualizar_foto_psicologia o eliminar_foto_psicologia.
    if request.method == "POST":
        respuesta_foto = procesar_foto_perfil_area(
            request,
            destino_url=reverse("psicologia_pendientes"),
            campo_archivo="foto_perfil_psicologia",
            action_actualizar="actualizar_foto_psicologia",
            action_eliminar="eliminar_foto_psicologia",
            nombre_area="Psicología",
        )

        if respuesta_foto:
            return respuesta_foto

    if not hay_semestre_activo_operativo():
        messages.warning(
            request,
            "No hay semestre activo. Psicología queda en modo solo consulta; no hay dictámenes pendientes para operar."
        )
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

    aprobados = Solicitud.objects.filter(
        estado_psicologia="APROBADO",
    ).order_by("-psicologia_en")

    rechazados = Solicitud.objects.filter(
        estado_psicologia="RECHAZADO",
    ).order_by("-psicologia_en")

    total_pendientes = qs.count()
    total_aprobados = aprobados.count()
    total_rechazados = rechazados.count()
    total_registros = total_aprobados + total_rechazados
    total_proceso = total_pendientes + total_registros

    return render(
        request,
        "admisiones/psicologia_pendientes.html",
        {
            "solicitudes": qs,
            "aprobados": aprobados,
            "rechazados": rechazados,
            "total_pendientes": total_pendientes,
            "total_aprobados": total_aprobados,
            "total_rechazados": total_rechazados,
            "total_registros": total_registros,
            "total_proceso": total_proceso,
            "porcentaje_pendientes": porcentaje_panel(total_pendientes, total_proceso),
            "porcentaje_aprobados": porcentaje_panel(total_aprobados, total_proceso),
            "porcentaje_rechazados": porcentaje_panel(total_rechazados, total_proceso),
            "porcentaje_dictaminados": porcentaje_panel(total_registros, total_proceso),
            **contexto_bloqueos_edicion_area("PSICOLOGIA"),
            **contexto_suplencias_usuario(request.user),
            **contexto_semestre_operativo(),
        },
    )



@login_required
def psicologia_dictaminar(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    insc = SolicitudInscripcion.objects.filter(solicitud_ingreso=sol).first()
    datos_menor = obtener_datos_menor_para_filtro(sol, insc)
    sol = aplicar_datos_identidad_menor_a_solicitud(sol, datos_menor)
    area_filtro_actual = AREA_FILTRO_PSICOLOGIA
    initial_compartido = obtener_initial_datos_compartidos_para_area(sol, area_filtro_actual)

    if not usuario_tiene_permiso_area_filtro(request.user, "psicologia"):
        return acceso_denegado_login(request, "No tienes permiso para dictaminar Psicología.")

    bloqueado = not puede_editar_filtro(request.user, sol, "psicologia")
    autorizacion_suplencia_actual = obtener_suplencia_activa_para_filtro(request.user, "psicologia")
    bloqueo_edicion_temporal, respuesta_bloqueo = iniciar_bloqueo_edicion_temporal(
        request,
        sol,
        area="PSICOLOGIA",
        autorizacion_suplencia=autorizacion_suplencia_actual,
        retorno="psicologia_pendientes",
        motivo="Dictamen de Psicología",
    )
    if respuesta_bloqueo:
        return respuesta_bloqueo

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

        post_data = preparar_post_con_datos_compartidos(request.POST, sol, area_filtro_actual)
        estado_decision = post_data.get("estado_psicologia")

        if not estado_decision or estado_decision == "PENDIENTE":
            form = DictamenPsicologiaForm(post_data, instance=sol)
            messages.error(request, "Debes seleccionar un dictamen final de Psicología: Aprobado o Rechazado.")
        else:
            form = DictamenPsicologiaForm(post_data, instance=sol)

            if form.is_valid():
                sol = form.save(commit=False)

                # Proteger identidad del menor: el filtro no debe modificarla.
                sol = aplicar_datos_identidad_menor_a_solicitud(sol, datos_menor)

                sol.estado_psicologia = estado_decision
                sol.psicologia_por = request.user
                sol.psicologia_en = timezone.now()

                autorizacion_suplencia = autorizacion_suplencia_actual
                if autorizacion_suplencia:
                    sol = aplicar_dictamen_suplencia(sol, "psicologia", autorizacion_suplencia, request.user)

                sol.save()

                if autorizacion_suplencia:
                    registrar_movimiento_dictamen_suplencia(
                        sol,
                        insc,
                        "psicologia",
                        autorizacion_suplencia,
                        request.user,
                    )

                errores_compartidos = guardar_datos_compartidos_desde_fuentes(
                    sol,
                    area_filtro_actual,
                    usuario=request.user,
                    post_data=post_data,
                    insc=insc,
                )

                for error in errores_compartidos[:3]:
                    messages.warning(request, error)

                messages.success(request, "Dictamen de psicología guardado exitosamente.")

                cierre_realizado, estado_inscripcion, mensaje_cierre = revisar_cierre_filtros(sol)
                if cierre_realizado:
                    messages.info(request, mensaje_cierre)

                liberar_bloqueo_edicion_temporal(
                    request,
                    sol,
                    observaciones="Dictamen de Psicología guardado correctamente.",
                )
                return redirect("psicologia_pendientes")

        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"Te faltó este campo ({field}): {error}")

        messages.warning(
            request,
            "⚠️ No se guardó el dictamen. Revisa los mensajes rojos de arriba.",
        )

    else:
        form = DictamenPsicologiaForm(instance=sol, initial=initial_compartido)

    return render(
        request,
        "admisiones/psicologia_dictaminar.html",
        {
            "sol": sol,
            "insc": insc,
            "form": form,
            "bloqueado": bloqueado,
            "bloqueo_edicion_temporal": bloqueo_edicion_temporal,
            **datos_menor,
            **contexto_datos_compartidos_filtro(sol, area_filtro_actual),
            **contexto_suplencias_usuario(request.user),
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
            **contexto_suplencias_usuario(request.user),
            **contexto_semestre_operativo(),
        },
    )


# ===================== NUTRICIÓN =====================
@login_required
def nutricion_pendientes(request):
    if not usuario_tiene_permiso_area_filtro(request.user, "nutricion"):
        return acceso_denegado_login(request, "No tienes permiso para entrar al filtro de Nutrición.")

    # Foto de perfil desde el panel principal de Nutrición.
    # El HTML envía:
    # - action_type=actualizar_foto_nutricion
    # - action_type=eliminar_foto_nutricion
    if request.method == "POST":
        respuesta_foto = procesar_foto_perfil_area(
            request,
            destino_url=reverse("nutricion_pendientes"),
            campo_archivo="foto_perfil_nutricion",
            action_actualizar="actualizar_foto_nutricion",
            action_eliminar="eliminar_foto_nutricion",
            nombre_area="Nutrición",
        )

        if respuesta_foto:
            return respuesta_foto

    if not hay_semestre_activo_operativo():
        messages.warning(
            request,
            "No hay semestre activo. Nutrición queda en modo solo consulta; no hay dictámenes pendientes para operar."
        )
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

    aprobados = Solicitud.objects.filter(
        estado_nutricion="APROBADO",
    ).order_by("-nutricion_en")

    rechazados = Solicitud.objects.filter(
        estado_nutricion="RECHAZADO",
    ).order_by("-nutricion_en")

    total_pendientes = qs.count()
    total_aprobados = aprobados.count()
    total_rechazados = rechazados.count()
    total_registros = total_aprobados + total_rechazados
    total_proceso = total_pendientes + total_registros

    return render(
        request,
        "admisiones/nutricion_pendientes.html",
        {
            "solicitudes": qs,
            "aprobados": aprobados,
            "rechazados": rechazados,
            "total_pendientes": total_pendientes,
            "total_aprobados": total_aprobados,
            "total_rechazados": total_rechazados,
            "total_registros": total_registros,
            "total_proceso": total_proceso,
            "porcentaje_pendientes": porcentaje_panel(total_pendientes, total_proceso),
            "porcentaje_aprobados": porcentaje_panel(total_aprobados, total_proceso),
            "porcentaje_rechazados": porcentaje_panel(total_rechazados, total_proceso),
            "porcentaje_dictaminados": porcentaje_panel(total_registros, total_proceso),
            "foto_perfil_nutricion_url": obtener_foto_perfil_usuario(request.user),
            "perfil_nutricion_soporta_foto": bool(obtener_campo_foto_perfil_usuario(request.user)),
            **contexto_bloqueos_edicion_area("NUTRICION"),
            **contexto_suplencias_usuario(request.user),
            **contexto_semestre_operativo(),
        },
    )



@login_required
def nutricion_dictaminar(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    insc = SolicitudInscripcion.objects.filter(solicitud_ingreso=sol).first()
    datos_menor = obtener_datos_menor_para_filtro(sol, insc)
    sol = aplicar_datos_identidad_menor_a_solicitud(sol, datos_menor)
    area_filtro_actual = AREA_FILTRO_NUTRICION
    initial_compartido = obtener_initial_datos_compartidos_para_area(sol, area_filtro_actual)

    if not usuario_tiene_permiso_area_filtro(request.user, "nutricion"):
        return acceso_denegado_login(request, "No tienes permiso para dictaminar Nutrición.")

    bloqueado = not puede_editar_filtro(request.user, sol, "nutricion")
    autorizacion_suplencia_actual = obtener_suplencia_activa_para_filtro(request.user, "nutricion")
    bloqueo_edicion_temporal, respuesta_bloqueo = iniciar_bloqueo_edicion_temporal(
        request,
        sol,
        area="NUTRICION",
        autorizacion_suplencia=autorizacion_suplencia_actual,
        retorno="nutricion_pendientes",
        motivo="Dictamen de Nutrición",
    )
    if respuesta_bloqueo:
        return respuesta_bloqueo

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

        post_data = preparar_post_con_datos_compartidos(request.POST, sol, area_filtro_actual)
        estado_decision = post_data.get("estado_nutricion")

        if not estado_decision or estado_decision == "PENDIENTE":
            form = DictamenNutricionForm(post_data, instance=sol)
            messages.error(request, "Debes seleccionar un dictamen final de Nutrición: Aprobado o Rechazado.")
        else:
            form = DictamenNutricionForm(post_data, instance=sol)

            if form.is_valid():
                sol = form.save(commit=False)

                # Proteger identidad del menor: Nutrición no debe modificarla.
                sol = aplicar_datos_identidad_menor_a_solicitud(sol, datos_menor)

                sol.estado_nutricion = estado_decision
                sol.nutricion_por = request.user
                sol.nutricion_en = timezone.now()

                autorizacion_suplencia = autorizacion_suplencia_actual
                if autorizacion_suplencia:
                    sol = aplicar_dictamen_suplencia(sol, "nutricion", autorizacion_suplencia, request.user)

                sol.save()

                if autorizacion_suplencia:
                    registrar_movimiento_dictamen_suplencia(
                        sol,
                        insc,
                        "nutricion",
                        autorizacion_suplencia,
                        request.user,
                    )

                errores_compartidos = guardar_datos_compartidos_desde_fuentes(
                    sol,
                    area_filtro_actual,
                    usuario=request.user,
                    post_data=post_data,
                    insc=insc,
                )

                for error in errores_compartidos[:3]:
                    messages.warning(request, error)

                messages.success(request, "Dictamen de nutrición guardado exitosamente.")

                cierre_realizado, estado_inscripcion, mensaje_cierre = revisar_cierre_filtros(sol)
                if cierre_realizado:
                    messages.info(request, mensaje_cierre)

                liberar_bloqueo_edicion_temporal(
                    request,
                    sol,
                    observaciones="Dictamen de Nutrición guardado correctamente.",
                )
                return redirect("nutricion_pendientes")

        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"Te faltó este campo ({field}): {error}")

        messages.warning(
            request,
            "⚠️ No se guardó el dictamen. Revisa los mensajes rojos de arriba.",
        )

    else:
        initial_nutricion = {
            "nombres_menor": n_menor,
            "apellido_paterno_menor": ap_menor,
            "apellido_materno_menor": am_menor,
            "fecha_nacimiento_menor": datos_menor.get("fecha_nacimiento_menor"),
            "curp_menor": datos_menor.get("curp_menor"),
        }
        initial_nutricion.update(initial_compartido)

        form = DictamenNutricionForm(
            instance=sol,
            initial=initial_nutricion,
        )

    contexto = {
        "sol": sol,
        "insc": insc,
        "form": form,
        "bloqueado": bloqueado,
        "bloqueo_edicion_temporal": bloqueo_edicion_temporal,
        "foto_perfil_nutricion_url": obtener_foto_perfil_usuario(request.user),
        "perfil_nutricion_soporta_foto": bool(obtener_campo_foto_perfil_usuario(request.user)),
        **datos_menor,
        **contexto_datos_compartidos_filtro(sol, area_filtro_actual),
        **contexto_suplencias_usuario(request.user),
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

    total_aprobados = aprobados.count()
    total_rechazados = rechazados.count()
    total_registros = total_aprobados + total_rechazados

    return render(
        request,
        "admisiones/nutricion_registro.html",
        {
            "aprobados": aprobados,
            "rechazados": rechazados,
            "total_aprobados": total_aprobados,
            "total_rechazados": total_rechazados,
            "total_registros": total_registros,
            "porcentaje_aprobados": porcentaje_panel(total_aprobados, total_registros),
            "porcentaje_rechazados": porcentaje_panel(total_rechazados, total_registros),
            "foto_perfil_nutricion_url": obtener_foto_perfil_usuario(request.user),
            "perfil_nutricion_soporta_foto": bool(obtener_campo_foto_perfil_usuario(request.user)),
            **contexto_suplencias_usuario(request.user),
            **contexto_semestre_operativo(),
        },
    )





def preparar_formulario_nutricion_solo_lectura(sol, datos_menor=None):
    """
    Prepara el formulario de Nutrición para que Médico pueda consultarlo
    dentro del dictamen médico sin permitir modificaciones.

    No se guarda nada de Nutrición desde Médico; solo se muestra la valoración
    ya capturada por el área de Nutrición.
    """
    datos_menor = datos_menor or {}

    initial = {
        "nombres_menor": datos_menor.get("nombre_nino") or datos_menor.get("nombres_menor"),
        "apellido_paterno_menor": datos_menor.get("paterno_nino") or datos_menor.get("apellido_paterno_menor"),
        "apellido_materno_menor": datos_menor.get("materno_nino") or datos_menor.get("apellido_materno_menor"),
        "fecha_nacimiento_menor": datos_menor.get("fecha_nacimiento_menor"),
        "curp_menor": datos_menor.get("curp_menor"),
    }

    try:
        form = DictamenNutricionForm(instance=sol, initial=initial)
    except Exception:
        return None

    for field in form.fields.values():
        field.required = False
        field.disabled = True

        clases_actuales = field.widget.attrs.get("class", "")
        if "form-control" not in clases_actuales and "form-select" not in clases_actuales:
            clases_actuales = f"{clases_actuales} form-control".strip()

        field.widget.attrs.update({
            "class": clases_actuales,
            "disabled": "disabled",
            "readonly": "readonly",
            "tabindex": "-1",
        })

    return form


def obtener_revision_nutricion_medica(sol, historia=None):
    """
    Recupera la revisión médica sobre Nutrición para repintar el formulario.
    Soporta dos formas:
    - Campos dedicados en Solicitud o HistoriaClinicaMedica, si existen.
    - Bloque guardado dentro de observaciones_medico, si el modelo aún no tiene campos dedicados.
    """
    revision = ""
    comentario = ""

    for obj in [historia, sol]:
        if not obj:
            continue

        if not revision and hasattr(obj, "revision_nutricion_medica"):
            revision = getattr(obj, "revision_nutricion_medica", "") or ""
            revision = {
                "ADECUADO": "BIEN",
                "REQUIERE_SEGUIMIENTO": "SEGUIMIENTO",
                "ALERTA": "OBSERVACION",
                "SIN_REVISION": "",
            }.get(revision, revision)

        if not comentario and hasattr(obj, "comentario_nutricion_medica"):
            comentario = getattr(obj, "comentario_nutricion_medica", "") or ""

        if not comentario and hasattr(obj, "comentario_revision_nutricion"):
            comentario = getattr(obj, "comentario_revision_nutricion", "") or ""

    if not revision or not comentario:
        observaciones = getattr(sol, "observaciones_medico", "") or ""

        if not revision:
            m_revision = re.search(
                r"Revisión médica de Nutrición:\s*(.+)",
                observaciones,
                flags=re.IGNORECASE,
            )
            if m_revision:
                texto_revision = m_revision.group(1).strip().splitlines()[0].strip().lower()
                if "seguimiento" in texto_revision:
                    revision = "SEGUIMIENTO"
                elif "observ" in texto_revision:
                    revision = "OBSERVACION"
                elif "bien" in texto_revision or "sin" in texto_revision:
                    revision = "BIEN"

        if not comentario:
            m_comentario = re.search(
                r"Comentario médico sobre Nutrición:\s*(.*)",
                observaciones,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if m_comentario:
                comentario = m_comentario.group(1).strip()

    return revision, comentario


def aplicar_revision_nutricion_medica(sol, historia, revision, comentario):
    """
    Guarda la conclusión médica sobre el formulario de Nutrición.

    Si tus modelos ya tienen campos:
    - revision_nutricion_medica
    - comentario_nutricion_medica

    se guardan ahí. Si todavía no existen, se conserva la información dentro
    de observaciones_medico para no romper el sistema ni requerir migración.
    """
    revision = (revision or "").strip().upper()
    comentario = (comentario or "").strip()

    revision_modelo = {
        "BIEN": "ADECUADO",
        "ADECUADO": "ADECUADO",
        "OBSERVACION": "ALERTA",
        "OBSERVACIÓN": "ALERTA",
        "ALERTA": "ALERTA",
        "SEGUIMIENTO": "REQUIERE_SEGUIMIENTO",
        "REQUIERE_SEGUIMIENTO": "REQUIERE_SEGUIMIENTO",
        "SIN_REVISION": "SIN_REVISION",
    }.get(revision, revision)

    etiquetas_revision = {
        "BIEN": "Bien / sin observaciones",
        "ADECUADO": "Bien / sin observaciones",
        "OBSERVACION": "Con observaciones",
        "ALERTA": "Con observaciones",
        "SEGUIMIENTO": "Requiere seguimiento",
        "REQUIERE_SEGUIMIENTO": "Requiere seguimiento",
    }

    sol_tiene_campos = False
    historia_tiene_campos = False

    if sol is not None:
        if hasattr(sol, "revision_nutricion_medica"):
            sol.revision_nutricion_medica = revision_modelo
            sol_tiene_campos = True

        if hasattr(sol, "comentario_nutricion_medica"):
            sol.comentario_nutricion_medica = comentario
            sol_tiene_campos = True

        if hasattr(sol, "comentario_revision_nutricion"):
            sol.comentario_revision_nutricion = comentario
            sol_tiene_campos = True

    if historia is not None:
        if hasattr(historia, "revision_nutricion_medica"):
            historia.revision_nutricion_medica = revision_modelo
            historia_tiene_campos = True

        if hasattr(historia, "comentario_nutricion_medica"):
            historia.comentario_nutricion_medica = comentario
            historia_tiene_campos = True

        if hasattr(historia, "comentario_revision_nutricion"):
            historia.comentario_revision_nutricion = comentario
            historia_tiene_campos = True

    if sol is not None and (revision or comentario) and not sol_tiene_campos:
        if hasattr(sol, "observaciones_medico"):
            observaciones_base = getattr(sol, "observaciones_medico", "") or ""
            observaciones_base = re.split(
                r"\n\s*---\s*Revisión médica de Nutrición\s*---",
                observaciones_base,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].rstrip()

            bloque = ["--- Revisión médica de Nutrición ---"]

            if revision:
                bloque.append(
                    f"Revisión médica de Nutrición: {etiquetas_revision.get(revision, revision)}"
                )

            if comentario:
                bloque.append(f"Comentario médico sobre Nutrición: {comentario}")

            sol.observaciones_medico = (
                f"{observaciones_base}\n\n" + "\n".join(bloque)
            ).strip()

    return sol, historia, sol_tiene_campos, historia_tiene_campos


# ===================== MÉDICO =====================
@login_required
def medico_pendientes(request):
    if not usuario_tiene_permiso_area_filtro(request.user, "medico"):
        return acceso_denegado_login(request, "No tienes permiso para entrar al filtro Médico.")

    # Foto de perfil desde el panel principal Médico.
    # El HTML envía:
    # - action_type=actualizar_foto_medico
    # - action_type=eliminar_foto_medico
    if request.method == "POST":
        respuesta_foto = procesar_foto_perfil_area(
            request,
            destino_url=reverse("medico_pendientes"),
            campo_archivo="foto_perfil_medico",
            action_actualizar="actualizar_foto_medico",
            action_eliminar="eliminar_foto_medico",
            nombre_area="Médico",
        )

        if respuesta_foto:
            return respuesta_foto

    if not hay_semestre_activo_operativo():
        messages.warning(
            request,
            "No hay semestre activo. Médico queda en modo solo consulta; no hay dictámenes pendientes para operar."
        )
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

    aprobados = Solicitud.objects.filter(
        estado_medico="APROBADO",
    ).order_by("-medico_en")

    rechazados = Solicitud.objects.filter(
        estado_medico="RECHAZADO",
    ).order_by("-medico_en")

    total_pendientes = qs.count()
    total_aprobados = aprobados.count()
    total_rechazados = rechazados.count()
    total_registros = total_aprobados + total_rechazados
    total_proceso = total_pendientes + total_registros

    return render(
        request,
        "admisiones/medico_pendientes.html",
        {
            "solicitudes": qs,
            "aprobados": aprobados,
            "rechazados": rechazados,
            "total_pendientes": total_pendientes,
            "total_aprobados": total_aprobados,
            "total_rechazados": total_rechazados,
            "total_registros": total_registros,
            "total_proceso": total_proceso,
            "porcentaje_pendientes": porcentaje_panel(total_pendientes, total_proceso),
            "porcentaje_aprobados": porcentaje_panel(total_aprobados, total_proceso),
            "porcentaje_rechazados": porcentaje_panel(total_rechazados, total_proceso),
            "porcentaje_dictaminados": porcentaje_panel(total_registros, total_proceso),
            "foto_perfil_medico_url": obtener_foto_perfil_usuario(request.user),
            "perfil_medico_soporta_foto": bool(obtener_campo_foto_perfil_usuario(request.user)),
            **contexto_bloqueos_edicion_area("MEDICA"),
            **contexto_suplencias_usuario(request.user),
            **contexto_semestre_operativo(),
        },
    )



@login_required
def medico_dictaminar(request, pk):
    sol = get_object_or_404(Solicitud, id=pk)
    insc = get_object_or_404(SolicitudInscripcion, solicitud_ingreso=sol)

    if not usuario_tiene_permiso_area_filtro(request.user, "medico"):
        return acceso_denegado_login(request, "No tienes permiso para dictaminar Médico.")

    bloqueado = not puede_editar_filtro(request.user, sol, "medico")
    autorizacion_suplencia_actual = obtener_suplencia_activa_para_filtro(request.user, "medico")
    tiene_suplencia_medica_actual = bool(autorizacion_suplencia_actual)

    # La reserva temporal y el botón "Salir y liberar" se usan únicamente
    # cuando otra persona está cubriendo el área médica por suplencia.
    # Para la médica titular normal, no se crea bloqueo aquí; así el botón
    # "Dictaminar" abre directamente el formulario y no regresa al panel.
    bloqueo_edicion_temporal = None
    if tiene_suplencia_medica_actual:
        bloqueo_edicion_temporal, respuesta_bloqueo = iniciar_bloqueo_edicion_temporal(
            request,
            sol,
            area="MEDICA",
            autorizacion_suplencia=autorizacion_suplencia_actual,
            retorno="medico_pendientes",
            motivo="Dictamen Médico",
        )
        if respuesta_bloqueo:
            return respuesta_bloqueo

    historia, created = HistoriaClinicaMedica.objects.get_or_create(inscripcion=insc)
    datos_menor = obtener_datos_menor_para_filtro(sol, insc)
    sol = aplicar_datos_identidad_menor_a_solicitud(sol, datos_menor)
    area_filtro_actual = AREA_FILTRO_MEDICO

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

    h_initial = aplicar_initial_datos_compartidos(h_initial, sol, area_filtro_actual)

    nutricion_form = preparar_formulario_nutricion_solo_lectura(sol, datos_menor)
    valoracion_nutricion = sol
    revision_nutricion_medica, comentario_nutricion_medica = obtener_revision_nutricion_medica(
        sol,
        historia,
    )

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

        post_data = preparar_post_con_datos_compartidos(request.POST, sol, area_filtro_actual)
        revision_nutricion_medica = (post_data.get("revision_nutricion_medica") or "").strip()
        comentario_nutricion_medica = (post_data.get("comentario_nutricion_medica") or "").strip()

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

                autorizacion_suplencia = autorizacion_suplencia_actual
                if autorizacion_suplencia:
                    sol = aplicar_dictamen_suplencia(sol, "medico", autorizacion_suplencia, request.user)

                historia_obj = h_form.save(commit=False)
                sol, historia_obj, _, _ = aplicar_revision_nutricion_medica(
                    sol,
                    historia_obj,
                    revision_nutricion_medica,
                    comentario_nutricion_medica,
                )

                sol.save()
                historia_obj.save()

                if autorizacion_suplencia:
                    registrar_movimiento_dictamen_suplencia(
                        sol,
                        insc,
                        "medico",
                        autorizacion_suplencia,
                        request.user,
                    )

                errores_compartidos = guardar_datos_compartidos_desde_fuentes(
                    sol,
                    area_filtro_actual,
                    usuario=request.user,
                    post_data=post_data,
                    historia=historia_obj,
                    insc=insc,
                )

                for error in errores_compartidos[:3]:
                    messages.warning(request, error)

                if hasattr(h_form, "save_m2m"):
                    h_form.save_m2m()

                messages.success(request, "Dictamen médico guardado.")

                cierre_realizado, estado_inscripcion, mensaje_cierre = revisar_cierre_filtros(sol)
                if cierre_realizado:
                    messages.info(request, mensaje_cierre)

                liberar_bloqueo_edicion_temporal(
                    request,
                    sol,
                    observaciones="Dictamen Médico guardado correctamente.",
                )
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
        form = DictamenMedicoForm(
            instance=sol,
            initial=obtener_initial_datos_compartidos_para_area(sol, area_filtro_actual),
        )
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
            "nutricion_form": nutricion_form,
            "valoracion_nutricion": valoracion_nutricion,
            "revision_nutricion_medica": revision_nutricion_medica,
            "comentario_nutricion_medica": comentario_nutricion_medica,
            "bloqueado": bloqueado,
            "bloqueo_edicion_temporal": bloqueo_edicion_temporal,
            "foto_perfil_medico_url": obtener_foto_perfil_usuario(request.user),
            "perfil_medico_soporta_foto": bool(obtener_campo_foto_perfil_usuario(request.user)),
            "mama_previo": bool(h_initial["nombres_madre"]),
            "papa_previo": bool(h_initial["nombres_padre"]),
            **datos_menor,
            **contexto_datos_compartidos_filtro(sol, area_filtro_actual),
            **contexto_suplencias_usuario(request.user),
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

    total_aprobados = aprobados.count()
    total_rechazados = rechazados.count()
    total_registros = total_aprobados + total_rechazados

    return render(
        request,
        "admisiones/medico_registro.html",
        {
            "aprobados": aprobados,
            "rechazados": rechazados,
            "total_aprobados": total_aprobados,
            "total_rechazados": total_rechazados,
            "total_registros": total_registros,
            "porcentaje_aprobados": porcentaje_panel(total_aprobados, total_registros),
            "porcentaje_rechazados": porcentaje_panel(total_rechazados, total_registros),
            "foto_perfil_medico_url": obtener_foto_perfil_usuario(request.user),
            "perfil_medico_soporta_foto": bool(obtener_campo_foto_perfil_usuario(request.user)),
            **contexto_suplencias_usuario(request.user),
            **contexto_semestre_operativo(),
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
            **contexto_suplencias_usuario(request.user),
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
    autorizacion_suplencia_actual = obtener_suplencia_activa_usuario_area(
        request.user,
        AutorizacionSuplencia.AreaCubierta.TRABAJO_SOCIAL,
        accion="PROCESO_SOCIAL",
    )
    bloqueo_edicion_temporal, respuesta_bloqueo = iniciar_bloqueo_edicion_temporal(
        request,
        inscripcion,
        area="TRABAJO_SOCIAL",
        autorizacion_suplencia=autorizacion_suplencia_actual,
        retorno="validacion_pagos_pendientes",
        motivo="Validación de pago por Trabajo Social",
    )
    if respuesta_bloqueo:
        return respuesta_bloqueo

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

            marcar_trabajo_social_por_suplencia(
                inscripcion=inscripcion,
                solicitud=inscripcion.solicitud_ingreso,
                usuario=request.user,
                accion=MovimientoSuplencia.TipoAccion.PAGO,
                descripcion="Comprobante presencial registrado durante cobertura temporal de Trabajo Social.",
            )

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

        marcar_trabajo_social_por_suplencia(
            inscripcion=inscripcion,
            solicitud=inscripcion.solicitud_ingreso,
            usuario=request.user,
            accion=MovimientoSuplencia.TipoAccion.PAGO,
            descripcion="Pago validado durante cobertura temporal de Trabajo Social.",
        )

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

        marcar_trabajo_social_por_suplencia(
            inscripcion=inscripcion,
            solicitud=inscripcion.solicitud_ingreso,
            usuario=request.user,
            accion=MovimientoSuplencia.TipoAccion.PAGO,
            descripcion="Comprobante de pago rechazado durante cobertura temporal de Trabajo Social.",
        )

        messages.warning(
            request,
            "Comprobante rechazado. El beneficiario podrá subir un nuevo comprobante."
        )

    else:
        messages.error(request, "Acción de pago no válida.")

    liberar_bloqueo_edicion_temporal(
        request,
        inscripcion,
        observaciones="Proceso de pago de Trabajo Social finalizado.",
    )
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
            **contexto_suplencias_usuario(request.user),
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
    autorizacion_suplencia_actual = obtener_suplencia_activa_usuario_area(
        request.user,
        AutorizacionSuplencia.AreaCubierta.TRABAJO_SOCIAL,
        accion="PROCESO_SOCIAL",
    )
    bloqueo_edicion_temporal, respuesta_bloqueo = iniciar_bloqueo_edicion_temporal(
        request,
        inscripcion,
        area="TRABAJO_SOCIAL",
        autorizacion_suplencia=autorizacion_suplencia_actual,
        retorno="codigos_responsable_pendientes",
        motivo="Código de responsable autorizado",
    )
    if respuesta_bloqueo:
        return respuesta_bloqueo

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
                    marcar_trabajo_social_por_suplencia(
                        inscripcion=inscripcion,
                        solicitud=inscripcion.solicitud_ingreso,
                        usuario=request.user,
                        accion=MovimientoSuplencia.TipoAccion.CODIGO_RESPONSABLE,
                        descripcion="Código de responsable generado o reseteado durante cobertura temporal de Trabajo Social.",
                    )

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
                            "bloqueo_edicion_temporal": bloqueo_edicion_temporal,
                            **contexto_suplencias_usuario(request.user),
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
            "bloqueo_edicion_temporal": bloqueo_edicion_temporal,
            **contexto_suplencias_usuario(request.user),
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

    autorizacion_suplencia_actual = obtener_suplencia_activa_usuario_area(
        request.user,
        AutorizacionSuplencia.AreaCubierta.TRABAJO_SOCIAL,
        accion="PROCESO_SOCIAL",
    )
    bloqueo_edicion_temporal, respuesta_bloqueo = iniciar_bloqueo_edicion_temporal(
        request,
        inscripcion,
        area="TRABAJO_SOCIAL",
        autorizacion_suplencia=autorizacion_suplencia_actual,
        retorno="codigos_responsable_pendientes",
        motivo="Entrega de código de responsable autorizado",
    )
    if respuesta_bloqueo:
        return respuesta_bloqueo

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
                marcar_trabajo_social_por_suplencia(
                    inscripcion=inscripcion,
                    solicitud=inscripcion.solicitud_ingreso,
                    usuario=request.user,
                    accion=MovimientoSuplencia.TipoAccion.CODIGO_RESPONSABLE,
                    descripcion="Entrega de código y credencial registrada durante cobertura temporal de Trabajo Social.",
                )

                messages.success(
                    request,
                    f"Entrega de código y credencial registrada para {responsable_codigo.nombre_completo}."
                )
            else:
                messages.warning(
                    request,
                    "El formulario es válido, pero no se pudo guardar la entrega."
                )

            liberar_bloqueo_edicion_temporal(
                request,
                inscripcion,
                observaciones="Entrega de código y credencial registrada.",
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
            "bloqueo_edicion_temporal": bloqueo_edicion_temporal,
            **contexto_suplencias_usuario(request.user),
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




# =========================================================
# PANEL DIRECTIVO - DATOS REALES PARA DASHBOARD POR PESTAÑAS
# =========================================================
def porcentaje_panel(parte, total):
    try:
        parte = int(parte or 0)
        total = int(total or 0)
    except Exception:
        return 0

    if total <= 0:
        return 0

    return round((parte * 100) / total)


def nombre_usuario_panel(user):
    if not user:
        return "Sin usuario"

    try:
        nombre = user.get_full_name()
        if nombre:
            return nombre
    except Exception:
        pass

    return (
        getattr(user, "nombre", "")
        or getattr(user, "email", "")
        or getattr(user, "username", "")
        or str(user)
    )


def qs_por_semestre_y_sede(qs, semestre=None, sede=None):
    if semestre:
        qs = qs.filter(semestre=semestre)
    if sede:
        qs = qs.filter(semestre__sede_configurada=sede)
    return qs


def qs_por_semestre_y_sede_o_sin_semestre(qs, semestre=None, sede=None):
    """
    Filtro para bandejas de seguimiento de Dirección.

    Algunos expedientes antiguos o creados antes de asignar semestre pueden tener
    semestre=NULL. Si se aplica qs_por_semestre_y_sede() directamente, esos
    expedientes quedan invisibles aunque estén en proceso o esperando veredicto.

    Regla:
    - Si se consulta un semestre/sede, se muestran los registros de ese semestre
      y también los registros sin semestre para que Dirección no pierda expedientes.
    - Si no hay filtro de semestre/sede, se conserva el queryset completo.
    """
    if semestre:
        qs = qs.filter(Q(semestre=semestre) | Q(semestre__isnull=True))
    if sede:
        qs = qs.filter(Q(semestre__sede_configurada=sede) | Q(semestre__isnull=True))
    return qs


def preparar_sedes_panel(semestre=None):
    sedes = []

    for sede in Sede.objects.order_by("nombre"):
        semestres_sede = Semestre.objects.filter(sede_configurada=sede)
        if semestre and getattr(semestre, "sede_configurada_id", None) == sede.id:
            semestres_sede = semestres_sede.filter(id=semestre.id)

        alumnos = SolicitudInscripcion.objects.filter(
            semestre__in=semestres_sede,
            estado="FINALIZADA",
        ).count()

        salas_base = Sala.objects.filter(sede=sede).count()
        salas_configuradas = SalaSemestre.objects.filter(
            semestre__in=semestres_sede,
            activa=True,
        ).count()

        maestras = AsignacionMaestra.objects.filter(
            sala_semestre__semestre__in=semestres_sede,
            activo=True,
        ).values("maestra_id").distinct().count()

        sedes.append({
            "id": sede.id,
            "nombre": getattr(sede, "nombre", "Sede"),
            "clave": getattr(sede, "clave", ""),
            "direccion": getattr(sede, "direccion", ""),
            "total_salas": salas_configuradas or salas_base,
            "total_alumnos": alumnos,
            "total_maestras": maestras,
            "estado": "Operativa" if semestres_sede.exists() else "Sin semestre",
        })

    return sedes


def preparar_alumnos_panel(alumnos_qs, dia_actual=None):
    alumnos = []
    registros_por_alumno = {}
    registros_lista = []

    operacion_iniciada = dia_operativo_tiene_operacion_ninos(dia_actual)

    if operacion_iniciada:
        registros = (
            RegistroDiarioAlumno.objects
            .filter(dia_operativo=dia_actual)
            .select_related("alumno", "sala_semestre", "sala_semestre__sala")
        )
        registros_lista = list(registros)
        registros_por_alumno = {r.alumno_id: r for r in registros_lista}

    chequeo_activo = chequeo_ausencias_activado(
        dia_actual=dia_actual,
        registros_hoy=registros_lista,
        alumnos_qs=alumnos_qs,
    ) if operacion_iniciada else False

    alumnos_ids_panel = set()
    try:
        alumnos_ids_panel = set(alumnos_qs.values_list("id", flat=True))
    except Exception:
        try:
            alumnos_ids_panel = {getattr(alumno, "id", None) for alumno in alumnos_qs if getattr(alumno, "id", None)}
        except Exception:
            alumnos_ids_panel = set()

    alumnos_retirados_mayor = alumnos_retirados_por_incidencia_mayor(
        dia_actual=dia_actual,
        registros_lista=registros_lista,
        alumnos_ids=alumnos_ids_panel,
    ) if operacion_iniciada else set()

    incidencias_por_alumno = {}
    if alumnos_qs.exists():
        conteos = (
            Incidencia.objects
            .filter(alumno__in=alumnos_qs)
            .values("alumno_id")
            .annotate(total=Count("id"))
        )
        incidencias_por_alumno = {item["alumno_id"]: item["total"] for item in conteos}

    for inscripcion in alumnos_qs[:250]:
        solicitud = inscripcion.solicitud_ingreso
        registro = registros_por_alumno.get(inscripcion.id)

        if not dia_actual:
            estado_dia = "Sin día operativo"
        elif not dia_operativo_es_laborable(dia_actual):
            estado_dia = "Día inhábil"
        elif not operacion_iniciada:
            estado_dia = "Día no iniciado"
        else:
            estado_dia = "Fuera de estancia"

        hora_entrada = "--"
        hora_salida = "--"

        if operacion_iniciada:
            if registro:
                if getattr(registro, "entrada_en", None):
                    hora_entrada = timezone.localtime(registro.entrada_en).strftime("%H:%M")
                if getattr(registro, "salida_en", None):
                    hora_salida = timezone.localtime(registro.salida_en).strftime("%H:%M")

                if getattr(registro, "entrada_en", None) and not getattr(registro, "salida_en", None):
                    estado_dia = "En estancia"
                elif registro_diario_marcado_ausente(registro):
                    estado_dia = "Ausente"
                elif inscripcion.id in alumnos_retirados_mayor:
                    estado_dia = "Ausente por incidencia mayor"
                elif getattr(registro, "salida_en", None):
                    estado_dia = "Fuera de estancia"
                elif chequeo_activo:
                    estado_dia = "Ausente"
                else:
                    estado_dia = "Fuera de estancia"
            else:
                estado_dia = "Ausente" if chequeo_activo else "Fuera de estancia"

        sala_nombre = "Sin sala"
        if getattr(inscripcion, "sala_semestre_asignada", None) and inscripcion.sala_semestre_asignada.sala:
            sala_nombre = inscripcion.sala_semestre_asignada.sala.nombre
        elif getattr(inscripcion, "sala_asignada", None):
            sala_nombre = inscripcion.sala_asignada.nombre

        alumnos.append({
            "id": inscripcion.id,
            "nombre": solicitud.nombre_menor_completo() if hasattr(solicitud, "nombre_menor_completo") else str(solicitud),
            "folio": getattr(solicitud, "folio", ""),
            "sala": sala_nombre,
            "tutor": solicitud.nombre_tutor_completo() if hasattr(solicitud, "nombre_tutor_completo") else "Sin tutor",
            "estado_dia": estado_dia,
            "hora_entrada": hora_entrada,
            "hora_salida": hora_salida,
            "total_incidencias": incidencias_por_alumno.get(inscripcion.id, 0),
        })

    return alumnos



def modelo_tiene_campo(modelo, campo):
    """Valida de forma segura si un modelo tiene un campo concreto."""
    try:
        modelo._meta.get_field(campo)
        return True
    except Exception:
        return False


def obtener_titulo_evento_calendario(evento):
    """Obtiene un texto corto para mostrar eventos/fechas del calendario."""
    if not evento:
        return "Fecha especial"

    for campo in ["titulo", "nombre", "motivo", "descripcion"]:
        valor = (getattr(evento, campo, "") or "").strip()
        if valor:
            return valor

    return "Fecha especial"


def normalizar_tipo_calendario(valor):
    valor = normalizar_texto(valor or "evento")
    valor = valor.replace("dia", "día") if valor == "dia festivo" else valor
    return valor or "evento"


def tipo_calendario_es_inhabil(tipo):
    """
    Solo los festivos y suspensiones deben afectar la operación diaria.
    Un evento o actividad especial se muestra en el calendario, pero no debe
    cerrar el día ni impedir que las maestras trabajen.
    """
    tipo = normalizar_texto(tipo or "")
    return tipo in [
        "dia festivo",
        "día festivo",
        "festivo",
        "suspension",
        "suspensión",
        "inhabil",
        "inhábil",
    ]


def agregar_linea_evento_existente(evento, titulo, descripcion="", tipo="", hora=""):
    """
    Si el modelo de calendario no permite duplicar fecha por semestre, se agrega
    la actividad como una línea adicional dentro del registro existente. Así no
    se bloquea al usuario cuando captura otra actividad el mismo día.
    """
    if not evento:
        return False

    hora = (hora or "").strip()
    titulo = (titulo or "").strip()
    descripcion = (descripcion or "").strip()
    tipo = (tipo or "Evento").strip()

    encabezado = f"{hora} - {titulo}" if hora else titulo
    nueva_linea = encabezado
    if tipo:
        nueva_linea = f"{nueva_linea} [{tipo}]"
    if descripcion:
        nueva_linea = f"{nueva_linea}: {descripcion}"

    campos_actualizados = []

    if modelo_tiene_campo(DiaFestivo, "descripcion"):
        descripcion_actual = (getattr(evento, "descripcion", "") or "").strip()
        if nueva_linea not in descripcion_actual:
            evento.descripcion = f"{descripcion_actual}\n{nueva_linea}".strip()
            campos_actualizados.append("descripcion")

    # Si no existe descripcion, se conserva la información en motivo o nombre.
    if not campos_actualizados:
        for campo in ["motivo", "nombre", "titulo"]:
            if modelo_tiene_campo(DiaFestivo, campo):
                valor_actual = (getattr(evento, campo, "") or "").strip()
                if nueva_linea not in valor_actual:
                    setattr(evento, campo, f"{valor_actual}\n{nueva_linea}".strip())
                    campos_actualizados.append(campo)
                break

    if modelo_tiene_campo(DiaFestivo, "tipo") and tipo:
        try:
            evento.tipo = tipo
            campos_actualizados.append("tipo")
        except Exception:
            pass

    if campos_actualizados:
        try:
            evento.save(update_fields=list(dict.fromkeys(campos_actualizados)))
        except Exception:
            evento.save()
        return True

    return False


def crear_evento_calendario_directiva(semestre, post_data, usuario=None):
    """
    Crea una actividad/fecha desde el panel directivo.

    Reglas aplicadas:
    - Permite capturar varias actividades en la misma fecha.
    - Si la base de datos permite duplicados, crea un registro nuevo.
    - Si el modelo bloquea duplicados por semestre-fecha, agrega la actividad
      al registro existente para no rechazar la captura.
    - Solo festivos/suspensiones regeneran calendario operativo como inhábil.
    """
    errores = []

    if not semestre:
        return False, ["No hay semestre activo para registrar la fecha."], None

    fecha_txt = (post_data.get("fecha") or "").strip()
    titulo = (post_data.get("titulo") or post_data.get("nombre") or post_data.get("motivo") or "").strip()
    descripcion = (post_data.get("descripcion") or "").strip()
    tipo = (post_data.get("tipo") or "Evento").strip()
    hora = (post_data.get("hora") or post_data.get("hora_inicio") or post_data.get("hora_evento") or "").strip()

    if not fecha_txt:
        errores.append("Debes capturar la fecha.")

    if not titulo:
        errores.append("Debes capturar el título de la actividad o fecha.")

    try:
        fecha = datetime.strptime(fecha_txt, "%Y-%m-%d").date()
    except Exception:
        fecha = None
        errores.append("La fecha no tiene un formato válido.")

    if errores:
        return False, errores, None

    titulo_guardado = f"{hora} - {titulo}" if hora else titulo
    descripcion_guardada = descripcion or titulo_guardado

    evento = DiaFestivo(semestre=semestre, fecha=fecha)

    for campo in ["titulo", "nombre", "motivo"]:
        if modelo_tiene_campo(DiaFestivo, campo):
            try:
                setattr(evento, campo, titulo_guardado)
            except Exception:
                pass

    if modelo_tiene_campo(DiaFestivo, "descripcion"):
        try:
            evento.descripcion = descripcion_guardada
        except Exception:
            pass

    if modelo_tiene_campo(DiaFestivo, "tipo"):
        try:
            evento.tipo = tipo
        except Exception:
            pass

    for campo in ["creado_por", "registrado_por", "actualizado_por"]:
        if usuario and modelo_tiene_campo(DiaFestivo, campo):
            try:
                setattr(evento, campo, usuario)
            except Exception:
                pass

    try:
        evento.save()
        return True, ["Fecha agregada correctamente al calendario."], evento
    except Exception as exc:
        # Compatibilidad: si el modelo tiene restricción única por fecha,
        # agregamos la nueva actividad dentro del registro ya existente.
        existente = (
            DiaFestivo.objects
            .filter(semestre=semestre, fecha=fecha)
            .order_by("id")
            .first()
        )

        if existente and agregar_linea_evento_existente(existente, titulo, descripcion, tipo, hora):
            return True, ["La fecha ya existía; se agregó la nueva actividad al mismo día."], existente

        return False, [f"No se pudo guardar la fecha: {exc}"], None


def preparar_calendario_panel(semestre=None, limite=35):
    calendario = []

    if not semestre:
        return calendario

    festivos_por_fecha = {}
    for evento in DiaFestivo.objects.filter(semestre=semestre).order_by("fecha", "id"):
        festivos_por_fecha.setdefault(evento.fecha, []).append(evento)

    dias_qs = DiaOperativoSemestre.objects.filter(semestre=semestre).order_by("fecha")[:limite]
    fechas_agregadas = set()

    for dia in dias_qs:
        eventos_fecha = festivos_por_fecha.get(dia.fecha, [])
        titulos_eventos = [obtener_titulo_evento_calendario(evento) for evento in eventos_fecha]
        titulo = ""

        if titulos_eventos:
            titulo = " · ".join(titulos_eventos[:3])
            if len(titulos_eventos) > 3:
                titulo = f"{titulo} +{len(titulos_eventos) - 3} más"
        elif not getattr(dia, "es_habil", True):
            titulo = "Inhábil"
        elif getattr(dia, "estado", "") == DiaOperativoSemestre.EstadoDia.ABIERTO:
            titulo = "Día abierto"
        elif getattr(dia, "estado", "") == DiaOperativoSemestre.EstadoDia.CERRADO:
            titulo = "Día cerrado"

        calendario.append({
            "fecha": dia.fecha,
            "es_habil": getattr(dia, "es_habil", True),
            "titulo": titulo,
            "estado": getattr(dia, "estado", ""),
            "eventos": eventos_fecha,
            "total_eventos": len(eventos_fecha),
        })
        fechas_agregadas.add(dia.fecha)

    # Si hay eventos fuera del calendario operativo generado o si aún no hay
    # días operativos, también se muestran para que Dirección no pierda de vista
    # las actividades capturadas.
    for fecha, eventos_fecha in festivos_por_fecha.items():
        if fecha in fechas_agregadas:
            continue

        titulos_eventos = [obtener_titulo_evento_calendario(evento) for evento in eventos_fecha]
        titulo = " · ".join(titulos_eventos[:3]) if titulos_eventos else "Fecha especial"
        if len(titulos_eventos) > 3:
            titulo = f"{titulo} +{len(titulos_eventos) - 3} más"

        calendario.append({
            "fecha": fecha,
            "es_habil": not any(tipo_calendario_es_inhabil(getattr(evento, "tipo", "")) for evento in eventos_fecha),
            "titulo": titulo,
            "estado": "EVENTO",
            "eventos": eventos_fecha,
            "total_eventos": len(eventos_fecha),
        })

    calendario = sorted(calendario, key=lambda item: item.get("fecha"))
    return calendario[:limite]

def preparar_actividades_panel(semestre=None):
    """
    Actividades directivas reales del calendario.

    Ya no se cargan aquí los días operativos abiertos/cerrados/programados,
    porque eso llena la vista de Actividades con información repetida del
    calendario de operación diaria. Esta sección queda para actividades,
    eventos, reuniones o fechas especiales capturadas en el calendario.
    """
    actividades = []

    if not semestre:
        return actividades

    eventos = (
        DiaFestivo.objects
        .filter(semestre=semestre)
        .order_by("-fecha", "-id")[:30]
    )

    for evento in eventos:
        tipo = (getattr(evento, "tipo", "") or "Actividad").strip()
        titulo = obtener_titulo_evento_calendario(evento)
        descripcion = (getattr(evento, "descripcion", "") or "").strip()

        actividades.append({
            "titulo": titulo,
            "descripcion": descripcion or f"{tipo} registrada para seguimiento directivo.",
            "fecha": evento.fecha,
            "sala": getattr(getattr(semestre, "sede_configurada", None), "nombre", ""),
            "tipo": tipo,
        })

    return actividades

def preparar_personal_panel(semestre=None):
    User = get_user_model()
    personal = []

    usuarios = (
        User.objects
        .filter(is_active=True)
        .exclude(tipo_persona__iexact="BENEFICIARIO")
        .exclude(tipo_persona__iexact="BENEFICIARIA")
        .order_by("email", "username")[:250]
    )
    asignaciones = {}

    if semestre:
        for asignacion in (
            AsignacionMaestra.objects
            .filter(sala_semestre__semestre=semestre, activo=True)
            .select_related("maestra", "sala_semestre", "sala_semestre__sala", "sala_semestre__sala__sede")
        ):
            asignaciones[asignacion.maestra_id] = asignacion

    dia_actual = None
    if semestre:
        dia_actual = DiaOperativoSemestre.objects.filter(
            semestre=semestre,
            fecha=timezone.localdate(),
        ).select_related("abierto_por", "cerrado_por").first()

    for user in usuarios:
        asignacion = asignaciones.get(user.id)
        sede_nombre = "General"
        area = getattr(user, "tipo_persona", "") or "Personal"

        if asignacion and asignacion.sala_semestre and asignacion.sala_semestre.sala:
            area = f"Sala {asignacion.sala_semestre.sala.nombre}"
            if asignacion.sala_semestre.sala.sede:
                sede_nombre = asignacion.sala_semestre.sala.sede.nombre

        hora_entrada = "--"
        hora_salida = "--"
        if dia_actual and getattr(dia_actual, "abierto_por_id", None) == user.id and getattr(dia_actual, "abierto_en", None):
            hora_entrada = timezone.localtime(dia_actual.abierto_en).strftime("%H:%M")
        if dia_actual and getattr(dia_actual, "cerrado_por_id", None) == user.id and getattr(dia_actual, "cerrado_en", None):
            hora_salida = timezone.localtime(dia_actual.cerrado_en).strftime("%H:%M")

        personal.append({
            "id": user.id,
            "nombre": nombre_usuario_panel(user),
            "rol": getattr(user, "tipo_persona", "") or "Personal",
            "area": area,
            "email": getattr(user, "email", ""),
            "sede": sede_nombre,
            "estado": "Activo" if user.is_active else "Inactivo",
            "hora_entrada": hora_entrada,
            "hora_salida": hora_salida,
        })

    return personal



def datos_reporte_directiva(reporte, contexto):
    """
    Construye los datos del reporte para usar la misma informacion en:
    - Vista previa dentro del dashboard.
    - PDF.
    - Excel/CSV.
    """
    reporte = (reporte or "general").strip().lower()

    total_ninos = contexto.get("total_ninos", 0) or 0
    ninos_en_estancia = contexto.get("ninos_en_estancia", 0) or 0
    ninos_ausentes = contexto.get("ninos_ausentes", 0) or 0
    ninos_fuera = contexto.get("ninos_fuera_estancia", 0) or 0

    incidencias_total = contexto.get("incidencias_total", 0) or 0
    incidencias_abiertas = contexto.get("incidencias_abiertas", 0) or 0
    incidencias_cerradas = contexto.get("incidencias_cerradas", 0) or 0
    kpi_riesgo = contexto.get("kpi_riesgo", 0) or 0
    incidencias_sin_seguimiento = contexto.get("incidencias_sin_seguimiento", 0) or 0

    total_dias = contexto.get("total_dias_operativos", 0) or 0
    dias_cerrados = contexto.get("dias_cerrados_operativos", 0) or 0
    dias_pendientes = max(total_dias - dias_cerrados, 0)

    total_expedientes = contexto.get("total_expedientes", 0) or 0
    expedientes_finalizados = (
        contexto.get("kpi_alumnos_total", None)
        if contexto.get("kpi_alumnos_total", None) is not None
        else contexto.get("total_ninos", 0)
    ) or 0
    expedientes_pendientes = max(total_expedientes - expedientes_finalizados, 0)

    porcentaje_estancia = contexto.get("porcentaje_ninos_estancia", 0) or 0
    porcentaje_ausentes = contexto.get("porcentaje_ninos_ausentes", 0) or 0
    porcentaje_fuera = contexto.get("porcentaje_ninos_fuera", 0) or 0
    porcentaje_incidencias = contexto.get("porcentaje_incidencias_cerradas", 0) or 0
    porcentaje_finalizados = contexto.get("porcentaje_finalizados", 0) or 0
    porcentaje_calendario = contexto.get("porcentaje_calendario", 0) or 0

    if reporte == "asistencia":
        return {
            "slug": "asistencia",
            "titulo": "Reporte de asistencia",
            "descripcion": "Resumen de niñas y niños presentes, ausentes y fuera de estancia según la operación diaria real.",
            "porcentaje": porcentaje_estancia,
            "metricas": [
                {"label": "Total de niños", "value": total_ninos, "hint": "Alumnos finalizados y activos del semestre."},
                {"label": "En estancia", "value": ninos_en_estancia, "hint": f"{porcentaje_estancia}% del total."},
                {"label": "Ausentes", "value": ninos_ausentes, "hint": f"{porcentaje_ausentes}% del total."},
                {"label": "Fuera de estancia", "value": ninos_fuera, "hint": f"{porcentaje_fuera}% del total."},
            ],
            "columnas": ["Estatus", "Cantidad", "Porcentaje", "Observacion"],
            "filas": [
                ["En estancia", ninos_en_estancia, f"{porcentaje_estancia}%", "Niños con entrada registrada y sin salida."],
                ["Ausentes", ninos_ausentes, f"{porcentaje_ausentes}%", "Niños marcados ausentes, sin entrada después de la hora límite o retirados por incidencia mayor."],
                ["Fuera de estancia", ninos_fuera, f"{porcentaje_fuera}%", "Niños pendientes de entrada antes del chequeo configurado o que ya registraron salida normal."],
                ["Total", total_ninos, "100%" if total_ninos else "0%", "Total de niños considerados en el reporte."],
            ],
        }

    if reporte == "incidencias":
        return {
            "slug": "incidencias",
            "titulo": "Reporte de incidencias",
            "descripcion": "Resumen de incidencias por estado, riesgo y seguimiento para consulta directiva.",
            "porcentaje": porcentaje_incidencias,
            "metricas": [
                {"label": "Total", "value": incidencias_total, "hint": "Incidencias visibles para Dirección."},
                {"label": "Abiertas", "value": incidencias_abiertas, "hint": "Pendientes de cierre."},
                {"label": "Cerradas", "value": incidencias_cerradas, "hint": f"{porcentaje_incidencias}% cerradas."},
                {"label": "Riesgo alto", "value": kpi_riesgo, "hint": "Casos que requieren mayor atención."},
            ],
            "columnas": ["Indicador", "Cantidad", "Porcentaje", "Observacion"],
            "filas": [
                ["Abiertas", incidencias_abiertas, f"{porcentaje_panel(incidencias_abiertas, incidencias_total)}%", "Incidencias que siguen activas."],
                ["Cerradas", incidencias_cerradas, f"{porcentaje_incidencias}%", "Incidencias con resolución final."],
                ["Riesgo alto", kpi_riesgo, f"{porcentaje_panel(kpi_riesgo, incidencias_total)}%", "Incidencias críticas o prioritarias."],
                ["Sin seguimiento", incidencias_sin_seguimiento, f"{porcentaje_panel(incidencias_sin_seguimiento, incidencias_total)}%", "Casos sin seguimiento registrado."],
                ["Médicas", (contexto.get("inc_medica_abiertas", 0) or 0) + (contexto.get("inc_medica_cerradas", 0) or 0), "-", "Incidencias del área médica."],
                ["Nutricionales", (contexto.get("inc_nutricional_abiertas", 0) or 0) + (contexto.get("inc_nutricional_cerradas", 0) or 0), "-", "Incidencias del área nutricional."],
                ["Psicológicas", (contexto.get("inc_psicologica_abiertas", 0) or 0) + (contexto.get("inc_psicologica_cerradas", 0) or 0), "-", "Incidencias del área psicológica."],
                ["Pedagógicas", (contexto.get("inc_pedagogica_abiertas", 0) or 0) + (contexto.get("inc_pedagogica_cerradas", 0) or 0), "-", "Incidencias del área pedagógica."],
            ],
        }

    if reporte == "expedientes":
        return {
            "slug": "expedientes",
            "titulo": "Reporte de expedientes",
            "descripcion": "Avance de expedientes finalizados respecto al total del semestre consultado.",
            "porcentaje": porcentaje_finalizados,
            "metricas": [
                {"label": "Total expedientes", "value": total_expedientes, "hint": "Expedientes del semestre."},
                {"label": "Finalizados", "value": expedientes_finalizados, "hint": f"{porcentaje_finalizados}% finalizados."},
                {"label": "Pendientes", "value": expedientes_pendientes, "hint": "Expedientes que siguen en proceso."},
                {"label": "Pendientes veredicto", "value": contexto.get("kpi_pendientes", 0) or 0, "hint": "Requieren resolución de Dirección."},
            ],
            "columnas": ["Estatus", "Cantidad", "Porcentaje", "Observacion"],
            "filas": [
                ["Finalizados", expedientes_finalizados, f"{porcentaje_finalizados}%", "Inscripciones concluidas."],
                ["Pendientes", expedientes_pendientes, f"{porcentaje_panel(expedientes_pendientes, total_expedientes)}%", "Expedientes en proceso."],
                ["Pendientes de veredicto", contexto.get("kpi_pendientes", 0) or 0, "-", "Expedientes que requieren revisión directiva."],
                ["Total", total_expedientes, "100%" if total_expedientes else "0%", "Total de expedientes considerados."],
            ],
        }

    if reporte == "calendario":
        return {
            "slug": "calendario",
            "titulo": "Reporte de calendario operativo",
            "descripcion": "Avance de días operativos del semestre: días cerrados, pendientes y porcentaje concluido.",
            "porcentaje": porcentaje_calendario,
            "metricas": [
                {"label": "Días operativos", "value": total_dias, "hint": "Total de días configurados."},
                {"label": "Días cerrados", "value": dias_cerrados, "hint": f"{porcentaje_calendario}% concluido."},
                {"label": "Días pendientes", "value": dias_pendientes, "hint": "Días por operar o cerrar."},
                {"label": "Salas configuradas", "value": contexto.get("kpi_salas", 0) or 0, "hint": "Salas activas del semestre."},
            ],
            "columnas": ["Indicador", "Cantidad", "Porcentaje", "Observacion"],
            "filas": [
                ["Días cerrados", dias_cerrados, f"{porcentaje_calendario}%", "Días operativos concluidos."],
                ["Días pendientes", dias_pendientes, f"{porcentaje_panel(dias_pendientes, total_dias)}%", "Días todavía abiertos o pendientes."],
                ["Total de días", total_dias, "100%" if total_dias else "0%", "Total del calendario operativo."],
            ],
        }

    return {
        "slug": "general",
        "titulo": "Reporte general directivo",
        "descripcion": "Resumen general de operación directiva.",
        "porcentaje": 0,
        "metricas": [
            {"label": "Total de niños", "value": total_ninos, "hint": "Niños registrados."},
            {"label": "Incidencias", "value": incidencias_total, "hint": "Incidencias visibles."},
            {"label": "Salas", "value": contexto.get("kpi_salas", 0) or 0, "hint": "Salas configuradas."},
            {"label": "Expedientes", "value": total_expedientes, "hint": "Expedientes del semestre."},
        ],
        "columnas": ["Indicador", "Valor", "Observacion"],
        "filas": [
            ["Total de niños", total_ninos, "Niños registrados."],
            ["Incidencias abiertas", incidencias_abiertas, "Casos pendientes."],
            ["Incidencias cerradas", incidencias_cerradas, "Casos concluidos."],
            ["Salas configuradas", contexto.get("kpi_salas", 0) or 0, "Salas activas."],
        ],
    }


def generar_reporte_directiva(request, reporte, formato, contexto):
    reporte = (reporte or "general").strip().lower()
    formato = (formato or "").strip().lower()

    if not formato:
        return None

    datos = datos_reporte_directiva(reporte, contexto)
    columnas = datos.get("columnas", [])
    filas = datos.get("filas", [])

    if formato in ["csv", "xlsx", "excel"]:
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="reporte_directiva_{datos.get("slug", reporte)}.csv"'
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(columnas)
        writer.writerows(filas)
        return response

    if formato == "pdf":
        titulo = escape(datos.get("titulo", "Reporte directivo"))
        descripcion = escape(datos.get("descripcion", "Resumen directivo."))
        semestre = escape(getattr(contexto.get("semestre_seleccionado"), "nombre", "Sin semestre") or "Sin semestre")
        sede = escape(getattr(contexto.get("sede_seleccionada"), "nombre", "Todas las sedes") or "Todas las sedes")
        fecha = timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M")

        metricas_html = ""
        for metrica in datos.get("metricas", []):
            metricas_html += f"""
                <td class="metric-card">
                    <div class="metric-label">{escape(str(metrica.get('label', 'Indicador')))}</div>
                    <div class="metric-value">{escape(str(metrica.get('value', '0')))}</div>
                    <div class="metric-hint">{escape(str(metrica.get('hint', '')))}</div>
                </td>
            """

        encabezados_html = "".join(f"<th>{escape(str(col))}</th>" for col in columnas)
        filas_html = ""
        for fila in filas:
            filas_html += "<tr>" + "".join(f"<td>{escape(str(celda))}</td>" for celda in fila) + "</tr>"

        html = f"""
        <!doctype html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                @page {{
                    size: letter;
                    margin: 1.5cm 1.35cm 1.5cm 1.35cm;
                    @frame footer_frame {{
                        -pdf-frame-content: footer_content;
                        left: 1.35cm;
                        right: 1.35cm;
                        bottom: .65cm;
                        height: .5cm;
                    }}
                }}
                body {{
                    font-family: Helvetica, Arial, sans-serif;
                    color: #102b6b;
                    font-size: 10.5pt;
                }}
                .topbar {{
                    background-color: #245bd6;
                    color: #ffffff;
                    padding: 18px 20px;
                    border-radius: 8px;
                }}
                .brand {{
                    font-size: 10pt;
                    font-weight: bold;
                    letter-spacing: .5px;
                }}
                h1 {{
                    font-size: 22pt;
                    margin: 10px 0 4px 0;
                    color: #ffffff;
                }}
                .subtitle {{
                    font-size: 10.5pt;
                    color: #eef4ff;
                    margin: 0;
                }}
                .info-table {{
                    width: 100%;
                    margin-top: 14px;
                    border-collapse: collapse;
                }}
                .info-table td {{
                    border: 1px solid #dbe5f6;
                    padding: 8px 10px;
                    background-color: #f7faff;
                    font-size: 9.5pt;
                }}
                .info-label {{
                    color: #60749d;
                    font-weight: bold;
                }}
                .section-title {{
                    font-size: 14pt;
                    color: #0b2a68;
                    margin: 18px 0 8px 0;
                    font-weight: bold;
                }}
                .metric-table {{
                    width: 100%;
                    border-collapse: separate;
                    border-spacing: 6px;
                    margin-top: 10px;
                }}
                .metric-card {{
                    border: 1px solid #dbe5f6;
                    background-color: #ffffff;
                    border-radius: 8px;
                    padding: 12px;
                    vertical-align: top;
                }}
                .metric-label {{
                    color: #60749d;
                    font-size: 9pt;
                    font-weight: bold;
                }}
                .metric-value {{
                    color: #0a2a66;
                    font-size: 22pt;
                    font-weight: bold;
                    margin-top: 4px;
                }}
                .metric-hint {{
                    color: #526b9a;
                    font-size: 8.5pt;
                    margin-top: 4px;
                }}
                .data-table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 8px;
                }}
                .data-table th {{
                    background-color: #e8f0ff;
                    color: #0b2a68;
                    padding: 9px;
                    border: 1px solid #cbdaf5;
                    font-size: 9.5pt;
                    text-align: left;
                }}
                .data-table td {{
                    padding: 8px 9px;
                    border: 1px solid #dbe5f6;
                    color: #263f6d;
                    font-size: 9.2pt;
                    vertical-align: top;
                }}
                .note {{
                    margin-top: 14px;
                    padding: 10px;
                    border-left: 4px solid #245bd6;
                    background-color: #f7faff;
                    color: #526b9a;
                    font-size: 9pt;
                }}
                #footer_content {{
                    color: #60749d;
                    font-size: 8pt;
                    text-align: right;
                }}
            </style>
        </head>
        <body>
            <div class="topbar">
                <div class="brand">ESTANCIA INFANTIL UNACH</div>
                <h1>{titulo}</h1>
                <p class="subtitle">{descripcion}</p>
            </div>

            <table class="info-table">
                <tr>
                    <td><span class="info-label">Semestre:</span><br>{semestre}</td>
                    <td><span class="info-label">Sede:</span><br>{sede}</td>
                    <td><span class="info-label">Generado:</span><br>{fecha}</td>
                </tr>
            </table>

            <div class="section-title">Indicadores principales</div>
            <table class="metric-table"><tr>{metricas_html}</tr></table>

            <div class="section-title">Detalle del reporte</div>
            <table class="data-table">
                <thead><tr>{encabezados_html}</tr></thead>
                <tbody>{filas_html}</tbody>
            </table>

            <div class="note">
                Documento generado automáticamente desde el Panel Directivo. La información corresponde a los registros visibles para Dirección en el semestre y sede consultados.
            </div>
            <div id="footer_content">Estancia Infantil UNACH - Panel Directivo</div>
        </body>
        </html>
        """
        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="reporte_directiva_{datos.get("slug", reporte)}.pdf"'
        pisa.CreatePDF(html, dest=response, link_callback=link_callback)
        return response

    return None


def registro_diario_marcado_ausente(registro):
    """
    Un niño solo cuenta como ausente si existe una marca explícita de ausencia
    en su registro diario. No se considera ausente únicamente por no haber
    llegado temprano; eso se calcula aparte, después de la hora límite.
    """
    if not registro:
        return False

    campos_booleanos = [
        "ausente",
        "marcado_ausente",
        "asistencia_ausente",
        "inasistencia",
        "no_asistio",
        "no_asistió",
        "ausencia_confirmada",
        "se_ausento",
        "se_ausentó",
    ]

    for campo in campos_booleanos:
        if hasattr(registro, campo):
            try:
                if bool(getattr(registro, campo)):
                    return True
            except Exception:
                pass

    campos_estado = [
        "estado",
        "estado_dia",
        "estado_asistencia",
        "tipo_asistencia",
    ]

    valores_ausente = {
        "ausente",
        "ausencia",
        "inasistencia",
        "no asistio",
        "no asistió",
        "no_asistio",
        "no_asistió",
    }

    for campo in campos_estado:
        if hasattr(registro, campo):
            valor = normalizar_texto(getattr(registro, campo, ""))
            if valor in valores_ausente:
                return True

    return False


def dia_operativo_tiene_operacion_ninos(dia_actual):
    """
    True únicamente cuando el día de la estancia ya fue iniciado por maestra
    o ya fue cerrado. Antes de abrir el día no se deben mostrar niñas/niños
    como dentro, fuera ni ausentes, porque aún no existe operación real.
    """
    return bool(
        dia_actual
        and dia_operativo_es_laborable(dia_actual)
        and getattr(dia_actual, "estado", "") in [
            DiaOperativoSemestre.EstadoDia.ABIERTO,
            DiaOperativoSemestre.EstadoDia.CERRADO,
        ]
    )


def parsear_hora_config_operacion(valor):
    """Convierte configuraciones tipo '09:30' o time a objeto time."""
    if not valor:
        return None

    if hasattr(valor, "hour") and hasattr(valor, "minute"):
        return valor

    valor = str(valor or "").strip()
    if not valor:
        return None

    for formato in ["%H:%M", "%H:%M:%S"]:
        try:
            return datetime.strptime(valor, formato).time()
        except Exception:
            continue

    return None


def obtener_hora_limite_entrada_operacion(dia_actual=None, registros_hoy=None, alumnos_qs=None):
    """
    Hora límite para que el panel convierta 'no pasó por código de entrada'
    en ausencia del día.

    Regla importante:
    - No se define una hora fija en código.
    - La hora debe salir de la configuración hecha por el Administrador
      en SalaSemestre.recepcion_fin.
    - Si no hay horario configurado, NO se activa el chequeo automático
      por hora mientras el día esté abierto. En ese caso solo cuentan
      ausencias explícitas, salidas reales e incidencias mayores con retiro.
    """
    sala_ids = set()

    if registros_hoy is not None:
        try:
            sala_ids.update(
                registros_hoy
                .exclude(sala_semestre_id__isnull=True)
                .values_list("sala_semestre_id", flat=True)
            )
        except Exception:
            try:
                sala_ids.update(
                    getattr(registro, "sala_semestre_id", None)
                    for registro in registros_hoy
                    if getattr(registro, "sala_semestre_id", None)
                )
            except Exception:
                pass

    if alumnos_qs is not None:
        try:
            sala_ids.update(
                alumnos_qs
                .exclude(sala_semestre_asignada_id__isnull=True)
                .values_list("sala_semestre_asignada_id", flat=True)
            )
        except Exception:
            try:
                sala_ids.update(
                    getattr(alumno, "sala_semestre_asignada_id", None)
                    for alumno in alumnos_qs
                    if getattr(alumno, "sala_semestre_asignada_id", None)
                )
            except Exception:
                pass

    if sala_ids:
        try:
            horas_recepcion = list(
                SalaSemestre.objects
                .filter(id__in=sala_ids)
                .exclude(recepcion_fin__isnull=True)
                .values_list("recepcion_fin", flat=True)
            )
            if horas_recepcion:
                # Se usa la hora más tarde configurada por el Administrador para
                # evitar marcar ausencias antes de que termine la recepción de
                # todas las salas consultadas por Dirección.
                return max(horas_recepcion)
        except Exception:
            pass

    return None


def chequeo_ausencias_activado(dia_actual=None, registros_hoy=None, alumnos_qs=None):
    """
    El chequeo automático de ausencias solo se activa cuando:
    - el día ya fue cerrado, o
    - la fecha del día operativo ya pasó, o
    - hoy ya superó la hora límite de entrada.
    Antes de esa hora, quien no ha entrado sigue como fuera/pendiente, no ausente.
    """
    if not dia_operativo_tiene_operacion_ninos(dia_actual):
        return False

    fecha_dia = getattr(dia_actual, "fecha", None)
    hoy = timezone.localdate()

    if getattr(dia_actual, "estado", "") == DiaOperativoSemestre.EstadoDia.CERRADO:
        return True

    if fecha_dia and fecha_dia < hoy:
        return True

    if fecha_dia and fecha_dia > hoy:
        return False

    hora_limite = obtener_hora_limite_entrada_operacion(
        dia_actual=dia_actual,
        registros_hoy=registros_hoy,
        alumnos_qs=alumnos_qs,
    )

    if not hora_limite:
        return False

    try:
        return timezone.localtime(timezone.now()).time() >= hora_limite
    except Exception:
        return False


def valores_nivel_incidencia_mayor():
    """Valores que representan incidencia mayor/alta en el modelo."""
    valores = {
        "ALTO",
        "ALTA",
        "MAYOR",
        "GRAVE",
        "URGENTE",
        "CRITICO",
        "CRÍTICO",
    }

    try:
        valores.add(Incidencia.NivelChoices.ALTO)
    except Exception:
        pass

    return list(valores)


def incidencia_indica_retiro_menor(incidencia):
    """
    Detecta de forma defensiva si una incidencia mayor implicó retiro del menor.
    Se apoya primero en campos booleanos si existen. Los textos solo se usan
    como respaldo para proyectos que todavía no tienen un campo específico.
    """
    if not incidencia:
        return False

    campos_booleanos = [
        "requiere_retiro",
        "retiro_del_menor",
        "menor_retirado",
        "retirado",
        "retiro_inmediato",
        "salida_por_incidencia",
        "requiere_salida",
        "traslado_medico",
        "canalizacion_urgente",
    ]

    for campo in campos_booleanos:
        if hasattr(incidencia, campo):
            try:
                if bool(getattr(incidencia, campo)):
                    return True
            except Exception:
                pass

    campos_texto = [
        "motivo_retiro",
        "motivo_salida",
        "observaciones_retiro",
        "resolucion",
        "intervencion_personal",
    ]
    palabras_retiro = ["retiro", "retirado", "retirada", "salida por incidencia", "se entrego", "se entregó"]

    for campo in campos_texto:
        if hasattr(incidencia, campo):
            valor = normalizar_texto(getattr(incidencia, campo, ""))
            if valor and any(palabra in valor for palabra in palabras_retiro):
                return True

    return False


def alumnos_retirados_por_incidencia_mayor(dia_actual=None, registros_lista=None, alumnos_ids=None):
    """
    Devuelve IDs de alumnos que tuvieron una incidencia mayor y fueron retirados.
    Una incidencia baja/leve no afecta la asistencia.
    """
    if not dia_actual:
        return set()

    alumnos_ids = set(alumnos_ids or [])
    registros_lista = list(registros_lista or [])
    alumnos_con_salida = {
        getattr(registro, "alumno_id", None)
        for registro in registros_lista
        if getattr(registro, "alumno_id", None) and getattr(registro, "salida_en", None)
    }

    try:
        qs = Incidencia.objects.filter(nivel__in=valores_nivel_incidencia_mayor())
    except Exception:
        return set()

    filtros_fecha = Q()
    tiene_filtro_fecha = False

    if modelo_tiene_campo(Incidencia, "dia_operativo"):
        filtros_fecha |= Q(dia_operativo=dia_actual)
        tiene_filtro_fecha = True

    if modelo_tiene_campo(Incidencia, "fecha_reporte") and getattr(dia_actual, "fecha", None):
        filtros_fecha |= Q(fecha_reporte__date=dia_actual.fecha)
        tiene_filtro_fecha = True

    if tiene_filtro_fecha:
        qs = qs.filter(filtros_fecha)

    if alumnos_ids:
        qs = qs.filter(alumno_id__in=alumnos_ids)

    try:
        qs = qs.select_related("registro_diario")
    except Exception:
        pass

    retirados = set()

    for incidencia in qs:
        alumno_id = getattr(incidencia, "alumno_id", None)
        if not alumno_id:
            continue

        registro_incidencia = getattr(incidencia, "registro_diario", None)
        tiene_salida_por_registro = bool(getattr(registro_incidencia, "salida_en", None))
        tiene_salida_del_dia = alumno_id in alumnos_con_salida

        if tiene_salida_por_registro or tiene_salida_del_dia or incidencia_indica_retiro_menor(incidencia):
            retirados.add(alumno_id)

    return retirados


def calcular_indicadores_ninos_operacion(total_ninos, registros_hoy=None, dia_actual=None, alumnos_qs=None):
    """
    Calcula los indicadores reales del panel directivo/supervisor.

    Reglas:
    - Antes de que una maestra inicie el día: 0 dentro, 0 ausentes y todos fuera.
    - En estancia: entrada registrada por código y sin salida.
    - Fuera de estancia: no ha entrado todavía o ya registró salida normal.
    - Ausente: ausencia explícita, sin entrada después del horario de recepción configurado,
      o retiro por incidencia mayor. Una incidencia baja/leve no cuenta como ausencia.
    """
    try:
        total_ninos = int(total_ninos or 0)
    except Exception:
        total_ninos = 0

    registros_hoy = registros_hoy or RegistroDiarioAlumno.objects.none()

    alumnos_ids = set()
    if alumnos_qs is not None:
        try:
            alumnos_ids = set(alumnos_qs.values_list("id", flat=True))
        except Exception:
            try:
                alumnos_ids = {getattr(alumno, "id", None) for alumno in alumnos_qs if getattr(alumno, "id", None)}
            except Exception:
                alumnos_ids = set()

    if alumnos_ids:
        total_ninos = len(alumnos_ids)

    operacion_iniciada = dia_operativo_tiene_operacion_ninos(dia_actual)
    hora_limite_entrada = obtener_hora_limite_entrada_operacion(
        dia_actual=dia_actual,
        registros_hoy=registros_hoy,
        alumnos_qs=alumnos_qs,
    ) if dia_actual else None

    if not operacion_iniciada:
        return {
            "total_ninos": total_ninos,
            "ninos_en_estancia": 0,
            "ninos_ausentes": 0,
            "ninos_fuera_estancia": total_ninos,
            "porcentaje_ninos_estancia": porcentaje_panel(0, total_ninos),
            "porcentaje_ninos_ausentes": porcentaje_panel(0, total_ninos),
            "porcentaje_ninos_fuera": porcentaje_panel(total_ninos, total_ninos),
            "operacion_diaria_iniciada": False,
            "chequeo_ausencias_activado": False,
            "hora_limite_entrada": hora_limite_entrada,
            "mensaje_operacion_ninos": (
                "El día operativo aún no ha sido iniciado por una maestra. "
                "Ningún niño está dentro ni ausente; los niños inscritos/asignados permanecen fuera de estancia hasta registrar entrada con código."
            ),
        }

    try:
        registros_lista = list(registros_hoy)
    except Exception:
        registros_lista = []

    if not alumnos_ids:
        alumnos_ids = {
            getattr(registro, "alumno_id", None)
            for registro in registros_lista
            if getattr(registro, "alumno_id", None)
        }
        if alumnos_ids:
            total_ninos = max(total_ninos, len(alumnos_ids))

    entrada_ids = {
        getattr(registro, "alumno_id", None)
        for registro in registros_lista
        if getattr(registro, "alumno_id", None) and getattr(registro, "entrada_en", None)
    }
    dentro_ids = {
        getattr(registro, "alumno_id", None)
        for registro in registros_lista
        if (
            getattr(registro, "alumno_id", None)
            and getattr(registro, "entrada_en", None)
            and not getattr(registro, "salida_en", None)
        )
    }
    ausentes_explicitos_ids = {
        getattr(registro, "alumno_id", None)
        for registro in registros_lista
        if getattr(registro, "alumno_id", None) and registro_diario_marcado_ausente(registro)
    }

    chequeo_activo = chequeo_ausencias_activado(
        dia_actual=dia_actual,
        registros_hoy=registros_hoy,
        alumnos_qs=alumnos_qs,
    )

    if chequeo_activo and alumnos_ids:
        sin_entrada_ids = alumnos_ids - entrada_ids
    elif chequeo_activo:
        sin_entrada_ids = {
            getattr(registro, "alumno_id", None)
            for registro in registros_lista
            if getattr(registro, "alumno_id", None) and not getattr(registro, "entrada_en", None)
        }
    else:
        sin_entrada_ids = set()

    retirados_por_incidencia_ids = alumnos_retirados_por_incidencia_mayor(
        dia_actual=dia_actual,
        registros_lista=registros_lista,
        alumnos_ids=alumnos_ids,
    )

    ausentes_ids = (
        ausentes_explicitos_ids
        | sin_entrada_ids
        | retirados_por_incidencia_ids
    )

    # Si por alguna captura contradictoria un menor aparece dentro, no debe
    # contarse simultáneamente como ausente.
    ausentes_ids = {alumno_id for alumno_id in ausentes_ids if alumno_id and alumno_id not in dentro_ids}
    dentro_ids = {alumno_id for alumno_id in dentro_ids if alumno_id and alumno_id not in ausentes_ids}

    ninos_en_estancia = len(dentro_ids)
    ninos_ausentes = len(ausentes_ids)
    ninos_fuera_estancia = max(total_ninos - ninos_en_estancia - ninos_ausentes, 0)

    return {
        "total_ninos": total_ninos,
        "ninos_en_estancia": ninos_en_estancia,
        "ninos_ausentes": ninos_ausentes,
        "ninos_fuera_estancia": ninos_fuera_estancia,
        "porcentaje_ninos_estancia": porcentaje_panel(ninos_en_estancia, total_ninos),
        "porcentaje_ninos_ausentes": porcentaje_panel(ninos_ausentes, total_ninos),
        "porcentaje_ninos_fuera": porcentaje_panel(ninos_fuera_estancia, total_ninos),
        "operacion_diaria_iniciada": True,
        "chequeo_ausencias_activado": chequeo_activo,
        "hora_limite_entrada": hora_limite_entrada,
        "mensaje_operacion_ninos": (
            "Operación diaria activa. Los conteos se calculan desde códigos de entrada/salida, "
            "chequeo de ausencias según el horario configurado e incidencias mayores con retiro."
        ),
    }


def construir_contexto_panel_directiva(request):
    semestres = Semestre.objects.order_by("-fecha_inicio")
    sedes = Sede.objects.order_by("nombre")

    semestre_activo = obtener_semestre_activo_operativo()
    semestre_id = request.GET.get("semestre_id") or request.GET.get("semestre")
    sede_id = request.GET.get("sede_id") or request.GET.get("sede")

    semestre_seleccionado = semestre_activo or semestres.first()
    if semestre_id:
        semestre_seleccionado = Semestre.objects.filter(pk=semestre_id).first() or semestre_seleccionado

    sede_seleccionada = None
    if sede_id:
        sede_seleccionada = Sede.objects.filter(pk=sede_id).first()
    elif semestre_seleccionado and getattr(semestre_seleccionado, "sede_configurada", None):
        sede_seleccionada = semestre_seleccionado.sede_configurada
    else:
        sede_seleccionada = sedes.first()

    modo_solo_consulta = not bool(
        semestre_activo
        and semestre_seleccionado
        and semestre_seleccionado.id == semestre_activo.id
    )

    alumnos_qs = (
        SolicitudInscripcion.objects
        .filter(estado="FINALIZADA")
        .select_related(
            "solicitud_ingreso",
            "semestre",
            "sala_semestre_asignada",
            "sala_semestre_asignada__sala",
        )
        .order_by("sala_semestre_asignada__sala__nombre", "solicitud_ingreso__apellido_paterno_menor", "solicitud_ingreso__nombres_menor")
    )
    alumnos_qs = qs_por_semestre_y_sede(alumnos_qs, semestre_seleccionado, sede_seleccionada)

    total_ninos = alumnos_qs.count()
    # Total de niñas/niños inscritos/asignados al semestre y sede consultados.
    # No debe confundirse con los niños que están físicamente dentro de la estancia.
    kpi_alumnos_total = total_ninos
    kpi_alumnos = 0

    dia_actual = None
    if semestre_seleccionado:
        dia_actual = DiaOperativoSemestre.objects.filter(
            semestre=semestre_seleccionado,
            fecha=timezone.localdate(),
        ).select_related("abierto_por", "cerrado_por").first()

    registros_hoy = RegistroDiarioAlumno.objects.none()
    if dia_actual:
        registros_hoy = RegistroDiarioAlumno.objects.filter(dia_operativo=dia_actual, alumno__in=alumnos_qs)

    indicadores_ninos = calcular_indicadores_ninos_operacion(
        total_ninos,
        registros_hoy=registros_hoy,
        dia_actual=dia_actual,
        alumnos_qs=alumnos_qs,
    )
    ninos_en_estancia = indicadores_ninos["ninos_en_estancia"]
    ninos_ausentes = indicadores_ninos["ninos_ausentes"]
    ninos_fuera_estancia = indicadores_ninos["ninos_fuera_estancia"]

    # Compatibilidad con el HTML actual de Dirección:
    # algunas tarjetas antiguas usan kpi_alumnos para la tarjeta "Niños en estancia".
    # Por eso este KPI operativo debe tomar el dato real del día, no el total de inscritos.
    kpi_alumnos = ninos_en_estancia

    porcentaje_ninos_estancia = indicadores_ninos["porcentaje_ninos_estancia"]
    porcentaje_ninos_ausentes = indicadores_ninos["porcentaje_ninos_ausentes"]
    porcentaje_ninos_fuera = indicadores_ninos["porcentaje_ninos_fuera"]

    salas_qs = SalaSemestre.objects.filter(activa=True)
    if semestre_seleccionado:
        salas_qs = salas_qs.filter(semestre=semestre_seleccionado)
    if sede_seleccionada:
        salas_qs = salas_qs.filter(sala__sede=sede_seleccionada)
    kpi_salas = salas_qs.count()

    dictamenes_pendientes = (
        SolicitudInscripcion.objects
        .filter(estado="ESPERANDO_DIRECTORA")
        .select_related("solicitud_ingreso", "usuario_tutor", "semestre")
        .order_by("-updated_at")
    )
    dictamenes_pendientes = qs_por_semestre_y_sede_o_sin_semestre(
        dictamenes_pendientes,
        semestre_seleccionado,
        sede_seleccionada,
    )

    # 2. Solicitudes en atención.
    # El HTML del panel directivo usa estas variables. Antes no se enviaban,
    # por eso las tarjetas marcaban 0 aunque sí existieran trámites.
    solicitudes_ingreso_atencion = (
        Solicitud.objects
        .filter(estado__in=[
            Solicitud.Estado.CAPTURA,
            Solicitud.Estado.RECIBIDA,
        ])
        .select_related()
        .order_by("-created_at")[:25]
    )

    solicitudes_inscripcion_atencion = (
        SolicitudInscripcion.objects
        .filter(estado__in=[
            "NUEVA",
            "EN_PROCESO",
            "DEVUELTA",
            "EN_REVISION",
            "FILTROS",
            "REVISION_FINAL_TS",
        ])
        .select_related("solicitud_ingreso", "usuario_tutor", "semestre")
        .order_by("-updated_at")
    )
    solicitudes_inscripcion_atencion = qs_por_semestre_y_sede_o_sin_semestre(
        solicitudes_inscripcion_atencion,
        semestre_seleccionado,
        sede_seleccionada,
    )[:25]

    expedientes_en_filtros = (
        SolicitudInscripcion.objects
        .filter(estado__in=["FILTROS", "REVISION_FINAL_TS"])
        .select_related("solicitud_ingreso", "semestre")
        .order_by("-updated_at")
    )
    expedientes_en_filtros = qs_por_semestre_y_sede_o_sin_semestre(
        expedientes_en_filtros,
        semestre_seleccionado,
        sede_seleccionada,
    )

    salas_en_revision = (
        SolicitudInscripcion.objects
        .filter(estado__in=["SALA_EN_REVISION", "SALA_RECHAZADA", "SALA_APROBADA", "FINALIZADA"])
        .select_related(
            "solicitud_ingreso",
            "semestre",
            "sala_semestre_asignada",
            "sala_semestre_asignada__sala",
        )
        .order_by("sala_semestre_asignada__sala__nombre", "solicitud_ingreso__apellido_paterno_menor")
    )
    salas_en_revision = qs_por_semestre_y_sede(salas_en_revision, semestre_seleccionado, sede_seleccionada)[:80]

    incidencias_base = obtener_incidencias_visibles_para_usuario(request.user)
    if semestre_seleccionado:
        incidencias_base = incidencias_base.filter(semestre=semestre_seleccionado)
    if sede_seleccionada:
        incidencias_base = incidencias_base.filter(semestre__sede_configurada=sede_seleccionada)

    incidencias_total = incidencias_base.count()
    incidencias_abiertas = incidencias_base.filter(estado=Incidencia.EstadoIncidencia.ABIERTA).count()
    incidencias_cerradas = incidencias_base.filter(estado=Incidencia.EstadoIncidencia.CERRADA).count()
    kpi_riesgo = incidencias_base.filter(nivel=Incidencia.NivelChoices.ALTO).count()
    incidencias_sin_seguimiento = incidencias_base.filter(seguimientos__isnull=True).distinct().count()

    def c(tipo, estado=None, nivel=None, con_seguimiento=False):
        qs = incidencias_base.filter(tipo=tipo)
        if estado:
            qs = qs.filter(estado=estado)
        if nivel:
            qs = qs.filter(nivel=nivel)
        if con_seguimiento:
            qs = qs.filter(seguimientos__isnull=False).distinct()
        return qs.count()

    total_dias = DiaOperativoSemestre.objects.filter(semestre=semestre_seleccionado).count() if semestre_seleccionado else 0
    dias_cerrados = DiaOperativoSemestre.objects.filter(semestre=semestre_seleccionado, estado=DiaOperativoSemestre.EstadoDia.CERRADO).count() if semestre_seleccionado else 0
    porcentaje_calendario = porcentaje_panel(dias_cerrados, total_dias)
    porcentaje_incidencias_cerradas = porcentaje_panel(incidencias_cerradas, incidencias_total)
    total_expedientes = SolicitudInscripcion.objects.filter(semestre=semestre_seleccionado).count() if semestre_seleccionado else SolicitudInscripcion.objects.count()
    porcentaje_finalizados = porcentaje_panel(total_ninos, total_expedientes)
    dias_pendientes = max(total_dias - dias_cerrados, 0)

    reportes_panel = [
        {
            "nombre": "Asistencia",
            "slug": "asistencia",
            "descripcion": "Porcentaje de niñas y niños presentes, ausentes y fuera de estancia.",
            "porcentaje": porcentaje_ninos_estancia,
        },
        {
            "nombre": "Incidencias cerradas",
            "slug": "incidencias",
            "descripcion": "Avance de incidencias cerradas contra el total registrado.",
            "porcentaje": porcentaje_incidencias_cerradas,
        },
        {
            "nombre": "Expedientes finalizados",
            "slug": "expedientes",
            "descripcion": "Inscripciones finalizadas respecto al total de expedientes del semestre.",
            "porcentaje": porcentaje_finalizados,
        },
        {
            "nombre": "Calendario operativo",
            "slug": "calendario",
            "descripcion": "Días cerrados o concluidos dentro del calendario operativo.",
            "porcentaje": porcentaje_calendario,
        },
    ]

    contexto = {
        "semestres": semestres,
        "sedes": sedes,
        "semestre_seleccionado": semestre_seleccionado,
        "semestre_activo_operativo": semestre_activo,
        "sede_seleccionada": sede_seleccionada,
        "modo_solo_consulta": modo_solo_consulta,
        "kpi_alumnos": kpi_alumnos,
        "kpi_alumnos_total": kpi_alumnos_total,
        "kpi_ninos_estancia": ninos_en_estancia,
        "total_ninos_asignados": total_ninos,
        "total_ninos_inscritos": total_ninos,
        "ninos_entregados": ninos_fuera_estancia,
        "kpi_pendientes": dictamenes_pendientes.count(),
        "kpi_riesgo": kpi_riesgo,
        "kpi_salas": kpi_salas,
        "total_ninos": total_ninos,
        "ninos_en_estancia": ninos_en_estancia,
        "ninos_ausentes": ninos_ausentes,
        "ninos_fuera_estancia": ninos_fuera_estancia,
        "porcentaje_ninos_estancia": porcentaje_ninos_estancia,
        "porcentaje_ninos_ausentes": porcentaje_ninos_ausentes,
        "porcentaje_ninos_fuera": porcentaje_ninos_fuera,
        "operacion_diaria_iniciada": indicadores_ninos.get("operacion_diaria_iniciada", False),
        "chequeo_ausencias_activado": indicadores_ninos.get("chequeo_ausencias_activado", False),
        "hora_limite_entrada": indicadores_ninos.get("hora_limite_entrada"),
        "mensaje_operacion_ninos": indicadores_ninos.get("mensaje_operacion_ninos", ""),
        "porcentaje_calendario": porcentaje_calendario,
        "porcentaje_incidencias_cerradas": porcentaje_incidencias_cerradas,
        "porcentaje_finalizados": porcentaje_finalizados,
        "total_dias_operativos": total_dias,
        "dias_cerrados_operativos": dias_cerrados,
        "dias_pendientes_operativos": dias_pendientes,
        "total_expedientes": total_expedientes,
        "dictamenes_pendientes": dictamenes_pendientes,
        "solicitudes_ingreso_atencion": solicitudes_ingreso_atencion,
        "solicitudes_ingreso_en_atencion": solicitudes_ingreso_atencion,
        "solicitudes_inscripcion_atencion": solicitudes_inscripcion_atencion,
        "solicitudes_inscripcion_en_atencion": solicitudes_inscripcion_atencion,
        "salas_en_revision": salas_en_revision,
        "expedientes_en_filtros": expedientes_en_filtros,
        "mensajes_aspirantes": [],
        "mensajes_alumnos": [],
        "incidencias_total": incidencias_total,
        "incidencias_abiertas": incidencias_abiertas,
        "incidencias_cerradas": incidencias_cerradas,
        "incidencias_sin_seguimiento": incidencias_sin_seguimiento,
        "inc_medica_abiertas": c(Incidencia.TipoIncidencia.MEDICA, Incidencia.EstadoIncidencia.ABIERTA),
        "inc_medica_seguimiento": c(Incidencia.TipoIncidencia.MEDICA, con_seguimiento=True),
        "inc_medica_cerradas": c(Incidencia.TipoIncidencia.MEDICA, Incidencia.EstadoIncidencia.CERRADA),
        "inc_medica_alto": c(Incidencia.TipoIncidencia.MEDICA, nivel=Incidencia.NivelChoices.ALTO),
        "inc_nutricional_abiertas": c(Incidencia.TipoIncidencia.NUTRICIONAL, Incidencia.EstadoIncidencia.ABIERTA),
        "inc_nutricional_seguimiento": c(Incidencia.TipoIncidencia.NUTRICIONAL, con_seguimiento=True),
        "inc_nutricional_cerradas": c(Incidencia.TipoIncidencia.NUTRICIONAL, Incidencia.EstadoIncidencia.CERRADA),
        "inc_nutricional_alto": c(Incidencia.TipoIncidencia.NUTRICIONAL, nivel=Incidencia.NivelChoices.ALTO),
        "inc_psicologica_abiertas": c(Incidencia.TipoIncidencia.PSICOLOGICA, Incidencia.EstadoIncidencia.ABIERTA),
        "inc_psicologica_seguimiento": c(Incidencia.TipoIncidencia.PSICOLOGICA, con_seguimiento=True),
        "inc_psicologica_cerradas": c(Incidencia.TipoIncidencia.PSICOLOGICA, Incidencia.EstadoIncidencia.CERRADA),
        "inc_psicologica_alto": c(Incidencia.TipoIncidencia.PSICOLOGICA, nivel=Incidencia.NivelChoices.ALTO),
        "inc_pedagogica_abiertas": c(Incidencia.TipoIncidencia.PEDAGOGICA, Incidencia.EstadoIncidencia.ABIERTA),
        "inc_pedagogica_seguimiento": c(Incidencia.TipoIncidencia.PEDAGOGICA, con_seguimiento=True),
        "inc_pedagogica_cerradas": c(Incidencia.TipoIncidencia.PEDAGOGICA, Incidencia.EstadoIncidencia.CERRADA),
        "inc_pedagogica_alto": c(Incidencia.TipoIncidencia.PEDAGOGICA, nivel=Incidencia.NivelChoices.ALTO),
        "sedes_panel": preparar_sedes_panel(semestre_seleccionado),
        "alumnos_panel": preparar_alumnos_panel(alumnos_qs, dia_actual),
        "actividades_panel": preparar_actividades_panel(semestre_seleccionado),
        "reportes_panel": reportes_panel,
        "calendario_dias_panel": preparar_calendario_panel(semestre_seleccionado),
        "calendario_panel": preparar_calendario_panel(semestre_seleccionado),
        "personal_panel": preparar_personal_panel(semestre_seleccionado),
    }

    reporte_solicitado = request.GET.get("reporte")
    if reporte_solicitado:
        contexto["reporte_actual"] = datos_reporte_directiva(reporte_solicitado, contexto)

    contexto.update(contexto_semestre_operativo())
    contexto.update(contexto_suplencias_direccion(request.user, request=request))
    contexto["modo_solo_consulta"] = modo_solo_consulta
    contexto["semestre_activo_operativo"] = semestre_activo
    return contexto


def procesar_foto_perfil_directiva(request, accion_directiva=None):
    """
    Guarda o elimina la foto de perfil de Dirección desde el panel directivo.

    Validaciones para proteger el servidor:
    - Solo JPG, JPEG, PNG o WEBP.
    - Tamaño máximo 3 MB.
    - Usa el campo real de imagen del modelo Usuario si existe.
    """
    accion_directiva = (accion_directiva or request.POST.get("accion_directiva") or "").strip()
    destino = f"{request.path}?seccion=configuracion"
    campo_foto = obtener_campo_foto_perfil_usuario(request.user)

    if not campo_foto:
        messages.warning(
            request,
            "No se pudo guardar la foto porque el modelo de usuario todavía no tiene un campo de imagen. "
            "Agrega un campo ImageField/FileField llamado foto_perfil en usuarios/models.py."
        )
        return redirect(destino)

    if accion_directiva == "eliminar_foto_perfil":
        archivo_actual = getattr(request.user, campo_foto, None)

        try:
            if archivo_actual:
                archivo_actual.delete(save=False)
        except Exception:
            pass

        setattr(request.user, campo_foto, None)
        try:
            request.user.save(update_fields=[campo_foto])
        except Exception:
            request.user.save()

        messages.success(request, "Foto de perfil eliminada correctamente.")
        return redirect(destino)

    if accion_directiva == "actualizar_foto_perfil":
        archivo = (
            request.FILES.get("foto_perfil")
            or request.FILES.get("foto_perfil_directora")
            or request.FILES.get("foto_perfil_maestra")
        )

        if not archivo:
            messages.error(request, "Selecciona una imagen antes de guardar la foto de perfil.")
            return redirect(destino)

        extension = os.path.splitext(getattr(archivo, "name", ""))[1].lower()
        extensiones_permitidas = {".jpg", ".jpeg", ".png", ".webp"}

        if extension not in extensiones_permitidas:
            messages.error(request, "Formato no permitido. Usa JPG, JPEG, PNG o WEBP.")
            return redirect(destino)

        max_bytes = 3 * 1024 * 1024
        if getattr(archivo, "size", 0) > max_bytes:
            peso_mb = round(archivo.size / (1024 * 1024), 2)
            messages.error(
                request,
                f"La foto pesa {peso_mb} MB. El máximo permitido es 3 MB para no cargar el sistema ni el servidor."
            )
            return redirect(destino)

        if getattr(archivo, "size", 0) <= 0:
            messages.error(request, "El archivo está vacío. Selecciona una imagen válida.")
            return redirect(destino)

        setattr(request.user, campo_foto, archivo)
        try:
            request.user.save(update_fields=[campo_foto])
        except Exception:
            request.user.save()

        messages.success(request, "Foto de perfil actualizada correctamente.")
        return redirect(destino)

    messages.warning(request, "Acción de foto de perfil no válida.")
    return redirect(destino)


def servir_reporte_final_directiva_seguro(request, modo="inline"):
    """
    Abre o descarga el Reporte Final de Ingreso desde una acción protegida
    del panel de Dirección.

    Seguridad:
    - No expone la URL pública del archivo en /media/.
    - Solo Dirección/Admin puede entrar porque panel_directiva valida el rol antes.
    - Solo atiende expedientes que realmente están esperando veredicto de Dirección.
    - Si el PDF falta, intenta regenerarlo desde backend y lo sirve con FileResponse.
    """
    inscripcion_id = (request.POST.get("inscripcion_id") or request.GET.get("inscripcion_id") or "").strip()

    if not inscripcion_id:
        return HttpResponse("No se recibió el expediente solicitado.", status=400)

    inscripcion = get_object_or_404(
        SolicitudInscripcion.objects.select_related("solicitud_ingreso", "usuario_tutor", "semestre"),
        pk=inscripcion_id,
        estado="ESPERANDO_DIRECTORA",
    )

    if not getattr(inscripcion, "reporte_final_pdf", None):
        pdf_generado, mensaje_pdf = guardar_pdf_reporte_final_en_inscripcion(inscripcion)
        if not pdf_generado:
            return HttpResponse(
                f"No se pudo preparar el Reporte Final de Ingreso: {escape(mensaje_pdf)}",
                status=404,
            )

    try:
        ruta_pdf = inscripcion.reporte_final_pdf.path
    except Exception:
        ruta_pdf = ""

    if not ruta_pdf or not os.path.exists(ruta_pdf):
        pdf_generado, mensaje_pdf = guardar_pdf_reporte_final_en_inscripcion(inscripcion)
        if not pdf_generado:
            return HttpResponse(
                f"El Reporte Final de Ingreso no está disponible: {escape(mensaje_pdf)}",
                status=404,
            )
        ruta_pdf = inscripcion.reporte_final_pdf.path

    ruta_pdf_abs = os.path.abspath(ruta_pdf)
    media_root_abs = os.path.abspath(getattr(settings, "MEDIA_ROOT", ""))

    if media_root_abs and not ruta_pdf_abs.startswith(media_root_abs + os.sep):
        return HttpResponseForbidden("El archivo solicitado no pertenece al repositorio permitido.")

    folio = getattr(inscripcion.solicitud_ingreso, "folio", None) or inscripcion.id
    nombre_archivo = f"reporte_final_ingreso_folio_{folio}.pdf"
    disposition = "attachment" if modo == "attachment" else "inline"

    respuesta = FileResponse(open(ruta_pdf_abs, "rb"), content_type="application/pdf")
    respuesta["Content-Disposition"] = f'{disposition}; filename="{nombre_archivo}"'
    respuesta["X-Content-Type-Options"] = "nosniff"
    return respuesta


@login_required
def panel_directiva(request):
    """
    Dashboard de Dirección con datos reales.
    Esta vista alimenta templates/portal/home_directiva.html.

    También procesa, sin crear HTML nuevo:
    - Pase de lista del personal.
    - Autorizaciones de suplencia.
    - Cancelación de suplencias.
    - Validación de movimientos por suplencia.
    """
    if not (usuario_es_directora(request.user) or usuario_es_admin(request.user)):
        messages.error(request, "No tienes permiso para entrar al panel directivo.")
        return redirect("/")

    if request.method == "POST":
        accion_directiva = (request.POST.get("accion_directiva") or "").strip()

        if accion_directiva == "ver_reporte_final_formulario":
            return servir_reporte_final_directiva_seguro(request, modo="inline")

        if accion_directiva == "descargar_reporte_final_pdf":
            return servir_reporte_final_directiva_seguro(request, modo="attachment")

        if accion_directiva in ["actualizar_foto_perfil", "eliminar_foto_perfil"]:
            return procesar_foto_perfil_directiva(request, accion_directiva)

        if accion_directiva == "guardar_pase_lista":
            semestre = obtener_semestre_activo_operativo()
            personal = list(personal_operativo_pase_lista_queryset())
            form = PaseListaPersonalForm(
                request.POST,
                usuario=request.user,
                semestre=semestre,
                fecha=timezone.localdate(),
                personal=personal,
            )

            if form.is_valid():
                form.guardar()
                messages.success(request, "Pase de lista del personal guardado correctamente.")
            else:
                messages.error(request, "No se pudo guardar el pase de lista. Revisa los estados del personal.")
                for campo, errores in form.errors.items():
                    for error in errores:
                        messages.error(request, f"{campo}: {error}")

            return redirect(f"{request.path}?seccion=suplencias")

        if accion_directiva == "crear_suplencia":
            semestre = obtener_semestre_activo_operativo()
            asistencia_id = request.POST.get("asistencia_personal_id") or request.POST.get("asistencia_id")
            asistencia = None

            if asistencia_id:
                asistencia = AsistenciaPersonal.objects.filter(pk=asistencia_id).select_related("trabajador").first()

            form = AutorizacionSuplenciaForm(
                request.POST,
                usuario=request.user,
                semestre=semestre,
                fecha=timezone.localdate(),
                asistencia_personal=asistencia,
            )

            if form.is_valid():
                try:
                    autorizacion = form.save()
                    messages.success(
                        request,
                        f"Suplencia autorizada correctamente: {autorizacion.suplente_nombre} cubrirá {autorizacion.get_area_cubierta_display()}."
                    )
                except ValidationError as exc:
                    messages.error(request, exc)
                except Exception as exc:
                    messages.error(request, f"No se pudo crear la suplencia: {exc}")
            else:
                messages.error(request, "No se pudo crear la suplencia. Revisa los datos.")
                for campo, errores in form.errors.items():
                    for error in errores:
                        messages.error(request, f"{campo}: {error}")

            return redirect(f"{request.path}?seccion=suplencias")

        if accion_directiva == "cancelar_suplencia":
            autorizacion_id = request.POST.get("autorizacion_id") or request.POST.get("suplencia_id")
            autorizacion = get_object_or_404(AutorizacionSuplencia, pk=autorizacion_id)
            form = CancelarSuplenciaForm(
                request.POST,
                autorizacion=autorizacion,
                usuario=request.user,
            )

            if form.is_valid():
                ok, errores = form.cancelar()
                if ok:
                    messages.success(request, "Suplencia cancelada correctamente.")
                else:
                    for error in errores:
                        messages.error(request, error)
            else:
                messages.error(request, "No se pudo cancelar la suplencia.")
                for campo, errores in form.errors.items():
                    for error in errores:
                        messages.error(request, f"{campo}: {error}")

            return redirect(f"{request.path}?seccion=suplencias")

        if accion_directiva == "validar_movimiento_suplencia":
            movimiento_id = request.POST.get("movimiento_id")
            movimiento = get_object_or_404(MovimientoSuplencia, pk=movimiento_id)
            form = RevisionMovimientoSuplenciaForm(
                request.POST,
                instance=movimiento,
                usuario=request.user,
            )

            if form.is_valid():
                form.save()
                messages.success(request, "Movimiento de suplencia actualizado correctamente.")
            else:
                messages.error(request, "No se pudo actualizar el movimiento.")
                for campo, errores in form.errors.items():
                    for error in errores:
                        messages.error(request, f"{campo}: {error}")

            return redirect(f"{request.path}?seccion=suplencias")

        if accion_directiva == "crear_evento_calendario":
            contexto_temporal = construir_contexto_panel_directiva(request)
            semestre = contexto_temporal.get("semestre_seleccionado") or obtener_semestre_activo_operativo()

            if contexto_temporal.get("modo_solo_consulta"):
                messages.warning(request, "No se pueden agregar fechas cuando el semestre está en modo solo consulta.")
                return redirect(f"{request.path}?seccion=calendario")

            ok, mensajes_calendario, evento_calendario = crear_evento_calendario_directiva(
                semestre,
                request.POST.copy(),
                usuario=request.user,
            )

            if ok:
                tipo_evento = (request.POST.get("tipo") or getattr(evento_calendario, "tipo", "") or "Evento").strip()
                if tipo_calendario_es_inhabil(tipo_evento) and semestre and semestre.dias_operativos.exists():
                    semestre.generar_dias_operativos()

                for mensaje in mensajes_calendario:
                    messages.success(request, mensaje)
            else:
                messages.error(request, "No se pudo guardar la fecha. Revisa los datos capturados.")
                for error in mensajes_calendario:
                    messages.error(request, error)

            return redirect(f"{request.path}?seccion=calendario")

    contexto = construir_contexto_panel_directiva(request)

    descarga = generar_reporte_directiva(
        request,
        request.GET.get("reporte"),
        request.GET.get("formato"),
        contexto,
    )
    if descarga:
        return descarga

    return render(request, "portal/home_directiva.html", contexto)


@login_required
@require_http_methods(["POST"])
def registrar_asistencia_personal(request):
    """
    Vista opcional para urls.py. Guarda el pase de lista y regresa al panel
    directivo. No requiere HTML nuevo.
    """
    if not (usuario_es_directora(request.user) or usuario_es_admin(request.user)):
        messages.error(request, "Solo Dirección puede registrar el pase de lista del personal.")
        return redirect("/")

    semestre = obtener_semestre_activo_operativo()
    personal = list(personal_operativo_pase_lista_queryset())
    form = PaseListaPersonalForm(
        request.POST,
        usuario=request.user,
        semestre=semestre,
        fecha=timezone.localdate(),
        personal=personal,
    )

    if form.is_valid():
        form.guardar()
        messages.success(request, "Pase de lista del personal guardado correctamente.")
    else:
        messages.error(request, "No se pudo guardar el pase de lista. Revisa los estados capturados.")
        for campo, errores in form.errors.items():
            for error in errores:
                messages.error(request, f"{campo}: {error}")

    return redirect(f"{reverse('panel_directiva')}?seccion=suplencias")


@login_required
@require_http_methods(["POST"])
def crear_suplencia(request):
    """
    Vista opcional para urls.py. Dirección crea la autorización de suplencia
    desde el mismo panel directivo.
    """
    if not (usuario_es_directora(request.user) or usuario_es_admin(request.user)):
        messages.error(request, "Solo Dirección puede autorizar suplencias.")
        return redirect("/")

    semestre = obtener_semestre_activo_operativo()
    asistencia_id = request.POST.get("asistencia_personal_id") or request.POST.get("asistencia_id")
    asistencia = None

    if asistencia_id:
        asistencia = AsistenciaPersonal.objects.filter(pk=asistencia_id).select_related("trabajador").first()

    form = AutorizacionSuplenciaForm(
        request.POST,
        usuario=request.user,
        semestre=semestre,
        fecha=timezone.localdate(),
        asistencia_personal=asistencia,
    )

    if form.is_valid():
        try:
            autorizacion = form.save()
            messages.success(
                request,
                f"Suplencia autorizada correctamente: {autorizacion.suplente_nombre} cubrirá {autorizacion.get_area_cubierta_display()}."
            )
        except Exception as exc:
            messages.error(request, f"No se pudo crear la suplencia: {exc}")
    else:
        messages.error(request, "No se pudo crear la suplencia. Revisa los datos.")
        for campo, errores in form.errors.items():
            for error in errores:
                messages.error(request, f"{campo}: {error}")

    return redirect(f"{reverse('panel_directiva')}?seccion=suplencias")


@login_required
@require_http_methods(["POST"])
def cancelar_suplencia(request, autorizacion_id):
    if not (usuario_es_directora(request.user) or usuario_es_admin(request.user)):
        messages.error(request, "Solo Dirección puede cancelar suplencias.")
        return redirect("/")

    autorizacion = get_object_or_404(AutorizacionSuplencia, pk=autorizacion_id)
    form = CancelarSuplenciaForm(
        request.POST,
        autorizacion=autorizacion,
        usuario=request.user,
    )

    if form.is_valid():
        ok, errores = form.cancelar()
        if ok:
            messages.success(request, "Suplencia cancelada correctamente.")
        else:
            for error in errores:
                messages.error(request, error)
    else:
        messages.error(request, "No se pudo cancelar la suplencia.")
        for campo, errores in form.errors.items():
            for error in errores:
                messages.error(request, f"{campo}: {error}")

    return redirect(f"{reverse('panel_directiva')}?seccion=suplencias")


@login_required
def bitacora_suplencias(request):
    """
    Consulta de movimientos por suplencia.

    Dirección y Supervisora pueden consultar. Supervisora solo ve y reporta.
    """
    if not (usuario_es_directora(request.user) or usuario_es_admin(request.user) or usuario_es_supervisora_general(request.user)):
        messages.error(request, "No tienes permiso para consultar la bitácora de suplencias.")
        return redirect("/")

    if usuario_es_supervisora_general(request.user):
        contexto = construir_contexto_panel_supervisor(request)
        contexto.update(contexto_bitacora_suplencias(request, limite=200))
        return render(request, "admisiones/supervisor/panel_supervisor.html", contexto)

    contexto = construir_contexto_panel_directiva(request)
    contexto.update(contexto_bitacora_suplencias(request, limite=200))
    contexto["reporte_actual"] = {
        "titulo": "Bitácora de suplencias",
        "descripcion": "Movimientos realizados mediante autorizaciones temporales.",
    }
    return render(request, "portal/home_directiva.html", contexto)


@login_required
@require_http_methods(["POST"])
def validar_movimiento_suplencia(request, movimiento_id):
    movimiento = get_object_or_404(MovimientoSuplencia, pk=movimiento_id)
    form = RevisionMovimientoSuplenciaForm(
        request.POST,
        instance=movimiento,
        usuario=request.user,
    )

    if form.is_valid():
        form.save()
        messages.success(request, "Movimiento de suplencia revisado correctamente.")
    else:
        messages.error(request, "No se pudo revisar el movimiento de suplencia.")
        for campo, errores in form.errors.items():
            for error in errores:
                messages.error(request, f"{campo}: {error}")

    siguiente = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("panel_directiva")
    return redirect(siguiente)


@login_required
@require_http_methods(["POST"])
def revisar_incidencia_suplencia(request, incidencia_id):
    incidencia = get_object_or_404(Incidencia, pk=incidencia_id)
    form = RevisarIncidenciaSuplenciaForm(
        request.POST,
        incidencia=incidencia,
        usuario=request.user,
    )

    if form.is_valid():
        ok, errores = form.revisar()
        if ok:
            registrar_movimiento_incidencia_suplencia(
                incidencia,
                incidencia.autorizacion_suplencia,
                request.user,
                accion=MovimientoSuplencia.TipoAccion.VALIDACION_TITULAR,
                descripcion="Incidencia registrada por suplencia revisada por el área titular.",
            )
            messages.success(request, "Incidencia revisada correctamente por el área titular.")
        else:
            for error in errores:
                messages.error(request, error)
    else:
        messages.error(request, "No se pudo revisar la incidencia.")
        for campo, errores in form.errors.items():
            for error in errores:
                messages.error(request, f"{campo}: {error}")

    return redirect("detalle_incidencia", incidencia_id=incidencia.id)


@login_required
@require_http_methods(["POST"])
def revisar_trabajo_social_suplencia(request, inscripcion_id):
    inscripcion = get_object_or_404(SolicitudInscripcion, pk=inscripcion_id)
    autorizacion = getattr(inscripcion, "trabajo_social_autorizacion_suplencia", None)

    form = RevisarTrabajoSocialSuplenciaForm(
        request.POST,
        inscripcion=inscripcion,
        usuario=request.user,
        autorizacion_suplencia=autorizacion,
    )

    if form.is_valid():
        ok, errores = form.revisar()
        if ok:
            registrar_movimiento_suplencia(
                autorizacion=autorizacion,
                usuario=request.user,
                accion=MovimientoSuplencia.TipoAccion.VALIDACION_TITULAR,
                descripcion="Proceso de Trabajo Social realizado por suplencia revisado por titular.",
                solicitud=inscripcion.solicitud_ingreso,
                inscripcion=inscripcion,
                objeto=inscripcion,
                estado=MovimientoSuplencia.EstadoMovimiento.VALIDADO,
            )
            messages.success(request, "Proceso de Trabajo Social revisado correctamente.")
        else:
            for error in errores:
                messages.error(request, error)
    else:
        messages.error(request, "No se pudo revisar el proceso de Trabajo Social.")
        for campo, errores in form.errors.items():
            for error in errores:
                messages.error(request, f"{campo}: {error}")

    siguiente = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("panel_admisiones")
    return redirect(siguiente)

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

    # Coordinadora de Sala no debe caer al panel general tipo Admin/Directora.
    # Si entra desde un enlace a panel_incidencias con tipo pedagógico, se le
    # muestra su dashboard operativo con filtros reales de sus incidencias.
    if (
        usuario_es_coordinadora_sala(request.user)
        and not usuario_es_admin(request.user)
        and not usuario_es_directora(request.user)
    ):
        tipo_get = normalizar_tipo_incidencia_param(request.GET.get("tipo"))
        if not tipo_get or tipo_get == Incidencia.TipoIncidencia.PEDAGOGICA:
            return dashboard_coordinadora(request)

    tipos_visibles = tipos_incidencia_usuario(request.user, para_crear=False)
    tipos_creables = tipos_incidencia_usuario(request.user, para_crear=True)
    es_admin_actual = usuario_es_admin(request.user)
    es_directora_actual = usuario_es_directora(request.user)
    tipo_unico_operativo = tipo_incidencia_unico_usuario(request.user)

    incidencias_base = obtener_incidencias_visibles_para_usuario(request.user)

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

    # Base para tarjetas por área: respeta estado, riesgo, semestre y búsqueda,
    # pero NO aplica tipo para que cada tarjeta pueda contar su categoría real.
    incidencias_para_tarjetas = incidencias_base

    if estado in ["ABIERTA", "CERRADA"]:
        incidencias_para_tarjetas = incidencias_para_tarjetas.filter(estado=estado)

    if nivel in ["LEVE", "MEDIO", "ALTO", "BAJO"]:
        incidencias_para_tarjetas = incidencias_para_tarjetas.filter(nivel=nivel)

    if semestre_id:
        incidencias_para_tarjetas = incidencias_para_tarjetas.filter(semestre_id=semestre_id)

    if q:
        incidencias_para_tarjetas = incidencias_para_tarjetas.filter(
            Q(descripcion__icontains=q)
            | Q(intervencion_personal__icontains=q)
            | Q(resolucion__icontains=q)
            | Q(alumno__solicitud_ingreso__nombres_menor__icontains=q)
            | Q(alumno__solicitud_ingreso__apellido_paterno_menor__icontains=q)
            | Q(alumno__solicitud_ingreso__apellido_materno_menor__icontains=q)
            | Q(sala_semestre__sala__nombre__icontains=q)
        )

    incidencias = incidencias_para_tarjetas
    if tipo:
        incidencias = incidencias.filter(tipo=tipo)

    resumen = {
        "total": incidencias.count(),
        "abiertas": incidencias.filter(estado=Incidencia.EstadoIncidencia.ABIERTA).count(),
        "cerradas": incidencias.filter(estado=Incidencia.EstadoIncidencia.CERRADA).count(),
        "alto": incidencias.filter(nivel=Incidencia.NivelChoices.ALTO).count(),
        "sin_seguimiento": incidencias.filter(seguimientos__isnull=True).distinct().count(),
    }

    def contar_area(tipo_area, estado_area=None, nivel_area=None, con_seguimiento=False):
        qs = incidencias_para_tarjetas.filter(tipo=tipo_area)
        if estado_area:
            qs = qs.filter(estado=estado_area)
        if nivel_area:
            qs = qs.filter(nivel=nivel_area)
        if con_seguimiento:
            qs = qs.filter(seguimientos__isnull=False).distinct()
        return qs.count()

    incidencias = incidencias.annotate(
        total_seguimientos=Count("seguimientos", distinct=True)
    )

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
            "inc_medica_abiertas": contar_area(Incidencia.TipoIncidencia.MEDICA, Incidencia.EstadoIncidencia.ABIERTA),
            "inc_medica_seguimiento": contar_area(Incidencia.TipoIncidencia.MEDICA, con_seguimiento=True),
            "inc_medica_cerradas": contar_area(Incidencia.TipoIncidencia.MEDICA, Incidencia.EstadoIncidencia.CERRADA),
            "inc_medica_alto": contar_area(Incidencia.TipoIncidencia.MEDICA, nivel_area=Incidencia.NivelChoices.ALTO),
            "inc_nutricional_abiertas": contar_area(Incidencia.TipoIncidencia.NUTRICIONAL, Incidencia.EstadoIncidencia.ABIERTA),
            "inc_nutricional_seguimiento": contar_area(Incidencia.TipoIncidencia.NUTRICIONAL, con_seguimiento=True),
            "inc_nutricional_cerradas": contar_area(Incidencia.TipoIncidencia.NUTRICIONAL, Incidencia.EstadoIncidencia.CERRADA),
            "inc_nutricional_alto": contar_area(Incidencia.TipoIncidencia.NUTRICIONAL, nivel_area=Incidencia.NivelChoices.ALTO),
            "inc_psicologica_abiertas": contar_area(Incidencia.TipoIncidencia.PSICOLOGICA, Incidencia.EstadoIncidencia.ABIERTA),
            "inc_psicologica_seguimiento": contar_area(Incidencia.TipoIncidencia.PSICOLOGICA, con_seguimiento=True),
            "inc_psicologica_cerradas": contar_area(Incidencia.TipoIncidencia.PSICOLOGICA, Incidencia.EstadoIncidencia.CERRADA),
            "inc_psicologica_alto": contar_area(Incidencia.TipoIncidencia.PSICOLOGICA, nivel_area=Incidencia.NivelChoices.ALTO),
            "inc_pedagogica_abiertas": contar_area(Incidencia.TipoIncidencia.PEDAGOGICA, Incidencia.EstadoIncidencia.ABIERTA),
            "inc_pedagogica_seguimiento": contar_area(Incidencia.TipoIncidencia.PEDAGOGICA, con_seguimiento=True),
            "inc_pedagogica_cerradas": contar_area(Incidencia.TipoIncidencia.PEDAGOGICA, Incidencia.EstadoIncidencia.CERRADA),
            "inc_pedagogica_alto": contar_area(Incidencia.TipoIncidencia.PEDAGOGICA, nivel_area=Incidencia.NivelChoices.ALTO),
            "puede_crear_alguna": bool(tipos_creables),
            "es_directora": es_directora_actual,
            "es_admin": es_admin_actual,
            **contexto_suplencias_usuario(request.user),
            **contexto_semestre_operativo(),
        },
    )

@login_required
def crear_incidencia(request, tipo=None):
    """
    Crea incidencia por tipo.

    Cambios principales:
    - El tipo se fija por el rol/área del usuario.
    - Para Coordinadora de Sala queda forzado a Pedagógica.
    - El registro diario se vincula automáticamente por alumno y fecha actual.
    - Si no existe registro diario del día, la incidencia se guarda con alumno,
      semestre y sala asignada, sin mostrar fijo el nombre de otro menor.
    - Los adjuntos se validan también en backend.
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
    dia_operativo_actual = obtener_dia_operativo_actual_incidencias(semestre)
    fecha_operativa_actual = getattr(dia_operativo_actual, "fecha", None) or timezone.localdate()

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
        else:
            # Si el usuario seleccionó un alumno y no seleccionó registro diario,
            # se intenta vincular el registro del día actual automáticamente.
            alumno_id = post_data.get("alumno")
            if alumno_id and not post_data.get("registro_diario"):
                alumno_post = (
                    SolicitudInscripcion.objects
                    .filter(pk=alumno_id, estado="FINALIZADA")
                    .select_related("solicitud_ingreso", "semestre", "sala_semestre_asignada", "sala_semestre_asignada__sala")
                    .first()
                )
                registro_auto = obtener_registro_diario_actual_para_alumno(alumno_post, semestre=semestre)
                if registro_auto:
                    post_data["registro_diario"] = str(registro_auto.id)

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

            autorizacion_suplencia = obtener_suplencia_activa_para_tipo_incidencia(request.user, tipo_forzado)
            if autorizacion_suplencia:
                incidencia = aplicar_suplencia_a_incidencia(incidencia, autorizacion_suplencia)

            registro_limpio = form.cleaned_data.get("registro_diario")
            alumno_limpio = form.cleaned_data.get("alumno")

            if registro_limpio:
                incidencia.registro_diario = registro_limpio
                incidencia.alumno = registro_limpio.alumno
                incidencia.dia_operativo = registro_limpio.dia_operativo
                incidencia.sala_semestre = registro_limpio.sala_semestre
                incidencia.semestre = registro_limpio.dia_operativo.semestre if registro_limpio.dia_operativo else semestre
            elif alumno_limpio:
                incidencia.alumno = alumno_limpio
                incidencia.semestre = getattr(alumno_limpio, "semestre", None) or semestre
                incidencia.sala_semestre = getattr(alumno_limpio, "sala_semestre_asignada", None)
            elif semestre and not getattr(incidencia, "semestre_id", None):
                incidencia.semestre = semestre

            incidencia.save()

            if autorizacion_suplencia:
                registrar_movimiento_incidencia_suplencia(
                    incidencia,
                    autorizacion_suplencia,
                    request.user,
                    accion=MovimientoSuplencia.TipoAccion.CREACION_INCIDENCIA,
                    descripcion="Incidencia registrada durante cobertura temporal autorizada por Dirección.",
                )

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

    registro_diario_auto = None
    alumno_inicial = None

    if registro_diario:
        registro_diario_auto = registro_diario
        alumno_inicial = registro_diario.alumno
    else:
        alumno_id_inicial = request.GET.get("alumno") or request.POST.get("alumno")
        if alumno_id_inicial:
            alumno_inicial = (
                SolicitudInscripcion.objects
                .filter(pk=alumno_id_inicial, estado="FINALIZADA")
                .select_related("solicitud_ingreso", "semestre", "sala_semestre_asignada", "sala_semestre_asignada__sala")
                .first()
            )
            registro_diario_auto = obtener_registro_diario_actual_para_alumno(alumno_inicial, semestre=semestre)

    total_alumnos_disponibles = form.fields["alumno"].queryset.count() if "alumno" in form.fields else 0

    return render(
        request,
        "admisiones/incidencias/crear_incidencia.html",
        {
            "form": form,
            "tipo_forzado": tipo_forzado,
            "registro_diario": registro_diario,
            "registro_diario_auto": registro_diario_auto,
            "registro_diario_auto_json": serializar_registro_diario_incidencia(registro_diario_auto),
            "alumno_inicial": alumno_inicial,
            "semestre": semestre,
            "dia_operativo_actual": dia_operativo_actual,
            "fecha_operativa_actual": fecha_operativa_actual,
            "fecha_registro_automatica": fecha_operativa_actual,
            "total_alumnos_disponibles": total_alumnos_disponibles,
            "titulo": f"Crear incidencia {dict(Incidencia.TipoIncidencia.choices).get(tipo_forzado, '')}",
            **contexto_suplencias_usuario(request.user),
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
            "form_revision_suplencia": RevisarIncidenciaSuplenciaForm(incidencia=incidencia, usuario=request.user) if getattr(incidencia, "creada_por_suplencia", False) else None,
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

            if getattr(incidencia, "autorizacion_suplencia_id", None):
                registrar_movimiento_incidencia_suplencia(
                    incidencia,
                    incidencia.autorizacion_suplencia,
                    request.user,
                    accion=MovimientoSuplencia.TipoAccion.SEGUIMIENTO_INCIDENCIA,
                    descripcion="Seguimiento registrado sobre incidencia creada por suplencia.",
                )

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
            **contexto_suplencias_usuario(request.user),
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

            if getattr(incidencia, "autorizacion_suplencia_id", None):
                registrar_movimiento_incidencia_suplencia(
                    incidencia,
                    incidencia.autorizacion_suplencia,
                    request.user,
                    accion=MovimientoSuplencia.TipoAccion.CIERRE_INCIDENCIA,
                    descripcion="Cierre registrado sobre incidencia creada por suplencia.",
                )

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
            **contexto_bloqueos_edicion_area("TRABAJO_SOCIAL"),
            **contexto_suplencias_usuario(request.user),
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
    autorizacion_suplencia_actual = obtener_suplencia_activa_usuario_area(
        request.user,
        AutorizacionSuplencia.AreaCubierta.TRABAJO_SOCIAL,
        accion="PROCESO_SOCIAL",
    )
    bloqueo_edicion_temporal, respuesta_bloqueo = iniciar_bloqueo_edicion_temporal(
        request,
        inscripcion,
        area="TRABAJO_SOCIAL",
        autorizacion_suplencia=autorizacion_suplencia_actual,
        retorno="reporte_final_pendientes",
        motivo="Reporte Final de Ingreso",
    )
    if respuesta_bloqueo:
        return respuesta_bloqueo

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
            semestre_activo = obtener_semestre_activo_operativo()
            inscripcion.reporte_final_aprobado = True
            inscripcion.reporte_final_motivos = motivos
            inscripcion.reporte_final_por = request.user
            inscripcion.reporte_final_en = timezone.now()
            inscripcion.estado = "ESPERANDO_DIRECTORA"
            inscripcion.observaciones = (
                "Trabajo Social autorizó la inscripción y registró el Reporte Final de Ingreso. "
                "Pendiente resolución final de Dirección."
            )
            campos_update = [
                "reporte_final_aprobado",
                "reporte_final_motivos",
                "reporte_final_por",
                "reporte_final_en",
                "estado",
                "observaciones",
            ]
            if semestre_activo and not getattr(inscripcion, "semestre_id", None):
                inscripcion.semestre = semestre_activo
                campos_update.append("semestre")
            campos_update.append("updated_at")
            inscripcion.save(update_fields=list(dict.fromkeys(campos_update)))

            marcar_trabajo_social_por_suplencia(
                inscripcion=inscripcion,
                solicitud=solicitud,
                usuario=request.user,
                accion=MovimientoSuplencia.TipoAccion.REPORTE_FINAL,
                descripcion="Reporte Final de Ingreso aceptado durante cobertura temporal de Trabajo Social.",
            )

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

            liberar_bloqueo_edicion_temporal(
                request,
                inscripcion,
                observaciones="Reporte Final de Ingreso aceptado.",
            )
            return redirect("reporte_final_pendientes")

        elif accion in ["RECHAZAR", "RECHAZADO"]:
            if not motivos:
                messages.error(
                    request,
                    "Para rechazar la inscripción debes escribir los motivos del Reporte Final."
                )
                return redirect("dictaminar_reporte_final", pk=pk)

            semestre_activo = obtener_semestre_activo_operativo()
            inscripcion.reporte_final_aprobado = False
            inscripcion.reporte_final_motivos = motivos
            inscripcion.reporte_final_por = request.user
            inscripcion.reporte_final_en = timezone.now()
            inscripcion.estado = "RECHAZADA"
            inscripcion.observaciones = (
                "Trabajo Social no autorizó la inscripción en el Reporte Final de Ingreso."
            )
            campos_update = [
                "reporte_final_aprobado",
                "reporte_final_motivos",
                "reporte_final_por",
                "reporte_final_en",
                "estado",
                "observaciones",
            ]
            if semestre_activo and not getattr(inscripcion, "semestre_id", None):
                inscripcion.semestre = semestre_activo
                campos_update.append("semestre")
            campos_update.append("updated_at")
            inscripcion.save(update_fields=list(dict.fromkeys(campos_update)))

            marcar_trabajo_social_por_suplencia(
                inscripcion=inscripcion,
                solicitud=solicitud,
                usuario=request.user,
                accion=MovimientoSuplencia.TipoAccion.REPORTE_FINAL,
                descripcion="Reporte Final de Ingreso rechazado durante cobertura temporal de Trabajo Social.",
            )

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

            liberar_bloqueo_edicion_temporal(
                request,
                inscripcion,
                observaciones="Reporte Final de Ingreso rechazado.",
            )
            return redirect("reporte_final_pendientes")

        messages.error(request, "Acción no válida para el Reporte Final.")

    return render(
        request,
        "admisiones/dictaminar_reporte_final.html",
        {
            "inscripcion": inscripcion,
            "solicitud": solicitud,
            "bloqueo_edicion_temporal": bloqueo_edicion_temporal,
            **contexto_suplencias_usuario(request.user),
            **contexto_semestre_operativo(),
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
def iniciar_apoyo_sala(request):
    """
    Inicia apoyo temporal de una maestra en otra sala.

    No requiere autorización de Dirección porque es un movimiento operativo rápido,
    pero queda registrado y visible para Supervisora/Dirección.
    """
    semestre = obtener_semestre_activo_operativo()

    if not usuario_es_maestra_o_asistente(request.user):
        return acceso_denegado_login(request, "Solo una maestra o asistente de sala puede apoyar otra sala.")

    if not semestre:
        messages.warning(request, "No hay semestre activo. No se puede iniciar apoyo temporal de sala.")
        return redirect("dashboard_maestra")

    if not usuario_tiene_asignacion_maestra_activa(request.user, semestre=semestre):
        messages.error(request, "Para apoyar otra sala primero debes tener una sala original asignada.")
        return redirect("dashboard_maestra")

    dia = obtener_dia_operativo_actual_maestra(request.user, semestre=semestre)

    if not dia or not dia_operativo_es_laborable(dia):
        messages.warning(request, mensaje_dia_no_operativo(dia) or "Hoy no permite operación diaria de menores.")
        return redirect("dashboard_maestra")

    if not dia_operativo_permite_apoyo_sala(dia):
        messages.warning(
            request,
            mensaje_apoyo_sala_no_disponible(dia)
            or "Primero debes iniciar el día operativo para poder apoyar otra sala."
        )
        return redirect("dashboard_maestra")

    apoyo_actual = obtener_apoyo_sala_activo_usuario(request.user)
    if apoyo_actual:
        messages.info(request, "Ya tienes un apoyo temporal activo. Finalízalo antes de iniciar otro.")
        return redirect("lista_alumnos_dia_maestra", dia_id=dia.id)

    sala_origen = obtener_sala_origen_maestra(request.user, semestre=semestre)
    salas_disponibles = obtener_salas_disponibles_para_apoyo(request.user, dia=dia, semestre=semestre)

    if request.method == "POST":
        form = ApoyoSalaMaestraForm(
            request.POST,
            usuario=request.user,
            dia_operativo=dia,
            sala_origen=sala_origen,
            salas_disponibles=salas_disponibles,
        )

        if form.is_valid():
            apoyo = form.save(commit=False)
            apoyo.maestra_titular_sala = obtener_maestra_titular_sala(
                apoyo.sala_apoyada,
                excluir_usuario=request.user,
            )
            apoyo.save()

            if apoyo.maestra_titular_sala:
                messages.warning(
                    request,
                    "La sala seleccionada tiene maestra titular asignada. "
                    "Tus registros quedarán como apoyo temporal; la sala conserva a su titular."
                )

            if dia.estado == DiaOperativoSemestre.EstadoDia.ABIERTO:
                asegurar_registros_alumnos_dia(dia, request.user)

            messages.success(
                request,
                "Apoyo temporal iniciado. No olvides finalizar el apoyo cuando regreses a tu sala original."
            )
            return redirect("lista_alumnos_dia_maestra", dia_id=dia.id)

        messages.error(request, "No se pudo iniciar el apoyo temporal. Revisa los campos.")
    else:
        form = ApoyoSalaMaestraForm(
            usuario=request.user,
            dia_operativo=dia,
            sala_origen=sala_origen,
            salas_disponibles=salas_disponibles,
        )

    return render(
        request,
        "admisiones/operacion_diaria/apoyar_sala.html",
        {
            "form": form,
            "semestre": semestre,
            "dia": dia,
            "sala_origen": sala_origen,
            "salas_disponibles": salas_disponibles,
            **contexto_apoyo_sala_maestra(request.user, dia),
            **contexto_semestre_operativo(),
        },
    )


@login_required
def finalizar_apoyo_sala(request):
    """Finaliza el apoyo temporal de sala iniciado por la maestra."""
    apoyo = obtener_apoyo_sala_activo_usuario(request.user)

    if not apoyo:
        messages.info(request, "No tienes apoyo temporal activo para finalizar.")
        return redirect("dashboard_maestra")

    dia = getattr(apoyo, "dia_operativo", None) or obtener_dia_operativo_actual_maestra(request.user)

    if request.method == "POST":
        form = FinalizarApoyoSalaMaestraForm(request.POST, instance=apoyo, usuario=request.user)

        if form.is_valid():
            form.save()
            messages.success(request, "Apoyo temporal finalizado. Ya puedes regresar a tu sala original.")
            return redirect("dashboard_maestra")

        messages.error(request, "No se pudo finalizar el apoyo temporal. Confirma la finalización.")
    else:
        form = FinalizarApoyoSalaMaestraForm(instance=apoyo, usuario=request.user)

    return render(
        request,
        "admisiones/operacion_diaria/finalizar_apoyo_sala.html",
        {
            "form": form,
            "apoyo": apoyo,
            "dia": dia,
            **contexto_apoyo_sala_maestra(request.user, dia),
            **contexto_semestre_operativo(),
        },
    )


@login_required
def dashboard_maestra(request):
    """
    Panel principal de operación diaria para maestras.

    Reglas aplicadas:
    - "Pendientes de entrada" no se trata como ausencia confirmada.
    - "Mis salas" cuenta alumnos asignados aunque el día no esté abierto.
    - "Historial de alumnos" recibe alumnos_asignados para consulta permanente.
    - Si hay apoyo temporal activo, las secciones operativas muestran solo la sala apoyada.
    """
    if request.method == "POST" and request.POST.get("accion_perfil_maestra"):
        return procesar_foto_perfil_maestra(request)

    semestre = obtener_semestre_activo_operativo()
    asignaciones = obtener_asignaciones_maestra_operativas(request.user, semestre=semestre)

    dia_actual = None
    registros = RegistroDiarioAlumno.objects.none()
    alumnos_asignados = SolicitudInscripcion.objects.none()
    salas = []
    salas_operativas_actuales = []

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
        # Mis salas: solo las salas propias de la maestra.
        salas = anotar_total_alumnos_asignados_salas(
            obtener_salas_propias_maestra(request.user, semestre=semestre),
            semestre=semestre,
        )
        salas = agregar_alumnos_asignados_a_salas(salas, semestre=semestre)

        # Operación diaria e historial: sala propia o sala apoyada, sin mezclarlas.
        salas_operativas_actuales = anotar_total_alumnos_asignados_salas(
            obtener_salas_maestra_operativas(request.user, semestre=semestre),
            semestre=semestre,
        )
        salas_operativas_actuales = agregar_alumnos_asignados_a_salas(salas_operativas_actuales, semestre=semestre)

        alumnos_asignados = obtener_alumnos_asignados_a_salas(
            salas_operativas_actuales,
            semestre=semestre,
        )

        dia_actual = obtener_dia_operativo_actual_maestra(request.user, semestre=semestre)

        if dia_actual and dia_actual.estado == DiaOperativoSemestre.EstadoDia.ABIERTO and dia_operativo_es_laborable(dia_actual):
            asegurar_registros_alumnos_dia(dia_actual, request.user)

        if dia_actual and dia_operativo_es_laborable(dia_actual):
            registros = obtener_registros_dia_maestra(dia_actual, request.user)

    total_registros = registros.count() if dia_actual else 0
    total_alumnos_asignados = sum(getattr(sala, "total_alumnos_asignados", 0) for sala in salas)
    total_alumnos_operacion = alumnos_asignados.count() if semestre else 0

    dia_con_operacion = bool(
        dia_actual
        and dia_operativo_es_laborable(dia_actual)
        and dia_actual.estado in (
            DiaOperativoSemestre.EstadoDia.ABIERTO,
            DiaOperativoSemestre.EstadoDia.CERRADO,
        )
    )

    # Pendiente de entrada solo se calcula cuando el día ya fue abierto.
    # Antes de abrir el día, no se considera ausencia ni pendiente operativo.
    pendientes_entrada = registros.filter(entrada_en__isnull=True).count() if dia_con_operacion else 0
    en_estancia = registros.filter(entrada_en__isnull=False, salida_en__isnull=True).count() if dia_con_operacion else 0
    con_salida = registros.filter(salida_en__isnull=False).count() if dia_con_operacion else 0

    try:
        completos = sum(
            1 for registro in registros
            if getattr(registro, "tiene_bitacora_entrada_completa", False)
            and getattr(registro, "tiene_bitacora_estancia_completa", False)
            and bool(getattr(registro, "salida_en", None))
        )
    except Exception:
        completos = registros.filter(estado=RegistroDiarioAlumno.EstadoRegistro.COMPLETO).count() if dia_actual else 0

    try:
        bitacoras_casa_completas = sum(1 for registro in registros if getattr(registro, "tiene_bitacora_entrada_completa", False))
        bitacoras_estancia_completas = sum(1 for registro in registros if getattr(registro, "tiene_bitacora_estancia_completa", False))
    except Exception:
        bitacoras_casa_completas = 0
        bitacoras_estancia_completas = 0

    # Para indicadores visuales, el total debe representar los alumnos asignados
    # a la sala que la maestra está viendo/operando, aunque aún no haya registros diarios.
    total_indicador = total_alumnos_operacion or total_registros
    fuera_estancia = max(total_indicador - en_estancia, 0)

    resumen_dia = {
        "total": total_indicador,
        "total_asignados": total_alumnos_operacion,
        "registros": total_registros if dia_con_operacion else 0,
        "sin_entrada": pendientes_entrada,
        "pendientes_entrada": pendientes_entrada,
        "en_estancia": en_estancia,
        "con_salida": con_salida,
        "fuera_estancia": fuera_estancia,
        "completos": completos if dia_con_operacion else 0,
        "pendientes": max((total_registros if dia_con_operacion else 0) - (completos if dia_con_operacion else 0), 0),
    }

    resumen_bitacoras = {
        "casa": bitacoras_casa_completas,
        "estancia": bitacoras_estancia_completas,
    }

    return render(
        request,
        "admisiones/operacion_diaria/panel_maestra.html",
        {
            "semestre": semestre,
            "asignaciones": asignaciones,
            "salas": salas,
            "salas_propias": salas,
            "salas_operativas_actuales": salas_operativas_actuales,
            "alumnos_asignados": alumnos_asignados,
            "alumnos_historial": alumnos_asignados,
            "alumnos_por_sala": salas_operativas_actuales,
            "total_alumnos_asignados": total_alumnos_asignados,
            "total_alumnos_operacion": total_alumnos_operacion,
            "dia_actual": dia_actual,
            "registros": registros,
            "resumen_dia": resumen_dia,
            "resumen_bitacoras": resumen_bitacoras,
            "foto_perfil_maestra_url": obtener_foto_perfil_usuario(request.user),
            "perfil_maestra_soporta_foto": bool(obtener_campo_foto_perfil_usuario(request.user)),
            "resumen_bitacoras_casa": {"completas": bitacoras_casa_completas},
            "resumen_bitacoras_estancia": {"completas": bitacoras_estancia_completas},
            "dia_no_operativo": bool(dia_actual and not dia_operativo_es_laborable(dia_actual)),
            "mensaje_dia_no_operativo": mensaje_dia_no_operativo(dia_actual) if dia_actual else "",
            **contexto_apoyo_sala_maestra(request.user, dia_actual),
            **contexto_semestre_operativo(),
        },
    )

@login_required
def abrir_dia_maestra(request, dia_id):

    """
    Cualquier maestra asignada a sala puede abrir la operación del día de la sede.

    Protección de concurrencia:
    - Si dos maestras intentan abrir el mismo día al mismo tiempo, la base de datos
      bloquea el registro del día mientras se procesa la apertura.
    - Gana la primera petición que confirme correctamente.
    - La segunda petición, al entrar después del bloqueo, detecta que el día ya está
      ABIERTO y solo redirige a la lista de alumnos.
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

            try:
                with transaction.atomic():
                    # Se vuelve a leer el día dentro de la transacción y con bloqueo.
                    # En MariaDB/PostgreSQL select_for_update bloquea la fila hasta terminar.
                    dia_bloqueado = (
                        DiaOperativoSemestre.objects
                        .select_for_update()
                        .select_related("semestre", "semestre__sede_configurada")
                        .get(pk=dia.id)
                    )

                    # Validación extra por seguridad dentro del bloqueo.
                    if not dia_operativo_es_laborable(dia_bloqueado):
                        messages.warning(
                            request,
                            mensaje_dia_no_operativo(dia_bloqueado)
                            or "Este día no permite operación diaria de menores."
                        )
                        return redirect("dashboard_maestra")

                    if dia_bloqueado.estado == DiaOperativoSemestre.EstadoDia.CERRADO:
                        messages.warning(
                            request,
                            "Este día ya está cerrado. Solo puede consultarse."
                        )
                        return redirect("dashboard_maestra")

                    if dia_bloqueado.estado == DiaOperativoSemestre.EstadoDia.ABIERTO:
                        # Otra maestra pudo haberlo abierto milisegundos antes.
                        creados = asegurar_registros_alumnos_dia(dia_bloqueado, request.user)

                        if dia_bloqueado.abierto_por_id == request.user.id:
                            messages.info(
                                request,
                                "El día ya estaba abierto por tu usuario. Puedes continuar con la operación diaria."
                            )
                        elif dia_bloqueado.abierto_por:
                            messages.info(
                                request,
                                "El día ya fue abierto por "
                                f"{usuario_nombre_legible(dia_bloqueado.abierto_por)}. "
                                "Puedes continuar con la operación diaria."
                            )
                        else:
                            messages.info(
                                request,
                                "El día ya estaba abierto. Puedes continuar con la operación diaria."
                            )

                        return redirect("lista_alumnos_dia_maestra", dia_id=dia_bloqueado.id)

                    ok, errores = dia_bloqueado.abrir(
                        usuario=request.user,
                        observaciones=observaciones,
                    )

                    if ok:
                        creados = asegurar_registros_alumnos_dia(dia_bloqueado, request.user)

                        messages.success(
                            request,
                            f"Día abierto correctamente. Registros de alumnos preparados: {creados}."
                        )

                        return redirect("lista_alumnos_dia_maestra", dia_id=dia_bloqueado.id)

                    messages.error(request, "No se pudo abrir el día.")
                    for error in errores:
                        messages.error(request, error)

            except DiaOperativoSemestre.DoesNotExist:
                messages.error(request, "No se encontró el día operativo solicitado.")
                return redirect("dashboard_maestra")

            except Exception as exc:
                messages.error(
                    request,
                    f"No se pudo abrir el día por un error de concurrencia o base de datos: {exc}"
                )
                return redirect("dashboard_maestra")
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
    Lista diaria de alumnos de la sala que la maestra opera actualmente.
    Si está apoyando otra sala, solo se muestran los alumnos de esa sala apoyada.
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

    total_registros = registros.count()
    pendientes_entrada = registros.filter(entrada_en__isnull=True).count()
    en_estancia = registros.filter(entrada_en__isnull=False, salida_en__isnull=True).count()
    con_salida = registros.filter(salida_en__isnull=False).count()

    try:
        completos = sum(
            1 for registro in registros
            if getattr(registro, "tiene_bitacora_entrada_completa", False)
            and getattr(registro, "tiene_bitacora_estancia_completa", False)
            and bool(getattr(registro, "salida_en", None))
        )
    except Exception:
        completos = registros.filter(estado=RegistroDiarioAlumno.EstadoRegistro.COMPLETO).count()

    salas_operativas_actuales = anotar_total_alumnos_asignados_salas(
        obtener_salas_maestra_operativas(request.user, semestre=dia.semestre),
        semestre=dia.semestre,
    )

    alumnos_asignados = obtener_alumnos_asignados_a_salas(
        salas_operativas_actuales,
        semestre=dia.semestre,
    )
    total_alumnos_operacion = alumnos_asignados.count()

    resumen_dia = {
        "total": total_alumnos_operacion or total_registros,
        "total_asignados": total_alumnos_operacion,
        "registros": total_registros,
        "pendientes_entrada": pendientes_entrada,
        "sin_entrada": pendientes_entrada,
        "en_estancia": en_estancia,
        "con_salida": con_salida,
        "completos": completos,
        "pendientes": max(total_registros - completos, 0),
    }

    return render(
        request,
        "admisiones/operacion_diaria/lista_alumnos_dia.html",
        {
            "dia": dia,
            "semestre": dia.semestre,
            "registros": registros,
            "resumen_dia": resumen_dia,
            "salas_operativas_actuales": salas_operativas_actuales,
            "sala_operacion_actual": salas_operativas_actuales[0] if salas_operativas_actuales else None,
            "alumnos_asignados": alumnos_asignados,
            "total_alumnos_operacion": total_alumnos_operacion,
            "dia_solo_lectura": dia.estado != DiaOperativoSemestre.EstadoDia.ABIERTO or not dia_operativo_es_laborable(dia),
            "dia_no_operativo": not dia_operativo_es_laborable(dia),
            "mensaje_dia_no_operativo": mensaje_dia_no_operativo(dia),
            **contexto_apoyo_sala_maestra(request.user, dia),
        },
    )



def obtener_ip_cliente(request):
    """
    Obtiene la IP del responsable/usuario para auditoría.
    Si el proyecto está detrás de proxy, toma X-Forwarded-For y usa la primera IP.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or None


def generar_qr_data_uri(texto):
    """
    Genera un QR como imagen base64 si la librería qrcode está instalada.
    Si no está instalada, devuelve cadena vacía y el HTML puede mostrar el enlace.

    Para activar QR real en pantalla instala:
        pip install qrcode[pil]
    """
    texto = str(texto or "").strip()
    if not texto:
        return ""

    try:
        import base64
        from io import BytesIO
        import qrcode

        imagen = qrcode.make(texto)
        buffer = BytesIO()
        imagen.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception:
        return ""


def construir_enlace_autorizacion_entrada(request, autorizacion):
    """
    Construye el enlace público de entrada usando únicamente el token.
    La URL no contiene nombre del menor, CURP, matrícula ni código de seguridad.
    """
    try:
        url = reverse("autorizar_entrada_responsable", args=[str(autorizacion.token)])
    except Exception:
        url = f"/admisiones/a/e/{autorizacion.token}/"

    return request.build_absolute_uri(url)


def nombre_menor_autorizacion_entrada(autorizacion):
    """
    Devuelve el nombre del menor para correos y pantallas de autorización.
    """
    try:
        alumno = autorizacion.registro_diario.alumno
        solicitud = alumno.solicitud_ingreso
        if hasattr(solicitud, "nombre_menor_completo"):
            return solicitud.nombre_menor_completo()
    except Exception:
        pass

    try:
        return autorizacion.alumno_nombre
    except Exception:
        return "el menor"


def enviar_correo_autorizacion_entrada(request, autorizacion):
    """
    Envía el correo al responsable autorizado para que valide la entrada desde su celular.

    Importante:
    - La maestra ya no escribe el código en su tableta.
    - El responsable abre el enlace, revisa la información y escribe su propio código.
    - Solo se envía por correo si el destino es @unach.mx.
    """
    autorizacion.preparar_datos_responsable()
    correo_destino = (autorizacion.correo_destino or "").strip().lower()

    if not correo_destino:
        return False, "El responsable autorizado no tiene correo registrado. Debe usarse QR presencial."

    if not es_correo_institucional_unach_views(correo_destino):
        return False, "El responsable no tiene correo institucional UNACH. Debe usarse QR presencial."

    enlace = construir_enlace_autorizacion_entrada(request, autorizacion)
    nombre_menor = nombre_menor_autorizacion_entrada(autorizacion)
    responsable = autorizacion.responsable_nombre or "Responsable autorizado"
    maestra = usuario_nombre_legible(autorizacion.solicitada_por)

    fecha_txt = ""
    try:
        if autorizacion.fecha_operativa:
            fecha_txt = autorizacion.fecha_operativa.strftime("%d/%m/%Y")
    except Exception:
        fecha_txt = ""

    expira_txt = ""
    try:
        if autorizacion.expira_en:
            expira_txt = timezone.localtime(autorizacion.expira_en).strftime("%d/%m/%Y %H:%M")
    except Exception:
        expira_txt = ""

    temperatura_txt = "No capturada"
    if autorizacion.temperatura_entrada is not None:
        temperatura_txt = f"{autorizacion.temperatura_entrada} °C"

    asunto = f"Autorización de entrada - {nombre_menor}"
    cuerpo = f"""Hola {responsable}:

La maestra {maestra} capturó una solicitud de entrada para {nombre_menor} en la Estancia Infantil UNACH.

Resumen de la solicitud:
- Menor: {nombre_menor}
- Sala: {autorizacion.sala_nombre}
- Fecha: {fecha_txt or 'Hoy'}
- Responsable seleccionado: {autorizacion.responsable_nombre or responsable}
- Parentesco: {autorizacion.responsable_parentesco or 'No especificado'}
- Credencial verificada por maestra: {'Sí' if autorizacion.credencial_entrada_validada else 'No'}
- Temperatura de entrada: {temperatura_txt}
- Observaciones de maestra: {autorizacion.observaciones_maestra or 'Sin observaciones'}

Para autorizar la entrada, abre este enlace desde tu celular y escribe tu código de seguridad de 4 dígitos:
{enlace}

Este enlace tiene vigencia limitada{f' hasta {expira_txt}' if expira_txt else ''}. Si no reconoces esta solicitud, no autorices la entrada y comunícate con la estancia.

Atentamente,
Estancia Infantil UNACH
"""

    enviado, mensaje = enviar_correo_institucional_unach(
        asunto=asunto,
        cuerpo=cuerpo,
        destinatarios=[correo_destino],
        usuario_emisor=request.user,
    )

    if enviado:
        autorizacion.marcar_enviada()
        return True, "Correo de autorización enviado correctamente."

    autorizacion.marcar_error(mensaje)
    return False, mensaje


def procesar_metodo_autorizacion_entrada(request, autorizacion):
    """
    Decide qué hacer con la autorización de entrada ya creada:
    - correo institucional UNACH: envía enlace por correo;
    - sin correo institucional: marca QR generado para mostrarlo en pantalla.
    """
    autorizacion.refresh_from_db()

    enlace = construir_enlace_autorizacion_entrada(request, autorizacion)

    usa_correo = bool(
        getattr(autorizacion, "usa_correo", False)
        and es_correo_institucional(getattr(autorizacion, "correo_destino", ""))
    )

    if usa_correo:
        enviado, mensaje = enviar_correo_autorizacion_entrada(request, autorizacion)
        return enviado, mensaje, enlace

    try:
        autorizacion.marcar_qr_generado()
        return True, "QR generado correctamente para autorización presencial.", enlace
    except Exception as exc:
        autorizacion.marcar_error(exc)
        return False, f"No se pudo generar la autorización por QR: {exc}", enlace


def obtener_autorizacion_entrada_pendiente(registro):
    """
    Devuelve la solicitud pendiente o enviada más reciente para un registro diario.
    """
    if not registro:
        return None

    qs = (
        AutorizacionEntrada.objects
        .filter(
            registro_diario=registro,
            estado__in=[
                AutorizacionEntrada.EstadoAutorizacion.PENDIENTE,
                AutorizacionEntrada.EstadoAutorizacion.ENVIADA,
                AutorizacionEntrada.EstadoAutorizacion.QR_GENERADO,
            ],
        )
        .select_related("responsable_autorizado", "solicitada_por")
        .order_by("-created_at")
    )

    autorizacion = qs.first()
    if autorizacion:
        try:
            autorizacion.expirar_si_corresponde()
        except Exception:
            pass
        if not autorizacion.esta_vigente:
            return None

    return autorizacion

@login_required
def registrar_entrada_alumno(request, registro_id):
    """
    Flujo de entrada con autorización en tableta.

    La maestra captura la información de entrada, selecciona al responsable
    autorizado y revisa el resumen en una ventana flotante. Después entrega
    la tableta al responsable para que escriba su código de 4 dígitos.

    Ya no se envía correo ni se genera QR para este proceso. La entrada queda
    registrada en el mismo momento únicamente si el código coincide con el
    tutor o familiar autorizado seleccionado.
    """
    registro = obtener_registro_diario_para_maestra(request, registro_id)
    responsables_codigo = obtener_responsables_codigo_inscripcion(registro.alumno)

    if not registro_diario_es_editable(registro):
        messages.warning(
            request,
            mensaje_dia_no_operativo(registro.dia_operativo)
            or "No se puede registrar entrada porque el día no está abierto."
        )
        return redirect("dashboard_maestra")

    if registro.entrada_en:
        messages.info(request, "Este alumno ya tiene entrada registrada.")
        return redirect("dashboard_maestra")

    autorizacion_pendiente = obtener_autorizacion_entrada_pendiente(registro)

    if request.method == "POST":
        form = SolicitarAutorizacionEntradaForm(
            request.POST,
            registro_diario=registro,
            usuario=request.user,
        )

        responsable_codigo, errores_codigo = obtener_responsable_operacion_desde_post(
            registro,
            request.POST,
            prefijo="entrada",
        )

        if form.is_valid() and not errores_codigo:
            try:
                with transaction.atomic():
                    # Bloqueo corto del registro para evitar entradas duplicadas
                    # si la maestra abrió la pantalla en más de una pestaña.
                    registro_bloqueado = (
                        RegistroDiarioAlumno.objects
                        .select_for_update()
                        .select_related("dia_operativo", "alumno", "sala_semestre")
                        .get(pk=registro.pk)
                    )

                    if registro_bloqueado.entrada_en:
                        messages.info(request, "Este alumno ya tiene entrada registrada.")
                        return redirect("dashboard_maestra")

                    datos_entrada = datos_entrada_desde_form_o_post(
                        form,
                        request.POST,
                        responsable_autorizado=responsable_codigo,
                    )

                    observaciones_entrada = (
                        getattr(form, "cleaned_data", {}).get("observaciones_maestra", "")
                        or request.POST.get("observaciones_maestra", "")
                        or ""
                    ).strip()

                    responsable_nombre = (
                        datos_entrada.get("responsable_nombre")
                        or getattr(responsable_codigo, "nombre_completo", "")
                        or "Responsable autorizado"
                    )
                    responsable_parentesco = (
                        datos_entrada.get("responsable_parentesco")
                        or getattr(responsable_codigo, "parentesco", "")
                        or ""
                    )
                    responsable_telefono = (
                        datos_entrada.get("responsable_telefono")
                        or getattr(responsable_codigo, "telefono", "")
                        or ""
                    )

                    campos_registro = {
                        "entrada_en": timezone.now(),
                        "entrada_por": request.user,
                        "responsable_entrada_nombre": responsable_nombre,
                        "responsable_entrada_parentesco": responsable_parentesco,
                        "responsable_entrada_telefono": responsable_telefono,
                        "credencial_entrada_validada": bool(datos_entrada.get("credencial_validada")),
                        "codigo_entrada_validado": True,
                        "temperatura_entrada": datos_entrada.get("temperatura"),
                    }

                    # Compatibilidad con distintos nombres de campo que puedan existir
                    # en RegistroDiarioAlumno para guardar observaciones de entrada.
                    for campo_observaciones in [
                        "observaciones_entrada",
                        "observacion_entrada",
                        "observaciones_maestra_entrada",
                    ]:
                        if hasattr(registro_bloqueado, campo_observaciones):
                            campos_registro[campo_observaciones] = observaciones_entrada
                            break

                    update_fields = []
                    for campo, valor in campos_registro.items():
                        if hasattr(registro_bloqueado, campo):
                            setattr(registro_bloqueado, campo, valor)
                            update_fields.append(campo)

                    if hasattr(registro_bloqueado, "updated_at"):
                        update_fields.append("updated_at")

                    if update_fields:
                        registro_bloqueado.save(update_fields=list(dict.fromkeys(update_fields)))
                    else:
                        registro_bloqueado.save()

                    # Si existía una autorización pendiente del flujo anterior
                    # correo/QR, se cancela para que no quede activa después de
                    # registrar la entrada en tableta.
                    autorizacion_pendiente_actual = obtener_autorizacion_entrada_pendiente(registro_bloqueado)
                    if autorizacion_pendiente_actual:
                        try:
                            autorizacion_pendiente_actual.cancelar(
                                usuario=request.user,
                                motivo="Cancelada automáticamente porque la entrada se autorizó en tableta.",
                            )
                        except Exception:
                            pass

                    BitacoraEntradaCasa.objects.get_or_create(
                        registro_diario=registro_bloqueado,
                    )

                messages.success(
                    request,
                    "Entrada registrada correctamente. El responsable autorizado escribió su código en la tableta y fue validado."
                )
                return redirect("bitacora_entrada_casa_maestra", registro_id=registro.id)

            except Exception as exc:
                messages.error(request, f"No se pudo registrar la entrada en tableta: {exc}")
        else:
            if form.errors:
                messages.error(request, "No se pudo registrar la entrada. Revisa los campos capturados.")
                for campo, errores in form.errors.items():
                    for error in errores:
                        messages.error(request, f"{campo}: {error}")

            for error in errores_codigo:
                messages.error(request, error)

            if not form.errors and errores_codigo:
                messages.error(
                    request,
                    "La entrada no se registró porque el código del responsable no fue validado."
                )
    else:
        form = SolicitarAutorizacionEntradaForm(
            registro_diario=registro,
            usuario=request.user,
        )

    # En el flujo nuevo no se genera enlace ni QR. Se conservan estas variables
    # vacías para no romper templates que todavía las esperen.
    autorizacion_pendiente = obtener_autorizacion_entrada_pendiente(registro)
    enlace_autorizacion = ""
    qr_data_uri = ""

    autorizaciones_entrada = (
        AutorizacionEntrada.objects
        .filter(registro_diario=registro)
        .select_related("responsable_autorizado", "solicitada_por")
        .order_by("-created_at")[:5]
    )

    return render(
        request,
        "admisiones/operacion_diaria/registrar_entrada.html",
        {
            "form": form,
            "registro": registro,
            "responsables_codigo": responsables_codigo,
            "tipo_formulario": registro.formulario_bitacora,
            "dia": registro.dia_operativo,
            "flujo_autorizacion_tableta": True,
            "flujo_autorizacion_por_correo": False,
            "flujo_autorizacion_por_qr": False,
            "autorizacion_pendiente": autorizacion_pendiente,
            "autorizacion_pendiente_url": enlace_autorizacion,
            "qr_data_uri": qr_data_uri,
            "autorizaciones_entrada": autorizaciones_entrada,
            **contexto_perfil_maestra(request.user),
            **contexto_apoyo_sala_maestra(request.user, registro.dia_operativo),
        },
    )


@login_required
@require_http_methods(["POST"])
def cancelar_autorizacion_entrada_maestra(request, autorizacion_id):
    """
    Permite a la maestra cancelar una solicitud pendiente para volver a enviarla.
    """
    autorizacion = get_object_or_404(
        AutorizacionEntrada.objects.select_related(
            "registro_diario",
            "registro_diario__dia_operativo",
            "registro_diario__alumno",
            "registro_diario__sala_semestre",
            "responsable_autorizado",
        ),
        pk=autorizacion_id,
    )

    registro = obtener_registro_diario_para_maestra(request, autorizacion.registro_diario_id)

    if autorizacion.solicitada_por_id and autorizacion.solicitada_por_id != request.user.id:
        messages.warning(
            request,
            "La solicitud fue creada por otra maestra. Solo puedes cancelarla si tienes permiso operativo sobre la sala."
        )

    motivo = (request.POST.get("motivo") or "Cancelada por la maestra desde el panel de entrada.").strip()
    ok, errores = autorizacion.cancelar(usuario=request.user, motivo=motivo)

    if ok:
        messages.success(request, "Solicitud de autorización cancelada correctamente.")
    else:
        for error in errores:
            messages.error(request, error)

    return redirect("registrar_entrada_alumno", registro_id=registro.id)


def autorizar_entrada_responsable(request, token):
    """
    Pantalla pública que abre el responsable desde su celular.
    Aquí revisa la información y autoriza/rechaza la entrada con su código.
    """
    autorizacion = get_object_or_404(
        AutorizacionEntrada.objects.select_related(
            "registro_diario",
            "registro_diario__dia_operativo",
            "registro_diario__alumno",
            "registro_diario__alumno__solicitud_ingreso",
            "registro_diario__sala_semestre",
            "registro_diario__sala_semestre__sala",
            "responsable_autorizado",
            "solicitada_por",
        ),
        token=token,
    )

    try:
        autorizacion.expirar_si_corresponde()
    except Exception:
        pass

    form = AutorizarEntradaResponsableForm(autorizacion=autorizacion)
    rechazo_form = RechazarAutorizacionEntradaForm(autorizacion=autorizacion)
    autorizada = False
    rechazada = False
    errores_operacion = []

    if request.method == "POST":
        accion = (request.POST.get("accion") or "AUTORIZAR").strip().upper()
        ip = obtener_ip_cliente(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:1000]

        if accion == "RECHAZAR":
            rechazo_form = RechazarAutorizacionEntradaForm(
                request.POST,
                autorizacion=autorizacion,
            )

            if rechazo_form.is_valid():
                rechazada, errores_operacion = rechazo_form.rechazar(
                    ip=ip,
                    user_agent=user_agent,
                )
                autorizacion.refresh_from_db()
            else:
                errores_operacion = [
                    str(error)
                    for errores in rechazo_form.errors.values()
                    for error in errores
                ]
        else:
            form = AutorizarEntradaResponsableForm(
                request.POST,
                autorizacion=autorizacion,
            )

            if form.is_valid():
                autorizada, errores_operacion = form.autorizar(
                    ip=ip,
                    user_agent=user_agent,
                )
                autorizacion.refresh_from_db()

                if autorizada:
                    BitacoraEntradaCasa.objects.get_or_create(
                        registro_diario=autorizacion.registro_diario
                    )
            else:
                errores_operacion = [
                    str(error)
                    for errores in form.errors.values()
                    for error in errores
                ]

    return render(
        request,
        "admisiones/operacion_diaria/autorizar_entrada.html",
        {
            "autorizacion": autorizacion,
            "form": form,
            "rechazo_form": rechazo_form,
            "autorizada": autorizada,
            "rechazada": rechazada,
            "errores_operacion": errores_operacion,
            "alumno_nombre": nombre_menor_autorizacion_entrada(autorizacion),
        },
    )


@login_required
def estado_autorizacion_entrada_maestra(request, registro_id):
    """
    Respuesta JSON para que la pantalla de la maestra consulte si el responsable ya autorizó.
    """
    registro = obtener_registro_diario_para_maestra(request, registro_id)
    autorizacion = (
        AutorizacionEntrada.objects
        .filter(registro_diario=registro)
        .select_related("responsable_autorizado")
        .order_by("-created_at")
        .first()
    )

    if autorizacion:
        try:
            autorizacion.expirar_si_corresponde()
        except Exception:
            pass
        autorizacion.refresh_from_db()

    try:
        registro.refresh_from_db()
    except Exception:
        pass

    enlace_autorizacion = ""
    qr_data_uri = ""

    if autorizacion and getattr(autorizacion, "esta_vigente", False):
        enlace_autorizacion = construir_enlace_autorizacion_entrada(request, autorizacion)
        if getattr(autorizacion, "usa_qr", False):
            qr_data_uri = generar_qr_data_uri(enlace_autorizacion)

    data = {
        "registro_id": registro.id,
        "entrada_registrada": bool(registro.entrada_en),
        "entrada_en": timezone.localtime(registro.entrada_en).strftime("%H:%M") if registro.entrada_en else "",
        "estado": getattr(autorizacion, "estado", "SIN_SOLICITUD") if autorizacion else "SIN_SOLICITUD",
        "estado_display": autorizacion.get_estado_display() if autorizacion else "Sin solicitud",
        "metodo_autorizacion": getattr(autorizacion, "metodo_autorizacion", "") if autorizacion else "",
        "usa_qr": bool(getattr(autorizacion, "usa_qr", False)) if autorizacion else False,
        "usa_correo": bool(getattr(autorizacion, "usa_correo", False)) if autorizacion else False,
        "responsable": getattr(autorizacion, "responsable_nombre", "") if autorizacion else "",
        "ultimo_error": getattr(autorizacion, "ultimo_error", "") if autorizacion else "",
        "enlace_autorizacion": enlace_autorizacion,
        "qr_data_uri": qr_data_uri,
        "redirect_url": "",
    }

    if registro.entrada_en:
        try:
            data["redirect_url"] = reverse("bitacora_entrada_casa_maestra", args=[registro.id])
        except Exception:
            data["redirect_url"] = ""

    return JsonResponse(data)


def obtener_origen_bitacora(request):
    """Origen de navegación para volver correctamente desde las bitácoras."""
    return (
        request.POST.get("origen")
        or request.GET.get("origen")
        or ""
    ).strip().lower()


def construir_url_regreso_bitacora(registro, origen="", next_url=""):
    origen = str(origen or "").strip().lower()
    next_url = str(next_url or "").strip()

    if next_url.startswith("/") and not next_url.startswith("//"):
        return next_url

    if origen == "historial":
        return reverse("historial_alumno_maestra", args=[registro.alumno_id])

    if origen == "estancia":
        return reverse("bitacora_estancia_maestra", args=[registro.id])

    return reverse("lista_alumnos_dia_maestra", args=[registro.dia_operativo_id])


def construir_url_estancia_desde_bitacora(registro, origen="", next_url=""):
    url = reverse("bitacora_estancia_maestra", args=[registro.id])
    params = {}
    if origen == "historial":
        params["origen"] = "historial"
    if next_url:
        params["next"] = next_url
    if params:
        return f"{url}?{urlencode(params)}"
    return url


def construir_url_casa_desde_bitacora(registro, origen="", next_url=""):
    url = reverse("bitacora_entrada_casa_maestra", args=[registro.id])
    params = {}
    if origen == "historial":
        params["origen"] = "historial"
    else:
        params["origen"] = "estancia"
    if next_url:
        params["next"] = next_url
    return f"{url}?{urlencode(params)}"


@login_required
def bitacora_entrada_casa_maestra(request, registro_id):
    registro = obtener_registro_diario_para_maestra(request, registro_id)
    origen_bitacora = obtener_origen_bitacora(request)
    next_bitacora = obtener_next_seguro(request, "")

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
            return redirect(construir_url_regreso_bitacora(registro, origen_bitacora, next_bitacora))

        form = BitacoraEntradaCasaForm(
            request.POST,
            instance=bitacora,
            registro_diario=registro,
            tipo_formulario=registro.formulario_bitacora,
        )

        if form.is_valid():
            obj = form.save(commit=False)
            obj.capturada_por = request.user
            obj = aplicar_tomas_leche_desde_post(obj, request.POST)

            if form.cleaned_data.get("marcar_completa"):
                obj.completa = True
                obj.capturada_en = timezone.now()

            obj.save()
            registro.marcar_completo_si_corresponde()

            messages.success(request, "Bitácora en casa guardada correctamente.")
            return redirect(construir_url_regreso_bitacora(registro, origen_bitacora, next_bitacora))

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
            "origen_bitacora": origen_bitacora,
            "origen_historial": origen_bitacora == "historial",
            "next_bitacora": next_bitacora,
            "url_regresar_bitacora": construir_url_regreso_bitacora(registro, origen_bitacora, next_bitacora),
            "url_continuar_estancia_bitacora": construir_url_estancia_desde_bitacora(registro, origen_bitacora, next_bitacora),
            **contexto_perfil_maestra(request.user),
            **obtener_contexto_tomas_leche_bitacora(bitacora, request.POST if request.method == "POST" else None),
            **contexto_apoyo_sala_maestra(request.user, registro.dia_operativo),
        },
    )


def obtener_contexto_tomas_leche_bitacora(bitacora, post_data=None):
    def get_attr(obj, names):
        for name in names:
            if hasattr(obj, name):
                v = getattr(obj, name)
                if v not in [None, "", {}, []]:
                    return v
        return ""
    def split_qty(v):
        import re
        v = str(v or "").strip()
        m = re.match(r"^([0-9]+(?:[.,][0-9]+)?)\s*(oz|ml|l|L)?$", v, re.I)
        if not m: return v, "oz"
        return m.group(1).replace(",","."), (m.group(2) or "oz").upper().replace("ML","ml")
    ctx={}
    for i in [1,2,3]:
        hora = (post_data.get(f"leche_{i}_hora") if post_data else "") or get_attr(bitacora,[f"leche_{i}_hora", f"toma_leche_{i}_hora"])
        cantidad = (post_data.get(f"leche_{i}_cantidad") if post_data else "") or get_attr(bitacora,[f"leche_{i}_cantidad", f"toma_leche_{i}_cantidad"])
        data = get_attr(bitacora,[f"tomas_de_leche_{i}", f"toma_leche_{i}", f"leche_{i}"])
        if isinstance(data, dict):
            hora = hora or data.get("hora", "")
            cantidad = cantidad or data.get("cantidad", "")
        if hasattr(hora, "strftime"):
            hora = hora.strftime("%H:%M")
        num, unidad = split_qty(cantidad)
        ctx[f"leche_{i}_hora_val"] = str(hora or "")[:5]
        ctx[f"leche_{i}_cantidad_numero"] = num
        ctx[f"leche_{i}_unidad"] = unidad if unidad in ["oz","ml","L"] else "oz"
    return ctx

def aplicar_tomas_leche_desde_post(obj, post_data):
    for i in [1,2,3]:
        hora = (post_data.get(f"leche_{i}_hora") or "").strip()
        cantidad = (post_data.get(f"leche_{i}_cantidad") or "").strip()
        for campo, valor in [(f"leche_{i}_hora", hora or None), (f"leche_{i}_cantidad", cantidad)]:
            if hasattr(obj, campo): setattr(obj, campo, valor)
        data = {"hora": hora, "cantidad": cantidad} if (hora or cantidad) else {}
        for campo in [f"tomas_de_leche_{i}", f"toma_leche_{i}", f"leche_{i}"]:
            if hasattr(obj, campo): setattr(obj, campo, data)
    return obj


@login_required
def bitacora_estancia_maestra(request, registro_id):
    registro = obtener_registro_diario_para_maestra(request, registro_id)
    origen_bitacora = obtener_origen_bitacora(request)
    next_bitacora = obtener_next_seguro(request, "")

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
            return redirect(construir_url_regreso_bitacora(registro, origen_bitacora, next_bitacora))

        form = BitacoraEstanciaForm(
            request.POST,
            instance=bitacora,
            registro_diario=registro,
            tipo_formulario=registro.formulario_bitacora,
        )

        if form.is_valid():
            obj = form.save(commit=False)
            obj.capturada_por = request.user
            obj = aplicar_tomas_leche_desde_post(obj, request.POST)

            if form.cleaned_data.get("marcar_completa"):
                obj.completa = True
                obj.capturada_en = timezone.now()

            obj.save()
            registro.marcar_completo_si_corresponde()

            messages.success(request, "Bitácora durante estancia guardada correctamente.")
            return redirect(construir_url_regreso_bitacora(registro, origen_bitacora, next_bitacora))

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
            "origen_bitacora": origen_bitacora,
            "origen_historial": origen_bitacora == "historial",
            "next_bitacora": next_bitacora,
            "url_regresar_bitacora": construir_url_regreso_bitacora(registro, origen_bitacora, next_bitacora),
            "url_ver_casa_bitacora": construir_url_casa_desde_bitacora(registro, origen_bitacora, next_bitacora),
            **contexto_perfil_maestra(request.user),
            **obtener_contexto_tomas_leche_bitacora(bitacora, request.POST if request.method == "POST" else None),
            **contexto_apoyo_sala_maestra(request.user, registro.dia_operativo),
        },
    )


def construir_enlace_autorizacion_salida(request, autorizacion):
    """
    Construye el enlace público de salida usando únicamente el token.
    La URL no contiene nombre del menor, CURP, matrícula ni código de seguridad.
    """
    try:
        url = reverse("autorizar_salida_responsable", args=[str(autorizacion.token)])
    except Exception:
        url = f"/admisiones/a/s/{autorizacion.token}/"

    return request.build_absolute_uri(url)


def nombre_menor_autorizacion_salida(autorizacion):
    """
    Devuelve el nombre del menor para correos y pantallas de autorización de salida.
    """
    try:
        alumno = autorizacion.registro_diario.alumno
        solicitud = alumno.solicitud_ingreso
        if hasattr(solicitud, "nombre_menor_completo"):
            return solicitud.nombre_menor_completo()
    except Exception:
        pass

    try:
        return autorizacion.alumno_nombre
    except Exception:
        return "el menor"


def enviar_correo_autorizacion_salida(request, autorizacion):
    """
    Envía correo institucional al responsable autorizado para validar la salida.
    Si el responsable no tiene correo institucional, debe usarse QR presencial.
    """
    autorizacion.preparar_datos_responsable()
    correo_destino = (autorizacion.correo_destino or "").strip().lower()

    if not correo_destino:
        return False, "El responsable autorizado no tiene correo registrado. Debe usarse QR presencial."

    if not es_correo_institucional_unach_views(correo_destino):
        return False, "El responsable no tiene correo institucional UNACH. Debe usarse QR presencial."

    enlace = construir_enlace_autorizacion_salida(request, autorizacion)
    nombre_menor = nombre_menor_autorizacion_salida(autorizacion)
    responsable = autorizacion.responsable_nombre or "Responsable autorizado"
    maestra = usuario_nombre_legible(autorizacion.solicitada_por)

    fecha_txt = ""
    try:
        if autorizacion.fecha_operativa:
            fecha_txt = autorizacion.fecha_operativa.strftime("%d/%m/%Y")
    except Exception:
        fecha_txt = ""

    expira_txt = ""
    try:
        if autorizacion.expira_en:
            expira_txt = timezone.localtime(autorizacion.expira_en).strftime("%d/%m/%Y %H:%M")
    except Exception:
        expira_txt = ""

    asunto = f"Autorización de salida - {nombre_menor}"
    cuerpo = f"""Hola {responsable}:

La maestra {maestra} capturó una solicitud de salida para {nombre_menor} en la Estancia Infantil UNACH.

Resumen de la solicitud:
- Menor: {nombre_menor}
- Sala: {autorizacion.sala_nombre}
- Fecha: {fecha_txt or 'Hoy'}
- Responsable seleccionado: {autorizacion.responsable_nombre or responsable}
- Parentesco: {autorizacion.responsable_parentesco or 'No especificado'}
- Credencial verificada por maestra: {'Sí' if autorizacion.credencial_salida_validada else 'No'}
- Tipo de salida: {autorizacion.tipo_salida or 'Salida normal'}
- Motivo de salida: {autorizacion.motivo_salida or 'Sin motivo especial'}
- Observación de salida: {autorizacion.observacion_salida or 'Sin observaciones'}

Para autorizar la salida, abre este enlace desde tu celular y escribe tu código de seguridad de 4 dígitos:
{enlace}

Este enlace tiene vigencia limitada{f' hasta {expira_txt}' if expira_txt else ''}. Si no reconoces esta solicitud, no autorices la salida y comunícate con la estancia.

Atentamente,
Estancia Infantil UNACH
"""

    enviado, mensaje = enviar_correo_institucional_unach(
        asunto=asunto,
        cuerpo=cuerpo,
        destinatarios=[correo_destino],
        usuario_emisor=request.user,
    )

    if enviado:
        autorizacion.marcar_enviada()
        return True, "Correo de autorización de salida enviado correctamente."

    autorizacion.marcar_error(mensaje)
    return False, mensaje


def procesar_metodo_autorizacion_salida(request, autorizacion):
    """
    Decide qué hacer con la autorización de salida ya creada:
    - correo institucional UNACH: envía enlace por correo;
    - sin correo institucional: marca QR generado para mostrarlo en pantalla.
    """
    autorizacion.refresh_from_db()

    enlace = construir_enlace_autorizacion_salida(request, autorizacion)

    usa_correo = bool(
        getattr(autorizacion, "usa_correo", False)
        and es_correo_institucional(getattr(autorizacion, "correo_destino", ""))
    )

    if usa_correo:
        enviado, mensaje = enviar_correo_autorizacion_salida(request, autorizacion)
        return enviado, mensaje, enlace

    try:
        autorizacion.marcar_qr_generado()
        return True, "QR generado correctamente para autorización presencial de salida.", enlace
    except Exception as exc:
        autorizacion.marcar_error(exc)
        return False, f"No se pudo generar la autorización de salida por QR: {exc}", enlace


def obtener_autorizacion_salida_pendiente(registro):
    """
    Devuelve la solicitud de salida pendiente, enviada o con QR más reciente.
    """
    if not registro:
        return None

    qs = (
        AutorizacionSalida.objects
        .filter(
            registro_diario=registro,
            estado__in=[
                AutorizacionSalida.EstadoAutorizacion.PENDIENTE,
                AutorizacionSalida.EstadoAutorizacion.ENVIADA,
                AutorizacionSalida.EstadoAutorizacion.QR_GENERADO,
            ],
        )
        .select_related("responsable_autorizado", "solicitada_por")
        .order_by("-created_at")
    )

    autorizacion = qs.first()
    if autorizacion:
        try:
            autorizacion.expirar_si_corresponde()
        except Exception:
            pass
        if not autorizacion.esta_vigente:
            return None

    return autorizacion


@login_required
@require_http_methods(["POST"])
def cancelar_autorizacion_salida_maestra(request, autorizacion_id):
    """
    Permite a la maestra cancelar una solicitud pendiente de salida.
    """
    autorizacion = get_object_or_404(
        AutorizacionSalida.objects.select_related(
            "registro_diario",
            "registro_diario__dia_operativo",
            "registro_diario__alumno",
            "registro_diario__sala_semestre",
            "responsable_autorizado",
        ),
        pk=autorizacion_id,
    )

    registro = obtener_registro_diario_para_maestra(request, autorizacion.registro_diario_id)

    if autorizacion.solicitada_por_id and autorizacion.solicitada_por_id != request.user.id:
        messages.warning(
            request,
            "La solicitud fue creada por otra maestra. Solo puedes cancelarla si tienes permiso operativo sobre la sala."
        )

    motivo = (request.POST.get("motivo") or "Cancelada por la maestra desde el panel de salida.").strip()
    ok, errores = autorizacion.cancelar(usuario=request.user, motivo=motivo)

    if ok:
        messages.success(request, "Solicitud de autorización de salida cancelada correctamente.")
    else:
        for error in errores:
            messages.error(request, error)

    return redirect("registrar_salida_alumno", registro_id=registro.id)


def autorizar_salida_responsable(request, token):
    """
    Pantalla pública que abre el responsable desde correo o QR.
    Aquí revisa la información y autoriza/rechaza la salida con su código.
    """
    autorizacion = get_object_or_404(
        AutorizacionSalida.objects.select_related(
            "registro_diario",
            "registro_diario__dia_operativo",
            "registro_diario__alumno",
            "registro_diario__alumno__solicitud_ingreso",
            "registro_diario__sala_semestre",
            "registro_diario__sala_semestre__sala",
            "responsable_autorizado",
            "solicitada_por",
        ),
        token=token,
    )

    try:
        autorizacion.expirar_si_corresponde()
    except Exception:
        pass

    form = AutorizarSalidaResponsableForm(autorizacion=autorizacion)
    rechazo_form = RechazarAutorizacionSalidaForm(autorizacion=autorizacion)
    autorizada = False
    rechazada = False
    errores_operacion = []

    if request.method == "POST":
        accion = (request.POST.get("accion") or "AUTORIZAR").strip().upper()
        ip = obtener_ip_cliente(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:1000]

        if accion == "RECHAZAR":
            rechazo_form = RechazarAutorizacionSalidaForm(
                request.POST,
                autorizacion=autorizacion,
            )

            if rechazo_form.is_valid():
                rechazada, errores_operacion = rechazo_form.rechazar(
                    ip=ip,
                    user_agent=user_agent,
                )
                autorizacion.refresh_from_db()
            else:
                errores_operacion = [
                    str(error)
                    for errores in rechazo_form.errors.values()
                    for error in errores
                ]
        else:
            form = AutorizarSalidaResponsableForm(
                request.POST,
                autorizacion=autorizacion,
            )

            if form.is_valid():
                autorizada, errores_operacion = form.autorizar(
                    ip=ip,
                    user_agent=user_agent,
                )
                autorizacion.refresh_from_db()
            else:
                errores_operacion = [
                    str(error)
                    for errores in form.errors.values()
                    for error in errores
                ]

    return render(
        request,
        "admisiones/operacion_diaria/autorizar_salida.html",
        {
            "autorizacion": autorizacion,
            "form": form,
            "rechazo_form": rechazo_form,
            "autorizada": autorizada,
            "rechazada": rechazada,
            "errores_operacion": errores_operacion,
            "alumno_nombre": nombre_menor_autorizacion_salida(autorizacion),
        },
    )


@login_required
def estado_autorizacion_salida_maestra(request, registro_id):
    """
    Respuesta JSON para que la pantalla de la maestra consulte si el responsable ya autorizó salida.
    """
    registro = obtener_registro_diario_para_maestra(request, registro_id)
    autorizacion = (
        AutorizacionSalida.objects
        .filter(registro_diario=registro)
        .select_related("responsable_autorizado")
        .order_by("-created_at")
        .first()
    )

    if autorizacion:
        try:
            autorizacion.expirar_si_corresponde()
        except Exception:
            pass
        autorizacion.refresh_from_db()

    try:
        registro.refresh_from_db()
    except Exception:
        pass

    enlace_autorizacion = ""
    qr_data_uri = ""

    if autorizacion and getattr(autorizacion, "esta_vigente", False):
        enlace_autorizacion = construir_enlace_autorizacion_salida(request, autorizacion)
        if getattr(autorizacion, "usa_qr", False):
            qr_data_uri = generar_qr_data_uri(enlace_autorizacion)

    data = {
        "registro_id": registro.id,
        "salida_registrada": bool(registro.salida_en),
        "salida_en": timezone.localtime(registro.salida_en).strftime("%H:%M") if registro.salida_en else "",
        "estado": getattr(autorizacion, "estado", "SIN_SOLICITUD") if autorizacion else "SIN_SOLICITUD",
        "estado_display": autorizacion.get_estado_display() if autorizacion else "Sin solicitud",
        "metodo_autorizacion": getattr(autorizacion, "metodo_autorizacion", "") if autorizacion else "",
        "usa_qr": bool(getattr(autorizacion, "usa_qr", False)) if autorizacion else False,
        "usa_correo": bool(getattr(autorizacion, "usa_correo", False)) if autorizacion else False,
        "responsable": getattr(autorizacion, "responsable_nombre", "") if autorizacion else "",
        "ultimo_error": getattr(autorizacion, "ultimo_error", "") if autorizacion else "",
        "enlace_autorizacion": enlace_autorizacion,
        "qr_data_uri": qr_data_uri,
        "redirect_url": "",
    }

    if registro.salida_en:
        try:
            data["redirect_url"] = reverse("lista_alumnos_dia_maestra", args=[registro.dia_operativo_id])
        except Exception:
            data["redirect_url"] = ""

    return JsonResponse(data)


@login_required
def registrar_salida_alumno(request, registro_id):
    """
    Flujo de salida con autorización en tableta.

    La maestra captura la información de salida, selecciona al responsable
    autorizado y revisa el resumen en una ventana flotante. Después entrega
    la tableta al responsable para que escriba su código de 4 dígitos.

    Ya no se envía correo ni se genera QR para este proceso. La salida queda
    registrada en el mismo momento únicamente si el código coincide con el
    tutor o familiar autorizado seleccionado.
    """
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
        form = SolicitarAutorizacionSalidaForm(
            request.POST,
            registro_diario=registro,
            usuario=request.user,
        )

        responsable_codigo, errores_codigo = obtener_responsable_operacion_desde_post(
            registro,
            request.POST,
            prefijo="salida",
        )

        form_valido = form.is_valid() or not errores_form_sin_codigo(form)

        if form_valido and not errores_codigo:
            try:
                with transaction.atomic():
                    registro_bloqueado = (
                        RegistroDiarioAlumno.objects
                        .select_for_update()
                        .select_related("dia_operativo", "alumno", "sala_semestre")
                        .get(pk=registro.pk)
                    )

                    if registro_bloqueado.salida_en:
                        messages.info(request, "Este alumno ya tiene salida registrada.")
                        return redirect("lista_alumnos_dia_maestra", dia_id=registro.dia_operativo_id)

                    datos_salida = datos_salida_desde_form_o_post(
                        form,
                        request.POST,
                        responsable_autorizado=responsable_codigo,
                    )

                    responsable_nombre = (
                        datos_salida.get("responsable_nombre")
                        or getattr(responsable_codigo, "nombre_completo", "")
                        or "Responsable autorizado"
                    )
                    responsable_parentesco = (
                        datos_salida.get("responsable_parentesco")
                        or getattr(responsable_codigo, "parentesco", "")
                        or ""
                    )
                    responsable_telefono = (
                        datos_salida.get("responsable_telefono")
                        or getattr(responsable_codigo, "telefono", "")
                        or ""
                    )

                    campos_registro = {
                        "salida_en": timezone.now(),
                        "salida_por": request.user,
                        "responsable_salida_nombre": responsable_nombre,
                        "responsable_salida_parentesco": responsable_parentesco,
                        "responsable_salida_telefono": responsable_telefono,
                        "credencial_salida_validada": bool(datos_salida.get("credencial_validada")),
                        "codigo_salida_validado": True,
                        "tipo_salida": datos_salida.get("tipo_salida") or "NORMAL",
                        "motivo_salida": datos_salida.get("motivo_salida") or "",
                        "observacion_salida": datos_salida.get("observacion_salida") or "",
                    }

                    update_fields = []
                    for campo, valor in campos_registro.items():
                        if hasattr(registro_bloqueado, campo):
                            setattr(registro_bloqueado, campo, valor)
                            update_fields.append(campo)

                    if hasattr(registro_bloqueado, "updated_at"):
                        update_fields.append("updated_at")

                    if update_fields:
                        registro_bloqueado.save(update_fields=list(dict.fromkeys(update_fields)))
                    else:
                        registro_bloqueado.save()

                    autorizacion_pendiente_actual = obtener_autorizacion_salida_pendiente(registro_bloqueado)
                    if autorizacion_pendiente_actual:
                        try:
                            autorizacion_pendiente_actual.cancelar(
                                usuario=request.user,
                                motivo="Cancelada automáticamente porque la salida se autorizó en tableta.",
                            )
                        except Exception:
                            pass

                messages.success(
                    request,
                    "Salida registrada correctamente. El responsable autorizado escribió su código en la tableta y fue validado."
                )
                return redirect("lista_alumnos_dia_maestra", dia_id=registro.dia_operativo_id)

            except Exception as exc:
                messages.error(request, f"No se pudo registrar la salida en tableta: {exc}")
        else:
            errores_formulario = errores_form_sin_codigo(form)
            if errores_formulario:
                messages.error(request, "No se pudo registrar la salida. Revisa los campos capturados.")
                for campo, errores in errores_formulario.items():
                    for error in errores:
                        messages.error(request, f"{campo}: {error}")

            for error in errores_codigo:
                messages.error(request, error)

            if not errores_formulario and errores_codigo:
                messages.error(
                    request,
                    "La salida no se registró porque el código del responsable no fue validado."
                )
    else:
        form = SolicitarAutorizacionSalidaForm(
            registro_diario=registro,
            usuario=request.user,
        )

    autorizacion_pendiente = obtener_autorizacion_salida_pendiente(registro)
    bitacora_casa = BitacoraEntradaCasa.objects.filter(registro_diario=registro).first()
    bitacora_estancia = BitacoraEstancia.objects.filter(registro_diario=registro).first()
    enlace_autorizacion = ""
    qr_data_uri = ""

    autorizaciones_salida = (
        AutorizacionSalida.objects
        .filter(registro_diario=registro)
        .select_related("responsable_autorizado", "solicitada_por")
        .order_by("-created_at")[:5]
    )

    return render(
        request,
        "admisiones/operacion_diaria/registrar_salida.html",
        {
            "form": form,
            "registro": registro,
            "responsables_codigo": responsables_codigo,
            "tipo_formulario": registro.formulario_bitacora,
            "dia": registro.dia_operativo,
            "flujo_autorizacion_salida": True,
            "flujo_autorizacion_tableta": True,
            "flujo_autorizacion_por_correo": False,
            "flujo_autorizacion_por_qr": False,
            "autorizacion_pendiente": autorizacion_pendiente,
            "autorizacion_pendiente_url": enlace_autorizacion,
            "qr_data_uri": qr_data_uri,
            "autorizaciones_salida": autorizaciones_salida,
            **contexto_perfil_maestra(request.user),
            "bitacora_casa": bitacora_casa,
            "bitacora_estancia": bitacora_estancia,
            **contexto_apoyo_sala_maestra(request.user, registro.dia_operativo),
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

    apoyo_activo = obtener_apoyo_sala_activo_usuario(request.user)
    if apoyo_activo:
        messages.warning(
            request,
            "No puedes cerrar el día porque tienes un apoyo temporal abierto. "
            "Finaliza el apoyo y regresa a tu sala original."
        )
        return redirect("lista_alumnos_dia_maestra", dia_id=dia.id)

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
            **contexto_apoyo_sala_maestra(request.user, dia),
        },
    )


@login_required
def historial_alumno_maestra(request, alumno_id):
    """
    Historial diario del alumno.
    La maestra solo puede verlo si el alumno pertenece a una de sus salas asignadas
    en el semestre activo o a la sala apoyada temporalmente.
    """
    semestre = obtener_semestre_activo_operativo()
    salas = obtener_salas_maestra_operativas(request.user, semestre=semestre)

    alumno = get_object_or_404(
        SolicitudInscripcion.objects.select_related("solicitud_ingreso", "sala_semestre_asignada", "semestre"),
        pk=alumno_id,
        sala_semestre_asignada__in=salas,
    )

    url_regresar_historial = obtener_next_seguro(request, reverse("dashboard_maestra") + "#historial-alumnos")

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
            "url_regresar_historial": url_regresar_historial,
            "foto_perfil_maestra_url": obtener_foto_perfil_usuario(request.user),
            "incidencias": Incidencia.objects.filter(alumno=alumno).select_related(
                "dia_operativo",
                "sala_semestre",
                "sala_semestre__sala",
                "registrada_por",
            ).order_by("-fecha_reporte"),
            **contexto_apoyo_sala_maestra(request.user, obtener_dia_operativo_actual_maestra(request.user, semestre=semestre)),
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
    Panel de Coordinadora de Sala con datos reales.

    - Muestra únicamente incidencias pedagógicas para Coordinadora de Sala.
    - Calcula totales reales del semestre activo.
    - Permite filtrar por mis incidencias, abiertas, cerradas y riesgo alto
      desde el mismo dashboard, sin enviar a la pantalla general de Admin/Directora.
    """
    if not (
        usuario_es_coordinadora_sala(request.user)
        or usuario_es_admin(request.user)
        or usuario_es_directora(request.user)
    ):
        messages.error(request, "No tienes permiso para entrar al panel de Coordinadora de Sala.")
        return redirect("/")

    # Foto de perfil desde el panel principal de Coordinación de Sala.
    # El HTML envía:
    # - action_type=actualizar_foto_coordinadora
    # - action_type=eliminar_foto_coordinadora
    if request.method == "POST":
        respuesta_foto = procesar_foto_perfil_area(
            request,
            destino_url=reverse("dashboard_coordinadora") + "#inicio",
            campo_archivo="foto_perfil_coordinadora",
            action_actualizar="actualizar_foto_coordinadora",
            action_eliminar="eliminar_foto_coordinadora",
            nombre_area="Coordinadora de Sala",
        )

        if respuesta_foto:
            return respuesta_foto

    semestre = obtener_semestre_activo_operativo()
    modo_solo_consulta = not hay_semestre_activo_operativo()
    seccion = (request.GET.get("seccion") or request.GET.get("vista") or "dashboard").strip().lower()
    estado = (request.GET.get("estado") or "").strip().upper()
    nivel = (request.GET.get("nivel") or "").strip().upper()
    q = (request.GET.get("q") or "").strip()

    incidencias_base = incidencias_pedagogicas_base_coordinadora(semestre=semestre)
    incidencias_propias_qs = incidencias_base.filter(registrada_por=request.user)

    # Filtros de navegación del dashboard.
    incidencias_filtradas = incidencias_base

    if seccion in ["mis", "mis_incidencias", "propias"]:
        incidencias_filtradas = incidencias_propias_qs
    elif seccion in ["abiertas", "pendientes"]:
        incidencias_filtradas = incidencias_filtradas.filter(estado=Incidencia.EstadoIncidencia.ABIERTA)
    elif seccion in ["cerradas", "historial"]:
        incidencias_filtradas = incidencias_filtradas.filter(estado=Incidencia.EstadoIncidencia.CERRADA)
    elif seccion in ["alto", "riesgo_alto", "riesgo"]:
        incidencias_filtradas = incidencias_filtradas.filter(nivel=Incidencia.NivelChoices.ALTO)

    # Compatibilidad con botones que mandan estado=ABIERTA/CERRADA desde panel_incidencias.
    if estado in ["ABIERTA", "CERRADA"]:
        incidencias_filtradas = incidencias_filtradas.filter(estado=estado)
        seccion = "abiertas" if estado == "ABIERTA" else "cerradas"

    if nivel in ["ALTO", "MEDIO", "BAJO", "LEVE"]:
        incidencias_filtradas = incidencias_filtradas.filter(nivel=nivel)
        if nivel == "ALTO":
            seccion = "riesgo_alto"

    if q:
        incidencias_filtradas = incidencias_filtradas.filter(
            Q(descripcion__icontains=q)
            | Q(intervencion_personal__icontains=q)
            | Q(resolucion__icontains=q)
            | Q(subtipo__icontains=q)
            | Q(alumno__solicitud_ingreso__nombres_menor__icontains=q)
            | Q(alumno__solicitud_ingreso__apellido_paterno_menor__icontains=q)
            | Q(alumno__solicitud_ingreso__apellido_materno_menor__icontains=q)
            | Q(sala_semestre__sala__nombre__icontains=q)
        )

    resumen_incidencias = resumen_incidencias_pedagogicas(incidencias_base)
    resumen_propias = resumen_incidencias_pedagogicas(incidencias_propias_qs)

    # Gráfica real sin duplicar registros:
    # Riesgo alto se separa como prioridad visual y no se suma otra vez en abiertas/cerradas.
    total_grafica_riesgo_alto = incidencias_base.filter(
        nivel=Incidencia.NivelChoices.ALTO
    ).count()
    total_grafica_abiertas = incidencias_base.filter(
        estado=Incidencia.EstadoIncidencia.ABIERTA
    ).exclude(
        nivel=Incidencia.NivelChoices.ALTO
    ).count()
    total_grafica_cerradas = incidencias_base.filter(
        estado=Incidencia.EstadoIncidencia.CERRADA
    ).exclude(
        nivel=Incidencia.NivelChoices.ALTO
    ).count()

    total_alumnos = 0
    total_salas = 0
    dia_operativo_actual = obtener_dia_operativo_actual_incidencias(semestre)

    if semestre:
        total_alumnos = SolicitudInscripcion.objects.filter(
            semestre=semestre,
            estado="FINALIZADA",
        ).count()
        total_salas = SalaSemestre.objects.filter(
            semestre=semestre,
            activa=True,
        ).count()

    # Datos sencillos para gráficas del HTML.
    # La gráfica separa riesgo alto para no duplicar porcentajes.
    grafica_incidencias_pedagogicas = [
        {
            "label": "Cerradas",
            "valor": total_grafica_cerradas,
            "porcentaje": porcentaje_panel(total_grafica_cerradas, resumen_incidencias["total"]),
        },
        {
            "label": "Abiertas",
            "valor": total_grafica_abiertas,
            "porcentaje": porcentaje_panel(total_grafica_abiertas, resumen_incidencias["total"]),
        },
        {
            "label": "Riesgo alto",
            "valor": total_grafica_riesgo_alto,
            "porcentaje": porcentaje_panel(total_grafica_riesgo_alto, resumen_incidencias["total"]),
        },
    ]

    incidencias_filtradas = incidencias_filtradas.annotate(
        total_seguimientos=Count("seguimientos", distinct=True)
    ).order_by("-fecha_reporte")

    return render(
        request,
        "admisiones/dashboard_coordinadora.html",
        {
            "semestre": semestre,
            "semestre_activo_operativo": semestre,
            "modo_solo_consulta": modo_solo_consulta,
            "dia_operativo_actual": dia_operativo_actual,
            "fecha_operativa_actual": getattr(dia_operativo_actual, "fecha", None) or timezone.localdate(),
            "seccion_actual": seccion,
            "filtros": {
                "seccion": seccion,
                "estado": estado,
                "nivel": nivel,
                "q": q,
                "tipo": Incidencia.TipoIncidencia.PEDAGOGICA,
            },

            # Listados para el dashboard y para el apartado Mis incidencias.
            "incidencias_pedagogicas": incidencias_filtradas[:50],
            "incidencias_tabla": incidencias_filtradas[:100],
            "mis_incidencias": incidencias_propias_qs.order_by("-fecha_reporte")[:50],
            "incidencias_propias": incidencias_propias_qs.order_by("-fecha_reporte")[:50],
            "ultimas_incidencias": incidencias_base.order_by("-fecha_reporte")[:8],
            "incidencias_abiertas": incidencias_base.filter(
                estado=Incidencia.EstadoIncidencia.ABIERTA
            ).order_by("-fecha_reporte")[:20],
            "incidencias_cerradas": incidencias_base.filter(
                estado=Incidencia.EstadoIncidencia.CERRADA
            ).order_by("-fecha_reporte")[:20],
            "incidencias_alto": incidencias_base.filter(
                nivel=Incidencia.NivelChoices.ALTO
            ).order_by("-fecha_reporte")[:20],

            # Totales directos para el HTML rediseñado.
            "resumen_incidencias": resumen_incidencias,
            "resumen_propias": resumen_propias,
            "total_pedagogicas": resumen_incidencias["total"],
            "total_abiertas": resumen_incidencias["abiertas"],
            "total_cerradas": resumen_incidencias["cerradas"],
            "total_riesgo_alto": resumen_incidencias["riesgo_alto"],
            "total_sin_seguimiento": resumen_incidencias["sin_seguimiento"],
            "total_grafica_cerradas": total_grafica_cerradas,
            "total_grafica_abiertas": total_grafica_abiertas,
            "total_grafica_riesgo_alto": total_grafica_riesgo_alto,
            "porcentaje_grafica_cerradas": porcentaje_panel(total_grafica_cerradas, resumen_incidencias["total"]),
            "porcentaje_grafica_abiertas": porcentaje_panel(total_grafica_abiertas, resumen_incidencias["total"]),
            "porcentaje_grafica_riesgo_alto": porcentaje_panel(total_grafica_riesgo_alto, resumen_incidencias["total"]),
            "foto_perfil_coordinadora_url": obtener_foto_perfil_usuario(request.user),
            "perfil_coordinadora_soporta_foto": bool(obtener_campo_foto_perfil_usuario(request.user)),
            "total_mis_incidencias": resumen_propias["total"],
            "total_mis_abiertas": resumen_propias["abiertas"],
            "total_mis_cerradas": resumen_propias["cerradas"],
            "porcentaje_abiertas": resumen_incidencias["porcentaje_abiertas"],
            "porcentaje_cerradas": resumen_incidencias["porcentaje_cerradas"],
            "porcentaje_riesgo_alto": resumen_incidencias["porcentaje_riesgo_alto"],
            "porcentaje_sin_seguimiento": resumen_incidencias["porcentaje_sin_seguimiento"],
            "grafica_incidencias_pedagogicas": grafica_incidencias_pedagogicas,
            "total_alumnos": total_alumnos,
            "total_salas": total_salas,
            **contexto_suplencias_usuario(request.user),
            **contexto_semestre_operativo(),
        },
    )


@login_required
def ajax_registro_diario_incidencia(request):
    """
    Devuelve por AJAX el registro diario del alumno para la fecha actual.
    Útil para que crear_incidencia.html muestre solo la fecha automática,
    sin dejar fijo el nombre de otro menor.
    """
    if not usuario_puede_ver_incidencias(request.user):
        return JsonResponse({"ok": False, "error": "Sin permiso."}, status=403)

    semestre = obtener_semestre_activo_operativo()
    alumno_id = request.GET.get("alumno") or request.GET.get("alumno_id")

    alumno = (
        SolicitudInscripcion.objects
        .filter(pk=alumno_id, estado="FINALIZADA")
        .select_related("solicitud_ingreso", "semestre", "sala_semestre_asignada", "sala_semestre_asignada__sala")
        .first()
    )

    if not alumno:
        return JsonResponse({"ok": False, "error": "No se encontró el alumno."}, status=404)

    if semestre and getattr(alumno, "semestre_id", None) != semestre.id:
        return JsonResponse({"ok": False, "error": "El alumno no pertenece al semestre activo."}, status=400)

    registro = obtener_registro_diario_actual_para_alumno(alumno, semestre=semestre)
    fecha = timezone.localdate()

    return JsonResponse({
        "ok": True,
        "alumno": {
            "id": alumno.id,
            "nombre": nombre_menor_desde_inscripcion(alumno),
        },
        "fecha": fecha.isoformat(),
        "fecha_display": fecha.strftime("%d/%m/%Y"),
        "registro": serializar_registro_diario_incidencia(registro),
        "mensaje": "Registro diario encontrado." if registro else "No hay registro diario abierto para este alumno en la fecha actual.",
    })


@login_required
def ajax_alumnos_incidencia(request):
    """
    Búsqueda liviana de alumnos finalizados para Select2.
    Si el HTML no usa AJAX, el select normal de IncidenciaForm sigue funcionando.
    """
    if not usuario_puede_ver_incidencias(request.user):
        return JsonResponse({"results": []}, status=403)

    semestre = obtener_semestre_activo_operativo()
    q = (request.GET.get("q") or "").strip()

    alumnos = (
        SolicitudInscripcion.objects
        .filter(estado="FINALIZADA")
        .select_related("solicitud_ingreso", "semestre", "sala_semestre_asignada", "sala_semestre_asignada__sala")
    )

    if semestre:
        alumnos = alumnos.filter(semestre=semestre)

    if q:
        alumnos = alumnos.filter(
            Q(solicitud_ingreso__nombres_menor__icontains=q)
            | Q(solicitud_ingreso__apellido_paterno_menor__icontains=q)
            | Q(solicitud_ingreso__apellido_materno_menor__icontains=q)
            | Q(solicitud_ingreso__folio__icontains=q)
        )

    results = []
    for alumno in alumnos.order_by(
        "solicitud_ingreso__apellido_paterno_menor",
        "solicitud_ingreso__apellido_materno_menor",
        "solicitud_ingreso__nombres_menor",
    )[:30]:
        sala = ""
        if getattr(alumno, "sala_semestre_asignada", None) and alumno.sala_semestre_asignada.sala:
            sala = alumno.sala_semestre_asignada.sala.nombre

        results.append({
            "id": alumno.id,
            "text": nombre_menor_desde_inscripcion(alumno),
            "sala": sala,
        })

    return JsonResponse({"results": results})


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

# =========================================================
# PANEL SUPERVISORA GENERAL / SECRETARÍA DE DIRECCIÓN
# Solo consulta: no crea, no edita, no elimina información.
# Este panel usa un único HTML:
# admisiones/templates/admisiones/panel_supervisor.html
# =========================================================

def usuario_es_supervisora_general(user):
    """
    Valida el acceso al panel de Supervisora General / Secretaría de Dirección.

    Reglas:
    - Administrador del Sistema puede entrar para pruebas y soporte.
    - Usuario con tipo_persona SUPERVISOR puede entrar.
    - Grupos con nombres relacionados a supervisión o secretaría de dirección pueden entrar.
    - La vista es únicamente de consulta.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if usuario_es_admin(user) or usuario_es_admin_sistema(user):
        return True

    tipo_persona = normalizar_texto(getattr(user, "tipo_persona", ""))

    if tipo_persona in [
        "supervisor",
        "supervisora",
        "supervisora general",
        "supervisor general",
        "secretaria direccion",
        "secretaria de direccion",
        "secretario direccion",
        "secretario de direccion",
    ]:
        return True

    roles = obtener_roles_usuario(user)

    palabras_validas = [
        "supervisor",
        "supervisora",
        "supervision",
        "supervision general",
        "supervisora general",
        "supervisor general",
        "secretaria direccion",
        "secretaria de direccion",
        "secretario direccion",
        "secretario de direccion",
    ]

    for rol in roles:
        if any(palabra in rol for palabra in palabras_validas):
            return True

    return False


def obtener_estado_incidencia_supervisor():
    """
    Devuelve los valores de estado disponibles en el modelo Incidencia.
    Se deja protegido para evitar errores si cambian los choices del modelo.
    """
    abierta = "ABIERTA"
    cerrada = "CERRADA"

    try:
        abierta = Incidencia.EstadoIncidencia.ABIERTA
        cerrada = Incidencia.EstadoIncidencia.CERRADA
    except Exception:
        pass

    return abierta, cerrada


def obtener_nivel_alto_incidencia_supervisor():
    """
    Devuelve el valor de riesgo alto disponible en el modelo Incidencia.
    """
    try:
        return Incidencia.NivelChoices.ALTO
    except Exception:
        return "ALTO"


def actividad_actual_sala_supervisor(sala_semestre):
    """
    Calcula una descripción corta de la actividad actual de una sala
    usando los horarios configurados en SalaSemestre.
    """
    if not sala_semestre:
        return "Sin configuración"

    ahora = timezone.localtime(timezone.now()).time()

    actividades = [
        ("Recepción", "recepcion_inicio", "recepcion_fin"),
        ("Desayuno", "desayuno_inicio", "desayuno_fin"),
        ("Actividad pedagógica", "actividad_pedagogica_inicio", "actividad_pedagogica_fin"),
        ("Recreo", "recreo_inicio", "recreo_fin"),
        ("Colación", "colacion_inicio", "colacion_fin"),
        ("Siesta", "siesta_inicio", "siesta_fin"),
        ("Comida", "comida_inicio", "comida_fin"),
    ]

    for nombre, campo_inicio, campo_fin in actividades:
        inicio = getattr(sala_semestre, campo_inicio, None)
        fin = getattr(sala_semestre, campo_fin, None)

        if inicio and fin and inicio <= ahora <= fin:
            if nombre == "Actividad pedagógica":
                actividad_nombre = (getattr(sala_semestre, "actividad_pedagogica_nombre", "") or "").strip()
                return actividad_nombre or nombre
            return nombre

    entrada_maestras = getattr(sala_semestre, "entrada_maestras", None)
    salida_maestras = getattr(sala_semestre, "salida_maestras", None)

    if entrada_maestras and salida_maestras and entrada_maestras <= ahora <= salida_maestras:
        return "Operación normal"

    return "Fuera de horario"


def preparar_salas_supervisor(salas_qs, alumnos_qs, registros_hoy, dia_actual=None):
    """
    Construye el resumen por sala para el panel de supervisión.
    """
    salas = []

    for sala_semestre in salas_qs.select_related("sala", "semestre", "sala__sede"):
        alumnos_sala = alumnos_qs.filter(sala_semestre_asignada=sala_semestre)
        total = alumnos_sala.count()

        registros_sala = registros_hoy.filter(sala_semestre=sala_semestre)
        indicadores_sala = calcular_indicadores_ninos_operacion(
            total,
            registros_hoy=registros_sala,
            dia_actual=dia_actual,
            alumnos_qs=alumnos_sala,
        )
        presentes = indicadores_sala["ninos_en_estancia"]
        ausentes = indicadores_sala["ninos_ausentes"]
        salieron = indicadores_sala["ninos_fuera_estancia"]

        maestras = (
            AsignacionMaestra.objects
            .filter(sala_semestre=sala_semestre, activo=True)
            .select_related("maestra")
            .order_by("maestra__nombre", "maestra__apellido_paterno")
        )

        responsables = [nombre_usuario_panel(asignacion.maestra) for asignacion in maestras[:3]]
        responsable_txt = ", ".join(responsables) if responsables else "Sin maestra asignada"

        capacidad = getattr(sala_semestre, "cupo", None) or getattr(sala_semestre, "cupo_real", None) or 0
        ocupacion = porcentaje_panel(total, capacidad) if capacidad else 0

        if presentes > 0:
            estado = "Activa"
        elif total > 0:
            estado = "Pendiente"
        else:
            estado = "Sin alumnos"

        salas.append({
            "id": sala_semestre.id,
            "nombre": getattr(getattr(sala_semestre, "sala", None), "nombre", "Sala"),
            "sede": getattr(getattr(getattr(sala_semestre, "sala", None), "sede", None), "nombre", ""),
            "responsable": responsable_txt,
            "total_alumnos": total,
            "presentes": presentes,
            "ausentes": ausentes,
            "salieron": salieron,
            "capacidad": capacidad,
            "ocupacion": ocupacion,
            "actividad_actual": actividad_actual_sala_supervisor(sala_semestre),
            "estado": estado,
        })

    return salas


def preparar_incidencias_supervisor(incidencias_qs):
    """
    Prepara filas resumidas de incidencias para consulta.
    """
    filas = []

    for incidencia in incidencias_qs[:100]:
        alumno = getattr(incidencia, "alumno", None)
        sala_semestre = getattr(incidencia, "sala_semestre", None)
        sala = getattr(sala_semestre, "sala", None)

        fecha = (
            getattr(incidencia, "fecha_reporte", None)
            or getattr(incidencia, "created_at", None)
            or getattr(incidencia, "fecha_registro", None)
        )

        if fecha:
            try:
                fecha_txt = timezone.localtime(fecha).strftime("%d/%m/%Y %H:%M")
            except Exception:
                fecha_txt = str(fecha)
        else:
            fecha_txt = "--"

        filas.append({
            "id": incidencia.id,
            "folio": getattr(incidencia, "folio", "") or f"INC-{incidencia.id}",
            "tipo": getattr(incidencia, "tipo", "") or "--",
            "categoria": getattr(incidencia, "categoria", "") or getattr(incidencia, "subtipo", "") or "--",
            "nivel": getattr(incidencia, "nivel", "") or "--",
            "estado": getattr(incidencia, "estado", "") or "--",
            "fecha": fecha_txt,
            "alumno": nombre_menor_desde_inscripcion(alumno) if alumno else "Sin alumno",
            "sala": getattr(sala, "nombre", "") or "Sin sala",
            "registrada_por": nombre_usuario_panel(getattr(incidencia, "registrada_por", None)),
            "descripcion": getattr(incidencia, "descripcion", "") or "",
        })

    return filas




def obtener_mejor_semestre_supervisor():
    """Devuelve el semestre con más niñas y niños finalizados usando datos reales."""
    mejor = {
        "id": "",
        "nombre": "Sin datos",
        "total_ninos": 0,
        "fecha_inicio": "",
        "fecha_fin": "",
    }

    for semestre in Semestre.objects.order_by("-fecha_inicio", "-id"):
        total = SolicitudInscripcion.objects.filter(
            semestre=semestre,
            estado="FINALIZADA",
        ).count()

        if total > mejor["total_ninos"]:
            mejor = {
                "id": semestre.id,
                "nombre": getattr(semestre, "nombre", "Semestre"),
                "total_ninos": total,
                "fecha_inicio": getattr(semestre, "fecha_inicio", None),
                "fecha_fin": getattr(semestre, "fecha_fin", None),
            }

    return mejor



# =========================================================
# AUXILIARES ESPECÍFICOS - PANEL SUPERVISORA ACTUALIZADO
# =========================================================

def obtener_nombre_menor_solicitud_supervisor(solicitud):
    """Nombre legible del menor para solicitudes de ingreso activas."""
    if not solicitud:
        return "Solicitud de ingreso"

    for attr in ("nombre_menor_completo", "nombre_completo_menor", "menor_nombre_completo"):
        valor = getattr(solicitud, attr, None)
        if callable(valor):
            try:
                valor = valor()
            except Exception:
                valor = ""
        if valor:
            return str(valor).strip().title()

    partes = [
        getattr(solicitud, "nombres_menor", "") or "",
        getattr(solicitud, "apellido_paterno_menor", "") or "",
        getattr(solicitud, "apellido_materno_menor", "") or "",
    ]
    nombre = " ".join(str(p).strip() for p in partes if str(p or "").strip()).strip()
    return nombre.title() if nombre else "Menor pendiente"


def valor_sexo_menor_inscripcion(inscripcion):
    """
    Normaliza el sexo del menor desde Solicitud o SolicitudInscripcion.
    Devuelve: MASCULINO, FEMENINO o cadena vacía.
    """
    objetos = [getattr(inscripcion, "solicitud_ingreso", None), inscripcion]
    campos = ["sexo_menor", "sexo", "genero_menor", "genero"]

    for obj in objetos:
        if not obj:
            continue
        for campo in campos:
            if not hasattr(obj, campo):
                continue
            valor_original = getattr(obj, campo, "")
            valor = normalizar_texto(valor_original)
            valor = valor.replace("_", " ").strip()
            if not valor:
                continue

            if valor in ["m", "masc", "masculino", "h", "hombre", "nino", "niño"] or "mascul" in valor:
                return "MASCULINO"
            if valor in ["f", "fem", "femenino", "mujer", "nina", "niña"] or "femen" in valor:
                return "FEMENINO"

    return ""


def contar_sexo_inscripciones_supervisor(alumnos_qs):
    """Cuenta niños y niñas desde el expediente de inscripción."""
    total_ninos = 0
    total_ninas = 0

    try:
        iterable = alumnos_qs.select_related("solicitud_ingreso")
    except Exception:
        iterable = alumnos_qs or []

    for inscripcion in iterable:
        sexo = valor_sexo_menor_inscripcion(inscripcion)
        if sexo == "MASCULINO":
            total_ninos += 1
        elif sexo == "FEMENINO":
            total_ninas += 1

    return total_ninos, total_ninas


def registro_tiene_entrada_supervisor(registro):
    return bool(registro and getattr(registro, "entrada_en", None))


def registro_indica_salida_anticipada_supervisor(registro):
    """
    Detecta salidas anticipadas sin depender de un único nombre de campo.
    Si el modelo tiene tipo_salida/motivo/observación, se revisan palabras clave.
    """
    if not registro or not getattr(registro, "salida_en", None):
        return False

    campos_booleanos = [
        "salida_anticipada",
        "es_salida_anticipada",
        "retirado_anticipadamente",
        "retiro_anticipado",
    ]
    for campo in campos_booleanos:
        if hasattr(registro, campo) and bool(getattr(registro, campo)):
            return True

    campos_texto = [
        "tipo_salida",
        "motivo_salida",
        "observacion_salida",
        "observaciones_salida",
        "motivo_retiro",
        "observaciones",
    ]
    palabras = [
        "anticipada",
        "anticipado",
        "retiro",
        "retirado",
        "retirada",
        "incidencia",
        "enfermedad",
        "malestar",
        "permiso",
    ]

    for campo in campos_texto:
        if not hasattr(registro, campo):
            continue
        valor = normalizar_texto(getattr(registro, campo, ""))
        if valor and any(palabra in valor for palabra in palabras):
            return True

    return False


def contar_salidas_anticipadas_supervisor(registros_hoy):
    try:
        registros = list(registros_hoy or [])
    except Exception:
        registros = []
    return sum(1 for registro in registros if registro_indica_salida_anticipada_supervisor(registro))


def calcular_asistencia_dia_supervisor(total_inscritos, registros_hoy=None, dia_actual=None):
    """
    Porcentaje del día: niñas y niños con entrada registrada / total inscritos.
    Incluye a quienes ya salieron, porque sí asistieron ese día.
    """
    try:
        total_inscritos = int(total_inscritos or 0)
    except Exception:
        total_inscritos = 0

    if total_inscritos <= 0 or not dia_operativo_tiene_operacion_ninos(dia_actual):
        return 0, 0

    try:
        asistencias = sum(1 for registro in registros_hoy if registro_tiene_entrada_supervisor(registro))
    except Exception:
        asistencias = 0

    return asistencias, porcentaje_panel(asistencias, total_inscritos)


def calcular_promedio_asistencia_mensual_supervisor(semestre=None, sede=None, fecha_referencia=None):
    """
    Promedio mensual de asistencia:
    - Se calcula por día válido del mes actual.
    - Solo se consideran días hábiles cerrados; si hoy ya está cerrado, entra al cálculo.
    - Cada día aporta su propio porcentaje: asistencias con entrada / inscritos de esa sede.
    - El promedio final es la suma de porcentajes diarios dividida entre los días considerados.
    """
    if not semestre:
        return {
            "promedio": 0,
            "dias_considerados": 0,
            "detalle": [],
        }

    fecha_referencia = fecha_referencia or timezone.localdate()

    dias_qs = (
        DiaOperativoSemestre.objects
        .filter(
            semestre=semestre,
            es_habil=True,
            fecha__year=fecha_referencia.year,
            fecha__month=fecha_referencia.month,
            fecha__lte=fecha_referencia,
        )
        .order_by("fecha")
    )

    try:
        dias_qs = dias_qs.filter(estado=DiaOperativoSemestre.EstadoDia.CERRADO)
    except Exception:
        dias_qs = dias_qs.filter(estado="CERRADO")

    porcentajes = []
    detalle = []

    for dia in dias_qs:
        alumnos_dia_qs = (
            SolicitudInscripcion.objects
            .filter(estado="FINALIZADA", semestre=semestre)
            .select_related("solicitud_ingreso", "semestre", "sala_semestre_asignada", "sala_semestre_asignada__sala")
        )
        alumnos_dia_qs = qs_por_semestre_y_sede(alumnos_dia_qs, semestre, sede)
        total_dia = alumnos_dia_qs.count()

        if total_dia <= 0:
            continue

        registros_dia = RegistroDiarioAlumno.objects.filter(
            dia_operativo=dia,
            alumno__in=alumnos_dia_qs,
            entrada_en__isnull=False,
        )
        asistencias_dia = registros_dia.count()
        porcentaje_dia = porcentaje_panel(asistencias_dia, total_dia)
        porcentajes.append(porcentaje_dia)
        detalle.append({
            "fecha": dia.fecha,
            "asistencias": asistencias_dia,
            "total": total_dia,
            "porcentaje": porcentaje_dia,
        })

    if not porcentajes:
        promedio = 0
    else:
        promedio = round(sum(porcentajes) / len(porcentajes))

    return {
        "promedio": promedio,
        "dias_considerados": len(porcentajes),
        "detalle": detalle,
    }


def preparar_inscripciones_por_sala_supervisor(salas_resumen):
    """Lista ligera para el bloque 'Niñas y niños por sala de la sede'."""
    filas = []
    for sala in salas_resumen or []:
        filas.append({
            "id": sala.get("id", ""),
            "nombre": sala.get("nombre", "Sala"),
            "sala": sala.get("nombre", "Sala"),
            "total": sala.get("total_alumnos", 0),
            "total_alumnos": sala.get("total_alumnos", 0),
        })
    return filas


def preparar_calendario_mes_supervisor(semestre=None, fecha_referencia=None):
    """Días del mes actual para mostrar festivos, inhábiles o eventos."""
    if not semestre:
        return []

    fecha_referencia = fecha_referencia or timezone.localdate()
    calendario = []

    festivos_por_fecha = {}
    for evento in DiaFestivo.objects.filter(
        semestre=semestre,
        fecha__year=fecha_referencia.year,
        fecha__month=fecha_referencia.month,
    ).order_by("fecha", "id"):
        festivos_por_fecha.setdefault(evento.fecha, []).append(evento)

    dias = DiaOperativoSemestre.objects.filter(
        semestre=semestre,
        fecha__year=fecha_referencia.year,
        fecha__month=fecha_referencia.month,
    ).order_by("fecha")

    fechas_agregadas = set()
    for dia in dias:
        eventos = festivos_por_fecha.get(dia.fecha, [])
        titulo = ""
        descripcion = ""

        if eventos:
            titulos = [obtener_titulo_evento_calendario(evento) for evento in eventos]
            titulo = " · ".join(titulos[:3])
            descripcion = "Evento registrado en calendario"
        elif not getattr(dia, "es_habil", True):
            titulo = "Día inhábil"
            descripcion = getattr(dia, "estado", "") or "Inhábil"
        else:
            titulo = ""
            descripcion = "Día hábil"

        calendario.append({
            "fecha": dia.fecha,
            "es_habil": getattr(dia, "es_habil", True),
            "titulo": titulo,
            "estado": getattr(dia, "estado", ""),
            "descripcion": descripcion,
            "eventos": eventos,
            "total_eventos": len(eventos),
        })
        fechas_agregadas.add(dia.fecha)

    for fecha, eventos in festivos_por_fecha.items():
        if fecha in fechas_agregadas:
            continue
        titulos = [obtener_titulo_evento_calendario(evento) for evento in eventos]
        calendario.append({
            "fecha": fecha,
            "es_habil": not any(tipo_calendario_es_inhabil(getattr(evento, "tipo", "")) for evento in eventos),
            "titulo": " · ".join(titulos[:3]) if titulos else "Evento del mes",
            "estado": "EVENTO",
            "descripcion": "Evento registrado en calendario",
            "eventos": eventos,
            "total_eventos": len(eventos),
        })

    return sorted(calendario, key=lambda item: item.get("fecha"))


def obtener_dias_festivos_mes_supervisor(semestre=None, fecha_referencia=None):
    if not semestre:
        return DiaFestivo.objects.none()
    fecha_referencia = fecha_referencia or timezone.localdate()
    return DiaFestivo.objects.filter(
        semestre=semestre,
        fecha__year=fecha_referencia.year,
        fecha__month=fecha_referencia.month,
    ).order_by("fecha", "id")


def solicitud_activa_supervisor_queryset(semestre=None, sede=None):
    """Solicitudes de ingreso vigentes para consulta de Supervisora."""
    qs = Solicitud.objects.all()

    estados_finales = []
    try:
        estados_finales.extend([
            Solicitud.Estado.RECHAZADA,
            Solicitud.Estado.APROBADA,
        ])
    except Exception:
        estados_finales.extend(["RECHAZADA", "APROBADA"])

    estados_finales.extend(["FINALIZADA", "CANCELADA", "CANCELADO", "ARCHIVADA", "ARCHIVADO"])
    estados_finales = list(dict.fromkeys([estado for estado in estados_finales if estado]))

    if modelo_tiene_campo(Solicitud, "estado"):
        qs = qs.exclude(estado__in=estados_finales)

    # Cuando la solicitud ya tiene inscripción vinculada, se filtra por el semestre/sede consultados.
    ids_inscripciones = None
    if semestre or sede:
        inscripciones = SolicitudInscripcion.objects.all()
        if semestre:
            inscripciones = inscripciones.filter(semestre=semestre)
        if sede:
            inscripciones = qs_por_semestre_y_sede(inscripciones, semestre, sede)
        ids_inscripciones = list(inscripciones.values_list("solicitud_ingreso_id", flat=True))

    # Si Solicitud tiene campo sede, se filtra directamente. Si no, se usa la relación con inscripción.
    if sede and modelo_tiene_campo(Solicitud, "sede"):
        qs = qs.filter(sede=sede)
    elif ids_inscripciones is not None:
        qs = qs.filter(id__in=ids_inscripciones)

    if modelo_tiene_campo(Solicitud, "created_at"):
        qs = qs.order_by("-created_at", "-id")
    elif modelo_tiene_campo(Solicitud, "fecha_solicitud"):
        qs = qs.order_by("-fecha_solicitud", "-id")
    else:
        qs = qs.order_by("-id")

    return qs


def preparar_solicitudes_ingreso_activas_supervisor(semestre=None, sede=None, limite=12):
    solicitudes = list(solicitud_activa_supervisor_queryset(semestre=semestre, sede=sede)[:limite])

    for solicitud in solicitudes:
        try:
            solicitud.nombre_menor = obtener_nombre_menor_solicitud_supervisor(solicitud)
        except Exception:
            pass

        try:
            solicitud.fecha_solicitud = (
                getattr(solicitud, "fecha_solicitud", None)
                or getattr(solicitud, "created_at", None)
                or getattr(solicitud, "fecha_creacion", None)
            )
        except Exception:
            pass

        if not getattr(solicitud, "sede", None):
            try:
                solicitud.sede = sede
            except Exception:
                pass

        if not getattr(solicitud, "sala", None):
            try:
                solicitud.sala = "Sala pendiente"
            except Exception:
                pass

    return solicitudes


def procesar_foto_perfil_supervisor(request):
    """
    Guarda o elimina la foto de perfil de la Supervisora desde su panel.

    Validaciones de servidor:
    - JPG, JPEG, PNG o WEBP.
    - Máximo 3 MB.
    - La foto pertenece solo al usuario autenticado.
    """
    accion = (request.POST.get("accion_supervisor_foto") or "").strip()
    destino = request.get_full_path() or reverse("panel_supervisor")
    if "accion_supervisor_foto" in destino:
        destino = reverse("panel_supervisor")

    campo_foto = obtener_campo_foto_perfil_usuario(request.user)

    if not campo_foto:
        messages.warning(
            request,
            "No se pudo guardar la foto porque el modelo de usuario todavía no tiene un campo de imagen. "
            "Agrega un ImageField/FileField llamado foto_perfil en usuarios/models.py."
        )
        return redirect(destino)

    if accion == "eliminar_foto":
        archivo_actual = getattr(request.user, campo_foto, None)
        try:
            if archivo_actual:
                archivo_actual.delete(save=False)
        except Exception:
            pass

        setattr(request.user, campo_foto, None)
        try:
            request.user.save(update_fields=[campo_foto])
        except Exception:
            request.user.save()

        messages.success(request, "Foto de perfil eliminada correctamente.")
        return redirect(destino)

    if accion == "guardar_foto":
        archivo = (
            request.FILES.get("foto_perfil")
            or request.FILES.get("foto_perfil_supervisor")
            or request.FILES.get("foto_perfil_supervisora")
        )

        if not archivo:
            messages.error(request, "Selecciona una imagen antes de guardar la foto de perfil.")
            return redirect(destino)

        extension = os.path.splitext(getattr(archivo, "name", ""))[1].lower()
        extensiones_permitidas = {".jpg", ".jpeg", ".png", ".webp"}

        if extension not in extensiones_permitidas:
            messages.error(request, "Formato no permitido. Usa JPG, JPEG, PNG o WEBP.")
            return redirect(destino)

        max_bytes = 3 * 1024 * 1024
        if getattr(archivo, "size", 0) > max_bytes:
            peso_mb = round(archivo.size / (1024 * 1024), 2)
            messages.error(
                request,
                f"La foto pesa {peso_mb} MB. El máximo permitido es 3 MB para proteger el sistema y el servidor."
            )
            return redirect(destino)

        if getattr(archivo, "size", 0) <= 0:
            messages.error(request, "El archivo está vacío. Selecciona una imagen válida.")
            return redirect(destino)

        setattr(request.user, campo_foto, archivo)
        try:
            request.user.save(update_fields=[campo_foto])
        except Exception:
            request.user.save()

        messages.success(request, "Foto de perfil actualizada correctamente.")
        return redirect(destino)

    messages.warning(request, "Acción de foto de perfil no válida.")
    return redirect(destino)

def filas_reporte_supervisor(tipo_reporte, contexto):
    """Construye filas CSV para los reportes descargables del panel supervisor."""
    tipo_reporte = (tipo_reporte or "general").strip().lower()
    filas = []

    semestre = contexto.get("semestre_seleccionado")
    sede = contexto.get("sede_seleccionada")

    encabezado = [
        ["Reporte", tipo_reporte.title()],
        ["Semestre consultado", getattr(semestre, "nombre", "") if semestre else ""],
        ["Sede consultada", getattr(sede, "nombre", "") if sede else "Todas / General"],
        ["Fecha de descarga", timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M:%S")],
        [],
    ]

    if tipo_reporte == "asistencia":
        filas = encabezado + [
            ["Indicador", "Total", "Porcentaje"],
            ["Niños en estancia", contexto.get("ninos_en_estancia", 0), contexto.get("porcentaje_ninos_estancia", 0)],
            ["Niños con salida anticipada", contexto.get("ninos_ausentes", 0), contexto.get("porcentaje_ninos_ausentes", 0)],
            ["Niños fuera de la estancia", contexto.get("ninos_entregados", 0), contexto.get("porcentaje_ninos_fuera", 0)],
            ["Asistencias registradas del día", contexto.get("asistencias_dia", 0), contexto.get("porcentaje_asistencia_dia", 0)],
            ["Promedio mensual de asistencia", contexto.get("promedio_asistencia_mes", 0), "%"],
            ["Días considerados para promedio mensual", contexto.get("dias_asistencia_mensual", 0), ""],
            ["Total de niñas y niños inscritos", contexto.get("total_inscritos_sede", 0), 100 if contexto.get("total_inscritos_sede", 0) else 0],
            [],
            ["Nombre", "Sala", "Estado", "Entrada", "Salida", "Tutor", "Incidencias"],
        ]
        for alumno in contexto.get("alumnos_panel", []):
            filas.append([
                alumno.get("nombre", ""),
                alumno.get("sala", ""),
                alumno.get("estado_dia", alumno.get("estado", "")),
                alumno.get("hora_entrada", ""),
                alumno.get("hora_salida", ""),
                alumno.get("tutor", ""),
                alumno.get("total_incidencias", 0),
            ])
        return filas

    if tipo_reporte == "incidencias":
        filas = encabezado + [
            ["Indicador", "Total"],
            ["Incidencias totales", contexto.get("incidencias_total", 0)],
            ["Incidencias abiertas", contexto.get("incidencias_abiertas", 0)],
            ["Incidencias cerradas", contexto.get("incidencias_cerradas", 0)],
            ["Riesgo alto", contexto.get("incidencias_alto", 0)],
            [],
            ["Folio", "Fecha", "Menor", "Sala", "Tipo", "Categoría", "Nivel", "Estado", "Registró", "Descripción"],
        ]
        for inc in contexto.get("incidencias_rows", []):
            filas.append([
                inc.get("folio", ""), inc.get("fecha", ""), inc.get("alumno", ""), inc.get("sala", ""),
                inc.get("tipo", ""), inc.get("categoria", ""), inc.get("nivel", ""), inc.get("estado", ""),
                inc.get("registrada_por", ""), inc.get("descripcion", ""),
            ])
        return filas

    if tipo_reporte == "salas":
        filas = encabezado + [["Sala", "Capacidad", "Inscritos", "Presentes", "Salida anticipada", "Fuera de estancia", "Ocupación", "Actividad actual", "Responsable"]]
        for sala in contexto.get("salas_resumen", []):
            filas.append([
                sala.get("nombre", ""), sala.get("capacidad", ""), sala.get("total_alumnos", 0),
                sala.get("presentes", 0), sala.get("ausentes", 0), sala.get("salieron", 0), sala.get("ocupacion", 0),
                sala.get("actividad_actual", ""), sala.get("responsable", ""),
            ])
        return filas

    if tipo_reporte == "personal":
        filas = encabezado + [["Nombre", "Rol", "Área", "Correo", "Sede", "Estado"]]
        for persona in contexto.get("personal_panel", []):
            filas.append([
                persona.get("nombre", ""), persona.get("rol", ""), persona.get("area", ""),
                persona.get("email", ""), persona.get("sede", ""), persona.get("estado", ""),
            ])
        return filas

    if tipo_reporte == "calendario":
        filas = encabezado + [
            ["Indicador", "Valor"],
            ["Días operativos", contexto.get("total_dias_operativos", 0)],
            ["Días abiertos", contexto.get("dias_abiertos_operativos", 0)],
            ["Días cerrados", contexto.get("dias_cerrados_operativos", 0)],
            ["Avance", f"{contexto.get('porcentaje_calendario', 0)}%"],
            [],
            ["Fecha", "Estado", "Tipo", "Descripción"],
        ]
        for dia in contexto.get("calendario_panel", []):
            filas.append([
                dia.get("fecha", ""), dia.get("estado", ""), "Hábil" if dia.get("es_habil", True) else "Inhábil", dia.get("titulo", ""),
            ])
        return filas

    # General actualizado para Supervisora.
    filas = encabezado + [
        ["Resumen general de la estancia", ""],
        ["Total de niñas y niños inscritos en la sede", contexto.get("total_inscritos_sede", 0)],
        ["Total niños", contexto.get("total_ninos_inscritos", 0)],
        ["Total niñas", contexto.get("total_ninas_inscritas", 0)],
        ["Niños en estancia", contexto.get("ninos_en_estancia", 0)],
        ["Niños con salida anticipada", contexto.get("ninos_ausentes", 0)],
        ["Niños fuera de la estancia", contexto.get("ninos_entregados", 0)],
        ["Asistencias registradas del día", contexto.get("asistencias_dia", 0)],
        ["Porcentaje de asistencia del día", f"{contexto.get('porcentaje_asistencia_dia', 0)}%"],
        ["Promedio mensual de asistencia", f"{contexto.get('promedio_asistencia_mes', 0)}%"],
        ["Días considerados para promedio mensual", contexto.get("dias_asistencia_mensual", 0)],
        ["Salas activas", contexto.get("kpi_salas", 0)],
        ["Solicitudes de ingreso activas", contexto.get("total_solicitudes_ingreso_activas", 0)],
        ["Incidencias totales", contexto.get("incidencias_total", 0)],
        ["Incidencias abiertas", contexto.get("incidencias_abiertas", 0)],
        ["Incidencias cerradas", contexto.get("incidencias_cerradas", 0)],
        ["Avance del calendario", f"{contexto.get('porcentaje_calendario', 0)}%"],
        [],
        ["Detalle por sala", ""],
        ["Sala", "Niñas y niños inscritos"],
    ]
    for sala in contexto.get("inscripciones_por_sala", []):
        filas.append([sala.get("nombre", sala.get("sala", "")), sala.get("total", sala.get("total_alumnos", 0))])

    filas += [[], ["Festivos, inhábiles o eventos del mes", ""]]
    filas.append(["Fecha", "Título", "Estado / descripción"])
    for dia in contexto.get("calendario_mes_panel", []):
        if not dia.get("es_habil", True) or dia.get("total_eventos", 0):
            fecha = dia.get("fecha", "")
            try:
                fecha = fecha.strftime("%d/%m/%Y")
            except Exception:
                pass
            filas.append([fecha, dia.get("titulo", ""), dia.get("descripcion", dia.get("estado", ""))])

    return filas


def construir_contexto_panel_supervisor(request):
    """
    Construye todos los datos del panel de Supervisora General.

    Versión ajustada:
    - Inicio solo muestra los KPIs solicitados.
    - Salas se calcula al día/tiempo real según registros de operación diaria.
    - Reporte general se calcula por semestre y sede seleccionados, sin mezclar sedes.
    - Solicitudes de ingreso activas se muestran como listado de consulta.
    """
    semestres = Semestre.objects.order_by("-fecha_inicio", "-id")
    sedes = Sede.objects.order_by("nombre")

    semestre_activo = obtener_semestre_activo_operativo()
    semestre_id = request.GET.get("semestre_id") or request.GET.get("semestre")
    sede_id = request.GET.get("sede_id") or request.GET.get("sede")

    semestre_seleccionado = semestre_activo or semestres.first()

    if semestre_id:
        semestre_seleccionado = Semestre.objects.filter(pk=semestre_id).first() or semestre_seleccionado

    sede_seleccionada = None

    if sede_id:
        sede_seleccionada = Sede.objects.filter(pk=sede_id).first()
    elif semestre_seleccionado and getattr(semestre_seleccionado, "sede_configurada", None):
        sede_seleccionada = semestre_seleccionado.sede_configurada
    else:
        sede_seleccionada = sedes.first()

    modo_solo_consulta = True
    hoy = timezone.localdate()

    dia_actual = None
    if semestre_seleccionado:
        dia_actual = (
            DiaOperativoSemestre.objects
            .filter(
                semestre=semestre_seleccionado,
                fecha=hoy,
            )
            .select_related("semestre", "abierto_por", "cerrado_por")
            .first()
        )

    alumnos_qs = (
        SolicitudInscripcion.objects
        .filter(estado="FINALIZADA")
        .select_related(
            "solicitud_ingreso",
            "semestre",
            "sala_semestre_asignada",
            "sala_semestre_asignada__sala",
            "sala_semestre_asignada__sala__sede",
            "usuario_tutor",
        )
        .order_by(
            "sala_semestre_asignada__sala__nombre",
            "solicitud_ingreso__apellido_paterno_menor",
            "solicitud_ingreso__apellido_materno_menor",
            "solicitud_ingreso__nombres_menor",
        )
    )
    alumnos_qs = qs_por_semestre_y_sede(alumnos_qs, semestre_seleccionado, sede_seleccionada)

    total_ninos = alumnos_qs.count()
    total_inscritos_sede = total_ninos
    total_ninos_inscritos, total_ninas_inscritas = contar_sexo_inscripciones_supervisor(alumnos_qs)

    registros_hoy = RegistroDiarioAlumno.objects.none()

    if dia_actual:
        registros_hoy = (
            RegistroDiarioAlumno.objects
            .filter(dia_operativo=dia_actual, alumno__in=alumnos_qs)
            .select_related(
                "alumno",
                "alumno__solicitud_ingreso",
                "sala_semestre",
                "sala_semestre__sala",
            )
        )

    indicadores_ninos = calcular_indicadores_ninos_operacion(
        total_ninos,
        registros_hoy=registros_hoy,
        dia_actual=dia_actual,
        alumnos_qs=alumnos_qs,
    )

    # KPIs solicitados para Inicio.
    ninos_en_estancia = indicadores_ninos["ninos_en_estancia"]
    ninos_salida_anticipada = contar_salidas_anticipadas_supervisor(registros_hoy)

    # La Supervisora ya no manejará el indicador "ausentes" en Inicio.
    # Todo menor que no está dentro de la estancia queda como fuera, salvo que
    # tenga salida anticipada para mostrarlo en su tarjeta propia.
    ninos_fuera_estancia = max(total_ninos - ninos_en_estancia - ninos_salida_anticipada, 0)

    # Se conserva este alias para que el HTML ya modificado no necesite más cambios:
    # ahora ninos_ausentes representa "Niños con salida anticipada" en Supervisora.
    ninos_ausentes = ninos_salida_anticipada

    salas_qs = SalaSemestre.objects.filter(activa=True).select_related("sala", "semestre", "sala__sede")

    if semestre_seleccionado:
        salas_qs = salas_qs.filter(semestre=semestre_seleccionado)

    if sede_seleccionada:
        salas_qs = salas_qs.filter(Q(sala__sede=sede_seleccionada) | Q(sala__sede__isnull=True))

    salas_resumen = preparar_salas_supervisor(
        salas_qs=salas_qs.order_by("sala__nombre"),
        alumnos_qs=alumnos_qs,
        registros_hoy=registros_hoy,
        dia_actual=dia_actual,
    )

    # Ajusta el conteo por sala para que la columna "ausentes" del HTML represente salida anticipada.
    for sala in salas_resumen:
        sala_id = sala.get("id")
        registros_sala = registros_hoy.filter(sala_semestre_id=sala_id) if sala_id else RegistroDiarioAlumno.objects.none()
        sala["ausentes"] = contar_salidas_anticipadas_supervisor(registros_sala)
        sala["salida_anticipada"] = sala["ausentes"]
        sala["salieron"] = max((sala.get("total_alumnos", 0) or 0) - (sala.get("presentes", 0) or 0) - (sala.get("ausentes", 0) or 0), 0)

    incidencias_qs = (
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

    if semestre_seleccionado:
        incidencias_qs = incidencias_qs.filter(semestre=semestre_seleccionado)

    if sede_seleccionada:
        incidencias_qs = incidencias_qs.filter(semestre__sede_configurada=sede_seleccionada)

    try:
        incidencias_qs = incidencias_qs.order_by("-fecha_reporte", "-id")
    except Exception:
        incidencias_qs = incidencias_qs.order_by("-id")

    estado_abierta, estado_cerrada = obtener_estado_incidencia_supervisor()
    nivel_alto = obtener_nivel_alto_incidencia_supervisor()

    incidencias_total = incidencias_qs.count()
    incidencias_abiertas = incidencias_qs.filter(estado=estado_abierta).count()
    incidencias_cerradas = incidencias_qs.filter(estado=estado_cerrada).count()
    incidencias_alto = incidencias_qs.filter(nivel=nivel_alto).count()

    inc_pedagogica = incidencias_qs.filter(tipo=Incidencia.TipoIncidencia.PEDAGOGICA).count()
    inc_nutricional = incidencias_qs.filter(tipo=Incidencia.TipoIncidencia.NUTRICIONAL).count()
    inc_medica = incidencias_qs.filter(tipo=Incidencia.TipoIncidencia.MEDICA).count()
    inc_psicologica = incidencias_qs.filter(tipo=Incidencia.TipoIncidencia.PSICOLOGICA).count()

    total_personal_activo = get_user_model().objects.filter(is_active=True).exclude(tipo_persona="BENEFICIARIO").count()
    total_maestras_activas = (
        AsignacionMaestra.objects
        .filter(sala_semestre__semestre=semestre_seleccionado, activo=True)
        .values("maestra_id")
        .distinct()
        .count()
        if semestre_seleccionado else 0
    )

    dias_operativos = DiaOperativoSemestre.objects.none()
    total_dias_operativos = 0
    dias_abiertos_operativos = 0
    dias_cerrados_operativos = 0
    porcentaje_calendario = 0

    if semestre_seleccionado:
        dias_operativos = DiaOperativoSemestre.objects.filter(semestre=semestre_seleccionado, es_habil=True)
        total_dias_operativos = dias_operativos.count()
        dias_abiertos_operativos = dias_operativos.filter(estado=DiaOperativoSemestre.EstadoDia.ABIERTO).count()
        dias_cerrados_operativos = dias_operativos.filter(estado=DiaOperativoSemestre.EstadoDia.CERRADO).count()
        porcentaje_calendario = porcentaje_panel(dias_cerrados_operativos, total_dias_operativos)

    porcentaje_ninos_estancia = porcentaje_panel(ninos_en_estancia, total_ninos)
    porcentaje_ninos_ausentes = porcentaje_panel(ninos_salida_anticipada, total_ninos)
    porcentaje_ninos_fuera = porcentaje_panel(ninos_fuera_estancia, total_ninos)
    porcentaje_incidencias_cerradas = porcentaje_panel(incidencias_cerradas, incidencias_total)

    asistencias_dia, porcentaje_asistencia_dia = calcular_asistencia_dia_supervisor(
        total_inscritos_sede,
        registros_hoy=registros_hoy,
        dia_actual=dia_actual,
    )
    resumen_mensual = calcular_promedio_asistencia_mensual_supervisor(
        semestre=semestre_seleccionado,
        sede=sede_seleccionada,
        fecha_referencia=hoy,
    )

    alumnos_panel = preparar_alumnos_panel(alumnos_qs, dia_actual=dia_actual)
    personal_panel = preparar_personal_panel(semestre=semestre_seleccionado)
    calendario_panel = preparar_calendario_panel(semestre=semestre_seleccionado, limite=60)
    calendario_mes_panel = preparar_calendario_mes_supervisor(semestre=semestre_seleccionado, fecha_referencia=hoy)
    dias_festivos_mes = obtener_dias_festivos_mes_supervisor(semestre=semestre_seleccionado, fecha_referencia=hoy)
    actividades_panel = preparar_actividades_panel(semestre=semestre_seleccionado)
    sedes_panel = preparar_sedes_panel(semestre=semestre_seleccionado)
    inscripciones_por_sala = preparar_inscripciones_por_sala_supervisor(salas_resumen)
    solicitudes_ingreso_activas = preparar_solicitudes_ingreso_activas_supervisor(
        semestre=semestre_seleccionado,
        sede=sede_seleccionada,
        limite=12,
    )
    total_solicitudes_ingreso_activas = solicitud_activa_supervisor_queryset(
        semestre=semestre_seleccionado,
        sede=sede_seleccionada,
    ).count()

    reportes_supervisor = [
        {
            "slug": "general",
            "titulo": "Reporte general de la estancia",
            "descripcion": "Inscritos, salas, semestre, calendario y asistencia de la sede consultada.",
            "porcentaje": porcentaje_asistencia_dia,
        },
        {
            "slug": "asistencia",
            "titulo": "Resumen de asistencia",
            "descripcion": "Niños en estancia, salida anticipada y fuera de la estancia.",
            "porcentaje": porcentaje_asistencia_dia,
        },
        {
            "slug": "incidencias",
            "titulo": "Resumen de incidencias",
            "descripcion": "Incidencias abiertas, cerradas y de riesgo alto.",
            "porcentaje": porcentaje_incidencias_cerradas,
        },
        {
            "slug": "salas",
            "titulo": "Reporte por sala",
            "descripcion": "Ocupación, responsables y actividad actual.",
            "porcentaje": porcentaje_panel(sum(s["presentes"] for s in salas_resumen), total_ninos),
        },
        {
            "slug": "calendario",
            "titulo": "Avance del calendario",
            "descripcion": "Días operativos abiertos, cerrados, festivos e inhábiles.",
            "porcentaje": porcentaje_calendario,
        },
        {
            "slug": "personal",
            "titulo": "Reporte de personal",
            "descripcion": "Trabajadores activos, roles, áreas y sedes asignadas.",
            "porcentaje": 100 if total_personal_activo else 0,
        },
    ]

    context = {
        "titulo_panel": "Panel de Supervisión General",
        "subtitulo_panel": "Vista general en tiempo real de la Estancia Infantil UNACH",
        "rol_panel": "Supervisora General",
        "semestres": semestres,
        "sedes": sedes,
        "semestre_activo": semestre_activo,
        "semestre_seleccionado": semestre_seleccionado,
        "sede_seleccionada": sede_seleccionada,
        "dia_actual": dia_actual,
        "modo_solo_consulta": modo_solo_consulta,
        "solo_lectura": True,
        "fecha_actualizacion": timezone.localtime(timezone.now()),

        # KPIs principales solicitados en Inicio.
        "total_ninos": total_ninos,
        "total_inscritos_sede": total_inscritos_sede,
        "total_alumnos_inscritos": total_inscritos_sede,
        "total_ninos_inscritos": total_ninos_inscritos,
        "total_ninos_masculino": total_ninos_inscritos,
        "total_varones": total_ninos_inscritos,
        "alumnos_masculino": total_ninos_inscritos,
        "total_ninas_inscritas": total_ninas_inscritas,
        "total_ninas_femenino": total_ninas_inscritas,
        "total_mujeres": total_ninas_inscritas,
        "alumnos_femenino": total_ninas_inscritas,
        "ninos_en_estancia": ninos_en_estancia,
        "ninos_ausentes": ninos_ausentes,
        "ninos_salida_anticipada": ninos_salida_anticipada,
        "ninos_fuera_estancia": ninos_fuera_estancia,
        "ninos_entregados": ninos_fuera_estancia,
        "kpi_alumnos": total_ninos,
        "kpi_salas": salas_qs.count(),
        "kpi_personal": total_personal_activo,
        "kpi_maestras": total_maestras_activas,
        "kpi_riesgo": incidencias_alto,

        # Porcentajes.
        "porcentaje_ninos_estancia": porcentaje_ninos_estancia,
        "porcentaje_ninos_ausentes": porcentaje_ninos_ausentes,
        "porcentaje_ninos_salida_anticipada": porcentaje_ninos_ausentes,
        "porcentaje_ninos_fuera": porcentaje_ninos_fuera,
        "asistencias_dia": asistencias_dia,
        "porcentaje_asistencia_dia": porcentaje_asistencia_dia,
        "asistencia_dia_porcentaje": porcentaje_asistencia_dia,
        "promedio_asistencia_mes": resumen_mensual.get("promedio", 0),
        "porcentaje_asistencia_mensual": resumen_mensual.get("promedio", 0),
        "asistencia_mensual_promedio": resumen_mensual.get("promedio", 0),
        "dias_asistencia_mensual": resumen_mensual.get("dias_considerados", 0),
        "dias_cerrados_mes": resumen_mensual.get("dias_considerados", 0),
        "detalle_asistencia_mensual": resumen_mensual.get("detalle", []),
        "operacion_diaria_iniciada": indicadores_ninos.get("operacion_diaria_iniciada", False),
        "chequeo_ausencias_activado": indicadores_ninos.get("chequeo_ausencias_activado", False),
        "hora_limite_entrada": indicadores_ninos.get("hora_limite_entrada"),
        "mensaje_operacion_ninos": indicadores_ninos.get("mensaje_operacion_ninos", ""),
        "porcentaje_incidencias_cerradas": porcentaje_incidencias_cerradas,
        "porcentaje_calendario": porcentaje_calendario,
        "total_dias_operativos": total_dias_operativos,
        "dias_abiertos_operativos": dias_abiertos_operativos,
        "dias_cerrados_operativos": dias_cerrados_operativos,

        # Incidencias.
        "incidencias_total": incidencias_total,
        "incidencias_abiertas": incidencias_abiertas,
        "incidencias_cerradas": incidencias_cerradas,
        "incidencias_alto": incidencias_alto,
        "incidencias_rows": preparar_incidencias_supervisor(incidencias_qs),
        "inc_pedagogica": inc_pedagogica,
        "inc_nutricional": inc_nutricional,
        "inc_medica": inc_medica,
        "inc_psicologica": inc_psicologica,

        # Secciones del HTML único.
        "alumnos_panel": alumnos_panel,
        "salas_resumen": salas_resumen,
        "personal_panel": personal_panel,
        "calendario_panel": calendario_panel,
        "calendario_mes_panel": calendario_mes_panel,
        "dias_festivos_mes": dias_festivos_mes,
        "actividades_panel": actividades_panel,
        "sedes_panel": sedes_panel,
        "reportes_supervisor": reportes_supervisor,
        "mejor_semestre": obtener_mejor_semestre_supervisor(),
        "inscripciones_por_sala": inscripciones_por_sala,
        "solicitudes_ingreso_activas": solicitudes_ingreso_activas,
        "total_solicitudes_ingreso_activas": total_solicitudes_ingreso_activas,

        # Perfil de supervisora.
        "foto_perfil_supervisor_url": obtener_foto_perfil_usuario(request.user),
        "perfil_supervisor_soporta_foto": bool(obtener_campo_foto_perfil_usuario(request.user)),

        # Se mantienen disponibles para reportes/compatibilidad, aunque ya no estén en la viñeta.
        "movimientos_suplencia_recientes": [],
        "bitacora_suplencias": [],
        "movimientos_suplencia": [],
        "total_movimientos_suplencia": 0,

        # Datos para gráficas.
        "grafica_asistencia_labels": ["En estancia", "Salida anticipada", "Fuera de estancia"],
        "grafica_asistencia_data": [ninos_en_estancia, ninos_salida_anticipada, ninos_fuera_estancia],
        "grafica_incidencias_labels": ["Pedagógicas", "Nutricionales", "Médicas", "Psicológicas"],
        "grafica_incidencias_data": [inc_pedagogica, inc_nutricional, inc_medica, inc_psicologica],
        "grafica_salas_labels": [s["nombre"] for s in salas_resumen],
        "grafica_salas_presentes": [s["presentes"] for s in salas_resumen],
        "grafica_salas_ausentes": [s["ausentes"] for s in salas_resumen],
    }

    context.update(contexto_semestre_operativo())
    # Se conservan estos contextos por compatibilidad con reportes o datos AJAX,
    # aunque la viñeta de Supervisora ya no muestre Suplencias ni Apoyos de sala.
    context.update(contexto_bitacora_suplencias(request, limite=100))
    context.update(contexto_suplencias_supervisor(request, limite=100))
    context.update(contexto_apoyos_sala_supervisor(request, limite=100))

    # Evita que los contextos de compatibilidad cambien los KPIs visuales solicitados.
    context["ninos_ausentes"] = ninos_salida_anticipada
    context["ninos_entregados"] = ninos_fuera_estancia
    context["ninos_fuera_estancia"] = ninos_fuera_estancia
    context["porcentaje_ninos_ausentes"] = porcentaje_ninos_ausentes
    context["porcentaje_ninos_fuera"] = porcentaje_ninos_fuera

    context["modo_solo_consulta"] = True
    context["solo_lectura"] = True

    return context


@login_required
def panel_supervisor(request):
    """
    Panel único para Supervisora General / Secretaría de Dirección.

    Es un dashboard de solo lectura para la operación, pero sí permite que la
    supervisora actualice o elimine su propia foto de perfil con validación de peso.
    """
    if not usuario_es_supervisora_general(request.user):
        return acceso_denegado_login(request, "No tienes permiso para entrar al panel de Supervisión General.")

    if request.method == "POST":
        if (request.POST.get("accion_supervisor_foto") or "").strip():
            return procesar_foto_perfil_supervisor(request)

        messages.warning(
            request,
            "El panel de Supervisión General es únicamente de consulta. No permite crear, editar ni eliminar información operativa."
        )
        return redirect("panel_supervisor")

    contexto = construir_contexto_panel_supervisor(request)

    return render(
        request,
        "admisiones/supervisor/panel_supervisor.html",
        contexto,
    )


@login_required
def descargar_reporte_supervisor(request, tipo_reporte="general"):
    """Descarga reportes CSV de solo consulta para Supervisora General."""
    if not usuario_es_supervisora_general(request.user):
        return acceso_denegado_login(request, "No tienes permiso para descargar reportes de Supervisión General.")

    contexto = construir_contexto_panel_supervisor(request)
    filas = filas_reporte_supervisor(tipo_reporte, contexto)

    nombre = (tipo_reporte or "general").strip().lower().replace(" ", "_")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="reporte_supervisor_{nombre}.csv"'
    response.write("\ufeff")

    writer = csv.writer(response)
    for fila in filas:
        writer.writerow(fila)

    return response


@login_required
def panel_supervisor_datos(request):
    """
    Respuesta JSON opcional para actualizar el panel con JavaScript.
    Si no deseas usar AJAX, puedes omitir esta ruta en urls.py y usar solo panel_supervisor.
    """
    if not usuario_es_supervisora_general(request.user):
        return JsonResponse(
            {
                "ok": False,
                "mensaje": "No tienes permiso para consultar estos datos.",
            },
            status=403,
        )

    contexto = construir_contexto_panel_supervisor(request)

    return JsonResponse({
        "ok": True,
        "fecha_actualizacion": contexto["fecha_actualizacion"].strftime("%d/%m/%Y %H:%M:%S"),
        "total_ninos": contexto["total_ninos"],
        "total_inscritos_sede": contexto.get("total_inscritos_sede", 0),
        "total_ninos_inscritos": contexto.get("total_ninos_inscritos", 0),
        "total_ninas_inscritas": contexto.get("total_ninas_inscritas", 0),
        "ninos_en_estancia": contexto["ninos_en_estancia"],
        "ninos_ausentes": contexto["ninos_ausentes"],
        "ninos_salida_anticipada": contexto.get("ninos_salida_anticipada", contexto["ninos_ausentes"]),
        "ninos_entregados": contexto["ninos_entregados"],
        "ninos_fuera_estancia": contexto["ninos_fuera_estancia"],
        "asistencias_dia": contexto.get("asistencias_dia", 0),
        "porcentaje_asistencia_dia": contexto.get("porcentaje_asistencia_dia", 0),
        "promedio_asistencia_mes": contexto.get("promedio_asistencia_mes", 0),
        "dias_asistencia_mensual": contexto.get("dias_asistencia_mensual", 0),
        "total_solicitudes_ingreso_activas": contexto.get("total_solicitudes_ingreso_activas", 0),
        "incidencias_abiertas": contexto["incidencias_abiertas"],
        "incidencias_cerradas": contexto["incidencias_cerradas"],
        "incidencias_alto": contexto["incidencias_alto"],
        "kpi_salas": contexto["kpi_salas"],
        "kpi_personal": contexto["kpi_personal"],
        "suplencias_hoy": contexto.get("suplencias_hoy", 0),
        "total_suplencias_activas": contexto.get("total_suplencias_activas", 0),
        "suplencias_pendientes_revision": contexto.get("suplencias_pendientes_revision", 0),
        "suplencias_validadas": contexto.get("suplencias_validadas", 0),
        "total_movimientos_suplencia": contexto.get("total_movimientos_suplencia", 0),
        "total_apoyos_sala_hoy": contexto.get("total_apoyos_sala_hoy", 0),
        "total_apoyos_sala_activos": contexto.get("total_apoyos_sala_activos", 0),
        "porcentaje_ninos_estancia": contexto["porcentaje_ninos_estancia"],
        "porcentaje_ninos_ausentes": contexto["porcentaje_ninos_ausentes"],
        "porcentaje_ninos_fuera": contexto["porcentaje_ninos_fuera"],
        "porcentaje_incidencias_cerradas": contexto["porcentaje_incidencias_cerradas"],
        "grafica_asistencia_labels": contexto["grafica_asistencia_labels"],
        "grafica_asistencia_data": contexto["grafica_asistencia_data"],
        "grafica_incidencias_labels": contexto["grafica_incidencias_labels"],
        "grafica_incidencias_data": contexto["grafica_incidencias_data"],
        "grafica_salas_labels": contexto["grafica_salas_labels"],
        "grafica_salas_presentes": contexto["grafica_salas_presentes"],
        "grafica_salas_ausentes": contexto["grafica_salas_ausentes"],
        "salas_resumen": contexto["salas_resumen"],
    })

