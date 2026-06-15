import io
import os
import re
from pathlib import Path
from datetime import timedelta

from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.models import Group
from django.http import JsonResponse, HttpResponse, FileResponse
from django.utils import timezone
from django.utils.html import escape
from django.db import transaction
from django.db.models import Q

try:
    from xhtml2pdf import pisa
except ImportError:
    pisa = None

from .models import AccessLog, AsignacionRolCiclo

try:
    from .decorators import ruta_por_rol as ruta_segura_por_rol, acceso_denegado_login
except Exception:
    ruta_segura_por_rol = None

    def acceso_denegado_login(request, mensaje="Acceso denegado."):
        logout(request)
        messages.error(request, mensaje)
        return redirect("login")


try:
    # IMPORTANTE: Importamos todos los modelos necesarios de admisiones
    from admisiones.models import (
        Solicitud,
        SolicitudInscripcion,
        Semestre,
        AsignacionMaestra,
        Sala,
        SalaSemestre,
        MensajeDirectora,
        Incidencia,
    )
except ImportError:
    pass

try:
    from admisiones.services import (
        generar_pdf_reporte_final_ingreso,
        enviar_correo_reporte_final_ingreso,
        usuario_es_admin_sistema,
        obtener_semestre_activo_operativo,
        hay_semestre_activo_operativo,
        contexto_semestre_operativo,
    )
except ImportError:
    generar_pdf_reporte_final_ingreso = None
    enviar_correo_reporte_final_ingreso = None

    def usuario_es_admin_sistema(user):
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_superuser", False) or getattr(user, "tipo_persona", "") == "ADMIN":
            return True
        try:
            return user.groups.filter(name__iexact="Administrador del Sistema").exists()
        except Exception:
            return False

    def obtener_semestre_activo_operativo(sede=None):
        try:
            return Semestre.objects.filter(estado="ACTIVO").order_by("-fecha_inicio", "-id").first()
        except Exception:
            return None

    def hay_semestre_activo_operativo(sede=None):
        return obtener_semestre_activo_operativo(sede=sede) is not None

    def contexto_semestre_operativo(sede=None):
        semestre_activo = obtener_semestre_activo_operativo(sede=sede)
        return {
            "semestre_activo_operativo": semestre_activo,
            "hay_semestre_activo_operativo": bool(semestre_activo),
            "modo_solo_consulta": not bool(semestre_activo),
            "aviso_semestre_operativo": (
                "" if semestre_activo else
                "No hay semestre activo/iniciado. Puedes consultar información existente, "
                "pero no puedes operar, agregar, modificar ni eliminar registros hasta que el Administrador inicie un nuevo semestre."
            ),
        }


def enmascarar_datos(texto):
    if not texto or len(texto) < 4:
        return "****"
    return texto[:2] + "****" + texto[-2:]



def limpiar_correo(valor):
    """
    Limpia correos capturados en formularios del panel de usuarios.

    Reglas:
    - Quita espacios al inicio y al final.
    - Convierte a minúsculas.
    - Quita espacios internos accidentales, por ejemplo:
      'trabajadora @unach.mx' -> 'trabajadora@unach.mx'.
    """
    valor = (valor or "").strip().lower()
    valor = re.sub(r"\s+", "", valor)
    return valor


def usuario_tiene_grupo(user, texto_grupo):
    """
    Busca un texto dentro de los grupos del usuario.
    Ejemplo: usuario_tiene_grupo(user, "trabajadora social")
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    texto_grupo = (texto_grupo or "").strip().lower()

    return user.groups.filter(name__icontains=texto_grupo).exists()


def obtener_texto_grupos_usuario(user):
    """
    Devuelve todos los grupos del usuario en un solo texto normalizado.
    Sirve como respaldo para usuarios que ya tenían roles asignados por Group.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return ""

    try:
        return " ".join(g.name.strip().lower() for g in user.groups.all())
    except Exception:
        return ""


def obtener_area_operativa_por_rol(nombre_rol):
    """
    Convierte el nombre del rol/grupo en el área operativa usada por el modelo Usuario.

    Esto permite que, cuando el Administrador del Sistema asigne un rol fijo,
    también quede guardada el área necesaria para pase de lista y suplencias.
    """
    rol = (nombre_rol or "").strip().lower()

    if not rol:
        return None

    if "directora" in rol or "direccion" in rol or "dirección" in rol:
        return "DIRECCION"

    if "trabajadora social" in rol or "trabajo social" in rol:
        return "TRABAJO_SOCIAL"

    if "psicóloga" in rol or "psicologa" in rol or "psicología" in rol or "psicologia" in rol:
        return "PSICOLOGIA"

    if "nutrióloga" in rol or "nutriologa" in rol or "nutrición" in rol or "nutricion" in rol:
        return "NUTRICION"

    if "médico" in rol or "medico" in rol or "médica" in rol or "medica" in rol:
        return "MEDICA"

    if (
        "pedagógica" in rol
        or "pedagogica" in rol
        or "pedagogía" in rol
        or "pedagogia" in rol
        or "coordinadora" in rol
        or "coordinador" in rol
        or "coordinacion de sala" in rol
        or "coordinación de sala" in rol
    ):
        return "PEDAGOGICA"

    if "maestra" in rol or "asistente" in rol or "sala" in rol:
        return "MAESTRA"

    return None


def limpiar_area_operativa(valor, tipo_persona="PERSONAL"):
    """
    Limpia y valida el área operativa recibida desde formularios.

    Si el usuario no es PERSONAL, se regresa None para evitar que supervisora,
    administrador, beneficiarios o alumnos aparezcan en pase de lista o suplencias.
    """
    if (tipo_persona or "").strip().upper() != "PERSONAL":
        return None

    area = (valor or "").strip().upper()
    if not area:
        return None

    User = get_user_model()
    areas_validas = [choice[0] for choice in getattr(User, "AREA_OPERATIVA_CHOICES", [])]

    if areas_validas and area not in areas_validas:
        return None

    return area


def aplicar_area_operativa_por_rol(usuario, nombre_rol):
    """
    Asigna area_operativa al usuario según el rol fijo seleccionado.
    No reemplaza los grupos, solo mantiene sincronizado el campo nuevo.
    """
    area = obtener_area_operativa_por_rol(nombre_rol)

    if hasattr(usuario, "area_operativa"):
        usuario.area_operativa = area

    return area


def usuario_es_directora(user):
    """
    Identifica a Dirección usando primero area_operativa y luego grupos.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "tipo_persona", "") != "PERSONAL":
        return False

    if getattr(user, "area_operativa", None) == "DIRECCION":
        return True

    grupos_usuario = obtener_texto_grupos_usuario(user)
    return "directora" in grupos_usuario or "direccion" in grupos_usuario or "dirección" in grupos_usuario


def usuario_es_trabajadora_social(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "tipo_persona", "") == "PERSONAL" and getattr(user, "area_operativa", None) == "TRABAJO_SOCIAL":
        return True

    grupos_usuario = obtener_texto_grupos_usuario(user)
    return "trabajadora social" in grupos_usuario or "trabajo social" in grupos_usuario


def usuario_es_psicologia(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "tipo_persona", "") == "PERSONAL" and getattr(user, "area_operativa", None) == "PSICOLOGIA":
        return True

    grupos_usuario = obtener_texto_grupos_usuario(user)
    return "psicóloga" in grupos_usuario or "psicologa" in grupos_usuario


def usuario_es_nutricion(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "tipo_persona", "") == "PERSONAL" and getattr(user, "area_operativa", None) == "NUTRICION":
        return True

    grupos_usuario = obtener_texto_grupos_usuario(user)
    return "nutrióloga" in grupos_usuario or "nutriologa" in grupos_usuario


def usuario_es_medica(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "tipo_persona", "") == "PERSONAL" and getattr(user, "area_operativa", None) == "MEDICA":
        return True

    grupos_usuario = obtener_texto_grupos_usuario(user)
    return "médico" in grupos_usuario or "medico" in grupos_usuario or "médica" in grupos_usuario or "medica" in grupos_usuario


def usuario_es_pedagogica(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "tipo_persona", "") == "PERSONAL" and getattr(user, "area_operativa", None) == "PEDAGOGICA":
        return True

    grupos_usuario = obtener_texto_grupos_usuario(user)
    return (
        "pedagógica" in grupos_usuario
        or "pedagogica" in grupos_usuario
        or "coordinadora" in grupos_usuario
        or "coordinador" in grupos_usuario
        or "coordinacion de sala" in grupos_usuario
        or "coordinación de sala" in grupos_usuario
    )


def usuario_es_maestra(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "tipo_persona", "") == "PERSONAL" and getattr(user, "area_operativa", None) == "MAESTRA":
        return True

    grupos_usuario = obtener_texto_grupos_usuario(user)
    return "asistente" in grupos_usuario or "maestra" in grupos_usuario


def obtener_contexto_personal_operativo():
    """
    Contexto base para paneles donde se necesitará pase de lista o suplencias.
    No crea suplencias todavía; solo manda listas filtradas desde usuarios.
    """
    User = get_user_model()

    try:
        personal_pase_lista = User.personal_para_pase_lista()
    except Exception:
        personal_pase_lista = User.objects.none()

    try:
        personal_suplencias = User.personal_para_suplencias()
    except Exception:
        personal_suplencias = User.objects.none()

    return {
        "personal_pase_lista": personal_pase_lista,
        "personal_suplencias": personal_suplencias,
    }


def usuario_es_supervisor_general(user):
    """
    Identifica a la Supervisora General / Secretaria de Dirección.

    Este rol es de solo consulta: entra al panel de supervisión general
    y no debe enviarse al panel de Dirección ni a paneles operativos.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    tipo_persona = (getattr(user, "tipo_persona", "") or "").strip().upper()
    if tipo_persona == "SUPERVISOR":
        return True

    try:
        grupos_usuario = " ".join(
            g.name.strip().lower() for g in user.groups.all()
        )
    except Exception:
        grupos_usuario = ""

    palabras_clave = [
        "supervisor",
        "supervisora",
        "supervision",
        "supervisión",
        "supervisora general",
        "supervisor general",
        "secretaria de direccion",
        "secretaria de dirección",
        "secretario de direccion",
        "secretario de dirección",
    ]

    return any(palabra in grupos_usuario for palabra in palabras_clave)



