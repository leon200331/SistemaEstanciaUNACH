from django.shortcuts import render, redirect, get_object_or_404
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.utils import timezone
from django.contrib import messages
# --- CAMBIO PUNTO 10: Quitamos el decorador que revelaba el admin y usamos user_passes_test ---
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_http_methods, require_POST
from django.urls import reverse
from django.conf import settings
from django.utils.text import slugify
from django.template.loader import render_to_string
from django.contrib.staticfiles import finders
from xhtml2pdf import pisa

# --- SEGURIDAD Y COMUNICACIÓN ---
from django.db import IntegrityError
from django.core.mail import send_mail, EmailMessage
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

import os
import io
from io import BytesIO
from .forms import (
    CapturaSolicitudForm,
    CrearSolicitudPanelForm,
    DictamenPsicologiaForm,
    DictamenNutricionForm,
    DictamenMedicoForm,
    HistoriaClinicaMedicaForm,
    SemestreForm
)
from .services import generar_pdf_fo301, generar_pdf_dictamen, generar_pdf_inscripcion_lleno
from .models import Solicitud, LinkCaptura, SolicitudInscripcion, HistoriaClinicaMedica, Semestre, SalaSemestre, \
    MensajeDirectora, Incidencia


# --- FUNCIÓN PARA LOS LOGOS EN PDF ---
def link_callback(uri, rel):
    if uri.startswith(settings.STATIC_URL):
        path = finders.find(uri.replace(settings.STATIC_URL, ""))
        if path:
            return path
    return uri


# --- NUEVA FUNCIÓN SILENCIOSA DE SEGURIDAD (PUNTO 10) ---
def verificacion_staff(user):
    """
    Verifica si el usuario tiene permisos administrativos.
    Si no los tiene, el decorador lo mandará al login de forma silenciosa.
    """
    return user.is_authenticated and (user.is_staff or getattr(user, 'tipo_persona', '') == 'ADMIN')


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
    elif sort_param == 'folio_asc':
        orden = 'id'
    elif sort_param == 'folio_desc':
        orden = '-id'

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
        cuerpo = f"Hola {solicitud.nombres_tutor},\n\nCompleta tu solicitud aquí: {url}"
        try:
            send_mail(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, [solicitud.correo])
            messages.success(request, "Correo enviado.")
        except Exception as e:
            messages.error(request, f"Fallo al enviar: {e}")
    return redirect("panel_admisiones")


# --- CAMBIO PUNTO 10: Redirección silenciosa sin revelar /admin/ ---
@user_passes_test(verificacion_staff, login_url='/')
def eliminar_solicitud(request, pk):
    s = get_object_or_404(Solicitud, pk=pk)
    s.delete()
    messages.success(request, "Solicitud eliminada.")
    return redirect('panel_admisiones')


# --- CAMBIO PUNTO 10: Redirección silenciosa sin revelar /admin/ ---
@user_passes_test(verificacion_staff, login_url='/')
def eliminar_todas_solicitudes(request):
    if request.method == "POST":
        Solicitud.objects.all().delete()
        messages.success(request, "Todas las solicitudes han sido eliminadas.")
    return redirect('panel_admisiones')


