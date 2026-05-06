import io
import os
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.models import Group
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.template.loader import get_template

# --- IMPORTACIÓN MAESTRA PARA ENCONTRAR LOS LOGOS ---
from django.contrib.staticfiles import finders

try:
    from xhtml2pdf import pisa
except ImportError:
    pisa = None

from .models import AccessLog, AsignacionRolCiclo

try:
    # IMPORTANTE: Importamos todos los modelos necesarios de admisiones
    from admisiones.models import (
        Solicitud, SolicitudInscripcion, Semestre, AsignacionMaestra,
        Sala, SalaSemestre, MensajeDirectora, Incidencia
    )
except ImportError:
    pass


def enmascarar_datos(texto):
    if not texto or len(texto) < 4:
        return "****"
    return texto[:2] + "****" + texto[-2:]


@login_required
def root_redirect_view(request):
    user = request.user

    if user.is_superuser or getattr(user, 'tipo_persona', '') == 'ADMIN':
        return redirect('panel_gobierno_ti')

    if request.session.get('sec_manto', False):
        logout(request)
        messages.error(request, 'El sistema está en Mantenimiento. Intente más tarde.')
        return redirect('login')

    if getattr(user, 'tipo_persona', '') == 'BENEFICIARIO':
        return redirect('portal_padres_home')

    if user.is_staff:
        grupo = user.groups.first().name.strip().lower() if user.groups.exists() else ""
        if "directora" in grupo: return redirect('dashboard_directiva')
        if "trabajadora social" in grupo: return redirect('dashboard_admin')
        if "coordinadora" in grupo: return redirect('dashboard_coordinadora')
        if "psicóloga" in grupo or "psicologa" in grupo: return redirect('psicologia_pendientes')
        if "nutrióloga" in grupo or "nutriologa" in grupo: return redirect('nutricion_pendientes')
        if "médico" in grupo or "medico" in grupo: return redirect('medico_pendientes')
        if "asistente" in grupo or "maestra" in grupo: return redirect('dashboard_maestra')

        logout(request)
        messages.error(request,
                       "Acceso Denegado: Su usuario no tiene un rol oficial asignado. Contacte al Administrador.")
        return redirect('login')

    logout(request)
    messages.error(request, "Error de rol de usuario.")
    return redirect('login')


# =======================================================
# DASHBOARD DE LA DIRECTIVA (CORREGIDO PARA MOSTRAR DATOS)
# =======================================================
@login_required
def dashboard_directiva(request):
    user = request.user
    grupo = user.groups.first().name.strip().lower() if user.groups.exists() else ""

    # Verificamos que sea Directora o Admin
    if getattr(user, 'tipo_persona', '') != 'ADMIN' and "directora" not in grupo and "secretario" not in grupo:
        logout(request)
        messages.error(request, 'Acceso denegado. Área exclusiva de Dirección.')
        return redirect('login')

    # 1. Filtramos los que están esperando la firma de la directora (Veredicto Final)
    dictamenes_pendientes = SolicitudInscripcion.objects.filter(estado='ESPERANDO_DIRECTORA').order_by('-updated_at')

    # 2. Filtramos las salas que Trabajo Social le mandó para autorizar (Ping-Pong)
    salas_en_revision = SolicitudInscripcion.objects.filter(estado='SALA_EN_REVISION').order_by('-updated_at')

    # 3. Expedientes que aún están en las áreas (Médico, Psico, Nutri)
    expedientes_en_filtros = SolicitudInscripcion.objects.filter(estado='FILTROS')

    context = {
        'dictamenes_pendientes': dictamenes_pendientes,
        'salas_en_revision': salas_en_revision,
        'expedientes_en_filtros': expedientes_en_filtros,
        'kpi_alumnos': SolicitudInscripcion.objects.filter(estado='FINALIZADA').count(),
        'kpi_pendientes': dictamenes_pendientes.count(),
        'kpi_riesgo': Incidencia.objects.filter(nivel='ALTO', resuelta=False).count(),
        'kpi_salas': Sala.objects.count(),
        'mensajes_aspirantes': MensajeDirectora.objects.filter(es_alumno_inscrito=False, leido=False).order_by(
            '-fecha_envio'),
        'mensajes_alumnos': MensajeDirectora.objects.filter(es_alumno_inscrito=True, leido=False).order_by(
            '-fecha_envio'),
        'incidencias_alto': Incidencia.objects.filter(nivel='ALTO', resuelta=False).order_by('-fecha_reporte'),
        'incidencias_bajo': Incidencia.objects.filter(nivel='BAJO', resuelta=False).order_by('-fecha_reporte'),
    }

    # Mandamos al HTML que tiene la tabla
    return render(request, 'portal/home_directiva.html', context)


