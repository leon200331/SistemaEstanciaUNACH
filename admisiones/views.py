from django.shortcuts import render, redirect, get_object_or_404
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.utils import timezone
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.urls import reverse
from django.conf import settings
from django.template.loader import render_to_string
from django.contrib.staticfiles import finders  # <--- AGREGADO PARA LOS LOGOS DEL PDF
from xhtml2pdf import pisa

# --- SEGURIDAD Y COMUNICACIÓN ---
from django.db import IntegrityError
from django.core.mail import send_mail, EmailMessage
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.utils.crypto import get_random_string

import os
from io import BytesIO
from .forms import (
    CapturaSolicitudForm,
    CrearSolicitudPanelForm,
    DictamenPsicologiaForm,
    DictamenNutricionForm,
    DictamenMedicoForm,
    HistoriaClinicaMedicaForm
)
from .services import generar_pdf_fo301, generar_pdf_dictamen, generar_pdf_inscripcion_lleno
from .models import Solicitud, LinkCaptura, SolicitudInscripcion, HistoriaClinicaMedica


# ===================== CAPTURA POR TOKEN (PADRES) =====================
def captura_por_token(request, token):
    link = get_object_or_404(LinkCaptura, token=token)
    if not link.vigente():
        raise Http404("Este enlace ya no es válido.")

    solicitud = link.solicitud
    if request.method == "POST":
        form = CapturaSolicitudForm(request.POST, instance=solicitud)
        if form.is_valid():
            form.save()
            link.usado = True
            link.usado_en = timezone.now()
            link.save(update_fields=["usado", "usado_en"])
            solicitud.estado = Solicitud.Estado.RECIBIDA
            solicitud.save(update_fields=["estado"])

            try:
                pdf_path = generar_pdf_fo301(solicitud)
                if pdf_path and os.path.exists(pdf_path):
                    from django.core.files import File
                    with open(pdf_path, "rb") as f:
                        solicitud.pdf.save(f"FO301_{solicitud.folio}.pdf", File(f), save=True)
            except Exception as e:
                print("Error al generar PDF inicial:", e)
            return render(request, "admisiones/gracias.html", {"folio": solicitud.folio})
    else:
        form = CapturaSolicitudForm(instance=solicitud)
    return render(request, "admisiones/captura.html", {"form": form})


# ===================== GESTIÓN DE PANEL (TRABAJO SOCIAL) =====================
@login_required
def panel_admisiones(request):
    orden = '-created_at'
    sort_param = request.GET.get('sort')
    if sort_param == 'apellidos':
        orden = 'apellido_paterno_tutor'
    solicitudes = Solicitud.objects.order_by(orden)
    form_crear = CrearSolicitudPanelForm()
    return render(request, "admisiones/panel.html", {"solicitudes": solicitudes, "form_crear": form_crear})


@require_http_methods(["POST"])
@login_required
def crear_solicitud_y_link(request):
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
            unidad_academica=unidad
        )
        LinkCaptura.objects.create(solicitud=solicitud)
        messages.success(request, f"Solicitud creada. Folio: {solicitud.folio}")
    return redirect("panel_admisiones")


@login_required
def editar_solicitud(request, solicitud_id):
    s = get_object_or_404(Solicitud, id=solicitud_id)
    if request.method == "POST":
        s.nombres_tutor = (request.POST.get("nombres_tutor") or "").strip()
        s.apellido_paterno_tutor = (request.POST.get("apellido_paterno_tutor") or "").strip()
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
        cuerpo = (
            f"Hola {solicitud.nombres_tutor},\n\n"
            f"Completa tu solicitud en el siguiente enlace de un solo uso:\n\n"
            f"{url}\n\n"
            f"Atentamente, UNACH."
        )
        try:
            send_mail(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, [solicitud.correo])
            messages.success(request, "Correo enviado correctamente.")
        except Exception as e:
            messages.error(request, f"Fallo al enviar: {e}")
    return redirect("panel_admisiones")


@staff_member_required
def eliminar_solicitud(request, pk):
    s = get_object_or_404(Solicitud, pk=pk)
    s.delete()
    messages.success(request, "Solicitud eliminada.")
    return redirect('panel_admisiones')