def bloquear_si_no_hay_semestre_activo(request, permitir_admin=False, sede=None):
    """
    Bloquea acciones operativas cuando no hay semestre activo.
    No cierra sesión: solo avisa y redirige.

    La lógica de semestre vive en admisiones/services.py.
    Este helper se queda aquí porque usa request, messages y redirect.
    """
    if permitir_admin and usuario_es_admin_sistema(request.user):
        return None

    if hay_semestre_activo_operativo(sede=sede):
        return None

    messages.warning(
        request,
        "No hay semestre activo/iniciado. Solo puedes consultar información existente; "
        "las acciones de operación se habilitarán cuando el Administrador inicie un nuevo semestre."
    )

    return redirect(request.META.get("HTTP_REFERER") or "/")


@login_required
def root_redirect_view(request):
    user = request.user

    if not getattr(user, "is_active", True) or not getattr(user, "estatus_operativo", True):
        logout(request)
        messages.error(request, "Tu cuenta está inactiva. Contacta al administrador.")
        return redirect("login")

    if usuario_es_admin_sistema(user):
        return redirect("panel_gobierno_ti")

    if request.session.get("sec_manto", False):
        logout(request)
        messages.error(request, "El sistema está en mantenimiento. Intente más tarde.")
        return redirect("login")

    # Supervisora General / Secretaria de Dirección.
    # Entra a su panel de solo consulta y no participa en suplencias.
    if usuario_es_supervisor_general(user):
        return redirect("panel_supervisor")

    if getattr(user, "tipo_persona", "") == "BENEFICIARIO":
        return redirect(reverse("portal_padres_home") + "#inicio")

    if user.is_staff:
        # Primero revisamos area_operativa, pero conservamos compatibilidad con grupos.
        if usuario_es_directora(user):
            return redirect("dashboard_directiva")

        if usuario_es_trabajadora_social(user):
            return redirect("dashboard_admin")

        if usuario_es_psicologia(user):
            return redirect("psicologia_pendientes")

        if usuario_es_nutricion(user):
            return redirect("nutricion_pendientes")

        if usuario_es_medica(user):
            return redirect("medico_pendientes")

        # Pedagógica / Coordinación de Sala.
        if usuario_es_pedagogica(user):
            return redirect("dashboard_coordinadora")

        # Maestras / Asistentes de sala.
        if usuario_es_maestra(user):
            return redirect("dashboard_maestra")

        logout(request)
        messages.error(
            request,
            "Acceso denegado: tu usuario no tiene un rol oficial asignado. Contacta al administrador.",
        )
        return redirect("login")

    logout(request)
    messages.error(request, "Error de rol de usuario.")
    return redirect("login")


# =======================================================
# DASHBOARD DE LA DIRECTIVA
# =======================================================
@login_required
def dashboard_directiva(request):
    user = request.user

    # La Supervisora General tiene su propio panel de solo consulta.
    # Aunque tenga un grupo parecido a Dirección, no debe entrar aquí.
    if usuario_es_supervisor_general(user):
        return redirect("panel_supervisor")

    # Verificamos que sea Directora o Admin.
    # Se usa area_operativa y también grupos para no romper usuarios anteriores.
    if not usuario_es_directora_o_admin(user):
        logout(request)
        messages.error(request, "Acceso denegado. Área exclusiva de Dirección.")
        return redirect("login")

    # 1. Filtramos los que están esperando la firma de la directora
    dictamenes_pendientes = SolicitudInscripcion.objects.filter(
        estado="ESPERANDO_DIRECTORA"
    ).order_by("-updated_at")

    # 2. Filtramos las salas que Trabajo Social le mandó para autorizar
    salas_en_revision = SolicitudInscripcion.objects.filter(
        estado="SALA_EN_REVISION"
    ).order_by("-updated_at")

    # 3. Expedientes que aún están en las áreas
    expedientes_en_filtros = SolicitudInscripcion.objects.filter(estado="FILTROS")

    context = {
        "dictamenes_pendientes": dictamenes_pendientes,
        "salas_en_revision": salas_en_revision,
        "expedientes_en_filtros": expedientes_en_filtros,
        "kpi_alumnos": SolicitudInscripcion.objects.filter(estado="FINALIZADA").count(),
        "kpi_pendientes": dictamenes_pendientes.count(),
        "kpi_riesgo": Incidencia.objects.filter(nivel="ALTO", resuelta=False).count(),
        "kpi_salas": Sala.objects.count(),
        "mensajes_aspirantes": MensajeDirectora.objects.filter(
            es_alumno_inscrito=False,
            leido=False,
        ).order_by("-fecha_envio"),
        "mensajes_alumnos": MensajeDirectora.objects.filter(
            es_alumno_inscrito=True,
            leido=False,
        ).order_by("-fecha_envio"),
        "incidencias_alto": Incidencia.objects.filter(
            nivel="ALTO",
            resuelta=False,
        ).order_by("-fecha_reporte"),
        "incidencias_bajo": Incidencia.objects.filter(
            nivel="BAJO",
            resuelta=False,
        ).order_by("-fecha_reporte"),
    }

    # Contexto preparado para el pase de lista del personal operativo.
    # La lógica real de asistencia/suplencias se conectará desde admisiones.
    context.update(obtener_contexto_personal_operativo())
    context.update(contexto_semestre_operativo())

    return render(request, "portal/home_directiva.html", context)