# =======================================================
# ACCIONES DE LA DIRECTIVA (BOTONES DE FIRMA Y SALAS)
# =======================================================
@login_required
def veredicto_final_directora(request, inscripcion_id):
    insc = get_object_or_404(SolicitudInscripcion, id=inscripcion_id)
    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'ACEPTAR':
            insc.estado = "ESPERANDO_SALA"
            messages.success(request, "Alumno aceptado. Se ha notificado a Trabajo Social para proponer sala.")
        elif accion == 'RECHAZAR':
            insc.estado = "RECHAZADA"
            messages.error(request, "El alumno ha sido rechazado.")
        elif accion == 'PENDIENTE':
            insc.estado = "ESPERANDO_DIRECTORA"

        insc.directora_por = request.user
        insc.directora_en = timezone.now()
        insc.save()
    return redirect('dashboard_directiva')


@login_required
def dictaminar_sala_directora(request, inscripcion_id):
    insc = get_object_or_404(SolicitudInscripcion, id=inscripcion_id)
    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'APROBAR':
            insc.estado = 'SALA_APROBADA'
            insc.motivo_rechazo_sala = ""
            messages.success(request, f"Sala {insc.sala_asignada.nombre} aprobada.")
        elif accion == 'RECHAZAR':
            insc.estado = 'SALA_RECHAZADA'
            insc.motivo_rechazo_sala = request.POST.get('motivo_rechazo')
            messages.warning(request, "Has rechazado la sala propuesta.")
        insc.save()
    return redirect('dashboard_directiva')


@login_required
def dashboard_admin(request):
    grupo = request.user.groups.first().name.strip().lower() if request.user.groups.exists() else ""
    if not request.user.is_staff or "trabajadora social" not in grupo:
        logout(request)
        messages.error(request, 'Acceso denegado. Área exclusiva de Trabajo Social.')
        return redirect('login')
    return render(request, 'portal/panel_admin.html')


@login_required
def dashboard_medico(request):
    grupo = request.user.groups.first().name.strip().lower() if request.user.groups.exists() else ""
    if not request.user.is_staff or ("médico" not in grupo and "medico" not in grupo):
        logout(request)
        messages.error(request, 'Acceso denegado. Área exclusiva del personal Médico.')
        return redirect('login')
    return render(request, 'dashboard/home_medico.html')