@staff_member_required
def eliminar_todas_solicitudes(request):
    if request.method == "POST":
        Solicitud.objects.all().delete()
        messages.success(request, "Todas las solicitudes han sido eliminadas.")
    return redirect('panel_admisiones')


# ===================== DICTAMEN INICIAL Y REVISIÓN TS =====================

@login_required
def revisar_solicitud(request, pk):
    s = get_object_or_404(Solicitud, pk=pk)
    inscripcion = SolicitudInscripcion.objects.filter(solicitud_ingreso=s).first()

    if request.method == "POST" and "accion_inscripcion" in request.POST:
        accion = request.POST.get("accion_inscripcion")
        comentario = request.POST.get("comentario_inscripcion", "").strip()
        docs_erroneos = request.POST.get("docs_erroneos", "").strip()

        if accion == "DEVOLVER":
            inscripcion.estado = "DEVUELTA"
            if docs_erroneos:
                inscripcion.observaciones = f"{docs_erroneos}|{comentario}"
            else:
                inscripcion.observaciones = comentario
            inscripcion.save()
            messages.warning(request, "Expediente devuelto al tutor para correcciones.")

        elif accion == "APROBAR":
            inscripcion.estado = "FILTROS"
            inscripcion.save()

            if s.correo:
                asunto = "Expediente Validado - Cita para Filtros Presenciales"
                cuerpo = (
                    f"Hola {s.nombres_tutor},\n\n"
                    f"Tu expediente digital ha sido revisado y está correcto.\n\n"
                    f"Por favor, preséntate en las instalaciones de la Estancia Infantil UNACH para realizar las valoraciones presenciales del menor (Filtro Médico, Nutricional y Psicológico).\n\n"
                    f"Nota: Puedes pasar con los especialistas en el orden que se encuentren disponibles para agilizar tu trámite.\n\n"
                    f"Atentamente, Trabajo Social UNACH."
                )
                try:
                    send_mail(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, [s.correo], fail_silently=True)
                except Exception as e:
                    print("Error enviando correo de filtros:", e)

            messages.success(request, "Expediente validado correctamente. Se envió correo para que asistan a filtros.")
        return redirect("revisar_solicitud", pk=pk)

    return render(request, "admisiones/revisar_solicitud.html", {"s": s, "inscripcion": inscripcion})


@login_required
def dictaminar_solicitud(request, pk):
    s = get_object_or_404(Solicitud, pk=pk)
    User = get_user_model()

    if request.method != "POST":
        return redirect("revisar_solicitud", pk=pk)

    accion = request.POST.get("accion")
    comentario = (request.POST.get("comentario") or "").strip()

    if accion == "RECHAZAR":
        if not comentario:
            messages.error(request, "Indica el motivo del rechazo.")
            return redirect("revisar_solicitud", pk=pk)

        s.estado = Solicitud.Estado.RECHAZADA
        s.comentario_respuesta = comentario
        s.dictaminado_por = request.user
        s.dictaminado_en = timezone.now()
        s.save()

        if s.correo:
            # --- SE AGREGA REQUEST=REQUEST PARA LOS LOGOS ---
            ruta_pdf = generar_pdf_dictamen(s)
            email = EmailMessage("Resultado Solicitud - UNACH", "Su solicitud fue RECHAZADA.",
                                 settings.DEFAULT_FROM_EMAIL, [s.correo])
            if ruta_pdf and os.path.exists(ruta_pdf):
                email.attach_file(ruta_pdf)
            email.send(fail_silently=True)
        messages.success(request, "Solicitud Rechazada.")
        return redirect("panel_admisiones")

    elif accion == "APROBAR":
        s.estado = Solicitud.Estado.APROBADA
        s.dictaminado_por = request.user
        s.dictaminado_en = timezone.now()
        s.save()

        correo_tutor = s.correo.lower().strip()
        password_temporal = get_random_string(8)

        user, created = User.objects.get_or_create(
            email=correo_tutor,
            defaults={
                'username': correo_tutor,
                'nombre': s.nombres_tutor,
                'apellido_paterno': s.apellido_paterno_tutor,
                'tipo_persona': 'BENEFICIARIO',
                'is_active': True
            }
        )
        user.set_password(password_temporal)
        user.save()

        SolicitudInscripcion.objects.get_or_create(solicitud_ingreso=s, defaults={'usuario_tutor': user})

        if s.correo:
            # --- SE AGREGA REQUEST=REQUEST PARA LOS LOGOS ---
            ruta_pdf = generar_pdf_dictamen(s)
            url_login = request.build_absolute_uri('/')
            asunto = "¡Felicidades! Solicitud Aprobada - UNACH"
            cuerpo = (
                f"Hola {s.nombres_tutor}:\n\n"
                f"Tu solicitud ha sido APROBADA.\n\n"
                f"Ingresa aquí para continuar: {url_login}\n"
                f"Usuario: {correo_tutor}\n"
                f"Contraseña Temporal: {password_temporal}\n\n"
                f"Atentamente, UNACH."
            )
            email = EmailMessage(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, [s.correo])
            if ruta_pdf and os.path.exists(ruta_pdf):
                email.attach_file(ruta_pdf)
            email.send(fail_silently=True)

        messages.success(request, f"¡Éxito! Claves enviadas a {s.correo}")
        return redirect("panel_admisiones")


