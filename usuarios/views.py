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
    from admisiones.models import Solicitud, SolicitudInscripcion, Semestre
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
        if "coordinadora de sala" in grupo: return redirect('lista_semestres')
        if "psicóloga" in grupo or "psicologa" in grupo: return redirect('psicologia_pendientes')
        if "nutrióloga" in grupo or "nutriologa" in grupo: return redirect('nutricion_pendientes')
        if "médico" in grupo or "medico" in grupo: return redirect('medico_pendientes')
        if "asistentes" in grupo or "maestras" in grupo: return redirect('lista_semestres')

        logout(request)
        messages.error(request,
                       "Acceso Denegado: Su usuario no tiene un rol oficial asignado. Contacte al Administrador.")
        return redirect('login')

    logout(request)
    messages.error(request, "Error de rol de usuario.")
    return redirect('login')


@login_required
def dashboard_directiva(request):
    grupo = request.user.groups.first().name.strip().lower() if request.user.groups.exists() else ""
    if not request.user.is_staff or "directora" not in grupo:
        logout(request)
        messages.error(request, 'Acceso denegado. Área exclusiva de Dirección.')
        return redirect('login')
    return render(request, 'portal/home_directiva.html', {})


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
            # ==============================================================
            # BLOQUE CORREGIDO: CREACIÓN DE USUARIO (BLINDADO CONTRA VALORES NULL)
            # ==============================================================
            if accion == 'create_user':
                email = request.POST.get('email', '').strip().lower()
                password = request.POST.get('password')
                nombre = request.POST.get('nombre', '').strip()
                apellido_paterno = request.POST.get('apellido_paterno', '').strip()
                apellido_materno = request.POST.get('apellido_materno', '').strip()
                curp = request.POST.get('curp', '').strip().upper()

                # BLINDAJE CONTRA NULL: Si viene vacío, asigna PERSONAL por defecto
                tipo_persona = request.POST.get('tipo_persona')
                if not tipo_persona:
                    tipo_persona = 'PERSONAL'

                num_empleado = request.POST.get('numero_empleado', '').strip()

                if User.objects.filter(email=email).exists() or User.objects.filter(username=email).exists():
                    if is_ajax: return JsonResponse(
                        {'status': 'error', 'msg': f'El correo "{email}" ya existe en el sistema.'})

                if curp and User.objects.filter(curp=curp).exists():
                    if is_ajax: return JsonResponse(
                        {'status': 'error', 'msg': f'La CURP "{curp}" ya está registrada con otro usuario.'})

                u = User.objects.create_user(username=email, email=email, password=password)
                u.nombre = nombre
                u.apellido_paterno = apellido_paterno
                u.apellido_materno = apellido_materno
                u.curp = curp
                u.tipo_persona = tipo_persona
                u.numero_empleado = num_empleado
                u.estatus_operativo = True
                u.is_active = True

                if tipo_persona == 'ADMIN':
                    u.is_superuser = True
                    u.is_staff = True
                else:
                    u.is_superuser = False
                    u.is_staff = True

                u.save()

                AccessLog.objects.create(usuario=request.user, accion=f"CREACIÓN: Registró a {nombre} [{tipo_persona}]")
                response_data['msg'] = f'Persona {nombre} registrada exitosamente.'

            elif accion == 'edit_user':
                user_id = request.POST.get('user_id')
                usr_edit = User.objects.get(id=user_id)
                email = request.POST.get('email')

                usr_edit.nombre = request.POST.get('nombre')
                usr_edit.apellido_paterno = request.POST.get('apellido_paterno')
                usr_edit.apellido_materno = request.POST.get('apellido_materno', '')
                usr_edit.curp = request.POST.get('curp', '').upper()
                usr_edit.numero_empleado = request.POST.get('numero_empleado')
                usr_edit.email = email
                usr_edit.username = email
                usr_edit.tipo_persona = request.POST.get('tipo_persona')

                estatus = (request.POST.get('estatus_operativo') == 'true')
                usr_edit.estatus_operativo = estatus
                usr_edit.is_active = estatus

                nueva_pass = request.POST.get('password')
                if nueva_pass:
                    usr_edit.set_password(nueva_pass)
                usr_edit.save()

                AccessLog.objects.create(usuario=request.user, accion=f"EDICIÓN: Actualizó a {usr_edit.nombre}")
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

                empleado = User.objects.get(id=usuario_id)
                grupo, _ = Group.objects.get_or_create(name=rol_fijo)

                if empleado.groups.filter(id=grupo.id).exists():
                    if is_ajax: return JsonResponse(
                        {'status': 'error', 'msg': f'El empleado {empleado.nombre} ya tiene el rol de {rol_fijo}.'})

                if semestre_id:
                    ciclo = Semestre.objects.get(id=semestre_id)
                    AsignacionRolCiclo.objects.update_or_create(
                        usuario=empleado, semestre=ciclo, defaults={'rol': grupo}
                    )

                empleado.groups.clear()
                empleado.groups.add(grupo)
                AccessLog.objects.create(usuario=request.user, accion=f"ASIGNÓ ROL: '{rol_fijo}' a {empleado.nombre}")
                response_data['msg'] = f'Rol asignado correctamente.'

            elif accion == 'remove_fixed_role':
                usuario_id = request.POST.get('usuario_id')
                empleado = User.objects.get(id=usuario_id)
                empleado.groups.clear()
                AccessLog.objects.create(usuario=request.user, accion=f"Removió roles a {empleado.nombre}")
                response_data['msg'] = f'Roles removidos a {empleado.nombre}.'

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
                nombre = request.POST.get('nombre_ciclo')
                inicio = request.POST.get('fecha_inicio')
                fin = request.POST.get('fecha_fin')
                Semestre.objects.filter(estado__in=['ACTIVO', 'CONFIGURACION']).update(estado='CERRADO')
                nuevo = Semestre.objects.create(nombre=nombre, estado='ACTIVO', fecha_inicio=inicio, fecha_fin=fin)
                AccessLog.objects.create(usuario=request.user, accion=f"Inició ciclo: {nuevo.nombre}")
                response_data['msg'] = f'¡Ciclo {nuevo.nombre} iniciado!'

            elif accion == 'end_cycle':
                Semestre.objects.filter(estado__in=['ACTIVO', 'CONFIGURACION']).update(estado='CERRADO')
                response_data['msg'] = 'Ciclo cerrado.'

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

    staff_list = User.objects.filter(is_staff=True).order_by('-date_joined')
    ciclos = []
    try:
        ciclos = Semestre.objects.all().order_by('-fecha_inicio')
    except:
        pass

    context = {
        'lista_staff': staff_list,
        'ciclos_historial': ciclos,
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

        # EL TRUCO MAESTRO: finders busca la ruta física exacta en todo tu proyecto
        ruta_unach = finders.find('img/logo_unach.png')
        ruta_eiu = finders.find('img/logo_eiu.png')

        # Protegemos contra errores de lectura en Windows reemplazando barras invertidas
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

        # --- MAGIA DEL AUTONOMBRADO ---
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

    return render(
        request,
        'portal/home_padres.html',
        {
            'solicitud_id': solicitud_id,
            'folio': folio,
            'ciclo_activo': ciclo_activo
        }
    )


def registro_inscripcion(request):
    return render(request, 'portal/registro_inscripcion.html')