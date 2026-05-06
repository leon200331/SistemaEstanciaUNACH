from django.shortcuts import render, redirect, get_object_or_404
from django.http import FileResponse, Http404, HttpResponse
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_http_methods
from django.urls import reverse
from django.conf import settings
from django.template.loader import render_to_string
from django.contrib.staticfiles import finders
from xhtml2pdf import pisa

from django.db import IntegrityError
from django.core.mail import send_mail, EmailMessage
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.db.models import Q

import os
import io
import datetime
from datetime import date
from io import BytesIO
from .forms import (
    CapturaSolicitudForm, CrearSolicitudPanelForm, DictamenPsicologiaForm,
    DictamenNutricionForm, DictamenMedicoForm, HistoriaClinicaMedicaForm,
    SemestreForm, BitacoraLactanteForm, BitacoraMaternalForm
)
from .services import generar_pdf_fo301, generar_pdf_dictamen, generar_pdf_inscripcion_lleno
from .models import (
    Solicitud, LinkCaptura, SolicitudInscripcion, HistoriaClinicaMedica,
    Semestre, SalaSemestre, MensajeDirectora, Incidencia,
    AsignacionMaestra, BitacoraLactante, BitacoraMaternal, Sala
)


def link_callback(uri, rel):
    if uri.startswith(settings.STATIC_URL):
        path = finders.find(uri.replace(settings.STATIC_URL, ""))
        if path: return path
    return uri


def verificacion_staff(user):
    return user.is_authenticated and (user.is_staff or getattr(user, 'tipo_persona', '') == 'ADMIN')


# ===================== CAPTURA POR TOKEN (PADRES) =====================
def captura_por_token(request, token):
    link = get_object_or_404(LinkCaptura, token=token)
    if not link.vigente(): raise Http404("Este enlace ya no es válido.")
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
                print("Error al generar PDF:", e)
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
        if unidad == "Otra": unidad = form.cleaned_data.get("unidad_academica_otra")
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


@user_passes_test(verificacion_staff, login_url='/')
def eliminar_solicitud(request, pk):
    s = get_object_or_404(Solicitud, pk=pk)
    s.delete()
    messages.success(request, "Solicitud eliminada.")
    return redirect('panel_admisiones')


@user_passes_test(verificacion_staff, login_url='/')
def eliminar_todas_solicitudes(request):
    if request.method == "POST":
        Solicitud.objects.all().delete()
        messages.success(request, "Todas eliminadas.")
    return redirect('panel_admisiones')


