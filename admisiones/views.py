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


# ===================== DESCARGAR PDF (CON SALVAVIDAS) =====================
@staff_member_required
def descargar_pdf_solicitud(request, solicitud_id):
    solicitud = get_object_or_404(Solicitud, id=solicitud_id)

    inscripcion = SolicitudInscripcion.objects.filter(solicitud_ingreso=solicitud).first()

    # 1. Si ya tiene expediente, generamos la Hoja de Inscripción nueva
    if inscripcion:
        pdf_path = generar_pdf_inscripcion_lleno(inscripcion)
        if pdf_path and os.path.exists(pdf_path):
            return FileResponse(open(pdf_path, "rb"), as_attachment=True,
                                filename=f"Hoja_Inscripcion_Folio_{solicitud.folio}.pdf")

    # 2. SALVAVIDAS: Si no tiene el PDF base generado, lo forzamos a crearse ahora mismo
    if not solicitud.pdf:
        try:
            from django.core.files import File
            pdf_path = generar_pdf_fo301(solicitud)
            if pdf_path and os.path.exists(pdf_path):
                with open(pdf_path, "rb") as f:
                    solicitud.pdf.save(f"FO301_{solicitud.folio}.pdf", File(f), save=True)
        except Exception as e:
            print("Fallo de emergencia al generar PDF:", e)

    # 3. Retornamos el PDF
    if solicitud.pdf:
        return FileResponse(solicitud.pdf.open("rb"), as_attachment=True,
                            filename=f"Solicitud_Basica_{solicitud.folio}.pdf")

    raise Http404("El archivo PDF no pudo generarse. Verifica que las plantillas Word existan y estén cerradas.")


def solicitud_publica_nueva(request):
    if request.method == "POST":
        kwargs = {"estado": "CAPTURA"} if "estado" in [f.name for f in Solicitud._meta.fields] else {}
        s = Solicitud.objects.create(**kwargs)
        return redirect("admisiones_captura", id=s.id)
    return render(request, "admisiones/publico_nuevo_ingreso.html")


# =========================================================
# VISTA DICTAMEN (CON LÓGICA DE PDF CORREGIDA Y CORREOS)
# =========================================================