# ===================== FUNCIÓN DE DESCARGA DIRECTA (TS) =====================
@login_required
def descargar_archivo_expediente(request, inscripcion_id, campo):
    user = request.user
    grupo = user.groups.first().name.strip().lower() if user.groups.exists() else ""

    # --- CAMBIO PUNTO 10: Si no es admin o TS, se manda directo al inicio de forma silenciosa ---
    if getattr(user, 'tipo_persona', '') != 'ADMIN' and "trabajadora social" not in grupo:
        return redirect('/')

    insc = get_object_or_404(SolicitudInscripcion, id=inscripcion_id)
    archivo_field = getattr(insc, campo, None)

    if not archivo_field:
        raise Http404("El archivo no existe.")

    mapeo_nombres = {
        'doc_menor_certificado_medico': 'Certificado_Medico_Menor',
        'doc_menor_cartilla_vacunacion': 'Cartilla_Vacunacion_Menor',
        'doc_menor_grupo_sanguineo': 'Grupo_Sanguineo_Menor',
        'doc_menor_acta_nacimiento': 'Acta_de_Nacimiento_Menor',
        'doc_menor_fotos': 'Fotografia_del_Menor',
        'doc_menor_laboratorio': 'Estudios_de_Laboratorio_Menor',
        'doc_tutor_acta_nacimiento': 'Acta_de_Nacimiento_Beneficiario',
        'doc_tutor_ine': 'INE_del_Beneficiario',
        'doc_tutor_fotos': 'Fotografia_del_Beneficiario',
        'doc_segundo_padre_fotos': 'Fotografia_Pareja',
        'doc_tutor_domicilio': 'Comprobante_de_Domicilio_Beneficiario',
        'doc_tutor_historial': 'Historial_Academico',
        'doc_tutor_horario': 'Horario_de_Clases',
        'doc_autorizado_carta': 'Carta_de_Autorizacion',
        'doc_autorizado_ine': 'INE_del_Autorizado',
        'doc_contacto_1_fotos': 'Fotografia_Autorizado_1',
        'doc_contacto_2_fotos': 'Fotografia_Autorizado_2',
        'doc_contacto_3_fotos': 'Fotografia_Autorizado_3',
        'reglamento_firmado': 'Reglamento_Interno_Firmado'
    }

    nombre_archivo = mapeo_nombres.get(campo, "Documento")
    matricula = insc.solicitud_ingreso.matricula or "SIN_MATRICULA"
    ext = os.path.splitext(archivo_field.name)[1]

    nombre_final = f"{nombre_archivo}_{matricula}{ext}"
    return FileResponse(archivo_field.open('rb'), as_attachment=True, filename=nombre_final)


# ===================== DICTAMEN INICIAL Y REVISIÓN TS =====================

@login_required
def revisar_solicitud(request, pk):
    s = get_object_or_404(Solicitud, pk=pk)
    inscripcion = SolicitudInscripcion.objects.filter(solicitud_ingreso=s).first()
    if request.method == "POST" and "accion_inscripcion" in request.POST:
        accion = request.POST.get("accion_inscripcion")
        if accion == "DEVOLVER":
            inscripcion.estado = "DEVUELTA"
            inscripcion.save()
            messages.warning(request, "Expediente devuelto.")
        elif accion == "APROBAR":
            inscripcion.estado = "FILTROS"
            inscripcion.save()
            messages.success(request, "Expediente validado.")
        return redirect("revisar_solicitud", pk=pk)
    return render(request, "admisiones/revisar_solicitud.html", {"s": s, "inscripcion": inscripcion})


@login_required
def dictaminar_solicitud(request, pk):
    s = get_object_or_404(Solicitud, pk=pk)
    User = get_user_model()
    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "APROBAR":
            s.estado = Solicitud.Estado.APROBADA
            s.save()
            user, _ = User.objects.get_or_create(email=s.correo,
                                                 defaults={'username': s.correo, 'tipo_persona': 'BENEFICIARIO',
                                                           'is_active': True})
            user.set_password('Unach2026')
            user.save()
            SolicitudInscripcion.objects.get_or_create(solicitud_ingreso=s, defaults={'usuario_tutor': user})
            messages.success(request, "Solicitud Aprobada.")
        return redirect("panel_admisiones")
    return redirect("revisar_solicitud", pk=pk)