# ===================== FUNCIÓN DE DESCARGA DIRECTA (TS) =====================
@login_required
def descargar_archivo_expediente(request, inscripcion_id, campo):
    user = request.user
    grupo = user.groups.first().name.strip().lower() if user.groups.exists() else ""
    if getattr(user, 'tipo_persona', '') != 'ADMIN' and "trabajadora social" not in grupo:
        return redirect('/')
    insc = get_object_or_404(SolicitudInscripcion, id=inscripcion_id)
    archivo_field = getattr(insc, campo, None)
    if not archivo_field: raise Http404("El archivo no existe.")

    mapeo_nombres = {
        'doc_menor_certificado_medico': 'Certificado_Medico_Menor',
        'doc_menor_cartilla_vacunacion': 'Cartilla_Vacunacion_Menor',
        'doc_menor_grupo_sanguineo': 'Grupo_Sanguineo_Menor', 'doc_menor_acta_nacimiento': 'Acta_de_Nacimiento_Menor',
        'doc_menor_fotos': 'Fotografia_del_Menor', 'doc_menor_laboratorio': 'Estudios_de_Laboratorio_Menor',
        'doc_tutor_acta_nacimiento': 'Acta_de_Nacimiento_Beneficiario', 'doc_tutor_ine': 'INE_del_Beneficiario',
        'doc_tutor_fotos': 'Fotografia_del_Beneficiario', 'doc_segundo_padre_fotos': 'Fotografia_Pareja',
        'doc_tutor_domicilio': 'Comprobante_de_Domicilio_Beneficiario', 'doc_tutor_historial': 'Historial_Academico',
        'doc_tutor_horario': 'Horario_de_Clases', 'doc_autorizado_carta': 'Carta_de_Autorizacion',
        'doc_autorizado_ine': 'INE_del_Autorizado', 'doc_contacto_1_fotos': 'Fotografia_Autorizado_1',
        'doc_contacto_2_fotos': 'Fotografia_Autorizado_2', 'doc_contacto_3_fotos': 'Fotografia_Autorizado_3',
        'reglamento_firmado': 'Reglamento_Interno_Firmado', 'doc_tutor_pago': 'Comprobante_Pago'
    }
    nombre_archivo = mapeo_nombres.get(campo, "Documento")
    matricula = insc.solicitud_ingreso.matricula or "SIN_MATRICULA"
    ext = os.path.splitext(archivo_field.name)[1]
    return FileResponse(archivo_field.open('rb'), as_attachment=True, filename=f"{nombre_archivo}_{matricula}{ext}")


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
            'doc_menor_fotos': 'Fotografia_del_Menor', 'doc_menor_laboratorio': 'Estudios_de_Laboratorio_Menor',
            'doc_tutor_acta_nacimiento': 'Acta_de_Nacimiento_Beneficiario', 'doc_tutor_ine': 'INE_del_Beneficiario',
            'doc_tutor_fotos': 'Fotografia_del_Beneficiario', 'doc_segundo_padre_fotos': 'Fotografia_Pareja',
            'doc_tutor_domicilio': 'Comprobante_de_Domicilio_Beneficiario',
            'doc_tutor_historial': 'Historial_Academico',
            'doc_tutor_horario': 'Horario_de_Clases', 'doc_autorizado_carta': 'Carta_de_Autorizacion',
            'doc_autorizado_ine': 'INE_del_Autorizado', 'doc_contacto_1_fotos': 'Fotografia_Autorizado_1',
            'doc_contacto_2_fotos': 'Fotografia_Autorizado_2', 'doc_contacto_3_fotos': 'Fotografia_Autorizado_3',
            'reglamento_firmado': 'Reglamento_Interno_Firmado', 'doc_tutor_pago': 'Comprobante_de_Pago'
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
                archivo.name = f"{nombre_legible}_{matricula}{ext}"
                setattr(inscripcion, campo, archivo)

        for key, value in request.POST.items():
            if key not in ['csrfmiddlewaretoken', 'enviar_revision']:
                if hasattr(inscripcion, key):
                    setattr(inscripcion, key, value)
                elif hasattr(inscripcion.solicitud_ingreso, key):
                    setattr(inscripcion.solicitud_ingreso, key, value)

        if request.POST.get('enviar_revision') == '1':
            inscripcion.estado = 'EN_REVISION'
            messages.success(request, "Expediente enviado. Tus archivos se organizaron correctamente.")
        else:
            messages.success(request, "Avance guardado exitosamente.")

        inscripcion.solicitud_ingreso.save()
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
    insc = SolicitudInscripcion.objects.filter(solicitud_ingreso=sol).first()
    if insc:
        sol.nombres_menor = sol.nombres_menor if sol.nombres_menor else getattr(insc, 'nombres_menor', '')
        sol.apellido_paterno_menor = sol.apellido_paterno_menor if sol.apellido_paterno_menor else getattr(insc,
                                                                                                           'apellido_paterno_menor',
                                                                                                           '')
        sol.apellido_materno_menor = sol.apellido_materno_menor if sol.apellido_materno_menor else getattr(insc,
                                                                                                           'apellido_materno_menor',
                                                                                                           '')

    if request.method == "POST":
        form = DictamenPsicologiaForm(request.POST, instance=sol)
        if form.is_valid():
            sol = form.save(commit=False)
            sol.psicologia_por = request.user
            sol.psicologia_en = timezone.now()
            sol.save()
            messages.success(request, "Dictamen de psicología guardado exitosamente.")
            return redirect("psicologia_pendientes")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Te faltó este campo ({field}): {error}")
            messages.warning(request, "⚠️ No se guardó el dictamen. Revisa los mensajes rojos de arriba.")
    else:
        form = DictamenPsicologiaForm(instance=sol)
    return render(request, "admisiones/psicologia_dictaminar.html", {"sol": sol, "form": form})


@login_required
def psicologia_registro(request):
    aprobados = Solicitud.objects.filter(estado_psicologia="APROBADO").order_by("-psicologia_en")
    rechazados = Solicitud.objects.filter(estado_psicologia="RECHAZADO").order_by("-psicologia_en")
    return render(request, "admisiones/psicologia_registro.html", {"aprobados": aprobados, "rechazados": rechazados})


@login_required
def nutricion_pendientes(request):
    folios = SolicitudInscripcion.objects.filter(estado='FILTROS').values_list('solicitud_ingreso_id', flat=True)
    qs = Solicitud.objects.filter(id__in=folios, estado_nutricion="PENDIENTE").order_by("-created_at")
    return render(request, "admisiones/nutricion_pendientes.html", {"solicitudes": qs})


