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
from xhtml2pdf import pisa

# --- IMPORT PARA EVITAR EL CRASH AL DUPLICAR EXPEDIENTES ---
from django.db import IntegrityError

# --- EmailMessage PARA ENVIAR ARCHIVOS ADJUNTOS ---
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
    HistoriaClinicaMedicaForm
)

import os
from .services import generar_pdf_fo301, generar_pdf_dictamen, generar_pdf_inscripcion_lleno
from .models import Solicitud, LinkCaptura, SolicitudInscripcion, HistoriaClinicaMedica

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

            link.usado = True
            link.usado_en = timezone.now()
            link.save(update_fields=["usado", "usado_en"])

            solicitud.estado = "RECIBIDA"
            solicitud.save(update_fields=["estado"])

            from django.core.files import File
            try:
                pdf_path = generar_pdf_fo301(solicitud)
                if pdf_path and os.path.exists(pdf_path):
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

    unidad_final = form.cleaned_data.get("unidad_academica", "")
    if unidad_final == "Otra":
        unidad_final = form.cleaned_data.get("unidad_academica_otra", "")

    solicitud = Solicitud.objects.create(
        estado="CAPTURA",
        nombres_tutor=form.cleaned_data["nombres_tutor"],
        apellido_paterno_tutor=form.cleaned_data["apellido_paterno_tutor"],
        apellido_materno_tutor=form.cleaned_data.get("apellido_materno_tutor", ""),
        matricula=form.cleaned_data.get("matricula", ""),
        unidad_academica=unidad_final,
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
        send_mail(asunto, cuerpo, getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@unach.mx"),
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


# ===================== DESCARGAR PDF =====================
@staff_member_required
def descargar_pdf_solicitud(request, solicitud_id):
    solicitud = get_object_or_404(Solicitud, id=solicitud_id)

    inscripcion = SolicitudInscripcion.objects.filter(solicitud_ingreso=solicitud).first()

    if inscripcion:
        pdf_path = generar_pdf_inscripcion_lleno(inscripcion)
        if pdf_path and os.path.exists(pdf_path):
            return FileResponse(open(pdf_path, "rb"), as_attachment=True,
                                filename=f"Hoja_Inscripcion_Folio_{solicitud.folio}.pdf")

    if not solicitud.pdf:
        try:
            from django.core.files import File
            pdf_path = generar_pdf_fo301(solicitud)
            if pdf_path and os.path.exists(pdf_path):
                with open(pdf_path, "rb") as f:
                    solicitud.pdf.save(f"FO301_{solicitud.folio}.pdf", File(f), save=True)
        except Exception as e:
            print("Fallo de emergencia al generar PDF:", e)

    if solicitud.pdf:
        return FileResponse(solicitud.pdf.open("rb"), as_attachment=True,
                            filename=f"Solicitud_Basica_{solicitud.folio}.pdf")

    raise Http404("El archivo PDF no pudo generarse.")


def solicitud_publica_nueva(request):
    if request.method == "POST":
        s = Solicitud.objects.create(estado="CAPTURA")
        return redirect("admisiones_captura", id=s.id)
    return render(request, "admisiones/publico_nuevo_ingreso.html")


# ===================== REVISIÓN Y DICTAMEN =====================
@login_required
def revisar_solicitud(request, pk):
    s = get_object_or_404(Solicitud, pk=pk)
    inscripcion = SolicitudInscripcion.objects.filter(solicitud_ingreso=s).first()

    if s.estado == Solicitud.Estado.CAPTURA:
        messages.warning(request, "Esta solicitud aún está en CAPTURA.")
        return redirect("panel_admisiones")

    return render(request, "admisiones/revisar_solicitud.html", {
        "s": s,
        "inscripcion": inscripcion
    })


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
        messages.success(request, f"Solicitud RECHAZADA.")
        return redirect("panel_admisiones")

    elif accion == "APROBAR":
        s.estado = Solicitud.Estado.APROBADA
        s.dictaminado_por = request.user
        s.dictaminado_en = timezone.now()
        s.save()

        # Aquí iría la lógica de creación de usuario Beneficiario que ya tienes implementada
        messages.success(request, "Solicitud APROBADA.")
        return redirect("panel_admisiones")


# ===================== PORTAL DE PADRES =====================
@login_required
def portal_inscripcion(request):
    inscripcion = SolicitudInscripcion.objects.filter(usuario_tutor__email=request.user.email).first()

    if not inscripcion:
        messages.error(request, "No tienes un proceso de inscripción activo.")
        return redirect('/')

    if request.method == 'POST':
        # Lógica de guardado de archivos del expediente...
        inscripcion.save()
        messages.success(request, "Avance guardado correctamente.")
        return redirect('portal_inscripcion')

    return render(request, 'admisiones/portal_inscripcion.html', {'inscripcion': inscripcion})


# ===================== ÁREAS ESPECIALISTAS =====================

# --- PSICOLOGÍA ---
@login_required
def psicologia_pendientes(request):
    qs = Solicitud.objects.filter(estado=Solicitud.Estado.APROBADA, estado_psicologia="PENDIENTE")
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


@login_required
def psicologia_pdf(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    html = render_to_string("admisiones/psicologia_pdf.html", {"sol": sol})
    response = HttpResponse(content_type="application/pdf")
    pisa.CreatePDF(html, dest=response)
    return response


@login_required
def psicologia_registro(request):
    return render(request, "admisiones/psicologia_registro.html")


# --- NUTRICIÓN ---
@login_required
def nutricion_pendientes(request):
    qs = Solicitud.objects.filter(estado=Solicitud.Estado.APROBADA, estado_nutricion="PENDIENTE")
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


@login_required
def nutricion_pdf(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    html = render_to_string("admisiones/nutricion_pdf.html", {"sol": sol})
    response = HttpResponse(content_type="application/pdf")
    pisa.CreatePDF(html, dest=response)
    return response


@login_required
def nutricion_registro(request):
    return render(request, "admisiones/nutricion_registro.html")


# --- MÉDICO ---
@login_required
def medico_pendientes(request):
    qs = Solicitud.objects.filter(estado=Solicitud.Estado.APROBADA, estado_medico="PENDIENTE")
    return render(request, "admisiones/medico_pendientes.html", {"solicitudes": qs})


@login_required
def medico_dictaminar(request, pk):
    sol = get_object_or_404(Solicitud, id=pk)
    inscripcion = get_object_or_404(SolicitudInscripcion, solicitud_ingreso=sol)
    historia, _ = HistoriaClinicaMedica.objects.get_or_create(inscripcion=inscripcion)

    if request.method == "POST":
        form = DictamenMedicoForm(request.POST, request.FILES, instance=sol)
        historia_form = HistoriaClinicaMedicaForm(request.POST, instance=historia)
        if form.is_valid() and historia_form.is_valid():
            sol = form.save(commit=False)
            sol.medico_por = request.user
            sol.medico_en = timezone.now()
            sol.save()
            historia_form.save()
            messages.success(request, "Dictamen médico guardado correctamente.")
            return redirect("medico_pendientes")
    else:
        form = DictamenMedicoForm(instance=sol)
        historia_form = HistoriaClinicaMedicaForm(instance=historia)

    return render(request, "admisiones/medico_dictaminar.html", {
        "sol": sol, "form": form, "historia_form": historia_form
    })


@login_required
def medico_pdf(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    html = render_to_string("admisiones/medico_pdf.html", {"sol": sol})
    response = HttpResponse(content_type="application/pdf")
    pisa.CreatePDF(html, dest=response)
    return response


@login_required
def medico_registro(request):
    return render(request, "admisiones/medico_registro.html")


# ===================== VEREDICTO DIRECTORA =====================
@login_required
def veredicto_final_directora(request, inscripcion_id):
    if request.method == 'POST' and request.user.is_staff:
        inscripcion = get_object_or_404(SolicitudInscripcion, id=inscripcion_id)
        accion = request.POST.get('accion')
        s = inscripcion.solicitud_ingreso

        if accion == 'ACEPTAR':
            inscripcion.estado = SolicitudInscripcion.EstadoInscripcion.FINALIZADA
            messages.success(request, f"¡Éxito! El aspirante {s.nombres_menor} ha sido ACEPTADO.")
        elif accion == 'RECHAZAR':
            inscripcion.estado = SolicitudInscripcion.EstadoInscripcion.RECHAZADA
            messages.error(request, f"La solicitud de {s.nombres_menor} ha sido RECHAZADA.")

        inscripcion.save()

    return redirect('dashboard_directiva')