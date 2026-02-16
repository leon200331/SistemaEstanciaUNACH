from django.shortcuts import render, redirect, get_object_or_404
from django.http import FileResponse
from django.http import Http404
from django.utils import timezone
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_http_methods
from django.urls import reverse
from django.conf import settings
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from .forms import CapturaSolicitudForm, CrearSolicitudPanelForm
from .services import generar_pdf_fo301
from .models import Solicitud, LinkCaptura


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

            # PDF (si lo usas)
            from django.core.files import File

            try:
                pdf_path = generar_pdf_fo301(solicitud)  # debe regresar la ruta del PDF

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
    solicitudes = Solicitud.objects.order_by("-created_at")
    form_crear = CrearSolicitudPanelForm()

    return render(
        request,
        "admisiones/panel.html",
        {
            "solicitudes": solicitudes,
            "form_crear": form_crear,
        },
    )


# ===================== CREAR SOLICITUD + LINK (DESDE MODAL) =====================
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
        correo=form.cleaned_data.get("correo", ""),
    )

    LinkCaptura.objects.create(solicitud=solicitud)

    messages.success(request, f"Solicitud creada. Folio: {solicitud.folio}")
    return redirect("panel_admisiones")


# ===================== ENVIAR LINK POR CORREO =====================
@require_http_methods(["GET", "POST"])
def enviar_link_por_correo(request, solicitud_id):
    solicitud = get_object_or_404(Solicitud, id=solicitud_id)

    link = (
        LinkCaptura.objects
        .filter(solicitud=solicitud, usado=False)
        .order_by("-creado_en")
        .first()
    )

    if not link:
        messages.error(request, "No hay un link activo para esta solicitud.")
        return redirect("panel_admisiones")

    if not solicitud.correo:
        messages.error(request, "Esta solicitud no tiene correo registrado.")
        return redirect("panel_admisiones")

    # ✅ URL absoluta
    url = request.build_absolute_uri(
        reverse("captura_por_token", args=[link.token])
    )

    asunto = f"Estancia Infantil UNACH - Link de captura (Folio {solicitud.folio})"

    try:
        nombre = solicitud.nombre_tutor_completo()
    except Exception:
        nombre = f"{solicitud.nombres_tutor} {solicitud.apellido_paterno_tutor}".strip()

    cuerpo = (
        f"Hola.\n\n"
        f"Se ha generado el enlace de captura para tu solicitud.\n"
        f"Folio: {solicitud.folio}\n"
        f"Nombre: {nombre}\n\n"
        f"Enlace (uso único):\n{url}\n\n"
        f"Atentamente,\nEstancia Infantil UNACH"
    )

    try:
        send_mail(
            subject=asunto,
            message=cuerpo,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@estanciaunach.local"),
            recipient_list=[solicitud.correo],
            fail_silently=False,
        )
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

        if not s.nombres_tutor:
            messages.error(request, "Nombre(s) es obligatorio.")
            return render(request, "admisiones/editar.html", {"solicitud": s})

        if not s.apellido_paterno_tutor:
            messages.error(request, "Apellido paterno es obligatorio.")
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


@staff_member_required
def descargar_pdf_solicitud(request, solicitud_id):
    solicitud = get_object_or_404(Solicitud, id=solicitud_id)

    if not solicitud.pdf:
        raise Http404("Esta solicitud no tiene PDF.")

    return FileResponse(
        solicitud.pdf.open("rb"),
        as_attachment=True,
        filename=f"FO301_{solicitud.folio}.pdf"
    )

from django.shortcuts import render, redirect
from .models import Solicitud

def solicitud_publica_nueva(request):
    """
    Entrada pública para nuevos ingresos.
    Crea una Solicitud (si tu modelo lo permite) y manda a captura/editar.
    """
    if request.method == "POST":
        # Si tu Solicitud tiene estado/folio, ajusta aquí
        kwargs = {}
        if "estado" in [f.name for f in Solicitud._meta.fields]:
            kwargs["estado"] = "CAPTURA"

        s = Solicitud.objects.create(**kwargs)

        # ✅ manda a la captura por ID (ajusta el name según tu urls)
        return redirect("admisiones_captura", id=s.id)

    return render(request, "admisiones/publico_nuevo_ingreso.html")

