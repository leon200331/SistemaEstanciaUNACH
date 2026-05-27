import io
import os
from pathlib import Path

from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.models import Group
from django.http import JsonResponse, HttpResponse, FileResponse
from django.utils import timezone
from django.utils.html import escape
from django.db import transaction

try:
    from xhtml2pdf import pisa
except ImportError:
    pisa = None

from .models import AccessLog, AsignacionRolCiclo

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



def usuario_tiene_grupo(user, texto_grupo):
    """
    Busca un texto dentro de los grupos del usuario.
    Ejemplo: usuario_tiene_grupo(user, "trabajadora social")
    """
    if not user.is_authenticated:
        return False

    texto_grupo = (texto_grupo or "").strip().lower()

    return user.groups.filter(name__icontains=texto_grupo).exists()



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

    if usuario_es_admin_sistema(user):
        return redirect("panel_gobierno_ti")

    if request.session.get("sec_manto", False):
        logout(request)
        messages.error(request, "El sistema está en mantenimiento. Intente más tarde.")
        return redirect("login")

    if getattr(user, "tipo_persona", "") == "BENEFICIARIO":
        return redirect("portal_padres_home")

    if user.is_staff:
        # Se revisan todos los grupos del usuario, no solo el primero.
        grupos_usuario = " ".join(
            g.name.strip().lower() for g in user.groups.all()
        )

        if "directora" in grupos_usuario:
            return redirect("dashboard_directiva")

        if "trabajadora social" in grupos_usuario:
            return redirect("dashboard_admin")

        if "psicóloga" in grupos_usuario or "psicologa" in grupos_usuario:
            return redirect("psicologia_pendientes")

        if "nutrióloga" in grupos_usuario or "nutriologa" in grupos_usuario:
            return redirect("nutricion_pendientes")

        if "médico" in grupos_usuario or "medico" in grupos_usuario:
            return redirect("medico_pendientes")

        # SPRINT 5:
        # Coordinadora de Sala ya tiene panel activo para incidencias pedagógicas.
        if (
            "coordinadora" in grupos_usuario
            or "coordinador" in grupos_usuario
            or "coordinacion de sala" in grupos_usuario
            or "coordinación de sala" in grupos_usuario
        ):
            return redirect("dashboard_coordinadora")

        # SPRINT 4 - Segunda parte:
        # Maestras / Asistentes de sala ya tienen panel activo de operación diaria.
        if "asistente" in grupos_usuario or "maestra" in grupos_usuario:
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
    grupo = user.groups.first().name.strip().lower() if user.groups.exists() else ""

    # Verificamos que sea Directora o Admin
    if getattr(user, "tipo_persona", "") != "ADMIN" and "directora" not in grupo and "secretario" not in grupo:
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

    context.update(contexto_semestre_operativo())

    return render(request, "portal/home_directiva.html", context)



def usuario_es_directora_o_admin(user):
    """
    Permite validar que solo Directora o Administrador emitan el veredicto final.
    """
    if not user.is_authenticated:
        return False

    grupo = user.groups.first().name.strip().lower() if user.groups.exists() else ""

    return (
        user.is_superuser
        or getattr(user, "tipo_persona", "") == "ADMIN"
        or "directora" in grupo
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

    Si el Administrador del Sistema cae aquí por accidente,
    no se le cierra la sesión ni se muestra error; se redirige a Gobierno TI.
    """
    if usuario_es_admin_sistema(request.user):
        return redirect("panel_gobierno_ti")

    grupo = request.user.groups.first().name.strip().lower() if request.user.groups.exists() else ""

    if not request.user.is_staff or "trabajadora social" not in grupo:
        logout(request)
        messages.error(request, "Acceso denegado. Área exclusiva de Trabajo Social.")
        return redirect("login")

    return render(request, "portal/panel_admin.html", contexto_semestre_operativo())


@login_required
def dashboard_medico(request):
    grupo = request.user.groups.first().name.strip().lower() if request.user.groups.exists() else ""

    if not request.user.is_staff or ("médico" not in grupo and "medico" not in grupo):
        logout(request)
        messages.error(request, "Acceso denegado. Área exclusiva del personal Médico.")
        return redirect("login")

    return render(request, "dashboard/home_medico.html", contexto_semestre_operativo())


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
            if accion == "create_user":
                email = request.POST.get("email", "").strip().lower()
                password = request.POST.get("password")
                nombre = request.POST.get("nombre", "").strip()
                apellido_paterno = request.POST.get("apellido_paterno", "").strip()
                apellido_materno = request.POST.get("apellido_materno", "").strip()
                curp = request.POST.get("curp", "").strip().upper()
                tipo_persona = request.POST.get("tipo_persona") or "PERSONAL"
                num_empleado = request.POST.get("numero_empleado", "").strip()

                # =====================================================
                # VALIDACIONES ANTES DE GUARDAR
                # Evita usuarios/correos huérfanos cuando falla otro dato.
                # =====================================================
                errores = []

                if not email:
                    errores.append("El correo es obligatorio.")

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
                email = request.POST.get("email", "").strip().lower()
                tipo_persona = request.POST.get("tipo_persona") or "PERSONAL"
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

                AccessLog.objects.create(
                    usuario=request.user,
                    accion=f"ASIGNÓ ROL: '{rol_fijo}' a {empleado.nombre}",
                )

                response_data["msg"] = (
                    f'Rol "{rol_fijo}" asignado correctamente. '
                    "La asignación a semestre/sala/horarios se realiza en Gestión de Semestres."
                )

            elif accion == "remove_fixed_role":
                usuario_id = request.POST.get("usuario_id")
                empleado = User.objects.get(id=usuario_id)
                empleado.groups.clear()
                AsignacionMaestra.objects.filter(maestra=empleado).delete()
                response_data["msg"] = "Rol removido. También se quitaron sus asignaciones de maestra si existían."

            elif accion == "abandon_admin":
                sucesor_id = request.POST.get("sucesor_id")
                sucesor = User.objects.get(id=sucesor_id)
                yo = request.user

                sucesor.is_superuser = True
                sucesor.tipo_persona = "ADMIN"
                sucesor.save()

                yo.is_superuser = False
                yo.tipo_persona = "PERSONAL"
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

    context = {
        "lista_staff": staff_list,
        "ciclos_historial": Semestre.objects.all().order_by("-fecha_inicio"),
        "logs": AccessLog.objects.all().order_by("-fecha_acceso")[:50],
        "encrypt_active": request.session.get("sec_encrypt", True),
    }

    context.update(contexto_semestre_operativo())

    return render(request, "portal/panel_ti.html", context)


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
    solicitud_activa = None
    semestre_activo = obtener_semestre_activo_operativo()
    ciclo_activo = bool(semestre_activo)

    try:
        # Si no hay semestre activo, el beneficiario puede iniciar sesión,
        # pero no se debe crear una nueva operación/solicitud automática.
        if ciclo_activo:
            solicitud_activa = Solicitud.objects.order_by("-id").first()

            if not solicitud_activa:
                kwargs = {}

                if "estado" in [f.name for f in Solicitud._meta.fields]:
                    kwargs["estado"] = "CAPTURA"

                solicitud_activa = Solicitud.objects.create(**kwargs)

    except Exception:
        solicitud_activa = None

    solicitud_id = solicitud_activa.id if solicitud_activa else None
    folio = getattr(solicitud_activa, "folio", None) if solicitud_activa else None

    context = {
        "solicitud_id": solicitud_id,
        "folio": folio,
        "ciclo_activo": ciclo_activo,
        "semestre_activo_operativo": semestre_activo,
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
    return redirect("portal_padres_home")