# ===================== PORTAL DE PADRES =====================
@login_required
def portal_inscripcion(request):
    inscripcion = SolicitudInscripcion.objects.filter(usuario_tutor=request.user).first()
    if not inscripcion: return redirect('/')

    if request.method == 'POST':
        mapeo_nombres = {
            'doc_menor_certificado_medico': 'Certificado_Medico_Menor',
            'doc_menor_cartilla_vacunacion': 'Cartilla_Vacunacion_Menor',
            'doc_menor_grupo_sanguineo': 'Grupo_Sanguineo_Menor',
            'doc_menor_acta_nacimiento': 'Acta_de_Nacimiento_Menor',
            'doc_menor_fotos': 'Fotografia_del_Menor',
            'doc_menor_laboratorio': 'Estudios_de_Laboratorio_Menor',
            'doc_tutor_acta_nacimiento': 'Acta_de_Nacimiento_Beneficiario',
            'doc_tutor_ine': 'INE_del_Beneficiario',
            'doc_tutor_fotos': 'Fotografia_del_Beneficiario',
            'doc_segundo_padre_fotos': 'Fotografia_Pareja',
            'doc_tutor_domicilio': 'Comprobante_de_Domicilio_Beneficiario',
            'doc_tutor_historial': 'Historial_Academico',
            'doc_tutor_horario': 'Horario_de_Clases',
            'doc_autorizado_carta': 'Carta_de_Autorizacion',
            'doc_autorizado_ine': 'INE_del_Autorizado',
            'doc_contacto_1_fotos': 'Fotografia_Autorizado_1',
            'doc_contacto_2_fotos': 'Fotografia_Autorizado_2',
            'doc_contacto_3_fotos': 'Fotografia_Autorizado_3',
            'reglamento_firmado': 'Reglamento_Interno_Firmado'
        }

        campos_fotos = ['doc_menor_fotos', 'doc_tutor_fotos', 'doc_segundo_padre_fotos', 'doc_contacto_1_fotos',
                        'doc_contacto_2_fotos', 'doc_contacto_3_fotos']
        matricula = inscripcion.solicitud_ingreso.matricula or "SIN_MATRICULA"

        for campo, nombre_legible in mapeo_nombres.items():
            if campo in request.FILES:
                archivo = request.FILES[campo]
                ext = os.path.splitext(archivo.name)[1].lower()

                if campo in campos_fotos and ext == '.pdf':
                    messages.error(request,
                                   f"Error: El campo '{nombre_legible}' no acepta PDFs. Por favor sube una imagen (.jpg o .png).")
                    continue

                nuevo_nombre = f"{nombre_legible}_{matricula}{ext}"
                archivo.name = nuevo_nombre
                setattr(inscripcion, campo, archivo)

        for key, value in request.POST.items():
            if key not in ['csrfmiddlewaretoken', 'enviar_revision'] and hasattr(inscripcion, key):
                setattr(inscripcion, key, value)

        if request.POST.get('enviar_revision') == '1':
            inscripcion.estado = 'EN_REVISION'
            messages.success(request, "Expediente enviado. Tus archivos se organizaron correctamente.")
        else:
            messages.success(request, "Avance guardado exitosamente.")

        inscripcion.save()
        return redirect('portal_inscripcion')

    return render(request, 'admisiones/portal_inscripcion.html', {'inscripcion': inscripcion})


# ===================== ESPECIALISTAS Y REGISTROS =====================

@login_required
def psicologia_pendientes(request):
    folios = SolicitudInscripcion.objects.filter(estado='FILTROS').values_list('solicitud_ingreso_id', flat=True)
    qs = Solicitud.objects.filter(id__in=folios, estado_psicologia="PENDIENTE").order_by("-created_at")
    return render(request, "admisiones/psicologia_pendientes.html", {"solicitudes": qs})


@login_required
def psicologia_dictaminar(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)

    if request.method == "POST":
        form = DictamenPsicologiaForm(request.POST, instance=sol)

        if form.is_valid():
            estado = request.POST.get("estado_psicologia")

            if estado not in ["APROBADO", "RECHAZADO"]:
                form.add_error(
                    "estado_psicologia",
                    "Debes seleccionar APROBADO o RECHAZADO para finalizar el dictamen."
                )
            else:
                sol = form.save(commit=False)
                sol.psicologia_por = request.user
                sol.psicologia_en = timezone.now()
                sol.save()
                return redirect("psicologia_pendientes")
    else:
        form = DictamenPsicologiaForm(instance=sol)

    return render(request, "admisiones/psicologia_dictaminar.html", {
        "sol": sol,
        "form": form
    })


@login_required
@require_POST
def psicologia_autoguardar(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)

    data = request.POST.copy()

    campos_excluidos = [
        "estado_psicologia",
        "observaciones_psicologia",
    ]

    for campo in campos_excluidos:
        if campo in data:
            del data[campo]

    # Mantener el estado real sin finalizar
    data["estado_psicologia"] = sol.estado_psicologia or "PENDIENTE"
    data["observaciones_psicologia"] = sol.observaciones_psicologia or ""

    form = DictamenPsicologiaForm(data, instance=sol)

    # Permitir PENDIENTE en autoguardado
    if "estado_psicologia" in form.fields:
        form.fields["estado_psicologia"].choices = [
            ("PENDIENTE", "Pendiente"),
            ("APROBADO", "Aprobado"),
            ("RECHAZADO", "Rechazado"),
        ]
        form.fields["estado_psicologia"].required = False

    if form.is_valid():
        sol_edit = form.save(commit=False)
        sol_edit.estado_psicologia = sol.estado_psicologia or "PENDIENTE"
        sol_edit.observaciones_psicologia = sol.observaciones_psicologia
        sol_edit.psicologia_por = request.user
        sol_edit.save()

        return JsonResponse({
            "ok": True,
            "mensaje": "Guardado automático realizado"
        })

    return JsonResponse({
        "ok": False,
        "errores": form.errors
    }, status=400)