@login_required
def panel_gobierno_ti(request):
    User = get_user_model()

    if getattr(request.user, 'tipo_persona', None) != 'ADMIN':
        logout(request)
        messages.error(request, 'ACCESO DENEGADO. No eres el Administrador del Sistema.')
        return redirect('login')

    if request.method == 'POST':
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        accion = request.POST.get('action_type')
        response_data = {'status': 'success', 'msg': 'Acción realizada'}

        try:
            if accion == 'create_user':
                email = request.POST.get('email', '').strip().lower()
                password = request.POST.get('password')
                nombre = request.POST.get('nombre', '').strip()
                apellido_paterno = request.POST.get('apellido_paterno', '').strip()
                apellido_materno = request.POST.get('apellido_materno', '').strip()
                curp = request.POST.get('curp', '').strip().upper()

                tipo_persona = request.POST.get('tipo_persona') or 'PERSONAL'
                num_empleado = request.POST.get('numero_empleado', '').strip()

                if User.objects.filter(email=email).exists() or User.objects.filter(username=email).exists():
                    if is_ajax: return JsonResponse(
                        {'status': 'error', 'msg': f'El correo "{email}" ya existe en el sistema.'})

                if curp and User.objects.filter(curp=curp).exists():
                    if is_ajax: return JsonResponse(
                        {'status': 'error', 'msg': f'La CURP "{curp}" ya está registrada con otro usuario.'})

                u = User.objects.create_user(username=email, email=email, password=password)
                u.nombre, u.apellido_paterno, u.apellido_materno = nombre, apellido_paterno, apellido_materno
                u.curp, u.tipo_persona, u.numero_empleado = curp, tipo_persona, num_empleado
                u.estatus_operativo, u.is_active, u.is_staff = True, True, True

                if tipo_persona == 'ADMIN': u.is_superuser = True
                u.save()

                AccessLog.objects.create(usuario=request.user, accion=f"CREACIÓN: Registró a {nombre} [{tipo_persona}]")
                response_data['msg'] = f'Persona {nombre} registrada exitosamente.'

            elif accion == 'edit_user':
                user_id = request.POST.get('user_id')
                usr_edit = User.objects.get(id=user_id)
                usr_edit.nombre = request.POST.get('nombre')
                usr_edit.apellido_paterno = request.POST.get('apellido_paterno')
                usr_edit.curp = request.POST.get('curp', '').upper()
                usr_edit.save()
                response_data['msg'] = 'Información actualizada correctamente.'

            elif accion == 'delete_user':
                user_id = request.POST.get('user_id')
                if int(user_id) != request.user.id:
                    User.objects.filter(id=user_id).delete()
                    response_data['msg'] = 'Persona eliminada del sistema.'

            elif accion == 'assign_fixed_role':
                usuario_id = request.POST.get('usuario_id')
                rol_fijo = request.POST.get('rol_fijo')
                semestre_id = request.POST.get('semestre_id')

                # --- DATOS PARA MAESTRAS ---
                sala_nombre = request.POST.get('sala_asignada')

                empleado = User.objects.get(id=usuario_id)
                grupo, _ = Group.objects.get_or_create(name=rol_fijo)

                if semestre_id:
                    ciclo = Semestre.objects.get(id=semestre_id)
                    AsignacionRolCiclo.objects.update_or_create(
                        usuario=empleado, semestre=ciclo, defaults={'rol': grupo}
                    )

                    # --- ESTA LÓGICA ESTÁ ADAPTADA A TU BASE DE DATOS EXACTA ---
                    if sala_nombre and ("asistente" in rol_fijo.lower() or "maestra" in rol_fijo.lower()):
                        # 1. Obtenemos o creamos la Sala Básica (Ej. L1)
                        sala_obj, _ = Sala.objects.get_or_create(nombre=sala_nombre)

                        # 2. Obtenemos o creamos el grupo Sala-Semestre
                        sala_semestre_obj, _ = SalaSemestre.objects.get_or_create(sala=sala_obj, semestre=ciclo)

                        # 3. Asignamos la maestra a ese grupo específico
                        AsignacionMaestra.objects.update_or_create(
                            maestra=empleado,
                            defaults={'sala_semestre': sala_semestre_obj}
                        )

                empleado.groups.clear()
                empleado.groups.add(grupo)
                AccessLog.objects.create(usuario=request.user, accion=f"ASIGNÓ ROL: '{rol_fijo}' a {empleado.nombre}")
                response_data['msg'] = f'Rol y Sala ({sala_nombre or "N/A"}) vinculados correctamente.'

            elif accion == 'remove_fixed_role':
                usuario_id = request.POST.get('usuario_id')
                empleado = User.objects.get(id=usuario_id)
                empleado.groups.clear()
                AsignacionMaestra.objects.filter(maestra=empleado).delete()
                response_data['msg'] = f'Roles removidos.'

            elif accion == 'abandon_admin':
                sucesor_id = request.POST.get('sucesor_id')
                sucesor = User.objects.get(id=sucesor_id)
                yo = request.user
                sucesor.is_superuser = True
                sucesor.tipo_persona = 'ADMIN'
                sucesor.save()
                yo.is_superuser = False
                yo.tipo_persona = 'PERSONAL'
                yo.save()
                AccessLog.objects.create(usuario=yo, accion=f"CEDER MANDO: {sucesor.nombre} es el nuevo Administrador.")
                response_data[
                    'msg'] = 'Has cedido la Administración. Tus permisos se han revocado, tu sesión seguirá abierta hasta que salgas manualmente.'

            elif accion == 'start_cycle':
                nombre = request.POST.get('nombre_semestre')
                inicio = request.POST.get('fecha_inicio')
                fin = request.POST.get('fecha_fin')
                Semestre.objects.filter(estado__in=['ACTIVO', 'CONFIGURACION']).update(estado='CERRADO')
                nuevo = Semestre.objects.create(nombre=nombre, estado='ACTIVO', fecha_inicio=inicio, fecha_fin=fin)
                AccessLog.objects.create(usuario=request.user, accion=f"Inició semestre: {nuevo.nombre}")
                response_data['msg'] = f'¡Semestre {nuevo.nombre} iniciado!'

            elif accion == 'end_cycle':
                Semestre.objects.filter(estado__in=['ACTIVO', 'CONFIGURACION']).update(estado='CERRADO')
                response_data['msg'] = 'Semestre cerrado.'

            elif accion == 'toggle_security':
                request.session['sec_encrypt'] = True if request.POST.get('toggle_encrypt') else False
                response_data['msg'] = 'Protocolos de seguridad aplicados.'

            elif accion == 'clear_history':
                AccessLog.objects.all().delete()
                response_data['msg'] = 'Historial depurado.'

            if is_ajax: return JsonResponse(response_data)

        except Exception as e:
            if is_ajax: return JsonResponse({'status': 'error', 'msg': str(e)})

        return redirect('panel_gobierno_ti')

    staff_list = User.objects.exclude(tipo_persona='BENEFICIARIO').order_by('-date_joined')

    context = {
        'lista_staff': staff_list,
        'ciclos_historial': Semestre.objects.all().order_by('-fecha_inicio'),
        'logs': AccessLog.objects.all().order_by('-fecha_acceso')[:50],
        'encrypt_active': request.session.get('sec_encrypt', True),
    }
    return render(request, 'portal/panel_ti.html', context)


