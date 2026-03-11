from django.shortcuts import render, redirect, get_object_or_404
from django.http import FileResponse
from django.http import Http404
from django.utils import timezone
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.urls import reverse
from django.conf import settings
from django.http import HttpResponseForbidden
from django.template.loader import render_to_string
from xhtml2pdf import pisa
from django.http import HttpResponse
from .forms import DictamenMedicoForm

# --- IMPORT PARA EVITAR EL CRASH AL DUPLICAR EXPEDIENTES ---
from django.db import IntegrityError

# --- SE AGREGÓ EmailMessage PARA PODER ENVIAR ARCHIVOS ADJUNTOS ---
from django.core.mail import send_mail, EmailMessage

from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from .forms import (
    CapturaSolicitudForm,
    CrearSolicitudPanelForm,
    DictamenPsicologiaForm,
    DictamenNutricionForm,
    DictamenMedicoForm,
)

# --- SE AGREGARON LIBRERÍAS Y FUNCIONES PARA EL PDF DINÁMICO ---
import os
from .services import generar_pdf_fo301, generar_pdf_dictamen, generar_pdf_inscripcion_lleno
from .models import Solicitud, LinkCaptura, SolicitudInscripcion

from django.utils.crypto import get_random_string


# ===================== CAPTURA POR TOKEN =====================
def captura_por_token(request, token):
    link = get_object_or_404(LinkCaptura, token=token)

    if not link.vigente():
        raise Http404("Este enlace ya no es válido.")

    solicitud = link.solicitud

    if request.method == "POST":
        form = CapturaSolicitudForm(request.POST, instance=solicitud)
        if form.is_valid():
            form.save()

            # Marcar link como usado
            link.usado = True
            link.usado_en = timezone.now()
            link.save(update_fields=["usado", "usado_en"])

            # Cambiar estado
            solicitud.estado = "RECIBIDA"
            solicitud.save(update_fields=["estado"])

            # PDF
            from django.core.files import File

            try:
                pdf_path = generar_pdf_fo301(solicitud)

                with open(pdf_path, "rb") as f:
                    solicitud.pdf.save(
                        f"FO301_{solicitud.folio}.pdf",
                        File(f),
                        save=True
                    )
            except Exception as e:
                print("Error al generar PDF:", e)

            return render(request, "admisiones/gracias.html", {"folio": solicitud.folio})
    else:
        form = CapturaSolicitudForm(instance=solicitud)

    return render(request, "admisiones/captura.html", {"form": form})


# ===================== PANEL ADMISIONES =====================
def panel_admisiones(request):
    orden = '-created_at'
    sort_param = request.GET.get('sort')
    if sort_param == 'apellidos':
        orden = 'apellido_paterno_tutor'

    solicitudes = Solicitud.objects.order_by(orden)
    form_crear = CrearSolicitudPanelForm()

    return render(
        request,
        "admisiones/panel.html",
        {
            "solicitudes": solicitudes,
            "form_crear": form_crear,
        },
    )


# ===================== ELIMINAR SOLICITUD =====================
@staff_member_required
def eliminar_solicitud(request, pk):
    s = get_object_or_404(Solicitud, pk=pk)
    folio = s.folio
    if request.method == "POST":
        s.delete()
        messages.success(request, f"Solicitud con Folio {folio} eliminada correctamente.")
        return redirect('panel_admisiones')
    return redirect('panel_admisiones')


@staff_member_required
def eliminar_todas_solicitudes(request):
    if request.method == "POST":
        total_eliminadas = Solicitud.objects.count()
        Solicitud.objects.all().delete()
        messages.success(request, f"Se han eliminado {total_eliminadas} solicitudes.")
        return redirect('panel_admisiones')
    return redirect('panel_admisiones')