def usuario_es_directora_o_admin(user):
    """
    Permite validar que solo Directora o Administrador emitan el veredicto final.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    return (
        getattr(user, "is_superuser", False)
        or getattr(user, "tipo_persona", "") == "ADMIN"
        or usuario_es_directora(user)
    )


def guardar_pdf_reporte_final_directora(inscripcion):
    """
    Genera nuevamente el PDF FO-301-02-18 ya con la resolución final de Dirección
    y guarda la ruta en el campo reporte_final_pdf.

    No duplica el archivo con FileField; solo registra la ruta relativa dentro de MEDIA_ROOT.
    """
    if generar_pdf_reporte_final_ingreso is None:
        return False, None, "No está disponible la función generar_pdf_reporte_final_ingreso."

    pdf_path = generar_pdf_reporte_final_ingreso(inscripcion)

    if not pdf_path or not os.path.exists(pdf_path):
        return False, None, "No se pudo generar el PDF del Reporte Final de Ingreso."

    ruta_relativa = os.path.relpath(pdf_path, settings.MEDIA_ROOT).replace("\\", "/")
    inscripcion.reporte_final_pdf.name = ruta_relativa
    inscripcion.save(update_fields=["reporte_final_pdf"])

    return True, pdf_path, "PDF del Reporte Final generado correctamente."


# =======================================================
# ACCIONES DE LA DIRECTIVA
# =======================================================
@login_required
def veredicto_final_directora(request, inscripcion_id):
    """
    Resolución final de Dirección para el Sprint 3.

    Flujo:
    - Recibe expedientes en ESPERANDO_DIRECTORA.
    - Directora acepta: pasa a ACEPTADO_ESPERANDO_PAGO.
    - Directora rechaza: pasa a RECHAZADA.
    - Se genera PDF FO-301-02-18 actualizado con la firma/resolución de Dirección.
    - Se envía correo al beneficiario con el Reporte Final de Ingreso adjunto.
    """
    if not usuario_es_directora_o_admin(request.user):
        logout(request)
        messages.error(request, "Acceso denegado. Área exclusiva de Dirección.")
        return redirect("login")

    if request.method == "POST":
        bloqueo_semestre = bloquear_si_no_hay_semestre_activo(request, permitir_admin=True)
        if bloqueo_semestre:
            return bloqueo_semestre

    insc = get_object_or_404(
        SolicitudInscripcion.objects.select_related("solicitud_ingreso", "usuario_tutor"),
        id=inscripcion_id,
    )

    if request.method == "POST":
        accion = (request.POST.get("accion") or "").strip().upper()
        observaciones = (
            request.POST.get("directora_observaciones")
            or request.POST.get("observaciones_directora")
            or request.POST.get("motivo_rechazo")
            or request.POST.get("comentario")
            or ""
        ).strip()

        if insc.estado != "ESPERANDO_DIRECTORA" and accion in ["ACEPTAR", "APROBAR", "RECHAZAR"]:
            messages.warning(
                request,
                "Este expediente no está pendiente de resolución final de Dirección."
            )
            return redirect("dashboard_directiva")

        if accion in ["ACEPTAR", "APROBAR"]:
            insc.directora_aprobado = True
            insc.directora_observaciones = observaciones
            insc.directora_por = request.user
            insc.directora_en = timezone.now()
            insc.estado = "ACEPTADO_ESPERANDO_PAGO"
            insc.observaciones = (
                "Dirección aprobó la inscripción final. "
                "Pendiente adjuntar comprobante de pago por Trabajo Social."
            )
            insc.save()

            pdf_generado, pdf_path, mensaje_pdf = guardar_pdf_reporte_final_directora(insc)

            if enviar_correo_reporte_final_ingreso is not None:
                enviado, mensaje_correo = enviar_correo_reporte_final_ingreso(insc, pdf_path)
            else:
                enviado, mensaje_correo = False, "No está disponible la función de envío de correo."

            if pdf_generado and enviado:
                messages.success(
                    request,
                    "Inscripción aprobada por Dirección. Se generó el Reporte Final y se envió el correo al beneficiario."
                )
            elif pdf_generado:
                messages.warning(
                    request,
                    f"Inscripción aprobada y PDF generado, pero no se pudo enviar el correo: {mensaje_correo}"
                )
            else:
                messages.warning(
                    request,
                    f"Inscripción aprobada, pero ocurrió un problema con el PDF: {mensaje_pdf}"
                )

        elif accion == "RECHAZAR":
            if not observaciones:
                messages.error(
                    request,
                    "Para rechazar la inscripción debes escribir el motivo u observaciones de Dirección."
                )
                return redirect("dashboard_directiva")

            insc.directora_aprobado = False
            insc.directora_observaciones = observaciones
            insc.directora_por = request.user
            insc.directora_en = timezone.now()
            insc.estado = "RECHAZADA"
            insc.observaciones = "Dirección rechazó la inscripción final."
            insc.save()

            pdf_generado, pdf_path, mensaje_pdf = guardar_pdf_reporte_final_directora(insc)

            if enviar_correo_reporte_final_ingreso is not None:
                enviado, mensaje_correo = enviar_correo_reporte_final_ingreso(insc, pdf_path)
            else:
                enviado, mensaje_correo = False, "No está disponible la función de envío de correo."

            if pdf_generado and enviado:
                messages.error(
                    request,
                    "Inscripción rechazada por Dirección. Se generó el Reporte Final y se envió el correo al beneficiario."
                )
            elif pdf_generado:
                messages.warning(
                    request,
                    f"Inscripción rechazada y PDF generado, pero no se pudo enviar el correo: {mensaje_correo}"
                )
            else:
                messages.warning(
                    request,
                    f"Inscripción rechazada, pero ocurrió un problema con el PDF: {mensaje_pdf}"
                )

        elif accion == "PENDIENTE":
            insc.estado = "ESPERANDO_DIRECTORA"
            insc.directora_observaciones = observaciones
            insc.save(update_fields=["estado", "directora_observaciones"])
            messages.info(request, "El expediente se mantiene pendiente de resolución final.")

        else:
            messages.error(request, "Acción no válida para Dirección.")

    return redirect("dashboard_directiva")


@login_required
def dictaminar_sala_directora(request, inscripcion_id):
    insc = get_object_or_404(SolicitudInscripcion, id=inscripcion_id)

    if request.method == "POST":
        bloqueo_semestre = bloquear_si_no_hay_semestre_activo(request, permitir_admin=True)
        if bloqueo_semestre:
            return bloqueo_semestre
        accion = request.POST.get("accion")

        if accion == "APROBAR":
            insc.estado = "SALA_APROBADA"
            insc.motivo_rechazo_sala = ""

            nombre_sala = "sin sala asignada"
            if getattr(insc, "sala_asignada", None):
                nombre_sala = insc.sala_asignada.nombre

            messages.success(request, f"Sala {nombre_sala} aprobada.")

        elif accion == "RECHAZAR":
            insc.estado = "SALA_RECHAZADA"
            insc.motivo_rechazo_sala = request.POST.get("motivo_rechazo", "").strip()
            messages.warning(request, "Has rechazado la sala propuesta.")

        insc.save()

    return redirect("dashboard_directiva")


@login_required
def dashboard_admin(request):
    """
    Panel de Trabajo Social.

    Aquí se calculan los números reales para el panel general:
    beneficiarios inscritos, pendientes, en proceso, finalizados y actividad reciente.
    """
    if usuario_es_admin_sistema(request.user):
        return redirect("panel_gobierno_ti")

    if not request.user.is_staff or not usuario_es_trabajadora_social(request.user):
        logout(request)
        messages.error(request, "Acceso denegado. Área exclusiva de Trabajo Social.")
        return redirect("login")

    if request.method == "POST":
        is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
        accion = request.POST.get("action_type")

        if accion in ["actualizar_foto_trabajo_social", "eliminar_foto_trabajo_social"]:
            return procesar_foto_perfil_trabajo_social_panel(request, accion, is_ajax=is_ajax)

        messages.warning(request, "Acción no válida para el panel de Trabajo Social.")
        return redirect("dashboard_admin")

    semestre_context = contexto_semestre_operativo()
    semestre_activo = semestre_context.get("semestre_activo_operativo")

    # Base de inscripciones. Si el modelo tiene campo semestre/ciclo/periodo, se filtra por el semestre activo.
    inscripciones_qs = SolicitudInscripcion.objects.all()
    campos_inscripcion = {campo.name for campo in SolicitudInscripcion._meta.get_fields()}

    if semestre_activo:
        for campo_semestre in ["semestre", "ciclo", "periodo"]:
            if campo_semestre in campos_inscripcion:
                try:
                    inscripciones_qs = inscripciones_qs.filter(**{campo_semestre: semestre_activo})
                    break
                except Exception:
                    pass

    def filtrar_estados(qs, estados):
        """Filtra por varios estados sin depender de mayúsculas/minúsculas."""
        if "estado" not in campos_inscripcion:
            return qs.none()

        consulta = Q()
        for estado in estados:
            consulta |= Q(estado__iexact=estado)
        return qs.filter(consulta)

    def excluir_estados(qs, estados):
        """Excluye varios estados sin depender de mayúsculas/minúsculas."""
        if "estado" not in campos_inscripcion:
            return qs

        consulta = Q()
        for estado in estados:
            consulta |= Q(estado__iexact=estado)
        return qs.exclude(consulta)

    def porcentaje(valor, total):
        if not total:
            return 0
        return round((valor * 100) / total, 1)

    estados_finalizados = [
        "FINALIZADA",
        "FINALIZADO",
        "INSCRITA",
        "INSCRITO",
        "COMPLETADA",
        "COMPLETADO",
    ]

    estados_fuera_proceso = [
        "RECHAZADA",
        "RECHAZADO",
        "CANCELADA",
        "CANCELADO",
        "BAJA",
    ]

    # Estados que normalmente requieren revisión o seguimiento de Trabajo Social.
    estados_pendientes_trabajo_social = [
        "CAPTURA",
        "EN_REVISION",
        "PENDIENTE",
        "FILTROS",
        "SALA_RECHAZADA",
        "ACEPTADO_ESPERANDO_PAGO",
        "PAGO_PENDIENTE",
        "PAGO_EN_REVISION",
        "COMPROBANTE_SUBIDO",
        "PAGO_RECHAZADO",
        "CODIGO_PENDIENTE",
        "CODIGO_GENERADO",
    ]

    estados_solicitudes = [
        "CAPTURA",
        "EN_REVISION",
        "PENDIENTE",
        "FILTROS",
        "SALA_RECHAZADA",
        "SALA_EN_REVISION",
    ]

    estados_reportes = [
        "FILTROS",
        "SALA_EN_REVISION",
        "ESPERANDO_DIRECTORA",
        "SALA_APROBADA",
    ]

    estados_pagos = [
        "ACEPTADO_ESPERANDO_PAGO",
        "PAGO_PENDIENTE",
        "PAGO_EN_REVISION",
        "COMPROBANTE_SUBIDO",
        "PAGO_RECHAZADO",
    ]

    estados_codigos = [
        "CODIGO_PENDIENTE",
        "CODIGO_GENERADO",
        "CODIGO_ENTREGADO",
    ]

    inscripciones_activas_qs = excluir_estados(inscripciones_qs, estados_fuera_proceso)

    total_beneficiarios_inscribiendo = inscripciones_activas_qs.count()
    beneficiarios_proceso_completo = filtrar_estados(inscripciones_activas_qs, estados_finalizados).count()
    beneficiarios_en_proceso = max(total_beneficiarios_inscribiendo - beneficiarios_proceso_completo, 0)

    beneficiarios_pendientes_atender = filtrar_estados(
        inscripciones_activas_qs,
        estados_pendientes_trabajo_social,
    ).count()

    # Si no coincide ningún estado específico, al menos se muestran los que siguen en proceso.
    if beneficiarios_pendientes_atender == 0 and beneficiarios_en_proceso > 0:
        beneficiarios_pendientes_atender = beneficiarios_en_proceso

    solicitudes_activas = filtrar_estados(inscripciones_activas_qs, estados_solicitudes).count()
    reportes_pendientes = filtrar_estados(inscripciones_activas_qs, estados_reportes).count()
    pagos_pendientes = filtrar_estados(inscripciones_activas_qs, estados_pagos).count()
    codigos_pendientes = filtrar_estados(inscripciones_activas_qs, estados_codigos).count()

    # Si existe algún campo booleano relacionado con entrega de código, lo usamos para mejorar el conteo.
    for campo_codigo in [
        "codigo_entregado",
        "codigo_seguridad_entregado",
        "codigo_responsable_entregado",
        "credencial_entregada",
    ]:
        if campo_codigo in campos_inscripcion:
            try:
                codigos_pendientes = inscripciones_activas_qs.filter(**{campo_codigo: False}).count()
                break
            except Exception:
                pass

    # Actividad reciente: inscripciones modificadas o creadas en los últimos 15 minutos.
    hace_15_minutos = timezone.now() - timedelta(minutes=15)

    if "updated_at" in campos_inscripcion:
        beneficiarios_inscribiendo_ahora = inscripciones_activas_qs.filter(
            updated_at__gte=hace_15_minutos
        ).count()
    elif "fecha_actualizacion" in campos_inscripcion:
        beneficiarios_inscribiendo_ahora = inscripciones_activas_qs.filter(
            fecha_actualizacion__gte=hace_15_minutos
        ).count()
    elif "created_at" in campos_inscripcion:
        beneficiarios_inscribiendo_ahora = inscripciones_activas_qs.filter(
            created_at__gte=hace_15_minutos
        ).count()
    elif "fecha_registro" in campos_inscripcion:
        beneficiarios_inscribiendo_ahora = inscripciones_activas_qs.filter(
            fecha_registro__gte=hace_15_minutos
        ).count()
    else:
        beneficiarios_inscribiendo_ahora = beneficiarios_en_proceso

    context = {
        "total_beneficiarios_inscribiendo": total_beneficiarios_inscribiendo,
        "beneficiarios_pendientes_atender": beneficiarios_pendientes_atender,
        "beneficiarios_proceso_completo": beneficiarios_proceso_completo,
        "porcentaje_proceso_completo": porcentaje(
            beneficiarios_proceso_completo,
            total_beneficiarios_inscribiendo,
        ),
        "beneficiarios_en_proceso": beneficiarios_en_proceso,
        "porcentaje_en_proceso": porcentaje(
            beneficiarios_en_proceso,
            total_beneficiarios_inscribiendo,
        ),
        "beneficiarios_inscribiendo_ahora": beneficiarios_inscribiendo_ahora,
        "porcentaje_pendientes_atender": porcentaje(
            beneficiarios_pendientes_atender,
            total_beneficiarios_inscribiendo,
        ),
        "solicitudes_activas": solicitudes_activas,
        "reportes_pendientes": reportes_pendientes,
        "pagos_pendientes": pagos_pendientes,
        "codigos_pendientes": codigos_pendientes,
        "porcentaje_solicitudes": porcentaje(solicitudes_activas, total_beneficiarios_inscribiendo),
        "porcentaje_reportes": porcentaje(reportes_pendientes, total_beneficiarios_inscribiendo),
        "porcentaje_pagos": porcentaje(pagos_pendientes, total_beneficiarios_inscribiendo),
        "porcentaje_codigos": porcentaje(codigos_pendientes, total_beneficiarios_inscribiendo),
    }

    context.update(obtener_contexto_personal_operativo())
    context.update(semestre_context)

    return render(request, "portal/panel_admin.html", context)


@login_required
def dashboard_medico(request):
    if not request.user.is_staff or not usuario_es_medica(request.user):
        logout(request)
        messages.error(request, "Acceso denegado. Área exclusiva del personal Médico.")
        return redirect("login")

    context = {}
    context.update(obtener_contexto_personal_operativo())
    context.update(contexto_semestre_operativo())

    return render(request, "dashboard/home_medico.html", context)



# =======================================================
# FOTO DE PERFIL - PORTAL DE PADRES / BENEFICIARIO
# =======================================================
def obtener_url_foto_perfil_usuario(user):
    """
    Devuelve la URL pública de la foto de perfil del usuario autenticado.
    Si el modelo no tiene campo de foto o no hay archivo guardado, regresa cadena vacía.
    """
    campo_foto = obtener_campo_foto_perfil_usuario(user)

    if not campo_foto:
        return ""

    try:
        archivo = getattr(user, campo_foto, None)
        if archivo and getattr(archivo, "url", None):
            return archivo.url
    except Exception:
        return ""

    return ""


def responder_accion_beneficiario_foto(request, status, mensaje):
    """
    Responde a las acciones de foto de perfil del Portal de Padres.
    El HTML del portal muestra estos mensajes con una notificación personalizada.
    """
    if status == "success":
        messages.success(request, mensaje)
    else:
        messages.error(request, mensaje)

    return redirect(reverse("portal_padres_home") + "#inicio")


def procesar_foto_perfil_beneficiario_panel(request, accion):
    """
    Guarda o elimina la foto de perfil del beneficiario desde portal/home_padres.html.

    Acciones esperadas desde el HTML:
    - actualizar_foto_beneficiario
    - eliminar_foto_beneficiario

    Reglas:
    - JPG, JPEG, PNG o WEBP.
    - Máximo 3 MB.
    """
    if not request.user or not getattr(request.user, "is_authenticated", False):
        return responder_accion_beneficiario_foto(
            request,
            "error",
            "Debes iniciar sesión para modificar tu foto de perfil.",
        )

    if getattr(request.user, "tipo_persona", "") != "BENEFICIARIO":
        return responder_accion_beneficiario_foto(
            request,
            "error",
            "Esta foto de perfil solo puede modificarse desde una cuenta de beneficiario.",
        )

    campo_foto = obtener_campo_foto_perfil_usuario(request.user)

    if not campo_foto:
        return responder_accion_beneficiario_foto(
            request,
            "error",
            "El modelo de usuarios no tiene configurado un campo de foto de perfil.",
        )

    if accion == "eliminar_foto_beneficiario":
        try:
            archivo_actual = getattr(request.user, campo_foto, None)

            if archivo_actual:
                if hasattr(request.user, "eliminar_foto_perfil"):
                    request.user.eliminar_foto_perfil(guardar=True)
                else:
                    try:
                        archivo_actual.delete(save=False)
                    except Exception:
                        pass

                    setattr(request.user, campo_foto, None)

                    try:
                        request.user.save(update_fields=[campo_foto])
                    except Exception:
                        request.user.save()

            try:
                AccessLog.objects.create(
                    usuario=request.user,
                    accion="PERFIL: Eliminó su foto de perfil del Portal de Padres.",
                )
            except Exception:
                pass

            return responder_accion_beneficiario_foto(
                request,
                "success",
                "Foto de perfil del beneficiario eliminada correctamente.",
            )

        except Exception as exc:
            return responder_accion_beneficiario_foto(
                request,
                "error",
                f"No se pudo eliminar la foto de perfil: {exc}",
            )

    if accion == "actualizar_foto_beneficiario":
        archivo = request.FILES.get("foto_perfil_beneficiario") or request.FILES.get("foto_perfil")
        es_valido, mensaje_validacion = validar_archivo_foto_perfil_admin(archivo)

        if not es_valido:
            return responder_accion_beneficiario_foto(
                request,
                "error",
                mensaje_validacion,
            )

        try:
            archivo_actual = getattr(request.user, campo_foto, None)

            if archivo_actual:
                try:
                    archivo_actual.delete(save=False)
                except Exception:
                    pass

            setattr(request.user, campo_foto, archivo)

            try:
                request.user.save(update_fields=[campo_foto])
            except Exception:
                request.user.save()

            try:
                AccessLog.objects.create(
                    usuario=request.user,
                    accion="PERFIL: Actualizó su foto de perfil del Portal de Padres.",
                )
            except Exception:
                pass

            return responder_accion_beneficiario_foto(
                request,
                "success",
                "Foto de perfil del beneficiario actualizada correctamente.",
            )

        except Exception as exc:
            return responder_accion_beneficiario_foto(
                request,
                "error",
                f"No se pudo guardar la foto de perfil: {exc}",
            )

    return responder_accion_beneficiario_foto(
        request,
        "error",
        "Acción de foto de perfil no válida.",
    )



# =======================================================
# FOTO DE PERFIL - ADMINISTRADOR DEL SISTEMA / PANEL TI
# =======================================================
MAX_FOTO_PERFIL_ADMIN_MB = 3
MAX_FOTO_PERFIL_ADMIN_BYTES = MAX_FOTO_PERFIL_ADMIN_MB * 1024 * 1024
EXTENSIONES_FOTO_PERFIL_ADMIN = {".jpg", ".jpeg", ".png", ".webp"}


def obtener_campo_foto_perfil_usuario(user):
    """
    Detecta de forma segura el campo real de foto de perfil del modelo Usuario.
    Actualmente el proyecto usa foto_perfil, pero se dejan alias para evitar romper
    si el nombre cambia después.
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
            if field.get_internal_type() in ["ImageField", "FileField"]:
                return campo
        except Exception:
            continue

    return ""