# ===================== PORTAL DE PADRES (EXPEDIENTE) =====================
@login_required
def portal_inscripcion(request):
    inscripcion = SolicitudInscripcion.objects.filter(usuario_tutor=request.user).first()
    if not inscripcion:
        return redirect('/')

    # --- MANEJO DE COMPROBANTE DE PAGO ---
    if request.method == 'POST' and 'subir_pago' in request.POST:
        pago_file = request.FILES.get('comprobante_pago')
        if pago_file:
            inscripcion.doc_tutor_pago = pago_file
            inscripcion.save()
            messages.success(request, "¡Comprobante de pago subido! Trabajo Social lo validará pronto.")
            return redirect('portal_inscripcion')

    if request.method == 'POST':
        archivos = [
            'doc_menor_certificado_medico', 'doc_menor_cartilla_vacunacion', 'doc_menor_grupo_sanguineo',
            'doc_menor_acta_nacimiento', 'doc_menor_fotos', 'doc_menor_laboratorio',
            'doc_tutor_acta_nacimiento', 'doc_tutor_ine', 'doc_tutor_fotos', 'doc_tutor_domicilio',
            'doc_tutor_historial', 'doc_tutor_horario',
            'doc_autorizado_carta', 'doc_autorizado_ine', 'doc_autorizado_fotos', 'reglamento_firmado'
        ]
        for campo in archivos:
            if campo in request.FILES:
                setattr(inscripcion, campo, request.FILES[campo])

        for key, value in request.POST.items():
            if key not in ['csrfmiddlewaretoken', 'enviar_revision', 'guardar_avance']:
                if hasattr(inscripcion, key):
                    setattr(inscripcion, key, value)
                elif hasattr(inscripcion.solicitud_ingreso, key):
                    setattr(inscripcion.solicitud_ingreso, key, value)

        inscripcion.solicitud_ingreso.save()
        inscripcion.acepto_reglamentos = request.POST.get('acepto_reglamentos') == 'on'

        if request.POST.get('enviar_revision') == '1':
            inscripcion.estado = 'EN_REVISION'
            inscripcion.observaciones = ""
            messages.success(request, "Expediente enviado a revisión exitosamente.")
        else:
            if inscripcion.estado == 'NUEVA':
                inscripcion.estado = 'EN_PROCESO'
            messages.success(request, "Expediente guardado como avance.")

        inscripcion.save()
        return redirect('portal_inscripcion')

    return render(request, 'admisiones/portal_inscripcion.html', {'inscripcion': inscripcion})


# ===================== ESPECIALISTAS =====================

# Psicología
@login_required
def psicologia_pendientes(request):
    qs = Solicitud.objects.filter(estado=Solicitud.Estado.APROBADA, estado_psicologia="PENDIENTE").order_by(
        "-created_at")
    return render(request, "admisiones/psicologia_pendientes.html", {"solicitudes": qs})


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
            return redirect("psicologia_pendientes")
    else:
        form = DictamenPsicologiaForm(instance=sol)
    return render(request, "admisiones/psicologia_dictaminar.html", {"sol": sol, "form": form})