# ==============================================================
# DESCARGA DE EXPEDIENTES EN PDF CON DOS LOGOS (CORREGIDO)
# ==============================================================
@login_required
def descargar_reporte_ciclo_pdf(request, ciclo_id):
    if getattr(request.user, 'tipo_persona', None) != 'ADMIN':
        logout(request)
        messages.error(request, 'ACCESO DENEGADO. No tienes permisos para descargar reportes.')
        return redirect('login')

    try:
        ciclo = get_object_or_404(Semestre, id=ciclo_id)
        asignaciones = AsignacionRolCiclo.objects.filter(semestre=ciclo)

        ruta_unach = finders.find('img/logo_unach.png')
        ruta_eiu = finders.find('img/logo_eiu.png')

        if ruta_unach: ruta_unach = ruta_unach.replace('\\', '/')
        if ruta_eiu: ruta_eiu = ruta_eiu.replace('\\', '/')

        context = {
            'ciclo': ciclo,
            'asignaciones': asignaciones,
            'fecha_reporte': timezone.now(),
            'ruta_logo_unach': ruta_unach,
            'ruta_logo_eiu': ruta_eiu
        }

        if not pisa:
            return HttpResponse('Error: Instale xhtml2pdf (pip install xhtml2pdf)', status=500)

        template = get_template('portal/reporte_ciclo_pdf.html')
        html = template.render(context)
        response = HttpResponse(content_type='application/pdf')

        meses = {1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril', 5: 'mayo', 6: 'junio', 7: 'julio', 8: 'agosto',
                 9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre'}

        if ciclo.fecha_inicio and ciclo.fecha_fin:
            mes_inicio = meses[ciclo.fecha_inicio.month]
            mes_fin = meses[ciclo.fecha_fin.month]
            anio = ciclo.fecha_inicio.year
            nombre_archivo = f"ciclo_escolar_{mes_inicio}_a_{mes_fin}_{anio}.pdf"
        else:
            nombre_archivo = f"ciclo_escolar_{ciclo.nombre.replace(' ', '_').lower()}.pdf"

        response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
        pisa_status = pisa.CreatePDF(io.BytesIO(html.encode('UTF-8')), dest=response)

        if pisa_status.err:
            return HttpResponse('Hubo un error al generar el PDF.', status=500)
        return response

    except Exception as e:
        messages.error(request, f"Error al generar reporte: {e}")
        return redirect('panel_gobierno_ti')


@login_required
def portal_padres_home(request):
    solicitud_activa = None
    ciclo_activo = False

    try:
        if Semestre.objects.filter(estado='ACTIVO').exists():
            ciclo_activo = True

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

    return render(request, 'portal/home_padres.html', {
        'solicitud_id': solicitud_id,
        'folio': folio,
        'ciclo_activo': ciclo_activo
    })


def registro_inscripcion(request):
    return render(request, 'portal/registro_inscripcion.html')