def responder_accion_panel_ti_foto(request, is_ajax, status, mensaje):
    """
    Devuelve JSON cuando el panel envía AJAX y usa messages cuando entra por POST normal.
    """
    if is_ajax:
        return JsonResponse({"status": status, "msg": mensaje})

    if status == "success":
        messages.success(request, mensaje)
    else:
        messages.warning(request, mensaje)

    return redirect("panel_gobierno_ti")


def validar_archivo_foto_perfil_admin(archivo):
    """
    Validación backend para que la foto del Administrador no sature el servidor.
    Aunque el HTML valide, esta validación protege si alguien modifica el navegador.
    """
    if not archivo:
        return False, "Selecciona una imagen para actualizar tu foto de perfil."

    extension = os.path.splitext(getattr(archivo, "name", "") or "")[1].lower()

    if extension not in EXTENSIONES_FOTO_PERFIL_ADMIN:
        return False, "Formato no permitido. Usa JPG, JPEG, PNG o WEBP."

    tamano = getattr(archivo, "size", 0) or 0

    if tamano <= 0:
        return False, "La imagen está vacía. Selecciona un archivo válido."

    if tamano > MAX_FOTO_PERFIL_ADMIN_BYTES:
        peso_mb = round(tamano / (1024 * 1024), 2)
        return False, f"La foto pesa {peso_mb} MB y supera el límite permitido de {MAX_FOTO_PERFIL_ADMIN_MB} MB."

    return True, "Imagen válida."