@login_required
def psicologia_registro(request):
    aprobados = Solicitud.objects.filter(estado_psicologia="APROBADO").order_by("-psicologia_en")
    rechazados = Solicitud.objects.filter(estado_psicologia="RECHAZADO").order_by("-psicologia_en")
    return render(request, "admisiones/psicologia_registro.html", {"aprobados": aprobados, "rechazados": rechazados})


# Nutrición
@login_required
def nutricion_pendientes(request):
    folios_listos = SolicitudInscripcion.objects.filter(
        estado='FILTROS'
    ).values_list('solicitud_ingreso_id', flat=True)

    qs = Solicitud.objects.filter(
        id__in=folios_listos,
        estado_nutricion="PENDIENTE"
    ).order_by("-created_at")

    return render(request, "admisiones/nutricion_pendientes.html", {"solicitudes": qs})


@login_required
def nutricion_dictaminar(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)

    if request.method == "POST":
        form = DictamenNutricionForm(request.POST, instance=sol)

        if form.is_valid():
            sol = form.save(commit=False)

            if sol.estado_nutricion not in ["APROBADO", "RECHAZADO"]:
                form.add_error("estado_nutricion", "Debes seleccionar APROBADO o RECHAZADO para finalizar el dictamen.")
            else:
                sol.nutricion_por = request.user
                sol.nutricion_en = timezone.now()
                sol.save()
                return redirect("nutricion_pendientes")
    else:
        form = DictamenNutricionForm(instance=sol)

    return render(request, "admisiones/nutricion_dictaminar.html", {
        "sol": sol,
        "form": form
    })


@login_required
@require_POST
def nutricion_autoguardar(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)

    data = request.POST.copy()

    # Quitamos campos finales del POST para que no interfieran en el autoguardado
    campos_excluidos = [
        "estado_nutricion",
        "observaciones_nutricion",
        "fecha_elaboracion_nutricion",
    ]

    for campo in campos_excluidos:
        if campo in data:
            del data[campo]

    # Reponemos valores actuales del registro
    data["estado_nutricion"] = sol.estado_nutricion or "PENDIENTE"
    data["observaciones_nutricion"] = sol.observaciones_nutricion or ""

    if sol.fecha_elaboracion_nutricion:
        data["fecha_elaboracion_nutricion"] = sol.fecha_elaboracion_nutricion.strftime("%Y-%m-%d")
    else:
        data["fecha_elaboracion_nutricion"] = ""

    form = DictamenNutricionForm(data, instance=sol)

    # 🔥 MUY IMPORTANTE: para autoguardado sí permitimos PENDIENTE
    if "estado_nutricion" in form.fields:
        form.fields["estado_nutricion"].choices = [
            ("PENDIENTE", "Pendiente"),
            ("APROBADO", "Aprobado"),
            ("RECHAZADO", "Rechazado"),
        ]
        form.fields["estado_nutricion"].required = False

    if form.is_valid():
        sol_edit = form.save(commit=False)

        # 🔒 Conservamos el estado real actual si aún no se ha finalizado
        sol_edit.estado_nutricion = sol.estado_nutricion or "PENDIENTE"
        sol_edit.observaciones_nutricion = sol.observaciones_nutricion
        sol_edit.fecha_elaboracion_nutricion = sol.fecha_elaboracion_nutricion

        sol_edit.nutricion_por = request.user
        sol_edit.save()

        return JsonResponse({
            "ok": True,
            "mensaje": "Guardado automático realizado"
        })

    return JsonResponse({
        "ok": False,
        "errores": form.errors
    }, status=400)


@login_required
def nutricion_registro(request):
    aprobados = Solicitud.objects.filter(estado_nutricion="APROBADO").order_by("-nutricion_en")
    rechazados = Solicitud.objects.filter(estado_nutricion="RECHAZADO").order_by("-nutricion_en")
    return render(request, "admisiones/nutricion_registro.html", {"aprobados": aprobados, "rechazados": rechazados})