# ===================== CREAR SOLICITUD + LINK =====================
@require_http_methods(["POST"])
def crear_solicitud_y_link(request):
    form = CrearSolicitudPanelForm(request.POST)

    if not form.is_valid():
        solicitudes = Solicitud.objects.order_by("-created_at")
        return render(
            request,
            "admisiones/panel.html",
            {
                "solicitudes": solicitudes,
                "form_crear": form,
            },
        )

    solicitud = Solicitud.objects.create(
        estado="CAPTURA",
        nombres_tutor=form.cleaned_data["nombres_tutor"],
        apellido_paterno_tutor=form.cleaned_data["apellido_paterno_tutor"],
        apellido_materno_tutor=form.cleaned_data.get("apellido_materno_tutor", ""),
        matricula=form.cleaned_data.get("matricula", ""),
        # --- SE GUARDA LA UNIDAD ACADÉMICA ---
        unidad_academica=form.cleaned_data.get("unidad_academica", ""),
        correo=form.cleaned_data.get("correo", ""),
    )

    LinkCaptura.objects.create(solicitud=solicitud)

    messages.success(request, f"Solicitud creada. Folio: {solicitud.folio}")
    return redirect("panel_admisiones")


# ===================== ENVIAR LINK POR CORREO =====================
@require_http_methods(["GET", "POST"])
def enviar_link_por_correo(request, solicitud_id):
    solicitud = get_object_or_404(Solicitud, id=solicitud_id)
    link = LinkCaptura.objects.filter(solicitud=solicitud, usado=False).order_by("-creado_en").first()

    if not link or not solicitud.correo:
        messages.error(request, "Falta link activo o correo.")
        return redirect("panel_admisiones")

    url = request.build_absolute_uri(reverse("captura_por_token", args=[link.token]))
    asunto = f"Estancia Infantil UNACH - Link de captura (Folio {solicitud.folio})"
    nombre = solicitud.nombre_tutor_completo() if hasattr(solicitud,
                                                          "nombre_tutor_completo") else f"{solicitud.nombres_tutor} {solicitud.apellido_paterno_tutor}"

    cuerpo = (
        f"Hola.\n\nSe ha generado el enlace de captura para tu solicitud.\n"
        f"Folio: {solicitud.folio}\nNombre: {nombre}\n\nEnlace (uso único):\n{url}\n\nAtentamente,\nEstancia Infantil UNACH"
    )

    try:
        send_mail(asunto, cuerpo, getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@estanciaunach.local"),
                  [solicitud.correo], fail_silently=False)
        messages.success(request, f"Link enviado a: {solicitud.correo}")
    except Exception as e:
        messages.error(request, f"No se pudo enviar el correo: {e}")

    return redirect("panel_admisiones")


# ===================== EDITAR DATOS BÁSICOS =====================
@require_http_methods(["GET", "POST"])
def editar_solicitud(request, solicitud_id):
    s = get_object_or_404(Solicitud, id=solicitud_id)

    if request.method == "POST":
        s.nombres_tutor = (request.POST.get("nombres_tutor") or "").strip()
        s.apellido_paterno_tutor = (request.POST.get("apellido_paterno_tutor") or "").strip()
        s.apellido_materno_tutor = (request.POST.get("apellido_materno_tutor") or "").strip()
        s.matricula = (request.POST.get("matricula") or "").strip()
        s.correo = (request.POST.get("correo") or "").strip()

        if not s.nombres_tutor or not s.apellido_paterno_tutor:
            messages.error(request, "Nombre y Apellido paterno son obligatorios.")
            return render(request, "admisiones/editar.html", {"solicitud": s})

        if s.correo:
            try:
                validate_email(s.correo)
            except ValidationError:
                messages.error(request, "Correo inválido. Ej: usuario@gmail.com")
                return render(request, "admisiones/editar.html", {"solicitud": s})

        s.save()
        messages.success(request, f"Datos actualizados. Folio: {s.folio}")
        return redirect("panel_admisiones")

    return render(request, "admisiones/editar.html", {"solicitud": s})