@login_required
def revisar_solicitud(request, pk):
    s = get_object_or_404(Solicitud, pk=pk)

    # Buscamos la inscripción ligada al folio
    inscripcion = SolicitudInscripcion.objects.filter(solicitud_ingreso=s).first()

    if s.estado == Solicitud.Estado.CAPTURA:
        messages.warning(request, "Esta solicitud aún está en CAPTURA (no ha sido enviada).")
        return redirect("panel_admisiones")

    # --- LÓGICA: REVISIÓN DEL REGLAMENTO PDF (TRABAJO SOCIAL) ---
    if request.method == 'POST' and inscripcion:
        accion_inscripcion = request.POST.get('accion_inscripcion')
        comentario_inscripcion = request.POST.get('comentario_inscripcion', '').strip()

        # Si el PDF está mal y Trabajo Social lo devuelve
        if accion_inscripcion == 'DEVOLVER':
            if not comentario_inscripcion:
                messages.error(request, "Debes escribir el motivo de la devolución (ej. Falta firma en PDF).")
            else:
                inscripcion.estado = SolicitudInscripcion.EstadoInscripcion.EN_PROCESO
                inscripcion.observaciones = comentario_inscripcion
                inscripcion.comentario_tutor = ""  # Limpiamos la respuesta vieja del tutor
                inscripcion.save()

                # CORREO PERSONALIZADO CON LINK AL PANEL
                if s.correo:
                    url_portal = request.build_absolute_uri(reverse('portal_padres_home'))
                    cuerpo_correo = f"""Estimado(a) {s.nombres_tutor}:\n\nTrabajo Social ha revisado su expediente y requiere una corrección en su documentación.\n\nMotivo de la devolución:\n"{comentario_inscripcion}"\n\nPor favor, ingrese a su Panel Familiar para subir el documento corregido y continuar con su trámite:\n🔗 {url_portal}\n\nAtentamente,\nEstancia Infantil UNACH"""
                    try:
                        send_mail(
                            "ACCIÓN REQUERIDA: Corrección de Expediente UNACH",
                            cuerpo_correo,
                            getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@unach.mx"),
                            [s.correo],
                            fail_silently=True
                        )
                    except:
                        pass
                messages.success(request, "Expediente devuelto al tutor. Se envió un correo de notificación.")
                return redirect('revisar_solicitud', pk=pk)

        # Si el PDF está perfecto y firmado
        elif accion_inscripcion == 'APROBAR':
            inscripcion.estado = SolicitudInscripcion.EstadoInscripcion.EN_FILTROS
            inscripcion.observaciones = ""
            inscripcion.save()

            # CORREO DE ÉXITO AL PAPÁ
            if s.correo:
                url_portal = request.build_absolute_uri(reverse('portal_padres_home'))
                cuerpo_exito = f"""Estimado(a) {s.nombres_tutor}:\n\n¡Excelentes noticias! Su documentación ha sido validada correctamente por Trabajo Social.\nSu expediente ha pasado a la etapa de Filtros (Evaluación Médica, Nutricional y Psicológica).\n\nPuede monitorear su avance desde su Panel Familiar:\n🔗 {url_portal}\n\nAtentamente,\nEstancia Infantil UNACH"""
                try:
                    send_mail(
                        "✅ Expediente Validado - Estancia Infantil UNACH",
                        cuerpo_exito,
                        getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@unach.mx"),
                        [s.correo],
                        fail_silently=True
                    )
                except:
                    pass

            messages.success(request, "Documentación validada correctamente. El expediente pasa a la etapa de Filtros.")
            return redirect('revisar_solicitud', pk=pk)

    # Le mandamos 'inscripcion' al HTML para que sepa qué mostrar
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

        try:
            SolicitudInscripcion.objects.get_or_create(solicitud_ingreso=s, defaults={'usuario_tutor': usuario_final})
        except IntegrityError:
            messages.error(request, "¡Error! Este correo o usuario ya está en otro y ya tiene expediente.")
            s.estado = Solicitud.Estado.RECIBIDA
            s.save()
            return redirect("revisar_solicitud", pk=pk)

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
# PORTAL DE PADRES (WIZARD DE INSCRIPCIÓN) - ACTUALIZADO CON CHECKLIST
# =========================================================
@login_required
def portal_inscripcion(request):
    inscripcion = SolicitudInscripcion.objects.filter(usuario_tutor__email=request.user.email).first()

    if not inscripcion:
        messages.error(request, "Error interno: No tienes un proceso de inscripción activo.")
        return redirect(request.META.get('HTTP_REFERER', '/'))

    # --- LÓGICA DE BLOQUEO DE PANTALLA ---
    # Si Trabajo Social ya lo pasó a Filtros, el papá ya NO puede ver el formulario.
    if inscripcion.estado in [SolicitudInscripcion.EstadoInscripcion.EN_REVISION,
                              SolicitudInscripcion.EstadoInscripcion.EN_FILTROS,
                              SolicitudInscripcion.EstadoInscripcion.FINALIZADA]:
        messages.info(request,
                      "Usted ya ha completado este proceso o su expediente está en revisión. No puede realizar modificaciones.")
        return redirect('/')  # Lo rebota a su panel principal (home_padres.html)

    if request.method == 'POST':
        # --- GUARDAR TODOS LOS ARCHIVOS DEL EXPEDIENTE ---
        lista_archivos = [
            'doc_menor_certificado_medico', 'doc_menor_cartilla_vacunacion', 'doc_menor_grupo_sanguineo',
            'doc_menor_acta_nacimiento', 'doc_menor_fotos', 'doc_menor_laboratorio',
            'doc_tutor_acta_nacimiento', 'doc_tutor_ine', 'doc_tutor_fotos', 'doc_tutor_domicilio',
            'doc_tutor_pago', 'doc_tutor_historial', 'doc_tutor_horario',
            'doc_autorizado_carta', 'doc_autorizado_ine', 'doc_autorizado_fotos',
            'reglamento_firmado'
        ]

        for campo in lista_archivos:
            if campo in request.FILES:
                setattr(inscripcion, campo, request.FILES[campo])

        # --- GUARDAR TEXTOS ---
        comentario = request.POST.get('comentario_tutor', '').strip()
        if comentario:
            inscripcion.comentario_tutor = comentario

        inscripcion.avance_academico = request.POST.get('avance_academico')
        inscripcion.estado_civil_tutor = request.POST.get('estado_civil_tutor')
        inscripcion.parentesco_tutor = request.POST.get('parentesco_tutor')

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

        if request.POST.get('acepto_reglamentos') == 'on':
            inscripcion.acepto_reglamentos = True
            inscripcion.fecha_aceptacion = timezone.now()
        else:
            inscripcion.acepto_reglamentos = False

        # --- LÓGICA BLINDADA DE ENVÍO Y VALIDACIÓN DE ARCHIVOS ---
        if 'enviar_revision' in request.POST:
            if not inscripcion.acepto_reglamentos:
                messages.error(request, "DEBES aceptar el reglamento para poder enviar tu inscripción.")
                return redirect('portal_inscripcion')

            # --- VALIDACIÓN ESTRICTA: El sistema revisa si falta alguno de los 17 archivos ---
            faltantes = []
            if not inscripcion.doc_menor_certificado_medico: faltantes.append("Certificado Médico (Menor)")
            if not inscripcion.doc_menor_cartilla_vacunacion: faltantes.append("Cartilla de Vacunación")
            if not inscripcion.doc_menor_grupo_sanguineo: faltantes.append("Grupo Sanguíneo")
            if not inscripcion.doc_menor_acta_nacimiento: faltantes.append("Acta de Nacimiento (Menor)")
            if not inscripcion.doc_menor_fotos: faltantes.append("Fotos del Menor")
            if not inscripcion.doc_menor_laboratorio: faltantes.append("Estudios de Laboratorio")

            if not inscripcion.doc_tutor_acta_nacimiento: faltantes.append("Acta de Nacimiento (Tutor)")
            if not inscripcion.doc_tutor_ine: faltantes.append("INE (Tutor)")
            if not inscripcion.doc_tutor_fotos: faltantes.append("Fotos del Tutor")
            if not inscripcion.doc_tutor_domicilio: faltantes.append("Comprobante de Domicilio")
            if not inscripcion.doc_tutor_pago: faltantes.append("Comprobante de Pago")
            if not inscripcion.doc_tutor_historial: faltantes.append("Historial Académico")
            if not inscripcion.doc_tutor_horario: faltantes.append("Horario de Clases")

            if not inscripcion.doc_autorizado_carta: faltantes.append("Carta de Autorización")
            if not inscripcion.doc_autorizado_ine: faltantes.append("INE Autorizado")
            if not inscripcion.doc_autorizado_fotos: faltantes.append("Fotos Autorizado")

            if not inscripcion.reglamento_firmado: faltantes.append("Reglamento Firmado")

            if faltantes:
                # Si falta algo, no lo deja enviar
                lista_errores = ", ".join(faltantes)
                messages.error(request,
                               f"¡ERROR! No puedes enviar el expediente. Faltan estos documentos: {lista_errores}")
                return redirect('portal_inscripcion')

            inscripcion.estado = SolicitudInscripcion.EstadoInscripcion.EN_REVISION
            inscripcion.observaciones = None
            messages.success(request, "¡Expediente reenviado con éxito! Trabajo Social ya lo tiene en su bandeja.")
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
    if (
            sol.estado_psicologia == Solicitud.EstadoEvaluacion.RECHAZADO
            or sol.estado_nutricion == Solicitud.EstadoEvaluacion.RECHAZADO
            or sol.estado_medico == Solicitud.EstadoEvaluacion.RECHAZADO
    ):
        sol.estado = Solicitud.Estado.RECHAZADA
        sol.save(update_fields=["estado"])
        return

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