def procesar_foto_perfil_admin_panel_ti(request, accion, is_ajax=False):
    """
    Guarda o elimina la foto de perfil del Administrador del Sistema desde panel_ti.html.

    Acciones esperadas desde el HTML:
    - actualizar_foto_admin
    - eliminar_foto_admin
    """
    if not usuario_es_admin_sistema(request.user):
        return responder_accion_panel_ti_foto(
            request,
            is_ajax,
            "error",
            "No tienes permiso para modificar la foto de perfil del Administrador.",
        )

    campo_foto = obtener_campo_foto_perfil_usuario(request.user)

    if not campo_foto:
        return responder_accion_panel_ti_foto(
            request,
            is_ajax,
            "error",
            "El modelo de usuarios no tiene configurado un campo de foto de perfil.",
        )

    if accion == "eliminar_foto_admin":
        try:
            if hasattr(request.user, "eliminar_foto_perfil"):
                request.user.eliminar_foto_perfil(guardar=True)
            else:
                archivo_actual = getattr(request.user, campo_foto, None)
                if archivo_actual:
                    try:
                        archivo_actual.delete(save=False)
                    except Exception:
                        pass

                setattr(request.user, campo_foto, None)
                try:
                    request.user.save(update_fields=[campo_foto])
                except Exception:
                    request.user.save()

            try:
                AccessLog.objects.create(
                    usuario=request.user,
                    accion="PERFIL: Eliminó su foto de perfil de Administrador.",
                )
            except Exception:
                pass

            return responder_accion_panel_ti_foto(
                request,
                is_ajax,
                "success",
                "Foto de perfil eliminada correctamente.",
            )

        except Exception as exc:
            return responder_accion_panel_ti_foto(
                request,
                is_ajax,
                "error",
                f"No se pudo eliminar la foto de perfil: {exc}",
            )

    if accion == "actualizar_foto_admin":
        archivo = request.FILES.get("foto_perfil_admin") or request.FILES.get("foto_perfil")
        es_valido, mensaje_validacion = validar_archivo_foto_perfil_admin(archivo)

        if not es_valido:
            return responder_accion_panel_ti_foto(
                request,
                is_ajax,
                "error",
                mensaje_validacion,
            )

        try:
            setattr(request.user, campo_foto, archivo)
            try:
                request.user.save(update_fields=[campo_foto])
            except Exception:
                request.user.save()

            try:
                AccessLog.objects.create(
                    usuario=request.user,
                    accion="PERFIL: Actualizó su foto de perfil de Administrador.",
                )
            except Exception:
                pass

            return responder_accion_panel_ti_foto(
                request,
                is_ajax,
                "success",
                "Foto de perfil actualizada correctamente.",
            )

        except Exception as exc:
            return responder_accion_panel_ti_foto(
                request,
                is_ajax,
                "error",
                f"No se pudo guardar la foto de perfil: {exc}",
            )

    return responder_accion_panel_ti_foto(
        request,
        is_ajax,
        "error",
        "Acción de foto de perfil no válida.",
    )


# =======================================================
# FOTO DE PERFIL - TRABAJO SOCIAL / PANEL PRINCIPAL
# =======================================================
def responder_accion_trabajo_social_foto(request, is_ajax, status, mensaje):
    """
    Responde a las acciones de foto de perfil de Trabajo Social.
    En POST normal usa messages para mostrar la notificación con el diseño del HTML.
    """
    if is_ajax:
        return JsonResponse({"status": status, "msg": mensaje})

    if status == "success":
        messages.success(request, mensaje)
    else:
        messages.error(request, mensaje)

    return redirect("dashboard_admin")


def procesar_foto_perfil_trabajo_social_panel(request, accion, is_ajax=False):
    """
    Guarda o elimina la foto de perfil de la Trabajadora Social desde panel_admin.html.

    Acciones esperadas desde el HTML:
    - actualizar_foto_trabajo_social
    - eliminar_foto_trabajo_social
    """
    if not getattr(request.user, "is_staff", False) or not usuario_es_trabajadora_social(request.user):
        return responder_accion_trabajo_social_foto(
            request,
            is_ajax,
            "error",
            "No tienes permiso para modificar la foto de perfil de Trabajo Social.",
        )

    campo_foto = obtener_campo_foto_perfil_usuario(request.user)

    if not campo_foto:
        return responder_accion_trabajo_social_foto(
            request,
            is_ajax,
            "error",
            "El modelo de usuarios no tiene configurado un campo de foto de perfil.",
        )

    if accion == "eliminar_foto_trabajo_social":
        try:
            archivo_actual = getattr(request.user, campo_foto, None)

            if not archivo_actual:
                return responder_accion_trabajo_social_foto(
                    request,
                    is_ajax,
                    "success",
                    "No había foto de perfil para eliminar.",
                )

            if hasattr(request.user, "eliminar_foto_perfil"):
                request.user.eliminar_foto_perfil(guardar=True)
            else:
                try:
                    archivo_actual.delete(save=False)
                except Exception:
                    pass

                setattr(request.user, campo_foto, None)
                try:
                    request.user.save(update_fields=[campo_foto])
                except Exception:
                    request.user.save()

            try:
                AccessLog.objects.create(
                    usuario=request.user,
                    accion="PERFIL: Eliminó su foto de perfil de Trabajo Social.",
                )
            except Exception:
                pass

            return responder_accion_trabajo_social_foto(
                request,
                is_ajax,
                "success",
                "Foto de perfil eliminada correctamente.",
            )

        except Exception as exc:
            return responder_accion_trabajo_social_foto(
                request,
                is_ajax,
                "error",
                f"No se pudo eliminar la foto de perfil: {exc}",
            )

    if accion == "actualizar_foto_trabajo_social":
        archivo = request.FILES.get("foto_perfil_trabajo_social") or request.FILES.get("foto_perfil")
        es_valido, mensaje_validacion = validar_archivo_foto_perfil_admin(archivo)

        if not es_valido:
            return responder_accion_trabajo_social_foto(
                request,
                is_ajax,
                "error",
                mensaje_validacion,
            )

        try:
            setattr(request.user, campo_foto, archivo)
            try:
                request.user.save(update_fields=[campo_foto])
            except Exception:
                request.user.save()

            try:
                AccessLog.objects.create(
                    usuario=request.user,
                    accion="PERFIL: Actualizó su foto de perfil de Trabajo Social.",
                )
            except Exception:
                pass

            return responder_accion_trabajo_social_foto(
                request,
                is_ajax,
                "success",
                "Foto de perfil actualizada correctamente.",
            )

        except Exception as exc:
            return responder_accion_trabajo_social_foto(
                request,
                is_ajax,
                "error",
                f"No se pudo guardar la foto de perfil: {exc}",
            )

    return responder_accion_trabajo_social_foto(
        request,
        is_ajax,
        "error",
        "Acción de foto de perfil no válida.",
    )