# --- NUEVA VERSIÓN DEL BOTÓN DE PDF ---
@staff_member_required
def descargar_pdf_solicitud(request, solicitud_id):
    solicitud = get_object_or_404(Solicitud, id=solicitud_id)

    # 1. Buscamos si el usuario ya tiene su expediente completo
    inscripcion = SolicitudInscripcion.objects.filter(solicitud_ingreso=solicitud).first()

    # 2. Si ya tiene expediente, generamos tu Word nuevo al vuelo
    if inscripcion:
        pdf_path = generar_pdf_inscripcion_lleno(inscripcion)
        if pdf_path and os.path.exists(pdf_path):
            return FileResponse(open(pdf_path, "rb"), as_attachment=True,
                                filename=f"Hoja_Inscripcion_Folio_{solicitud.folio}.pdf")

    # 3. Si apenas hizo la captura inicial (no ha entrado al portal), le damos el PDF básico
    if solicitud.pdf:
        return FileResponse(solicitud.pdf.open("rb"), as_attachment=True,
                            filename=f"Solicitud_Basica_{solicitud.folio}.pdf")

    raise Http404("El usuario aún no ha generado información para el PDF.")


def solicitud_publica_nueva(request):
    if request.method == "POST":
        kwargs = {"estado": "CAPTURA"} if "estado" in [f.name for f in Solicitud._meta.fields] else {}
        s = Solicitud.objects.create(**kwargs)
        return redirect("admisiones_captura", id=s.id)
    return render(request, "admisiones/publico_nuevo_ingreso.html")


# =========================================================
# VISTA DICTAMEN
# =========================================================

@login_required
def revisar_solicitud(request, pk):
    s = get_object_or_404(Solicitud, pk=pk)
    if s.estado == Solicitud.Estado.CAPTURA:
        messages.warning(request, "Esta solicitud aún está en CAPTURA (no ha sido enviada).")
        return redirect("panel_admisiones")
    return render(request, "admisiones/revisar_solicitud.html", {"s": s})