# ===================== NUTRICIÓN =====================
@login_required
def nutricion_pendientes(request):
    qs = Solicitud.objects.filter(
        estado=Solicitud.Estado.RECIBIDA,
        estado_nutricion=Solicitud.EstadoEvaluacion.PENDIENTE
    ).order_by("-created_at")
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
            actualizar_estado_final(sol)
            return redirect("nutricion_pendientes")
    else:
        form = DictamenNutricionForm(instance=sol)

    return render(request, "admisiones/nutricion_dictaminar.html", {"sol": sol, "form": form})


# ===================== MÉDICO =====================
@login_required
def medico_pendientes(request):
    qs = Solicitud.objects.filter(
        estado=Solicitud.Estado.APROBADA,
        estado_medico=Solicitud.EstadoEvaluacion.PENDIENTE
    ).order_by("-created_at")
    return render(request, "admisiones/medico_pendientes.html", {"solicitudes": qs})


@login_required
def medico_dictaminar(request, pk):
    sol = get_object_or_404(Solicitud, pk=pk)

    bloqueado = sol.estado_medico in [
        Solicitud.EstadoEvaluacion.APROBADO,
        Solicitud.EstadoEvaluacion.RECHAZADO,
    ]

    if request.method == "POST":
        if bloqueado:
            messages.warning(request, "Esta evaluación médica ya fue finalizada y no puede modificarse.")
            return redirect("medico_dictaminar", pk=sol.pk)

        form = DictamenMedicoForm(request.POST, request.FILES, instance=sol)
        if form.is_valid():
            sol = form.save(commit=False)
            sol.medico_por = request.user
            sol.medico_en = timezone.now()
            sol.save()
            actualizar_estado_final(sol)
            messages.success(request, "Dictamen médico guardado correctamente.")
            return redirect("medico_pendientes")
    else:
        form = DictamenMedicoForm(instance=sol)

    return render(request, "admisiones/medico_dictaminar.html", {
        "sol": sol,
        "form": form,
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


# =========================================================
# VISTA: VEREDICTO FINAL DE LA DIRECTORA (ÉPICA 2 - FIN)
# =========================================================
@login_required
def veredicto_final_directora(request, inscripcion_id):
    if request.method == 'POST':
        # Verificamos que solo staff (directiva) pueda hacer esto
        if not request.user.is_staff:
            return HttpResponseForbidden("No tienes permisos para dictaminar.")

        inscripcion = get_object_or_404(SolicitudInscripcion, id=inscripcion_id)
        accion = request.POST.get('accion')
        s = inscripcion.solicitud_ingreso

        if accion == 'ACEPTAR':
            # Cambiamos el estado oficial a FINALIZADA (Aceptado en la Estancia)
            inscripcion.estado = SolicitudInscripcion.EstadoInscripcion.FINALIZADA
            inscripcion.save()

            # Generamos el correo de Bienvenida Oficial
            if s.correo:
                asunto = "¡Felicidades! Admisión Aprobada - Estancia Infantil UNACH"
                cuerpo = f"""Estimado(a) {s.nombres_tutor}:\n\nNos complace informarle que después de revisar sus evaluaciones médicas, nutricionales y psicológicas, su hijo(a) {s.nombres_menor} ha sido ACEPTADO(A) OFICIALMENTE en la Estancia Infantil UNACH.\n\nEn breve se le informará sobre su sala asignada y la fecha de la junta de inicio de semestre.\n\nAtentamente,\nDirección General"""

                try:
                    email = EmailMessage(asunto, cuerpo, getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@unach.mx"),
                                         [s.correo])
                    email.send(fail_silently=True)
                except Exception as e:
                    print("Error al enviar correo de aceptación:", e)

            messages.success(request, f"¡Éxito! El aspirante {s.nombres_menor} ha sido ACEPTADO oficialmente.")

        elif accion == 'RECHAZAR':
            # Cambiamos el estado oficial a RECHAZADA
            inscripcion.estado = SolicitudInscripcion.EstadoInscripcion.RECHAZADA
            inscripcion.save()

            if s.correo:
                asunto = "Resultado de Admisión - Estancia Infantil UNACH"
                cuerpo = f"""Estimado(a) {s.nombres_tutor}:\n\nLe informamos que el proceso de revisión ha concluido. Lamentablemente, por motivos de cupo o dictámenes de los especialistas, no nos es posible aceptar su solicitud de ingreso en este ciclo escolar.\n\nAgradecemos su interés en la Estancia Infantil UNACH.\n\nAtentamente,\nDirección General"""
                try:
                    send_mail(asunto, cuerpo, getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@unach.mx"), [s.correo],
                              fail_silently=True)
                except:
                    pass

            messages.error(request, f"La solicitud de {s.nombres_menor} ha sido RECHAZADA. Se envió correo al tutor.")

    return redirect('dashboard_directiva')