@login_required
def medico_pendientes(request):
    folios_listos = SolicitudInscripcion.objects.filter(
        estado='FILTROS'
    ).values_list('solicitud_ingreso_id', flat=True)

    qs = Solicitud.objects.filter(
        id__in=folios_listos,
        estado_medico="PENDIENTE"
    ).order_by("-created_at")

    return render(request, "admisiones/medico_pendientes.html", {"solicitudes": qs})


@login_required
def medico_dictaminar(request, pk):
    sol = get_object_or_404(Solicitud, id=pk)
    insc = get_object_or_404(SolicitudInscripcion, solicitud_ingreso=sol)
    historia, _ = HistoriaClinicaMedica.objects.get_or_create(inscripcion=insc)

    bloqueado = sol.estado_medico in ["APROBADO", "RECHAZADO"]

    if request.method == "POST":
        form = DictamenMedicoForm(request.POST, request.FILES, instance=sol)
        h_form = HistoriaClinicaMedicaForm(request.POST, instance=historia)

        if form.is_valid() and h_form.is_valid():
            sol = form.save(commit=False)
            sol.medico_por = request.user
            sol.medico_en = timezone.now()
            sol.save()
            historia = h_form.save(commit=False)
            historia.inscripcion = insc
            historia.save()

            messages.success(request, "Dictamen médico guardado correctamente.")
            return redirect("medico_pendientes")
    else:
        form = DictamenMedicoForm(instance=sol)
        h_form = HistoriaClinicaMedicaForm(instance=historia)

    return render(request, "admisiones/medico_dictaminar.html", {
        "sol": sol,
        "form": form,
        "historia_form": h_form,
        "bloqueado": bloqueado,
    })