@login_required
def dictaminar_solicitud(request, pk):
    s = get_object_or_404(Solicitud, pk=pk)
    User = get_user_model()

    if request.method != "POST" or s.estado not in [Solicitud.Estado.RECIBIDA]:
        return redirect("revisar_solicitud", pk=pk)

    accion = request.POST.get("accion")
    comentario = (request.POST.get("comentario") or "").strip()

    if accion == "RECHAZAR":
        if not comentario:
            messages.error(request, "Para rechazar debes escribir un motivo.")
            return redirect("revisar_solicitud", pk=pk)

        s.estado = Solicitud.Estado.RECHAZADA
        s.comentario_respuesta = comentario
        s.dictaminado_por = request.user
        s.dictaminado_en = timezone.now()
        s.save()

        if s.correo:
            ruta_pdf = generar_pdf_dictamen(s)
            nombre = s.nombre_tutor_completo() if hasattr(s, "nombre_tutor_completo") else "aspirante"
            body = f"Estimado/a {nombre}:\n\nLe informamos que su solicitud ha sido RECHAZADA.\nMotivo: {s.comentario_respuesta}\n\nAdjunto su Dictamen Oficial.\n\nEstancia Infantil UNACH"

            email = EmailMessage("Resultado de Solicitud", body,
                                 getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@unach.mx"), [s.correo])
            if ruta_pdf:
                email.attach_file(ruta_pdf)
            email.send(fail_silently=False)

        messages.success(request, f"Solicitud dictaminada: RECHAZADA. Se envió el PDF por correo.")
        return redirect("panel_admisiones")

    elif accion == "APROBAR":
        s.estado = Solicitud.Estado.APROBADA
        s.comentario_respuesta = None
        s.dictaminado_por = request.user
        s.dictaminado_en = timezone.now()
        s.save()

        correo_tutor = s.correo.lower()
        usuario_existente = User.objects.filter(email=correo_tutor).first()
        password_temporal = get_random_string(length=8)

        if not usuario_existente:
            nuevo_usuario = User.objects.create_user(username=correo_tutor, email=correo_tutor,
                                                     password=password_temporal)
            nuevo_usuario.nombre = s.nombres_tutor
            nuevo_usuario.apellido_paterno = s.apellido_paterno_tutor
            nuevo_usuario.apellido_materno = s.apellido_materno_tutor
            nuevo_usuario.tipo_persona = 'BENEFICIARIO'
            nuevo_usuario.estatus_operativo = True
            nuevo_usuario.save()
            usuario_final = nuevo_usuario
        else:
            usuario_existente.set_password(password_temporal)
            usuario_existente.save()
            usuario_final = usuario_existente

        # --- AQUÍ ESTÁ EL ESCUDO TRY/EXCEPT ---
        try:
            SolicitudInscripcion.objects.get_or_create(solicitud_ingreso=s, defaults={'usuario_tutor': usuario_final})
        except IntegrityError:
            messages.error(request, "¡Error! Este correo o usuario ya está en otro y ya tiene expediente.")
            s.estado = Solicitud.Estado.RECIBIDA
            s.save()
            return redirect("revisar_solicitud", pk=pk)
        # --------------------------------------

        if s.correo:
            ruta_pdf = generar_pdf_dictamen(s)
            url_login = request.build_absolute_uri('/')
            nombre = s.nombre_tutor_completo() if hasattr(s, "nombre_tutor_completo") else "aspirante"

            body = (
                f"Estimado/a {nombre}:\n\n"
                f"¡Su solicitud ha sido APROBADA!\n\n"
                f"Ingrese a nuestro portal:\n"
                f"🔗 Link: {url_login}\n"
                f"👤 Usuario: {usuario_final.email}\n"
                f"🔑 Clave Temporal: {password_temporal}\n\n"
                f"Atentamente,\nEstancia Infantil UNACH"
            )

            email = EmailMessage(
                "¡Solicitud Aprobada! - Inicia tu Inscripción UNACH",
                body,
                getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@unach.mx"),
                [s.correo],
            )
            if ruta_pdf:
                email.attach_file(ruta_pdf)
            email.send(fail_silently=False)

        messages.success(request, "Solicitud APROBADA. Se creó el expediente y se enviaron credenciales.")
        return redirect("panel_admisiones")


# =========================================================
# PORTAL DE PADRES (WIZARD DE INSCRIPCIÓN) - ACTUALIZADO
# =========================================================
@login_required
def portal_inscripcion(request):
    inscripcion = SolicitudInscripcion.objects.filter(usuario_tutor__email=request.user.email).first()

    if not inscripcion:
        messages.error(request, "Error interno: No tienes un proceso de inscripción activo.")
        return redirect(request.META.get('HTTP_REFERER', '/'))

    if request.method == 'POST':
        if inscripcion.estado in ['EN_REVISION', 'FINALIZADA']:
            messages.error(request, "Tu expediente ya fue enviado. No puedes modificarlo.")
            return redirect('portal_inscripcion')

        # 1. Beneficiario (Tutor)
        inscripcion.avance_academico = request.POST.get('avance_academico')
        inscripcion.estado_civil_tutor = request.POST.get('estado_civil_tutor')
        inscripcion.parentesco_tutor = request.POST.get('parentesco_tutor')

        # 2. Menor (Nombres se guardan en Solicitud original, Edades y Detalles en Inscripción)
        s = inscripcion.solicitud_ingreso
        s.nombres_menor = request.POST.get('nombres_menor')
        s.apellido_paterno_menor = request.POST.get('apellido_paterno_menor')
        s.apellido_materno_menor = request.POST.get('apellido_materno_menor')

        fecha_nac = request.POST.get('fecha_nacimiento_menor')
        s.fecha_nacimiento_menor = fecha_nac if fecha_nac else None

        s.curp_menor = request.POST.get('curp_menor')
        s.save()

        inscripcion.estado_nacimiento_menor = request.POST.get('estado_nacimiento_menor')
        inscripcion.municipio_nacimiento_menor = request.POST.get('municipio_nacimiento_menor')

        try:
            inscripcion.edad_anios_menor = int(request.POST.get('edad_anios_menor') or 0)
            inscripcion.edad_meses_menor = int(request.POST.get('edad_meses_menor') or 0)
        except ValueError:
            pass

        inscripcion.sexo_menor = request.POST.get('sexo_menor')
        inscripcion.tipo_sangre_menor = request.POST.get('tipo_sangre_menor')

        # 3. El otro Padre/Madre (Estructurado)
        inscripcion.parentesco_segundo_padre = request.POST.get('parentesco_segundo_padre')
        inscripcion.nombres_segundo_padre = request.POST.get('nombres_segundo_padre')
        inscripcion.apellido_paterno_segundo_padre = request.POST.get('apellido_paterno_segundo_padre')
        inscripcion.apellido_materno_segundo_padre = request.POST.get('apellido_materno_segundo_padre')

        inscripcion.estado_civil_segundo_padre = request.POST.get('estado_civil_segundo_padre')
        inscripcion.ocupacion_segundo_padre = request.POST.get('ocupacion_segundo_padre')

        inscripcion.estado_domicilio_segundo_padre = request.POST.get('estado_domicilio_segundo_padre')
        inscripcion.ciudad_segundo_padre = request.POST.get('ciudad_segundo_padre')
        inscripcion.codigo_postal_segundo_padre = request.POST.get('codigo_postal_segundo_padre')
        inscripcion.calle_segundo_padre = request.POST.get('calle_segundo_padre')
        inscripcion.numero_exterior_segundo_padre = request.POST.get('numero_exterior_segundo_padre')
        inscripcion.numero_interior_segundo_padre = request.POST.get('numero_interior_segundo_padre')

        inscripcion.celular_segundo_padre = request.POST.get('celular_segundo_padre')
        inscripcion.correo_segundo_padre = request.POST.get('correo_segundo_padre')

        # 4. Familiares Autorizados (Estructurados)
        inscripcion.contacto_1_nombres = request.POST.get('contacto_1_nombres')
        inscripcion.contacto_1_apellido_paterno = request.POST.get('contacto_1_apellido_paterno')
        inscripcion.contacto_1_apellido_materno = request.POST.get('contacto_1_apellido_materno')
        inscripcion.contacto_1_parentesco = request.POST.get('contacto_1_parentesco')
        inscripcion.contacto_1_telefono = request.POST.get('contacto_1_telefono')

        inscripcion.contacto_2_nombres = request.POST.get('contacto_2_nombres')
        inscripcion.contacto_2_apellido_paterno = request.POST.get('contacto_2_apellido_paterno')
        inscripcion.contacto_2_apellido_materno = request.POST.get('contacto_2_apellido_materno')
        inscripcion.contacto_2_parentesco = request.POST.get('contacto_2_parentesco')
        inscripcion.contacto_2_telefono = request.POST.get('contacto_2_telefono')

        inscripcion.contacto_3_nombres = request.POST.get('contacto_3_nombres')
        inscripcion.contacto_3_apellido_paterno = request.POST.get('contacto_3_apellido_paterno')
        inscripcion.contacto_3_apellido_materno = request.POST.get('contacto_3_apellido_materno')
        inscripcion.contacto_3_parentesco = request.POST.get('contacto_3_parentesco')
        inscripcion.contacto_3_telefono = request.POST.get('contacto_3_telefono')

        # Reglamentos
        if request.POST.get('acepto_reglamentos') == 'on':
            inscripcion.acepto_reglamentos = True
            inscripcion.fecha_aceptacion = timezone.now()
        else:
            inscripcion.acepto_reglamentos = False

        if 'enviar_revision' in request.POST:
            if not inscripcion.acepto_reglamentos:
                messages.error(request, "DEBES aceptar el reglamento para poder enviar tu inscripción.")
                return redirect('portal_inscripcion')

            inscripcion.estado = SolicitudInscripcion.EstadoInscripcion.EN_REVISION
            messages.success(request, "¡Expediente enviado con éxito! Trabajo Social lo revisará pronto.")
        else:
            inscripcion.estado = SolicitudInscripcion.EstadoInscripcion.EN_PROCESO
            messages.success(request, "Avance guardado correctamente. Puedes continuar luego.")

        inscripcion.save()
        return redirect('portal_inscripcion')

    return render(request, 'admisiones/portal_inscripcion.html', {'inscripcion': inscripcion})


# =========================================================
# DICTÁMENES POR ÁREA (PSICOLOGÍA / NUTRICIÓN / MÉDICO)
# =========================================================
def actualizar_estado_final(sol: Solicitud):
    # Si alguna área rechaza -> RECHAZADA final
    if (
            sol.estado_psicologia == Solicitud.EstadoEvaluacion.RECHAZADO
            or sol.estado_nutricion == Solicitud.EstadoEvaluacion.RECHAZADO
            or sol.estado_medico == Solicitud.EstadoEvaluacion.RECHAZADO
    ):
        sol.estado = Solicitud.Estado.RECHAZADA
        sol.save(update_fields=["estado"])
        return

    # Si las 3 aprueban -> APROBADA final
    if sol.todas_aprobadas():
        sol.estado = Solicitud.Estado.APROBADA
        sol.save(update_fields=["estado"])


# ===================== PSICOLOGÍA =====================
@login_required
def psicologia_pendientes(request):
    grupo = request.user.groups.first().name.strip().lower() if request.user.groups.exists() else ""
    if (grupo != "psicologa") and (not request.user.is_superuser):
        return HttpResponseForbidden("No tienes permisos para esta sección.")

    qs = Solicitud.objects.filter(
        estado=Solicitud.Estado.APROBADA,
        estado_psicologia=Solicitud.EstadoEvaluacion.PENDIENTE
    ).order_by("-created_at")

    return render(request, "admisiones/psicologia_pendientes.html", {"solicitudes": qs})

@login_required
def psicologia_registro(request):
    aprobados = Solicitud.objects.filter(
        estado_psicologia=Solicitud.EstadoEvaluacion.APROBADO
    ).order_by("-psicologia_en")

    rechazados = Solicitud.objects.filter(
        estado_psicologia=Solicitud.EstadoEvaluacion.RECHAZADO
    ).order_by("-psicologia_en")

    total_registros = aprobados.count() + rechazados.count()

    return render(request, "admisiones/psicologia_registro.html", {
        "aprobados": aprobados,
        "rechazados": rechazados,
        "total_registros": total_registros,
    })

@login_required
def psicologia_dictaminar(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)

    if request.method == "POST":
        form = DictamenPsicologiaForm(request.POST, instance=sol)
        if form.is_valid():
            sol = form.save(commit=False)
            sol.psicologia_por = request.user
            sol.psicologia_en = timezone.now()
            sol.save()
            actualizar_estado_final(sol)
            return redirect("psicologia_pendientes")
    else:
        form = DictamenPsicologiaForm(instance=sol)

    return render(request, "admisiones/psicologia_dictaminar.html", {"sol": sol, "form": form})

import os
from django.conf import settings

@login_required
def psicologia_pdf(request, pk):
    grupos_usuario = [g.name.strip().lower() for g in request.user.groups.all()]

    tiene_permiso = (
        request.user.is_superuser
        or any("psicologia" in g for g in grupos_usuario)
        or any("psicólogo" in g for g in grupos_usuario)
        or any("psicologo" in g for g in grupos_usuario)
        or any("psicóloga" in g for g in grupos_usuario)
        or any("psicologa" in g for g in grupos_usuario)
    )

    if not tiene_permiso:
        return HttpResponse("No tienes permisos para esta sección.", status=403)

    sol = get_object_or_404(Solicitud, pk=pk)

    html = render_to_string("admisiones/psicologia_pdf.html", {
        "sol": sol
    })

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="Dictamen_Psicologia_{sol.folio}.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response)

    if pisa_status.err:
        return HttpResponse("Error al generar el PDF", status=500)

    return response


# ===================== NUTRICIÓN =====================
@login_required
def nutricion_pendientes(request):
    grupo = request.user.groups.first().name.strip().lower() if request.user.groups.exists() else ""

    if not (
        "nutriologa" in grupo
        or "nutrióloga" in grupo
        or "nutriologo" in grupo
        or "nutriólogo" in grupo
        or "nutricion" in grupo
        or "nutrición" in grupo
        or request.user.is_superuser
    ):
        return HttpResponseForbidden("No tienes permisos para esta sección.")

    qs = Solicitud.objects.filter(
        estado=Solicitud.Estado.APROBADA,
        estado_nutricion=Solicitud.EstadoEvaluacion.PENDIENTE
    ).order_by("-created_at")

    return render(request, "admisiones/nutricion_pendientes.html", {"solicitudes": qs})


@login_required
def nutricion_registro(request):
    grupo = request.user.groups.first().name.strip().lower() if request.user.groups.exists() else ""

    if not (
        "nutriologa" in grupo
        or "nutrióloga" in grupo
        or "nutriologo" in grupo
        or "nutriólogo" in grupo
        or "nutricion" in grupo
        or "nutrición" in grupo
        or request.user.is_superuser
    ):
        return HttpResponseForbidden("No tienes permisos para esta sección.")

    aprobados = Solicitud.objects.filter(
        estado_nutricion=Solicitud.EstadoEvaluacion.APROBADO
    ).order_by("-nutricion_en", "-created_at")

    rechazados = Solicitud.objects.filter(
        estado_nutricion=Solicitud.EstadoEvaluacion.RECHAZADO
    ).order_by("-nutricion_en", "-created_at")

    return render(
        request,
        "admisiones/nutricion_registro.html",
        {
            "aprobados": aprobados,
            "rechazados": rechazados,
            "total_registros": aprobados.count() + rechazados.count(),
        }
    )


@login_required
def nutricion_dictaminar(request, pk):
    grupos_usuario = [g.name.strip().lower() for g in request.user.groups.all()]

    tiene_permiso = (
        request.user.is_superuser
        or any("nutriologa" in g for g in grupos_usuario)
        or any("nutrióloga" in g for g in grupos_usuario)
        or any("nutriologo" in g for g in grupos_usuario)
        or any("nutriólogo" in g for g in grupos_usuario)
        or any("nutricion" in g for g in grupos_usuario)
        or any("nutrición" in g for g in grupos_usuario)
    )

    if not tiene_permiso:
        return HttpResponseForbidden("No tienes permisos para esta sección.")

    sol = get_object_or_404(Solicitud, pk=pk)

    bloqueado = sol.estado_nutricion in [
        Solicitud.EstadoEvaluacion.APROBADO,
        Solicitud.EstadoEvaluacion.RECHAZADO,
    ]

    if request.method == "POST":
        if bloqueado:
            messages.warning(request, "Esta evaluación de nutrición ya fue finalizada y no puede modificarse.")
            return redirect("nutricion_dictaminar", pk=sol.pk)

        form = DictamenNutricionForm(request.POST, instance=sol)
        if form.is_valid():
            sol = form.save(commit=False)
            sol.nutricion_por = request.user
            sol.nutricion_en = timezone.now()
            sol.save()
            actualizar_estado_final(sol)
            messages.success(request, "Valoración de nutrición guardada correctamente.")
            return redirect("nutricion_pendientes")
    else:
        form = DictamenNutricionForm(instance=sol)

    return render(request, "admisiones/nutricion_dictaminar.html", {
        "sol": sol,
        "form": form,
        "bloqueado": bloqueado,
    })

@login_required
def nutricion_pdf(request, pk):
    grupos_usuario = [g.name.strip().lower() for g in request.user.groups.all()]

    tiene_permiso = (
        request.user.is_superuser
        or any("nutriologa" in g for g in grupos_usuario)
        or any("nutrióloga" in g for g in grupos_usuario)
        or any("nutriologo" in g for g in grupos_usuario)
        or any("nutriólogo" in g for g in grupos_usuario)
        or any("nutricion" in g for g in grupos_usuario)
        or any("nutrición" in g for g in grupos_usuario)
    )

    if not tiene_permiso:
        return HttpResponse("No tienes permisos para esta sección.", status=403)

    sol = get_object_or_404(Solicitud, pk=pk)

    logo_path = os.path.join(settings.BASE_DIR, "static", "img", "logo.png")
    logo_uri = f"file:///{logo_path.replace(os.sep, '/')}"

    html = render_to_string("admisiones/nutricion_pdf.html", {
        "sol": sol,
        "logo_uri": logo_uri,
    })

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="Dictamen_Nutricion_{sol.folio}.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response)

    if pisa_status.err:
        return HttpResponse("Error al generar el PDF", status=500)

    return response


# ===================== MÉDICO =====================
@login_required
def medico_pendientes(request):
    qs = Solicitud.objects.filter(
        estado=Solicitud.Estado.APROBADA,
        estado_medico=Solicitud.EstadoEvaluacion.PENDIENTE
    ).order_by("-created_at")
    return render(request, "admisiones/medico_pendientes.html", {"solicitudes": qs})

from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.utils import timezone

from .models import Solicitud, SolicitudInscripcion, HistoriaClinicaMedica
from .forms import DictamenMedicoForm, HistoriaClinicaMedicaForm


from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.utils import timezone

from .models import Solicitud, SolicitudInscripcion, HistoriaClinicaMedica
from .forms import DictamenMedicoForm, HistoriaClinicaMedicaForm


def medico_dictaminar(request, pk):
    sol = get_object_or_404(Solicitud, id=pk)
    inscripcion = get_object_or_404(SolicitudInscripcion, solicitud_ingreso=sol)

    historia, created = HistoriaClinicaMedica.objects.get_or_create(
        inscripcion=inscripcion
    )

    bloqueado = sol.estado_medico != Solicitud.EstadoEvaluacion.PENDIENTE

    if request.method == "POST" and not bloqueado:
        form = DictamenMedicoForm(request.POST, request.FILES, instance=sol)
        historia_form = HistoriaClinicaMedicaForm(request.POST, instance=historia)

        if form.is_valid() and historia_form.is_valid():
            solicitud_guardada = form.save(commit=False)
            solicitud_guardada.medico_por = request.user
            solicitud_guardada.medico_en = timezone.now()
            solicitud_guardada.save()

            historia_guardada = historia_form.save(commit=False)
            historia_guardada.inscripcion = inscripcion
            historia_guardada.save()

            messages.success(request, "Dictamen médico guardado correctamente.")
            return redirect("medico_pendientes")
        else:
            messages.error(request, "Corrige los errores del formulario.")
    else:
        form = DictamenMedicoForm(instance=sol)
        historia_form = HistoriaClinicaMedicaForm(instance=historia)

        return render(request, "admisiones/medico_dictaminar.html", {
        "sol": sol,
        "form": form,
        "historia_form": historia_form,
        "bloqueado": bloqueado,
    })

@login_required
def medico_registro(request):
    aprobados = Solicitud.objects.filter(
        estado_medico=Solicitud.EstadoEvaluacion.APROBADO
    ).order_by("-medico_en", "-created_at")

    rechazados = Solicitud.objects.filter(
        estado_medico=Solicitud.EstadoEvaluacion.RECHAZADO
    ).order_by("-medico_en", "-created_at")

    return render(
        request,
        "admisiones/medico_registro.html",
        {
            "aprobados": aprobados,
            "rechazados": rechazados,
            "total_registros": aprobados.count() + rechazados.count(),
        }
    )
@login_required
def medico_pdf(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)

    logo_path = os.path.join(settings.BASE_DIR, "static", "img", "logo.png")
    logo_uri = f"file:///{logo_path.replace(os.sep, '/')}"

    html = render_to_string("admisiones/medico_pdf.html", {
        "sol": sol,
        "logo_uri": logo_uri,
    })

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="Dictamen_Medico_{sol.folio}.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response)

    if pisa_status.err:
        return HttpResponse("Error al generar el PDF", status=500)

    return response