# Nutrición
@login_required
def nutricion_pendientes(request):
    qs = Solicitud.objects.filter(estado=Solicitud.Estado.APROBADA, estado_nutricion="PENDIENTE").order_by(
        "-created_at")
    return render(request, "admisiones/nutricion_pendientes.html", {"solicitudes": qs})


@login_required
def nutricion_dictaminar(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    if request.method == "POST":
        form = DictamenNutricionForm(request.POST, instance=sol)
        if form.is_valid():
            sol = form.save(commit=False)
            sol.nutricion_por = request.user
            sol.nutricion_en = timezone.now()
            sol.save()
            return redirect("nutricion_pendientes")
    else:
        form = DictamenNutricionForm(instance=sol)
    return render(request, "admisiones/nutricion_dictaminar.html", {"sol": sol, "form": form})


# Médico
@login_required
def medico_pendientes(request):
    qs = Solicitud.objects.filter(estado=Solicitud.Estado.APROBADA, estado_medico="PENDIENTE").order_by("-created_at")
    return render(request, "admisiones/medico_pendientes.html", {"solicitudes": qs})


@login_required
def medico_dictaminar(request, pk):
    sol = get_object_or_404(Solicitud, id=pk)
    insc = get_object_or_404(SolicitudInscripcion, solicitud_ingreso=sol)
    historia, _ = HistoriaClinicaMedica.objects.get_or_create(inscripcion=insc)
    if request.method == "POST":
        form = DictamenMedicoForm(request.POST, request.FILES, instance=sol)
        h_form = HistoriaClinicaMedicaForm(request.POST, instance=historia)
        if form.is_valid() and h_form.is_valid():
            sol = form.save(commit=False)
            sol.medico_por = request.user
            sol.medico_en = timezone.now()
            sol.save()
            h_form.save()
            messages.success(request, "Médico guardado.")
            return redirect("medico_pendientes")
    else:
        form = DictamenMedicoForm(instance=sol)
        h_form = HistoriaClinicaMedicaForm(instance=historia)
    return render(request, "admisiones/medico_dictaminar.html", {"sol": sol, "form": form, "historia_form": h_form})


# ===================== REPORTE FINAL DE INGRESO (TRABAJO SOCIAL) =====================

@login_required
def reporte_final_pendientes(request):
    inscripciones = SolicitudInscripcion.objects.filter(
        estado='FILTROS',
        solicitud_ingreso__estado_medico='APROBADO',
        solicitud_ingreso__estado_nutricion='APROBADO',
        solicitud_ingreso__estado_psicologia='APROBADO',
        reporte_final_aprobado__isnull=True
    ).order_by('created_at')
    return render(request, 'admisiones/reporte_final_pendientes.html', {'inscripciones': inscripciones})


@login_required
def dictaminar_reporte_final(request, pk):
    inscripcion = get_object_or_404(SolicitudInscripcion, id=pk)
    if request.method == 'POST':
        decision = request.POST.get('decision')
        motivos = request.POST.get('motivos', '').strip()
        if decision == 'APROBAR':
            inscripcion.reporte_final_aprobado = True
            inscripcion.estado = 'ESPERANDO_DIRECTORA'
            messages.success(request, "Reporte Final guardado. Pasó a la Directora.")
        elif decision == 'RECHAZAR':
            inscripcion.reporte_final_aprobado = False
            inscripcion.reporte_final_motivos = motivos
            inscripcion.estado = 'RECHAZADA'
            messages.error(request, "Solicitud rechazada.")
        inscripcion.reporte_final_por = request.user
        inscripcion.reporte_final_en = timezone.now()
        inscripcion.save()
        return redirect('reporte_final_pendientes')
    return render(request, 'admisiones/dictaminar_reporte_final.html', {'inscripcion': inscripcion})


# ===================== VISTAS FINALES Y PDFs =====================

@login_required
def veredicto_final_directora(request, inscripcion_id):
    if request.method == 'POST' and request.user.is_staff:
        insc = get_object_or_404(SolicitudInscripcion, id=inscripcion_id)
        accion = request.POST.get('accion')
        insc.directora_por = request.user
        insc.directora_en = timezone.now()

        if accion == 'ACEPTAR':
            insc.estado = "ACEPTADO_ESPERANDO_PAGO"
            mensaje_alerta = "¡Alumno aceptado! Reporte final enviado al tutor."
        elif accion == 'RECHAZAR':
            insc.estado = "RECHAZADA"
            mensaje_alerta = "Inscripción rechazada."

        insc.save()

        if insc.solicitud_ingreso.correo:
            # --- SE AGREGA REQUEST=REQUEST PARA LOS LOGOS ---
            html = render_to_string("admisiones/reporte_final_pdf.html", {"inscripcion": insc}, request=request)
            pdf_file = BytesIO()
            pisa.CreatePDF(html, dest=pdf_file)

            estado_texto = "APROBADO" if accion == 'ACEPTAR' else "RECHAZADO"
            asunto = f"Veredicto Final de Ingreso ({estado_texto}) - UNACH"
            cuerpo = f"Estimado(a) {insc.solicitud_ingreso.nombres_tutor},\n\nAdjunto el Reporte Final de Ingreso."

            email = EmailMessage(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, [insc.solicitud_ingreso.correo])
            email.attach(f"Reporte_Final_{insc.solicitud_ingreso.folio}.pdf", pdf_file.getvalue(), 'application/pdf')
            email.send(fail_silently=True)

        messages.success(request, mensaje_alerta)
    return redirect('dashboard_directiva')


@login_required
def descargar_reporte_final_padre(request, inscripcion_id):
    insc = get_object_or_404(SolicitudInscripcion, id=inscripcion_id, usuario_tutor=request.user)
    if insc.estado not in ['ACEPTADO_ESPERANDO_PAGO', 'RECHAZADA', 'FINALIZADA']:
        messages.error(request, "Tu reporte final aún no está listo.")
        return redirect('portal_inscripcion')

    # --- SE AGREGA REQUEST=REQUEST PARA LOS LOGOS ---
    html = render_to_string("admisiones/reporte_final_pdf.html", {"inscripcion": insc}, request=request)
    response = HttpResponse(content_type="application/pdf")
    pisa.CreatePDF(html, dest=response)
    return response


# =======================================================
# AQUÍ ESTÁ EL CAMBIO PARA GENERAR EL PDF CON LAS TABLITAS
# =======================================================
@staff_member_required
def descargar_pdf_solicitud(request, solicitud_id):
    sol = get_object_or_404(Solicitud, id=solicitud_id)

    # 1. Si el papá ya llenó su inscripción oficial, generamos el expediente con tablitas al instante
    if hasattr(sol, 'inscripcion_oficial'):
        ruta_pdf_lleno = generar_pdf_inscripcion_lleno(sol.inscripcion_oficial)
        if ruta_pdf_lleno and os.path.exists(ruta_pdf_lleno):
            return FileResponse(open(ruta_pdf_lleno, 'rb'), content_type='application/pdf',
                                filename=f"Expediente_{sol.folio}.pdf")

    # 2. Fallback: Si no lo ha llenado, descargamos el formato inicial (si existe)
    if sol.pdf:
        return FileResponse(sol.pdf.open("rb"), content_type='application/pdf', filename=f"Solicitud_{sol.folio}.pdf")

    raise Http404("El documento PDF aún no se ha generado porque el tutor no ha terminado de llenar su expediente.")


def solicitud_publica_nueva(request):
    return render(request, "admisiones/publico_nuevo_ingreso.html")


# --- FUNCIÓN MÁGICA PARA LOS LOGOS EN PDF ---
def link_callback(uri, rel):
    """
    Convierte URLs web en rutas locales (de tu laptop) para que el PDF pueda leer las imágenes.
    """
    if uri.startswith(settings.STATIC_URL):
        path = finders.find(uri.replace(settings.STATIC_URL, ""))
        if path:
            return path
    return uri


@login_required
def psicologia_pdf(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)

    html = render_to_string("admisiones/psicologia_pdf.html", {"sol": sol}, request=request)
    response = HttpResponse(content_type="application/pdf")
    response['Content-Disposition'] = f'inline; filename="Dictamen_Psicologia_{sol.folio}.pdf"'

    # AQUI ESTÁ LA MAGIA: Agregamos el link_callback
    pisa.CreatePDF(html, dest=response, link_callback=link_callback)

    return response


@login_required
def nutricion_pdf(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    # --- SE AGREGA REQUEST=REQUEST PARA LOS LOGOS ---
    html = render_to_string("admisiones/nutricion_pdf.html", {"sol": sol}, request=request)
    response = HttpResponse(content_type="application/pdf")
    pisa.CreatePDF(html, dest=response)
    return response


@login_required
def medico_pdf(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    # --- SE AGREGA REQUEST=REQUEST PARA LOS LOGOS ---
    html = render_to_string("admisiones/medico_pdf.html", {"sol": sol}, request=request)
    response = HttpResponse(content_type="application/pdf")
    pisa.CreatePDF(html, dest=response)
    return response


# =================================================================
# HISTORIAL DE REGISTROS (DICTAMINADOS)
# =================================================================

@login_required
def psicologia_registro(request):
    # Buscamos los que ya no están pendientes
    aprobados = Solicitud.objects.filter(estado=Solicitud.Estado.APROBADA, estado_psicologia="APROBADO").order_by(
        "-psicologia_en")
    rechazados = Solicitud.objects.filter(estado=Solicitud.Estado.APROBADA, estado_psicologia="RECHAZADO").order_by(
        "-psicologia_en")

    contexto = {
        "aprobados": aprobados,
        "rechazados": rechazados,
        "total_dictaminados": aprobados.count() + rechazados.count()
    }
    return render(request, "admisiones/psicologia_registro.html", contexto)


@login_required
def nutricion_registro(request):
    aprobados = Solicitud.objects.filter(estado=Solicitud.Estado.APROBADA, estado_nutricion="APROBADO").order_by(
        "-nutricion_en")
    rechazados = Solicitud.objects.filter(estado=Solicitud.Estado.APROBADA, estado_nutricion="RECHAZADO").order_by(
        "-nutricion_en")

    contexto = {
        "aprobados": aprobados,
        "rechazados": rechazados,
        "total_dictaminados": aprobados.count() + rechazados.count()
    }
    return render(request, "admisiones/nutricion_registro.html", contexto)


@login_required
def medico_registro(request):
    aprobados = Solicitud.objects.filter(estado=Solicitud.Estado.APROBADA, estado_medico="APROBADO").order_by(
        "-medico_en")
    rechazados = Solicitud.objects.filter(estado=Solicitud.Estado.APROBADA, estado_medico="RECHAZADO").order_by(
        "-medico_en")

    contexto = {
        "aprobados": aprobados,
        "rechazados": rechazados,
        "total_dictaminados": aprobados.count() + rechazados.count()
    }
    return render(request, "admisiones/medico_registro.html", contexto)


# ===================== VALIDACIÓN DE PAGOS (TRABAJO SOCIAL) =====================

@login_required
def validacion_pagos_pendientes(request):
    """Muestra la lista de papás que ya subieron su comprobante de pago."""
    # Filtramos los que están en este estado Y que el campo del documento no esté vacío
    inscripciones = SolicitudInscripcion.objects.filter(
        estado='ACEPTADO_ESPERANDO_PAGO'
    ).exclude(doc_tutor_pago='').order_by('created_at')

    return render(request, 'admisiones/validacion_pagos.html', {'inscripciones': inscripciones})


@login_required
def registrar_pago_valido(request, pk):
    """Procesa la validación (Aprueba o Rechaza el recibo)."""
    inscripcion = get_object_or_404(SolicitudInscripcion, id=pk)

    if request.method == 'POST':
        accion = request.POST.get('accion')

        if accion == 'VALIDAR':
            # ¡Se acabó el proceso! El niño es oficialmente un alumno.
            inscripcion.estado = 'FINALIZADA'
            messages.success(request,
                             f"¡Pago validado! El alumno {inscripcion.solicitud_ingreso.nombres_menor} está OFICIALMENTE INSCRITO.")

        elif accion == 'RECHAZAR':
            # Si el ticket es falso o no se ve, borramos el archivo para que el papá lo vuelva a subir
            if inscripcion.doc_tutor_pago:
                inscripcion.doc_tutor_pago.delete(save=False)

            # Dejamos el estado igual, pero le mandamos una observación
            inscripcion.observaciones = "El comprobante de pago es ilegible o incorrecto. Por favor, súbelo nuevamente."
            messages.warning(request, "Pago rechazado. Se le pedirá al tutor que suba un nuevo comprobante.")

        inscripcion.save()

    return redirect('validacion_pagos_pendientes')