@login_required
@require_POST
def medico_autoguardar(request, pk):
    sol = get_object_or_404(Solicitud, id=pk)
    insc = get_object_or_404(SolicitudInscripcion, solicitud_ingreso=sol)
    historia, _ = HistoriaClinicaMedica.objects.get_or_create(inscripcion=insc)

    def txt(nombre):
        valor = request.POST.get(nombre, "")
        valor = valor.strip()
        return valor if valor != "" else ""

    def bool_si_no(nombre):
        valor = request.POST.get(nombre, "").strip().upper()
        if valor == "SI":
            return True
        if valor == "NO":
            return False
        return None

    try:
        # Datos del menor
        historia.nombres_paciente = txt("nombres_paciente")
        historia.apellido_paterno_paciente = txt("apellido_paterno_paciente")
        historia.apellido_materno_paciente = txt("apellido_materno_paciente")
        historia.nombre_paciente = " ".join(
            x for x in [
                historia.nombres_paciente,
                historia.apellido_paterno_paciente,
                historia.apellido_materno_paciente
            ] if x
        )

        fecha_nacimiento = txt("fecha_nacimiento")
        if fecha_nacimiento:
            historia.fecha_nacimiento = fecha_nacimiento

        historia.edad = txt("edad")
        historia.sexo = txt("sexo")
        historia.quien_cuida_menor = txt("quien_cuida_menor")
        historia.lugar_fecha_elaboracion = txt("lugar_fecha_elaboracion")

        # Padre
        historia.nombres_padre = txt("nombres_padre")
        historia.apellido_paterno_padre = txt("apellido_paterno_padre")
        historia.apellido_materno_padre = txt("apellido_materno_padre")
        historia.nombre_padre = " ".join(
            x for x in [
                historia.nombres_padre,
                historia.apellido_paterno_padre,
                historia.apellido_materno_padre
            ] if x
        )

        historia.edad_padre = txt("edad_padre")
        historia.tabaquismo_padre = bool_si_no("tabaquismo_padre")
        historia.alcoholismo_padre = bool_si_no("alcoholismo_padre")
        historia.drogas_padre = bool_si_no("drogas_padre")
        historia.enfermedades_actuales_padre = txt("enfermedades_actuales_padre")
        historia.alergias_padre = txt("alergias_padre")

        # Madre
        historia.nombres_madre = txt("nombres_madre")
        historia.apellido_paterno_madre = txt("apellido_paterno_madre")
        historia.apellido_materno_madre = txt("apellido_materno_madre")
        historia.nombre_madre = " ".join(
            x for x in [
                historia.nombres_madre,
                historia.apellido_paterno_madre,
                historia.apellido_materno_madre
            ] if x
        )

        historia.edad_madre = txt("edad_madre")
        historia.tabaquismo_madre = bool_si_no("tabaquismo_madre")
        historia.alcoholismo_madre = bool_si_no("alcoholismo_madre")
        historia.drogas_madre = bool_si_no("drogas_madre")
        historia.enfermedades_actuales_madre = txt("enfermedades_actuales_madre")
        historia.enfermedades_infancia_madre = txt("enfermedades_infancia_madre")
        historia.alergias_madre = txt("alergias_madre")

        # Antecedentes no patológicos
        historia.numero_gestas = txt("numero_gestas")
        historia.semanas_gestacion = txt("semanas_gestacion")
        historia.tipo_parto = txt("tipo_parto")
        historia.complicaciones_embarazo = txt("complicaciones_embarazo")
        historia.medicamentos_embarazo = txt("medicamentos_embarazo")
        historia.exposicion_radiacion = txt("exposicion_radiacion")
        historia.sufrimiento_fetal = txt("sufrimiento_fetal")
        historia.motivo_cesarea = txt("motivo_cesarea")

        # Antecedentes patológicos
        historia.enfermedades_actuales = txt("enfermedades_actuales")
        historia.enfermedades_neonatales = txt("enfermedades_neonatales")
        historia.enfermedades_exantematicas = txt("enfermedades_exantematicas")
        historia.internamientos_quirurgicos = txt("internamientos_quirurgicos")
        historia.alergia_medicamentos = txt("alergia_medicamentos")
        historia.alergia_alimentos = txt("alergia_alimentos")
        historia.personas_enfermas_casa = txt("personas_enfermas_casa")

        # Padecimiento actual
        historia.vomitos = txt("vomitos")
        historia.excreta_acuosa = txt("excreta_acuosa")
        historia.fiebre = txt("fiebre")
        historia.tos = txt("tos")
        historia.rinorrea = txt("rinorrea")
        historia.erupciones = txt("erupciones")
        historia.dificultad_respiratoria = txt("dificultad_respiratoria")

        # Exploración física
        historia.peso_actual = txt("peso_actual")
        historia.talla = txt("talla")
        historia.temperatura = txt("temperatura")
        historia.frecuencia_cardiaca = txt("frecuencia_cardiaca")
        historia.frecuencia_respiratoria = txt("frecuencia_respiratoria")
        historia.tension_arterial = txt("tension_arterial")
        historia.estado_nutricional = txt("estado_nutricional")

        # Dictamen clínico
        historia.diagnostico = txt("diagnostico")
        historia.pronostico = txt("pronostico")
        historia.elaborado_por = txt("elaborado_por")

        historia.inscripcion = insc
        historia.save()

        # Solicitud
        estado_medico = request.POST.get("estado_medico", "").strip()
        observaciones_medico = request.POST.get("observaciones_medico", "").strip()

        if estado_medico:
            sol.estado_medico = estado_medico

        sol.observaciones_medico = observaciones_medico
        sol.medico_por = request.user
        sol.medico_en = timezone.now()
        sol.save()

        return JsonResponse({
            "ok": True,
            "message": "Cambios guardados automáticamente.",
            "hora": timezone.localtime().strftime("%H:%M:%S")
        })

    except Exception as e:
        print("=========== ERROR AUTOGUARDADO MÉDICO ===========")
        print("ERROR:", str(e))
        print("POST:", request.POST)
        print("=================================================")

        return JsonResponse({
            "ok": False,
            "message": f"Error al autoguardar: {str(e)}"
        }, status=400)

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
def medico_registro(request):
    aprobados = Solicitud.objects.filter(estado_medico="APROBADO").order_by("-medico_en")
    rechazados = Solicitud.objects.filter(estado_medico="RECHAZADO").order_by("-medico_en")
    return render(request, "admisiones/medico_registro.html", {"aprobados": aprobados, "rechazados": rechazados})


@login_required
def descargar_pdf_solicitud(request, solicitud_id):
    sol = get_object_or_404(Solicitud, id=solicitud_id)
    matricula = sol.matricula or "S_M"
    nombre_archivo = f"Expediente_Inscripcion_{matricula}.pdf"
    if hasattr(sol, 'inscripcion_oficial'):
        ruta = generar_pdf_inscripcion_lleno(sol.inscripcion_oficial)
        if ruta and os.path.exists(ruta):
            return FileResponse(open(ruta, 'rb'), as_attachment=True, filename=nombre_archivo)
    if sol.pdf:
        return FileResponse(sol.pdf.open("rb"), as_attachment=True, filename=nombre_archivo)
    raise Http404("PDF no disponible.")