@login_required
def nutricion_dictaminar(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    insc = SolicitudInscripcion.objects.filter(solicitud_ingreso=sol).first()
    if insc:
        sol.nombres_menor = sol.nombres_menor if sol.nombres_menor else getattr(insc, 'nombres_menor', '')
        sol.apellido_paterno_menor = sol.apellido_paterno_menor if sol.apellido_paterno_menor else getattr(insc,
                                                                                                           'apellido_paterno_menor',
                                                                                                           '')
        sol.apellido_materno_menor = sol.apellido_materno_menor if sol.apellido_materno_menor else getattr(insc,
                                                                                                           'apellido_materno_menor',
                                                                                                           '')

    if request.method == "POST":
        form = DictamenNutricionForm(request.POST, instance=sol)
        if form.is_valid():
            sol = form.save(commit=False)
            sol.nutricion_por = request.user
            sol.nutricion_en = timezone.now()
            sol.save()
            messages.success(request, "Dictamen de nutrición guardado exitosamente.")
            return redirect("nutricion_pendientes")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Te faltó este campo ({field}): {error}")
            messages.warning(request, "⚠️ No se guardó el dictamen. Revisa los mensajes rojos de arriba.")
    else:
        form = DictamenNutricionForm(instance=sol)
    return render(request, "admisiones/nutricion_dictaminar.html", {"sol": sol, "form": form})


@login_required
def nutricion_registro(request):
    aprobados = Solicitud.objects.filter(estado_nutricion="APROBADO").order_by("-nutricion_en")
    rechazados = Solicitud.objects.filter(estado_nutricion="RECHAZADO").order_by("-nutricion_en")
    return render(request, "admisiones/nutricion_registro.html", {"aprobados": aprobados, "rechazados": rechazados})


@login_required
def medico_pendientes(request):
    folios = SolicitudInscripcion.objects.filter(estado='FILTROS').values_list('solicitud_ingreso_id', flat=True)
    qs = Solicitud.objects.filter(id__in=folios, estado_medico="PENDIENTE").order_by("-created_at")
    return render(request, "admisiones/medico_pendientes.html", {"solicitudes": qs})


# =========================================================================
# VISTA MÉDICA CORREGIDA PARA EVITAR EL ERROR DE MAX_LENGTH DE LA BD
# =========================================================================
@login_required
def medico_dictaminar(request, pk):
    sol = get_object_or_404(Solicitud, id=pk)
    insc = get_object_or_404(SolicitudInscripcion, solicitud_ingreso=sol)

    historia, created = HistoriaClinicaMedica.objects.get_or_create(inscripcion=insc)

    # 1. Recuperar el nombre del menor asegurando que no llegue vacío
    n_menor = sol.nombres_menor or getattr(insc, 'nombres_menor', '')
    ap_menor = sol.apellido_paterno_menor or getattr(insc, 'apellido_paterno_menor', '')
    am_menor = sol.apellido_materno_menor or getattr(insc, 'apellido_materno_menor', '')

    # 2. Construir Diccionario INITIAL
    h_initial = {
        'nombres_paciente': n_menor,
        'apellido_paterno_paciente': ap_menor,
        'apellido_materno_paciente': am_menor,
    }

    # Edades y sexo
    anios = insc.edad_anios_menor or 0
    meses = insc.edad_meses_menor or 0
    h_initial['edad'] = historia.edad or f"{anios} años, {meses} meses"

    sexo_bd = insc.sexo_menor or getattr(sol, 'sexo_nutricion', '')
    if sexo_bd in ['M', 'MASCULINO']:
        h_initial['sexo'] = "Masculino"
    elif sexo_bd in ['F', 'FEMENINO']:
        h_initial['sexo'] = "Femenino"
    else:
        h_initial['sexo'] = historia.sexo

    if sol.fecha_nacimiento_menor and not historia.fecha_nacimiento:
        h_initial['fecha_nacimiento'] = sol.fecha_nacimiento_menor

    h_initial[
        'quien_cuida_menor'] = historia.quien_cuida_menor or sol.persona_aparte_padres_cuidado_psicologia or "Padres"

    # 3. LÓGICA PADRE
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
    elif sol.parentesco == 'PADRE':
        nombres_padre = sol.nombres_tutor
        paterno_padre = sol.apellido_paterno_tutor
        materno_padre = sol.apellido_materno_tutor

    h_initial['nombres_padre'] = nombres_padre
    h_initial['apellido_paterno_padre'] = paterno_padre
    h_initial['apellido_materno_padre'] = materno_padre
    h_initial['edad_padre'] = historia.edad_padre or sol.edad_padre_psicologia

    # 4. LÓGICA MADRE
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
    elif sol.parentesco == 'MADRE':
        nombres_madre = sol.nombres_tutor
        paterno_madre = sol.apellido_paterno_tutor
        materno_madre = sol.apellido_materno_tutor

    h_initial['nombres_madre'] = nombres_madre
    h_initial['apellido_paterno_madre'] = paterno_madre
    h_initial['apellido_materno_madre'] = materno_madre
    h_initial['edad_madre'] = historia.edad_madre or sol.edad_madre_psicologia

    # 5. DATOS TÉCNICOS (PRE-CORTADOS PARA QUE NO DEN ERROR AL ENTRAR)
    g_raw = historia.numero_gestas or sol.numero_gesta_psicologia or ""
    if "1" in g_raw:
        g_raw = "1"
    elif "2" in g_raw:
        g_raw = "2"
    elif "3" in g_raw:
        g_raw = "3"
    elif "4" in g_raw:
        g_raw = "4 o mas"
    h_initial['numero_gestas'] = g_raw[:10]

    s_raw = historia.semanas_gestacion or sol.semanas_gestacion_psicologia or ""
    if "Menos" in s_raw:
        s_raw = "< 37 sem"
    elif "37" in s_raw:
        s_raw = "37 a 41 sem"
    elif "42" in s_raw:
        s_raw = "> 42 sem"
    elif "Desconoce" in s_raw:
        s_raw = "Desconoce"
    h_initial['semanas_gestacion'] = s_raw[:20]

    h_initial['peso_actual'] = historia.peso_actual or sol.peso_actual or sol.peso_al_nacer_psicologia
    h_initial['talla'] = historia.talla or sol.talla_actual or sol.talla_al_nacer_psicologia

    parto = (sol.tipo_nacimiento_psicologia or "").upper()
    tipo_parto = historia.tipo_parto
    if not tipo_parto:
        if "CESAREA" in parto:
            tipo_parto = "Cesárea"
        elif "PARTO" in parto:
            tipo_parto = "Eutócico"
    h_initial['tipo_parto'] = tipo_parto

    # 6. SOBREESCRIBIR CON DATOS GUARDADOS EN LA HISTORIA PREVIAMENTE (Si los hay)
    if historia.nombre_paciente:
        parts = historia.nombre_paciente.split()
        if len(parts) >= 3:
            h_initial['nombres_paciente'] = " ".join(parts[:-2])
            h_initial['apellido_paterno_paciente'] = parts[-2]
            h_initial['apellido_materno_paciente'] = parts[-1]
        elif len(parts) == 2:
            h_initial['nombres_paciente'] = parts[0]
            h_initial['apellido_paterno_paciente'] = parts[1]
            h_initial['apellido_materno_paciente'] = ""
        else:
            h_initial['nombres_paciente'] = historia.nombre_paciente

    if historia.nombre_padre:
        parts = historia.nombre_padre.split()
        if len(parts) >= 3:
            h_initial['nombres_padre'] = " ".join(parts[:-2])
            h_initial['apellido_paterno_padre'] = parts[-2]
            h_initial['apellido_materno_padre'] = parts[-1]
        elif len(parts) == 2:
            h_initial['nombres_padre'] = parts[0]
            h_initial['apellido_paterno_padre'] = parts[1]
            h_initial['apellido_materno_padre'] = ""
        else:
            h_initial['nombres_padre'] = historia.nombre_padre

    if historia.nombre_madre:
        parts = historia.nombre_madre.split()
        if len(parts) >= 3:
            h_initial['nombres_madre'] = " ".join(parts[:-2])
            h_initial['apellido_paterno_madre'] = parts[-2]
            h_initial['apellido_materno_madre'] = parts[-1]
        elif len(parts) == 2:
            h_initial['nombres_madre'] = parts[0]
            h_initial['apellido_paterno_madre'] = parts[1]
            h_initial['apellido_materno_madre'] = ""
        else:
            h_initial['nombres_madre'] = historia.nombre_madre

    if request.method == "POST":
        # =========================================================================
        # LA SOLUCIÓN AL ERROR ROJO: RECORTAMOS EL TEXTO LARGO ANTES DE GUARDAR
        # =========================================================================
        post_data = request.POST.copy()

        if 'numero_gestas' in post_data:
            g_val = post_data['numero_gestas']
            if "1" in g_val:
                g_val = "1"
            elif "2" in g_val:
                g_val = "2"
            elif "3" in g_val:
                g_val = "3"
            elif "4" in g_val:
                g_val = "4 o mas"
            post_data['numero_gestas'] = g_val[:10]  # Recorta máximo a 10 letras

        if 'semanas_gestacion' in post_data:
            s_val = post_data['semanas_gestacion']
            if "Menos" in s_val:
                s_val = "< 37 sem"
            elif "37" in s_val:
                s_val = "37 a 41 sem"
            elif "42" in s_val:
                s_val = "> 42 sem"
            elif "Desconoce" in s_val:
                s_val = "Desconoce"
            post_data['semanas_gestacion'] = s_val[:20]  # Recorta máximo a 20 letras

        estado_decision = post_data.get('estado_medico')
        if not estado_decision or estado_decision == 'PENDIENTE':
            messages.error(request, "⚠️ ERROR: Debes seleccionar un Veredicto Final (Aprobado o Rechazado).")
            form = DictamenMedicoForm(post_data, request.FILES, instance=sol)
            h_form = HistoriaClinicaMedicaForm(post_data, instance=historia, initial=h_initial)
        else:
            form = DictamenMedicoForm(post_data, request.FILES, instance=sol)
            h_form = HistoriaClinicaMedicaForm(post_data, instance=historia, initial=h_initial)

            if form.is_valid() and h_form.is_valid():
                sol = form.save(commit=False)
                sol.estado_medico = estado_decision
                sol.medico_por = request.user
                sol.medico_en = timezone.now()
                sol.save()
                h_form.save()
                messages.success(request, "Dictamen médico guardado.")
                return redirect("medico_pendientes")
            else:
                if not form.is_valid():
                    for f, errs in form.errors.items():
                        for e in errs: messages.error(request, f"Error Médico ({f}): {e}")
                if not h_form.is_valid():
                    for f, errs in h_form.errors.items():
                        for e in errs: messages.error(request, f"Error Historia Clínica ({f}): {e}")
                messages.warning(request, "⚠️ Hay campos obligatorios en blanco, no se pudo guardar.")
    else:
        form = DictamenMedicoForm(instance=sol)
        h_form = HistoriaClinicaMedicaForm(instance=historia, initial=h_initial)

    return render(request, "admisiones/medico_dictaminar.html", {
        "sol": sol,
        "form": form,
        "historia_form": h_form,
        "mama_previo": bool(h_initial['nombres_madre']),
        "papa_previo": bool(h_initial['nombres_padre'])
    })


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
        if ruta and os.path.exists(ruta): return FileResponse(open(ruta, 'rb'), as_attachment=True,
                                                              filename=nombre_archivo)
    if sol.pdf: return FileResponse(sol.pdf.open("rb"), as_attachment=True, filename=nombre_archivo)
    raise Http404("PDF no disponible.")


@login_required
def psicologia_pdf(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    insc = SolicitudInscripcion.objects.filter(solicitud_ingreso=sol).first()
    context = {"sol": sol, "insc": insc}
    html = render_to_string("admisiones/psicologia_pdf.html", context, request=request)
    response = HttpResponse(content_type="application/pdf")
    response['Content-Disposition'] = f'attachment; filename="Dictamen_Psicologia.pdf"'
    pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    return response


@login_required
def nutricion_pdf(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    insc = SolicitudInscripcion.objects.filter(solicitud_ingreso=sol).first()
    context = {"sol": sol, "insc": insc}
    html = render_to_string("admisiones/nutricion_pdf.html", context, request=request)
    response = HttpResponse(content_type="application/pdf")
    response['Content-Disposition'] = f'attachment; filename="Dictamen_Nutricion.pdf"'
    pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    return response


@login_required
def medico_pdf(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)
    insc = SolicitudInscripcion.objects.filter(solicitud_ingreso=sol).first()
    context = {"sol": sol, "insc": insc}
    html = render_to_string("admisiones/medico_pdf.html", context, request=request)
    response = HttpResponse(content_type="application/pdf")
    response['Content-Disposition'] = f'attachment; filename="Dictamen_Medico.pdf"'
    pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    return response


@login_required
def descargar_reporte_final_padre(request, inscripcion_id):
    insc = get_object_or_404(SolicitudInscripcion, id=inscripcion_id, usuario_tutor=request.user)
    html = render_to_string("admisiones/reporte_final_pdf.html", {"inscripcion": insc}, request=request)
    response = HttpResponse(content_type="application/pdf")
    pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    return response


def solicitud_publica_nueva(request):
    return render(request, "admisiones/publico_nuevo_ingreso.html")


# =========================================================
# SOLUCIÓN DE PAGOS (DESCONECTADOS DEL FLUJO PRINCIPAL)
# =========================================================
@login_required
def validacion_pagos_pendientes(request):
    # La vista sigue existiendo pero ya no afecta si el niño entra o no a la sala
    insc = SolicitudInscripcion.objects.filter(estado='ACEPTADO_ESPERANDO_PAGO').order_by('-updated_at')
    return render(request, 'admisiones/validacion_pagos.html', {'inscripciones': insc})


@login_required
def registrar_pago_valido(request, pk):
    insc = get_object_or_404(SolicitudInscripcion, id=pk)
    if request.method == 'POST':
        pass
    return redirect('validacion_pagos_pendientes')


@login_required
def lista_semestres(request):
    sem = Semestre.objects.all().order_by('-fecha_inicio')
    salas = ['L1', 'L2', 'L3', 'M1', 'M2', 'M3']
    return render(request, 'admisiones/coordinadora_de_salas.html', {'semestres': sem, 'salas_lista': salas})


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


# =========================================================
# FLUJO CORRECTO: REPORTE -> DIRECTORA (TS gestiona Reporte Final)
# =========================================================

# 1. TRABAJO SOCIAL: Aprueba el reporte final y lo manda a la Directora
@login_required
def dictaminar_reporte_final(request, pk):
    insc = get_object_or_404(SolicitudInscripcion, id=pk)

    if request.method == 'POST':
        decision = request.POST.get('decision')

        if decision == 'APROBAR':
            # MAGIA ABSOLUTA: Forzamos el estado directamente en SQL. Nada lo puede cancelar.
            SolicitudInscripcion.objects.filter(id=pk).update(
                reporte_final_aprobado=True,
                estado='ESPERANDO_DIRECTORA',
                reporte_final_por=request.user,
                reporte_final_en=timezone.now()
            )

            # Recargamos la información y calculamos la sala
            insc.refresh_from_db()
            try:
                insc.evaluar_y_recomendar_sala()
            except Exception as e:
                print(f"Error ignorado en sala: {e}")

            messages.success(request, "Reporte Final aprobado. El expediente ya está en la bandeja de la Directora.")

        else:
            SolicitudInscripcion.objects.filter(id=pk).update(
                reporte_final_aprobado=False,
                estado='RECHAZADA',
                reporte_final_por=request.user,
                reporte_final_en=timezone.now()
            )
            messages.warning(request, "El expediente ha sido rechazado.")

        return redirect('reporte_final_pendientes')

    return render(request, 'admisiones/dictaminar_reporte_final.html', {'inscripcion': insc})


@login_required
def reporte_final_pendientes(request):
    insc = SolicitudInscripcion.objects.filter(
        estado='FILTROS',
        solicitud_ingreso__estado_medico='APROBADO',
        reporte_final_aprobado__isnull=True
    ).order_by('-updated_at')
    return render(request, 'admisiones/reporte_final_pendientes.html', {'inscripciones': insc})


# 3. TS ve la lista y propone sala (o finaliza si ya se la aprobaron)
@login_required
def lista_asignacion_salas(request):
    inscripciones = SolicitudInscripcion.objects.filter(
        estado__in=['ESPERANDO_SALA', 'SALA_RECHAZADA', 'SALA_APROBADA']
    ).order_by('-updated_at')

    return render(request, 'admisiones/lista_asignacion_salas.html', {'inscripciones': inscripciones})


@login_required
def asignar_sala_definitiva(request, inscripcion_id):
    insc = get_object_or_404(SolicitudInscripcion, id=inscripcion_id)
    if getattr(request.user, 'tipo_persona', '') != 'ADMIN' and not request.user.is_staff: return redirect('/')

    if request.method == 'POST':
        accion = request.POST.get('accion', 'ENVIAR_DIRECTORA')  # Por defecto enviar a directora

        if accion == 'ENVIAR_DIRECTORA':
            sala_id = request.POST.get('sala_id')
            if sala_id:
                sala_seleccionada = get_object_or_404(Sala, id=sala_id)
                insc.sala_asignada = sala_seleccionada
                insc.estado = "SALA_EN_REVISION"
                insc.motivo_rechazo_sala = ""
                insc.save()
                messages.success(request,
                                 f"Se ha propuesto la Sala {sala_seleccionada.nombre}. Enviado a la Directora para su autorización.")
            else:
                messages.error(request, "Debes seleccionar una sala válida.")

        elif accion == 'GUARDAR_FINAL':
            insc.sala_bloqueada = True
            insc.estado = "FINALIZADA"
            insc.save()
            messages.success(request, "¡Asignación Finalizada! El alumno ya está oficialmente inscrito en la sala.")

        return redirect('lista_asignacion_salas')

    salas = Sala.objects.all()
    return render(request, 'admisiones/asignar_sala_ts.html', {'inscripcion': insc, 'salas': salas})


# =========================================================
# VISTAS PARA ASISTENTES Y COORDINACIÓN (BITÁCORAS)
# =========================================================

@login_required
def dashboard_maestra(request):
    # 1. Buscamos cuál es la sala original de esta maestra (titular)
    asignacion = AsignacionMaestra.objects.filter(maestra=request.user).select_related('sala_semestre__sala').first()
    sala_maestra = asignacion.sala_semestre.sala if asignacion else None

    # 2. LA MEMORIA: ¿La maestra forzó el cambio a otra sala en la URL?
    sala_id_ver = request.GET.get('sala')

    if sala_id_ver:
        if str(sala_id_ver).isdigit():
            sala_actual = get_object_or_404(Sala, id=sala_id_ver)
        else:
            sala_actual = get_object_or_404(Sala, nombre=sala_id_ver)
    else:
        sala_actual = sala_maestra

    # 3. Obtenemos TODOS los alumnos inscritos (FINALIZADA)
    todos_alumnos = SolicitudInscripcion.objects.filter(estado='FINALIZADA').select_related('solicitud_ingreso',
                                                                                            'sala_asignada').order_by(
        'solicitud_ingreso__apellido_paterno_menor')

    alumnos = []
    todas_las_salas = Sala.objects.all().order_by('nombre')

    # 4. Acomodamos a los niños (Solo los de la sala que se está viendo en pantalla)
    for alum in todos_alumnos:
        if sala_actual and alum.sala_asignada == sala_actual:
            alumnos.append(alum)

    return render(request, 'portal/dashboard_maestra.html', {
        'sala_maestra': sala_maestra,  # La sala oficial de la maestra (para saber si está cubriendo)
        'sala_actual': sala_actual,  # La sala que está viendo en la pantalla (L1, L2, etc.)
        'alumnos': alumnos,  # La lista de niños de ESA sala que está viendo
        'todas_las_salas': todas_las_salas,  # Para el menú del modal
    })


@login_required
def dashboard_coordinadora(request):
    b_lactantes = BitacoraLactante.objects.filter(estado='ENVIADO').order_by('fecha')
    b_maternales = BitacoraMaternal.objects.filter(estado='ENVIADO').order_by('fecha')

    lactantes_list = [('L1', b_lactantes.filter(alumno__sala_asignada__nombre='L1')),
                      ('L2', b_lactantes.filter(alumno__sala_asignada__nombre='L2')),
                      ('L3', b_lactantes.filter(alumno__sala_asignada__nombre='L3'))]
    maternales_list = [('M1', b_maternales.filter(alumno__sala_asignada__nombre='M1')),
                       ('M2', b_maternales.filter(alumno__sala_asignada__nombre='M2')),
                       ('M3', b_maternales.filter(alumno__sala_asignada__nombre='M3'))]

    return render(request, 'admisiones/coordinadora_de_salas.html',
                  {'lactantes_list': lactantes_list, 'maternales_list': maternales_list})


@login_required
def expediente_bitacoras(request, alumno_id):
    alumno = get_object_or_404(SolicitudInscripcion, id=alumno_id)
    # Obtenemos bitácoras ordenadas de la más nueva a la más vieja
    bit_l = BitacoraLactante.objects.filter(alumno=alumno).order_by('-fecha')
    bit_m = BitacoraMaternal.objects.filter(alumno=alumno).order_by('-fecha')

    hoy = timezone.now().date()

    return render(request, 'portal/expediente_bitacoras.html', {
        'alumno': alumno,
        'bitacoras_lactantes': bit_l,
        'bitacoras_maternales': bit_m,
        'hoy': hoy
    })


@login_required
def crear_bitacora(request, alumno_id):
    alumno = get_object_or_404(SolicitudInscripcion, id=alumno_id)
    sol = alumno.solicitud_ingreso
    hoy = timezone.now().date()

    sala_nombre = alumno.sala_asignada.nombre if alumno.sala_asignada else "L1"
    es_maternal = sala_nombre.upper().startswith('M')

    # 1. ¿Queremos ver una bitácora específica del historial?
    bitacora_id = request.GET.get('id')
    ModelBitacora = BitacoraMaternal if es_maternal else BitacoraLactante

    if bitacora_id:
        instance = get_object_or_404(ModelBitacora, id=bitacora_id, alumno=alumno)
    else:
        # Si no se pide una ID, buscamos si ya existe una de hoy para no duplicar
        instance = ModelBitacora.objects.filter(alumno=alumno, fecha=hoy).first()

    if request.method == 'POST':
        form = BitacoraMaternalForm(request.POST, instance=instance) if es_maternal else BitacoraLactanteForm(
            request.POST, instance=instance)
        if form.is_valid():
            bitacora = form.save(commit=False)
            bitacora.alumno = alumno
            # GUARDAMOS QUIÉN LA HIZO (Rastreo para la coordinadora)
            bitacora.maestra = request.user
            bitacora.fecha = instance.fecha if instance else hoy

            # Si estaba rechazada, al guardar vuelve a borrador para revisión
            if bitacora.estado == 'RECHAZADO':
                bitacora.estado = 'BORRADOR'

            datos_cuestionario = {}
            for field in form.fields:
                if field not in ['estado', 'comentarios_coordinadora'] and not field.endswith('_str'):
                    valor = form.cleaned_data.get(field)
                    if isinstance(valor, (datetime.date, datetime.time)): valor = str(valor)
                    datos_cuestionario[field] = valor

            bitacora.datos_json = datos_cuestionario
            bitacora.save()
            messages.success(request, f"Bitácora de {sol.nombres_menor} guardada correctamente.")
            return redirect('expediente_bitacoras', alumno_id=alumno.id)
    else:
        edad_str = f"{alumno.edad_anios_menor or 0} años, {alumno.edad_meses_menor or 0} meses"
        nombre_completo = f"{sol.nombres_menor} {sol.apellido_paterno_menor} {sol.apellido_materno_menor}"

        datos_iniciales = {
            'fecha_str': instance.fecha.strftime("%d / %m / %Y") if instance else hoy.strftime("%d / %m / %Y"),
            'nombre_completo_menor': nombre_completo,
            'sala_str': sala_nombre, 'edad_str': edad_str,
        }

        if instance:
            form = BitacoraMaternalForm(instance=instance) if es_maternal else BitacoraLactanteForm(instance=instance)
        else:
            form = BitacoraMaternalForm(initial=datos_iniciales) if es_maternal else BitacoraLactanteForm(
                initial=datos_iniciales)

    # Lógica de BLOQUEO: Solo editable si es de HOY o si la Coordinadora pidió corregir
    bloqueado = False
    if instance:
        if instance.estado in ['APROBADO', 'EN_DIRECTIVA']:
            bloqueado = True
        elif instance.fecha < hoy and instance.estado != 'RECHAZADO':
            bloqueado = True

    template_name = 'portal/form_bitacora_maternal.html' if es_maternal else 'portal/form_bitacora_lactante.html'
    return render(request, template_name, {
        'alumno': alumno,
        'form': form,
        'bloqueado': bloqueado,
        'bitacora': instance
    })


@login_required
def enviar_bitacora_coordinadora(request, bitacora_id, tipo):
    bitacora = get_object_or_404(BitacoraLactante if tipo == 'lactante' else BitacoraMaternal, id=bitacora_id)
    bitacora.estado = "ENVIADO"
    bitacora.save()
    messages.success(request, "Bitácora enviada a coordinación.")
    return redirect('expediente_bitacoras', alumno_id=bitacora.alumno.id)


@login_required
def aprobar_bitacora_coordinadora(request, bitacora_id, tipo):
    bitacora = get_object_or_404(BitacoraLactante if tipo == 'lactante' else BitacoraMaternal, id=bitacora_id)
    bitacora.estado = "APROBADO"
    bitacora.save()
    return redirect('dashboard_coordinadora')


@login_required
def corregir_bitacora_coordinadora(request, bitacora_id, tipo):
    bitacora = get_object_or_404(BitacoraLactante if tipo == 'lactante' else BitacoraMaternal, id=bitacora_id)
    if request.method == "POST":
        bitacora.estado = "RECHAZADO"
        bitacora.comentarios_coordinadora = request.POST.get("comentarios")
        bitacora.save()
    return redirect('dashboard_coordinadora')


@login_required
def enviar_bitacora_directora(request, bitacora_id, tipo):
    bitacora = get_object_or_404(BitacoraLactante if tipo == 'lactante' else BitacoraMaternal, id=bitacora_id)
    if bitacora.estado == "APROBADO":
        bitacora.estado = "EN_DIRECTIVA"
        bitacora.save()
    return redirect('expediente_bitacoras', alumno_id=bitacora.alumno.id)


@login_required
def descargar_pdf_bitacora(request, bitacora_id, tipo):
    bitacora = get_object_or_404(BitacoraLactante if tipo == 'lactante' else BitacoraMaternal, id=bitacora_id)
    sol = bitacora.alumno.solicitud_ingreso
    sala = bitacora.alumno.sala_asignada.nombre if getattr(bitacora.alumno, 'sala_asignada', None) else "SinSala"
    nombre_archivo = f"{sol.apellido_paterno_menor}_{sol.apellido_materno_menor}_{sol.nombres_menor.replace(' ', '_')}_{sala}.pdf"

    template = "portal/bitacora_lactante_pdf.html" if tipo == 'lactante' else "portal/bitacora_maternal_pdf.html"
    html = render_to_string(template, {"bitacora": bitacora, "sol": sol, "alumno": bitacora.alumno}, request=request)

    response = HttpResponse(content_type="application/pdf")
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    return response