@login_required
def panel_gobierno_ti(request):
    User = get_user_model()

    if not usuario_es_admin_sistema(request.user):
        logout(request)
        messages.error(request, "ACCESO DENEGADO. No eres el Administrador del Sistema.")
        return redirect("login")

    if request.method == "POST":
        is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
        accion = request.POST.get("action_type")
        response_data = {"status": "success", "msg": "Acción realizada"}

        try:
            if accion in ["actualizar_foto_admin", "eliminar_foto_admin"]:
                return procesar_foto_perfil_admin_panel_ti(request, accion, is_ajax=is_ajax)

            elif accion == "create_user":
                email = limpiar_correo(request.POST.get("email", ""))
                password = request.POST.get("password")
                nombre = request.POST.get("nombre", "").strip()
                apellido_paterno = request.POST.get("apellido_paterno", "").strip()
                apellido_materno = request.POST.get("apellido_materno", "").strip()
                curp = request.POST.get("curp", "").strip().upper()
                tipo_persona = request.POST.get("tipo_persona") or "PERSONAL"
                area_operativa = limpiar_area_operativa(
                    request.POST.get("area_operativa"),
                    tipo_persona=tipo_persona,
                )
                num_empleado = request.POST.get("numero_empleado", "").strip()

                # =====================================================
                # VALIDACIONES ANTES DE GUARDAR
                # Evita usuarios/correos huérfanos cuando falla otro dato.
                # =====================================================
                errores = []

                if not email:
                    errores.append("El correo es obligatorio.")

                if email and not email.endswith("@unach.mx"):
                    errores.append("El correo del personal debe terminar en @unach.mx.")

                if not password:
                    errores.append("La contraseña es obligatoria.")

                if not nombre:
                    errores.append("El nombre es obligatorio.")

                if not apellido_paterno:
                    errores.append("El apellido paterno es obligatorio.")

                if not curp:
                    errores.append("La CURP es obligatoria.")

                if not num_empleado:
                    errores.append("El número de empleado es obligatorio.")

                if email and (
                    User.objects.filter(email__iexact=email).exists()
                    or User.objects.filter(username__iexact=email).exists()
                ):
                    errores.append(f'El correo "{email}" ya existe en el sistema.')

                if curp and User.objects.filter(curp__iexact=curp).exists():
                    errores.append(f'La CURP "{curp}" ya está registrada con otro usuario.')

                if num_empleado and User.objects.filter(numero_empleado=num_empleado).exists():
                    errores.append(f'El número de empleado "{num_empleado}" ya está registrado con otro usuario.')

                if errores:
                    mensaje_error = " ".join(errores)

                    if is_ajax:
                        return JsonResponse(
                            {
                                "status": "error",
                                "msg": mensaje_error,
                            }
                        )

                    messages.error(request, mensaje_error)
                    return redirect("panel_gobierno_ti")

                # =====================================================
                # GUARDADO ATÓMICO
                # Si algo falla al crear usuario o bitácora, se cancela todo.
                # =====================================================
                with transaction.atomic():
                    u = User.objects.create_user(
                        username=email,
                        email=email,
                        password=password,
                    )

                    u.nombre = nombre
                    u.apellido_paterno = apellido_paterno
                    u.apellido_materno = apellido_materno
                    u.curp = curp
                    u.tipo_persona = tipo_persona
                    if hasattr(u, "area_operativa"):
                        u.area_operativa = area_operativa
                    u.numero_empleado = num_empleado
                    u.estatus_operativo = True
                    u.is_active = True
                    u.is_staff = True

                    if tipo_persona == "ADMIN":
                        u.is_superuser = True

                    u.save()

                    AccessLog.objects.create(
                        usuario=request.user,
                        accion=f"CREACIÓN: Registró a {nombre} [{tipo_persona}]",
                    )

                response_data["msg"] = f"Persona {nombre} registrada exitosamente."

            elif accion == "edit_user":
                user_id = request.POST.get("user_id")
                usr_edit = User.objects.get(id=user_id)

                nombre = request.POST.get("nombre", "").strip()
                apellido_paterno = request.POST.get("apellido_paterno", "").strip()
                apellido_materno = request.POST.get("apellido_materno", "").strip()
                curp = request.POST.get("curp", "").strip().upper()
                email = limpiar_correo(request.POST.get("email", ""))
                tipo_persona = request.POST.get("tipo_persona") or "PERSONAL"
                area_operativa = limpiar_area_operativa(
                    request.POST.get("area_operativa", getattr(usr_edit, "area_operativa", "")),
                    tipo_persona=tipo_persona,
                )
                numero_empleado = request.POST.get("numero_empleado", "").strip()
                estatus_operativo = request.POST.get("estatus_operativo", "true")
                password = request.POST.get("password", "").strip()

                errores = []

                if not nombre:
                    errores.append("El nombre es obligatorio.")

                if not apellido_paterno:
                    errores.append("El apellido paterno es obligatorio.")

                if not curp:
                    errores.append("La CURP es obligatoria.")

                if not email:
                    errores.append("El correo es obligatorio.")

                if email and not email.endswith("@unach.mx"):
                    errores.append("El correo del personal debe terminar en @unach.mx.")

                if not numero_empleado and tipo_persona != "ADMIN":
                    errores.append("El número de empleado es obligatorio.")

                if email and (
                    User.objects.filter(email__iexact=email).exclude(pk=usr_edit.pk).exists()
                    or User.objects.filter(username__iexact=email).exclude(pk=usr_edit.pk).exists()
                ):
                    errores.append(f'El correo "{email}" ya existe en otro usuario.')

                if curp and User.objects.filter(curp__iexact=curp).exclude(pk=usr_edit.pk).exists():
                    errores.append(f'La CURP "{curp}" ya está registrada con otro usuario.')

                if numero_empleado and User.objects.filter(numero_empleado=numero_empleado).exclude(pk=usr_edit.pk).exists():
                    errores.append(f'El número de empleado "{numero_empleado}" ya está registrado con otro usuario.')

                if errores:
                    mensaje_error = " ".join(errores)

                    if is_ajax:
                        return JsonResponse(
                            {
                                "status": "error",
                                "msg": mensaje_error,
                            }
                        )

                    messages.error(request, mensaje_error)
                    return redirect("panel_gobierno_ti")

                with transaction.atomic():
                    usr_edit.nombre = nombre
                    usr_edit.apellido_paterno = apellido_paterno
                    usr_edit.apellido_materno = apellido_materno
                    usr_edit.curp = curp
                    usr_edit.email = email
                    usr_edit.username = email
                    usr_edit.tipo_persona = tipo_persona
                    if hasattr(usr_edit, "area_operativa"):
                        usr_edit.area_operativa = area_operativa
                    usr_edit.numero_empleado = numero_empleado
                    usr_edit.estatus_operativo = estatus_operativo == "true"
                    usr_edit.is_active = estatus_operativo == "true"
                    usr_edit.is_staff = True

                    if tipo_persona == "ADMIN":
                        usr_edit.is_superuser = True
                    elif usr_edit.pk != request.user.pk:
                        usr_edit.is_superuser = False

                    if password:
                        usr_edit.set_password(password)

                    usr_edit.save()

                    AccessLog.objects.create(
                        usuario=request.user,
                        accion=f"EDICIÓN: Actualizó datos de {usr_edit.nombre} ({usr_edit.email})",
                    )

                response_data["msg"] = "Información actualizada correctamente."

            elif accion == "delete_user":
                user_id = request.POST.get("user_id")

                if int(user_id) != request.user.id:
                    User.objects.filter(id=user_id).delete()
                    response_data["msg"] = "Persona eliminada del sistema."

            elif accion == "assign_fixed_role":
                usuario_id = request.POST.get("usuario_id")
                rol_fijo = (request.POST.get("rol_fijo") or "").strip()

                if not usuario_id or not rol_fijo:
                    raise ValueError("Debe seleccionar un empleado y un rol.")

                # Compatibilidad con el nombre anterior del rol de maestras.
                if rol_fijo == "Asistentes de Salas (Maestras)":
                    rol_fijo = "Maestra / Asistente de Sala"

                empleado = User.objects.get(id=usuario_id)
                grupo, _ = Group.objects.get_or_create(name=rol_fijo)

                # Sprint 4:
                # Roles y Permisos SOLO define el tipo de empleado y su acceso.
                # La asignación a semestre, sala y horarios se realiza en Gestión de Semestres.
                empleado.groups.clear()
                empleado.groups.add(grupo)

                area_asignada = aplicar_area_operativa_por_rol(empleado, rol_fijo)
                campos_actualizar = []

                if hasattr(empleado, "area_operativa"):
                    campos_actualizar.append("area_operativa")

                # Al asignar un rol operativo, se asegura que el usuario sea personal activo.
                if rol_fijo != "Administrador del Sistema" and getattr(empleado, "tipo_persona", "") != "ADMIN":
                    empleado.tipo_persona = "PERSONAL"
                    empleado.is_staff = True
                    empleado.is_active = True
                    campos_actualizar.extend(["tipo_persona", "is_staff", "is_active"])

                if campos_actualizar:
                    empleado.save(update_fields=list(dict.fromkeys(campos_actualizar)))

                AccessLog.objects.create(
                    usuario=request.user,
                    accion=f"ASIGNÓ ROL: '{rol_fijo}' a {empleado.nombre}",
                )

                if area_asignada:
                    response_data["msg"] = (
                        f'Rol "{rol_fijo}" asignado correctamente. '
                        f"Área operativa actualizada a {area_asignada}. "
                        "La asignación a semestre/sala/horarios se realiza en Gestión de Semestres."
                    )
                else:
                    response_data["msg"] = (
                        f'Rol "{rol_fijo}" asignado correctamente. '
                        "La asignación a semestre/sala/horarios se realiza en Gestión de Semestres."
                    )

            elif accion == "remove_fixed_role":
                usuario_id = request.POST.get("usuario_id")
                empleado = User.objects.get(id=usuario_id)
                empleado.groups.clear()
                if hasattr(empleado, "area_operativa"):
                    empleado.area_operativa = None
                    empleado.save(update_fields=["area_operativa"])
                AsignacionMaestra.objects.filter(maestra=empleado).delete()
                response_data["msg"] = "Rol removido. También se quitaron sus asignaciones de maestra si existían."

            elif accion == "abandon_admin":
                sucesor_id = request.POST.get("sucesor_id")
                sucesor = User.objects.get(id=sucesor_id)
                yo = request.user

                sucesor.is_superuser = True
                sucesor.tipo_persona = "ADMIN"
                if hasattr(sucesor, "area_operativa"):
                    sucesor.area_operativa = None
                sucesor.save()

                yo.is_superuser = False
                yo.tipo_persona = "PERSONAL"
                if hasattr(yo, "area_operativa"):
                    yo.area_operativa = None
                yo.save()

                AccessLog.objects.create(
                    usuario=yo,
                    accion=f"CEDER MANDO: {sucesor.nombre} es el nuevo Administrador.",
                )

                response_data[
                    "msg"
                ] = "Has cedido la Administración. Tus permisos se han revocado, tu sesión seguirá abierta hasta que salgas manualmente."

            elif accion == "start_cycle":
                nombre = request.POST.get("nombre_semestre")
                inicio = request.POST.get("fecha_inicio")
                fin = request.POST.get("fecha_fin")

                Semestre.objects.filter(estado__in=["ACTIVO", "CONFIGURACION"]).update(estado="CERRADO")

                nuevo = Semestre.objects.create(
                    nombre=nombre,
                    estado="ACTIVO",
                    fecha_inicio=inicio,
                    fecha_fin=fin,
                )

                AccessLog.objects.create(
                    usuario=request.user,
                    accion=f"Inició semestre: {nuevo.nombre}",
                )

                response_data["msg"] = f"¡Semestre {nuevo.nombre} iniciado!"

            elif accion == "end_cycle":
                Semestre.objects.filter(estado__in=["ACTIVO", "CONFIGURACION"]).update(estado="CERRADO")
                response_data["msg"] = "Semestre cerrado."

            elif accion == "toggle_security":
                request.session["sec_encrypt"] = True if request.POST.get("toggle_encrypt") else False
                response_data["msg"] = "Protocolos de seguridad aplicados."

            elif accion == "clear_history":
                AccessLog.objects.all().delete()
                response_data["msg"] = "Historial depurado."

            if is_ajax:
                return JsonResponse(response_data)

        except Exception as e:
            if is_ajax:
                return JsonResponse({"status": "error", "msg": str(e)})

        return redirect("panel_gobierno_ti")

    staff_list = User.objects.exclude(tipo_persona="BENEFICIARIO").order_by("-date_joined")

    area_operativa_choices = getattr(User, "AREA_OPERATIVA_CHOICES", [])
    areas_suplencia = getattr(User, "AREAS_PERMITIDAS_SUPLENCIA", [])
    areas_pase_lista = getattr(User, "AREAS_PASE_LISTA", [])

    # =====================================================
    # INCIDENCIAS DENTRO DEL MISMO PANEL TI
    # Ya no se manda a otra vista. Los filtros se aplican aquí mismo.
    # URL resultante: /gobierno-ti/?tipo=NUTRICIONAL, etc.
    # =====================================================
    estado = (request.GET.get("estado") or "").strip().upper()
    nivel = (request.GET.get("nivel") or "").strip().upper()
    tipo = (request.GET.get("tipo") or "").strip().upper()

    campos_incidencia = {campo.name for campo in Incidencia._meta.get_fields()}
    incidencias_qs = Incidencia.objects.all()

    if estado:
        if "estado" in campos_incidencia:
            estados_alias = {
                "ABIERTA": ["ABIERTA", "ABIERTO", "PENDIENTE", "EN_SEGUIMIENTO"],
                "CERRADA": ["CERRADA", "CERRADO", "RESUELTA", "RESUELTO"],
            }.get(estado, [estado])

            q_estado = Q()
            for valor_estado in estados_alias:
                q_estado |= Q(estado__iexact=valor_estado)

            incidencias_qs = incidencias_qs.filter(q_estado)

        elif "resuelta" in campos_incidencia:
            if estado in ["ABIERTA", "ABIERTO", "PENDIENTE", "EN_SEGUIMIENTO"]:
                incidencias_qs = incidencias_qs.filter(resuelta=False)
            elif estado in ["CERRADA", "CERRADO", "RESUELTA", "RESUELTO"]:
                incidencias_qs = incidencias_qs.filter(resuelta=True)

    if nivel:
        if "nivel" in campos_incidencia:
            incidencias_qs = incidencias_qs.filter(nivel__iexact=nivel)
        elif "nivel_riesgo" in campos_incidencia:
            incidencias_qs = incidencias_qs.filter(nivel_riesgo__iexact=nivel)

    if tipo:
        campos_tipo = [
            nombre_campo
            for nombre_campo in ["tipo", "tipo_incidencia", "categoria", "area"]
            if nombre_campo in campos_incidencia
        ]

        alias_tipo = {
            "MEDICA": ["MEDICA", "MÉDICA", "MEDICO", "MÉDICO", "SALUD"],
            "NUTRICIONAL": ["NUTRICIONAL", "NUTRICION", "NUTRICIÓN", "NUTRICIONALES"],
            "PSICOLOGICA": ["PSICOLOGICA", "PSICOLÓGICA", "PSICOLOGIA", "PSICOLOGÍA"],
            "PEDAGOGICA": ["PEDAGOGICA", "PEDAGÓGICA", "PEDAGOGIA", "PEDAGOGÍA", "COORDINACION", "COORDINACIÓN"],
        }.get(tipo, [tipo])

        q_tipo = Q()
        for campo_tipo in campos_tipo:
            for valor_tipo in alias_tipo:
                q_tipo |= Q(**{f"{campo_tipo}__iexact": valor_tipo})

        if q_tipo.children:
            incidencias_qs = incidencias_qs.filter(q_tipo)

    if "fecha_reporte" in campos_incidencia:
        incidencias_qs = incidencias_qs.order_by("-fecha_reporte", "-id")
    elif "fecha_registro" in campos_incidencia:
        incidencias_qs = incidencias_qs.order_by("-fecha_registro", "-id")
    elif "created_at" in campos_incidencia:
        incidencias_qs = incidencias_qs.order_by("-created_at", "-id")
    else:
        incidencias_qs = incidencias_qs.order_by("-id")

    def valor_incidencia(obj, *nombres, default="--"):
        for nombre in nombres:
            if hasattr(obj, nombre):
                valor = getattr(obj, nombre)
                if valor is not None and valor != "":
                    return valor
        return default

    incidencias_rows = []
    for inc in incidencias_qs:
        if "estado" in campos_incidencia:
            estado_mostrar = valor_incidencia(inc, "estado")
        elif "resuelta" in campos_incidencia:
            estado_mostrar = "CERRADA" if getattr(inc, "resuelta", False) else "ABIERTA"
        else:
            estado_mostrar = "--"

        incidencias_rows.append({
            "obj": inc,
            "id": inc.id,
            "folio": valor_incidencia(inc, "folio", "codigo", default=f"INC-{inc.id}"),
            "tipo": valor_incidencia(inc, "tipo", "tipo_incidencia", "categoria", "area"),
            "nivel": valor_incidencia(inc, "nivel", "nivel_riesgo"),
            "estado": estado_mostrar,
            "fecha": valor_incidencia(inc, "fecha_reporte", "fecha_registro", "created_at", "fecha"),
            "descripcion": valor_incidencia(inc, "descripcion", "detalle", "observaciones", "motivo"),
            "responsable": valor_incidencia(inc, "creado_por", "registrado_por", "reportado_por", "usuario"),
            "menor": valor_incidencia(inc, "menor", "nino", "niño", "alumno", "solicitud_inscripcion"),
        })

    # Contadores generales para tarjetas.
    total_incidencias = Incidencia.objects.count()

    if "resuelta" in campos_incidencia:
        total_abiertas = Incidencia.objects.filter(resuelta=False).count()
        total_cerradas = Incidencia.objects.filter(resuelta=True).count()
    elif "estado" in campos_incidencia:
        total_abiertas = Incidencia.objects.filter(
            estado__in=["ABIERTA", "ABIERTO", "PENDIENTE", "EN_SEGUIMIENTO"]
        ).count()
        total_cerradas = Incidencia.objects.filter(
            estado__in=["CERRADA", "CERRADO", "RESUELTA", "RESUELTO"]
        ).count()
    else:
        total_abiertas = 0
        total_cerradas = 0

    if "nivel" in campos_incidencia:
        total_riesgo_alto = Incidencia.objects.filter(nivel__iexact="ALTO").count()
    elif "nivel_riesgo" in campos_incidencia:
        total_riesgo_alto = Incidencia.objects.filter(nivel_riesgo__iexact="ALTO").count()
    else:
        total_riesgo_alto = 0

    context = {
        "lista_staff": staff_list,
        "area_operativa_choices": area_operativa_choices,
        "areas_suplencia": areas_suplencia,
        "areas_pase_lista": areas_pase_lista,
        "ciclos_historial": Semestre.objects.all().order_by("-fecha_inicio"),
        "logs": AccessLog.objects.all().order_by("-fecha_acceso")[:50],
        "encrypt_active": request.session.get("sec_encrypt", True),
        "estado": estado,
        "nivel": nivel,
        "tipo": tipo,
        "incidencias_rows": incidencias_rows,
        "total_incidencias": total_incidencias,
        "total_abiertas": total_abiertas,
        "total_cerradas": total_cerradas,
        "total_riesgo_alto": total_riesgo_alto,
    }

    context.update(contexto_semestre_operativo())

    return render(request, "portal/panel_ti.html", context)