@login_required
def psicologia_pdf(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    html = render_to_string("admisiones/psicologia_pdf.html", {"sol": sol}, request=request)
    response = HttpResponse(content_type="application/pdf")
    matricula = sol.matricula or sol.folio or "S_M"
    response['Content-Disposition'] = f'attachment; filename="Dictamen_Psicologia_{matricula}.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    if pisa_status.err:
        return HttpResponse("Error al generar el PDF de psicología", status=500)
    return response


@login_required
def nutricion_pdf(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    html = render_to_string("admisiones/nutricion_pdf.html", {"sol": sol}, request=request)
    response = HttpResponse(content_type="application/pdf")
    matricula = sol.matricula or sol.folio or "S_M"
    response['Content-Disposition'] = f'attachment; filename="Dictamen_Nutricion_{matricula}.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    if pisa_status.err:
        return HttpResponse("Error al generar el PDF de nutrición", status=500)
    return response


@login_required
def medico_pdf(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    # Validación básica de permisos
    if not (
        request.user.is_superuser
        or request.user.is_staff
        or request.user.groups.filter(name__in=["medica", "admin", "directora", "jefa_superior", "administrativo"]).exists()
    ):
        raise Http404("No autorizado")

    # Generar PDF en memoria
    html = render_to_string("admisiones/medico_pdf.html", {"sol": sol}, request=request)
    resultado = io.BytesIO()
    pdf = pisa.CreatePDF(io.StringIO(html), dest=resultado)

    if pdf.err:
        return HttpResponse("Error al generar el PDF", status=500)

    nombre_menor = f"{sol.nombres_menor or ''} {sol.apellido_paterno_menor or ''} {sol.apellido_materno_menor or ''}".strip()
    nombre_archivo = f"Dictamen_Medico_{sol.folio}_{slugify(nombre_menor) or 'solicitud'}.pdf"

    response = HttpResponse(resultado.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{nombre_archivo}"'
    return response


@login_required
def descargar_reporte_final_padre(request, inscripcion_id):
    insc = get_object_or_404(SolicitudInscripcion, id=inscripcion_id, usuario_tutor=request.user)
    html = render_to_string("admisiones/reporte_final_pdf.html", {"inscripcion": insc}, request=request)
    response = HttpResponse(content_type="application/pdf")
    matricula = insc.solicitud_ingreso.matricula or "S_M"
    response['Content-Disposition'] = f'attachment; filename="Reporte_Final_Inscripcion_{matricula}.pdf"'
    pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    return response


def solicitud_publica_nueva(request):
    return render(request, "admisiones/publico_nuevo_ingreso.html")


@login_required
def validacion_pagos_pendientes(request):
    insc = SolicitudInscripcion.objects.filter(estado='ACEPTADO_ESPERANDO_PAGO').exclude(doc_tutor_pago='')
    return render(request, 'admisiones/validacion_pagos.html', {'inscripciones': insc})


@login_required
def registrar_pago_valido(request, pk):
    insc = get_object_or_404(SolicitudInscripcion, id=pk)
    if request.method == 'POST':
        insc.estado = 'FINALIZADA'
        insc.save()
    return redirect('validacion_pagos_pendientes')


@login_required
def lista_semestres(request):
    sem = Semestre.objects.all().order_by('-fecha_inicio')
    return render(request, 'admisiones/coordinadora_de_salas.html', {'semestres': sem})


@login_required
def crear_semestre(request):
    if request.method == 'POST':
        form = SemestreForm(request.POST)
        if form.is_valid(): form.save(); return redirect('lista_semestres')
    return render(request, 'admisiones/crear_semestre.html', {'form': SemestreForm()})


@login_required
def detalle_semestre(request, semestre_id):
    sem = get_object_or_404(Semestre, id=semestre_id)
    salas = SalaSemestre.objects.filter(semestre=sem)
    return render(request, 'admisiones/detalle_semestre.html', {'semestre': sem, 'salas_activas': salas})


@login_required
def dictaminar_reporte_final(request, pk):
    insc = get_object_or_404(SolicitudInscripcion, id=pk)
    if request.method == 'POST':
        insc.reporte_final_aprobado = (request.POST.get('decision') == 'APROBAR')
        insc.estado = 'ESPERANDO_DIRECTORA' if insc.reporte_final_aprobado else 'RECHAZADA'
        insc.save()
        return redirect('reporte_final_pendientes')
    return render(request, 'admisiones/dictaminar_reporte_final.html', {'inscripcion': insc})

# ===================== DASHBOARD DIRECTIVA (NUEVO) =====================
@login_required
def dashboard_directiva(request):
    # Verificamos que sea Directora, Secretario o Admin
    user = request.user
    grupo = user.groups.first().name.strip().lower() if user.groups.exists() else ""
    if getattr(user, 'tipo_persona', '') != 'ADMIN' and "directora" not in grupo and "secretario" not in grupo:
        return redirect('/')

    # 1. EXPEDIENTES PARA VEREDICTO FINAL
    dictamenes_pendientes = SolicitudInscripcion.objects.filter(
        estado='ESPERANDO_DIRECTORA'
    ).order_by('-updated_at')

    # 2. SUPERVISIÓN GLOBAL
    expedientes_en_filtros = SolicitudInscripcion.objects.filter(estado='FILTROS')

    # 3. BANDEJA DE CORREOS / MENSAJES (Separados)
    mensajes_aspirantes = MensajeDirectora.objects.filter(es_alumno_inscrito=False, leido=False).order_by(
        '-fecha_envio')
    mensajes_alumnos = MensajeDirectora.objects.filter(es_alumno_inscrito=True, leido=False).order_by('-fecha_envio')

    # 4. PANEL DE INCIDENCIAS
    incidencias_alto = Incidencia.objects.filter(nivel='ALTO', resuelta=False).order_by('-fecha_reporte')
    incidencias_bajo = Incidencia.objects.filter(nivel='BAJO', resuelta=False).order_by('-fecha_reporte')

    # Estadísticas para los KPI
    kpi_alumnos = SolicitudInscripcion.objects.filter(estado='FINALIZADA').count()
    kpi_pendientes = dictamenes_pendientes.count()
    kpi_riesgo = incidencias_alto.count()

    context = {
        'dictamenes_pendientes': dictamenes_pendientes,
        'mensajes_aspirantes': mensajes_aspirantes,
        'mensajes_alumnos': mensajes_alumnos,
        'incidencias_alto': incidencias_alto,
        'incidencias_bajo': incidencias_bajo,
        'kpi_alumnos': kpi_alumnos,
        'kpi_pendientes': kpi_pendientes,
        'kpi_riesgo': kpi_riesgo,
        'expedientes_en_filtros': expedientes_en_filtros,
    }
    return render(request, 'admisiones/dashboard_directiva.html', context)


# ===================== VEREDICTO FINAL (DIRECTORA / SECRETARIO / ADMIN) =====================
@login_required
def veredicto_final_directora(request, inscripcion_id):
    insc = get_object_or_404(SolicitudInscripcion, id=inscripcion_id)

    # 1. VERIFICACIÓN DE ROLES (Punto 19: Directora, Secretario técnico, Administrador)
    user = request.user
    grupo = user.groups.first().name.strip().lower() if user.groups.exists() else ""

    es_autorizado = (
            getattr(user, 'tipo_persona', '') == 'ADMIN' or
            "directora" in grupo or
            "secretario" in grupo or
            "administrador" in grupo
    )

    if not es_autorizado:
        messages.error(request, "No tienes permiso para emitir este veredicto.")
        return redirect('/')

    # 2. APLICAR EL ESTATUS (Aceptado, Rechazado, Pendiente)
    if request.method == 'POST':
        accion = request.POST.get('accion')

        if accion == 'ACEPTAR':
            insc.estado = "ACEPTADO_ESPERANDO_PAGO"
            messages.success(request, f"Expediente de {insc.solicitud_ingreso.nombres_menor} ACEPTADO.")

        elif accion == 'RECHAZAR':
            insc.estado = "RECHAZADA"
            messages.error(request, f"Expediente de {insc.solicitud_ingreso.nombres_menor} RECHAZADO.")

        elif accion == 'PENDIENTE':
            insc.estado = "ESPERANDO_DIRECTORA"
            messages.warning(request, f"Expediente de {insc.solicitud_ingreso.nombres_menor} marcado como PENDIENTE.")

        # Registrar quién tomó la decisión y cuándo
        insc.directora_por = request.user
        insc.directora_en = timezone.now()
        insc.save()

    return redirect('dashboard_directiva')