# ==============================================================
# INCIDENCIAS - VISTA EXCLUSIVA PARA ADMINISTRADOR DEL SISTEMA
# Esta vista evita mandar al Administrador al panel de Directora.
# ==============================================================
@login_required
def panel_incidencias_ti(request):
    """
    Compatibilidad con la URL anterior.
    Ya no renderiza otro HTML: redirige al mismo Panel TI conservando filtros.
    """
    if not usuario_es_admin_sistema(request.user):
        logout(request)
        messages.error(request, "ACCESO DENEGADO. Área exclusiva del Administrador del Sistema.")
        return redirect("login")

    base_url = reverse("panel_gobierno_ti")
    query_string = request.META.get("QUERY_STRING", "")

    if query_string:
        return redirect(f"{base_url}?{query_string}")

    return redirect(base_url)


# ==============================================================
# DESCARGA DE REPORTE DE CICLO EN PDF
# No usa template HTML eliminado.
# Guarda el PDF en media/reportes/ciclos/
# ==============================================================
@login_required
def descargar_reporte_ciclo_pdf(request, ciclo_id):
    if not usuario_es_admin_sistema(request.user):
        logout(request)
        messages.error(request, "ACCESO DENEGADO. No tienes permisos para descargar reportes.")
        return redirect("login")

    if not pisa:
        return HttpResponse("Error: instale xhtml2pdf con pip install xhtml2pdf", status=500)

    try:
        ciclo = get_object_or_404(Semestre, id=ciclo_id)
        asignaciones = AsignacionRolCiclo.objects.filter(semestre=ciclo).select_related(
            "usuario",
            "rol",
        )

        meses = {
            1: "enero",
            2: "febrero",
            3: "marzo",
            4: "abril",
            5: "mayo",
            6: "junio",
            7: "julio",
            8: "agosto",
            9: "septiembre",
            10: "octubre",
            11: "noviembre",
            12: "diciembre",
        }

        if ciclo.fecha_inicio and ciclo.fecha_fin:
            mes_inicio = meses.get(ciclo.fecha_inicio.month, "inicio")
            mes_fin = meses.get(ciclo.fecha_fin.month, "fin")
            anio = ciclo.fecha_inicio.year
            nombre_archivo = f"ciclo_escolar_{mes_inicio}_a_{mes_fin}_{anio}.pdf"
        else:
            nombre_limpio = ciclo.nombre.replace(" ", "_").lower()
            nombre_archivo = f"ciclo_escolar_{nombre_limpio}.pdf"

        filas = ""

        for asignacion in asignaciones:
            usuario = getattr(asignacion, "usuario", None)
            rol = getattr(asignacion, "rol", None)

            nombre_usuario = "Sin usuario"
            correo_usuario = ""

            if usuario:
                nombre_usuario = " ".join(
                    filter(
                        None,
                        [
                            getattr(usuario, "nombre", ""),
                            getattr(usuario, "apellido_paterno", ""),
                            getattr(usuario, "apellido_materno", ""),
                        ],
                    )
                ).strip() or getattr(usuario, "email", "Sin usuario")

                correo_usuario = getattr(usuario, "email", "")

            nombre_rol = getattr(rol, "name", "Sin rol")

            filas += f"""
            <tr>
                <td>{escape(nombre_usuario)}</td>
                <td>{escape(correo_usuario)}</td>
                <td>{escape(nombre_rol)}</td>
            </tr>
            """

        if not filas:
            filas = """
            <tr>
                <td colspan="3" style="text-align:center;">
                    No hay asignaciones registradas para este semestre.
                </td>
            </tr>
            """

        html = f"""
        <!DOCTYPE html>
        <html lang="es">
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    font-size: 12px;
                    color: #222;
                }}
                h1 {{
                    text-align: center;
                    font-size: 20px;
                    margin-bottom: 5px;
                }}
                h2 {{
                    text-align: center;
                    font-size: 15px;
                    margin-top: 0;
                    margin-bottom: 20px;
                }}
                .info {{
                    margin-bottom: 18px;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                }}
                th, td {{
                    border: 1px solid #555;
                    padding: 6px;
                }}
                th {{
                    background-color: #eeeeee;
                    text-align: left;
                }}
                .footer {{
                    margin-top: 30px;
                    font-size: 10px;
                    text-align: right;
                }}
            </style>
        </head>
        <body>
            <h1>Estancia Infantil UNACH</h1>
            <h2>Informe general de semestre</h2>

            <div class="info">
                <p><strong>Semestre:</strong> {escape(ciclo.nombre)}</p>
                <p><strong>Fecha de inicio:</strong> {escape(str(ciclo.fecha_inicio or "No registrada"))}</p>
                <p><strong>Fecha de fin:</strong> {escape(str(ciclo.fecha_fin or "No registrada"))}</p>
                <p><strong>Estado:</strong> {escape(str(ciclo.estado or "No registrado"))}</p>
                <p><strong>Fecha de generación:</strong> {timezone.now().strftime("%d/%m/%Y %H:%M")}</p>
            </div>

            <table>
                <thead>
                    <tr>
                        <th>Personal</th>
                        <th>Correo</th>
                        <th>Rol asignado</th>
                    </tr>
                </thead>
                <tbody>
                    {filas}
                </tbody>
            </table>

            <div class="footer">
                Documento generado automáticamente por el Sistema de Estancia Infantil UNACH.
            </div>
        </body>
        </html>
        """

        carpeta_reportes = Path(settings.MEDIA_ROOT) / "reportes" / "ciclos"
        carpeta_reportes.mkdir(parents=True, exist_ok=True)

        ruta_pdf = carpeta_reportes / nombre_archivo

        with open(ruta_pdf, "wb") as archivo_pdf:
            pisa_status = pisa.CreatePDF(io.BytesIO(html.encode("UTF-8")), dest=archivo_pdf)

        if pisa_status.err:
            return HttpResponse("Hubo un error al generar el PDF.", status=500)

        return FileResponse(
            open(ruta_pdf, "rb"),
            as_attachment=True,
            filename=nombre_archivo,
        )

    except Exception as e:
        messages.error(request, f"Error al generar reporte: {e}")
        return redirect("panel_gobierno_ti")


@login_required
def portal_padres_home(request):
    if getattr(request.user, "tipo_persona", "") != "BENEFICIARIO":
        logout(request)
        messages.error(request, "Acceso denegado. Área exclusiva para beneficiarios.")
        return redirect("login")

    if request.method == "POST":
        accion = (request.POST.get("action_type") or "").strip()

        if accion in ["actualizar_foto_beneficiario", "eliminar_foto_beneficiario"]:
            return procesar_foto_perfil_beneficiario_panel(request, accion)

        messages.warning(request, "Acción no válida para el Portal de Padres.")
        return redirect(reverse("portal_padres_home") + "#inicio")

    solicitud_activa = None
    mi_inscripcion = None
    semestre_activo = obtener_semestre_activo_operativo()
    ciclo_activo = bool(semestre_activo)

    try:
        # Primero se intenta encontrar el expediente propio del beneficiario.
        # Esto evita mostrar datos de otro tutor por tomar simplemente la última solicitud del sistema.
        mi_inscripcion = (
            SolicitudInscripcion.objects
            .select_related("solicitud_ingreso", "usuario_tutor")
            .filter(usuario_tutor=request.user)
            .order_by("-updated_at", "-id")
            .first()
        )

        if mi_inscripcion and getattr(mi_inscripcion, "solicitud_ingreso", None):
            solicitud_activa = mi_inscripcion.solicitud_ingreso

        # Si el proyecto todavía no tiene una inscripción ligada al usuario,
        # se conserva el comportamiento anterior como respaldo para no romper el flujo.
        if not solicitud_activa and ciclo_activo:
            solicitud_activa = Solicitud.objects.order_by("-id").first()

            if not solicitud_activa:
                kwargs = {}

                if "estado" in [f.name for f in Solicitud._meta.fields]:
                    kwargs["estado"] = "CAPTURA"

                solicitud_activa = Solicitud.objects.create(**kwargs)

    except Exception:
        solicitud_activa = None
        mi_inscripcion = None

    solicitud_id = solicitud_activa.id if solicitud_activa else None
    folio = getattr(solicitud_activa, "folio", None) if solicitud_activa else None

    context = {
        "solicitud_id": solicitud_id,
        "folio": folio,
        "mi_inscripcion": mi_inscripcion,
        "ciclo_activo": ciclo_activo,
        "semestre_activo_operativo": semestre_activo,
        "foto_perfil_beneficiario_url": obtener_url_foto_perfil_usuario(request.user),
        "perfil_beneficiario_soporta_foto": bool(obtener_campo_foto_perfil_usuario(request.user)),
    }
    context.update(contexto_semestre_operativo())

    return render(
        request,
        "portal/home_padres.html",
        context,
    )




@login_required
def registro_inscripcion(request):
    messages.info(
        request,
        "La pantalla de registro de inscripción directa está desactivada. Usa el portal de padres.",
    )
    return redirect(reverse("portal_padres_home") + "#inicio")
