from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.http import JsonResponse

from .models import AccessLog

# ✅ Solicitud (admisiones)
from admisiones.models import Solicitud


# --- DEFINIMOS LOS GRUPOS DE PODER ---
ROLES_ADMINISTRATIVOS = [
    'admin', 'jefa_superior', 'directora', 'administrativo'
]

ROLES_MEDICOS = [
    'medica', 'psicologa', 'nutriologa', 'trabajo_social'
]


# --- FUNCIÓN AUXILIAR PARA ENCRIPTAR DATOS VISUALMENTE ---
def enmascarar_datos(texto):
    if not texto or len(texto) < 4:
        return "****"
    return texto[:2] + "****" + texto[-2:]


# --- VISTA SEMÁFORO (ROUTER DE SEGURIDAD) ---
@login_required
def root_redirect_view(request):
    user = request.user

    # SEGURIDAD: MODO MANTENIMIENTO
    if request.session.get('sec_manto', False) and not user.is_superuser:
        return render(request, '403_prohibido.html',
                      {'mensaje': 'El sistema está en Mantenimiento. Intente más tarde.'})

    # ✅ Superusuario: va al panel TI
    if user.is_superuser:
        return redirect('panel_gobierno_ti')

    # ✅ Staff: va al panel administrativo
    if user.is_staff:
        return redirect('dashboard_admin')

    # ✅ Si existe campo rol (tu sistema viejo), respétalo
    rol = getattr(user, 'rol', None)
    if rol == 'tutor':
        return redirect('portal_padres_home')

    if rol in ROLES_MEDICOS:
        return redirect('dashboard_medico')

    # Fallback seguro
    return redirect('portal_padres_home')


# --- VISTAS PROTEGIDAS ---
@login_required
def dashboard_admin(request):
    # Si existe rol, valida. Si no existe, permite staff
    rol = getattr(request.user, 'rol', None)
    if rol is not None:
        if rol not in ROLES_ADMINISTRATIVOS:
            return render(request, '403_prohibido.html')
    else:
        if not request.user.is_staff:
            return render(request, '403_prohibido.html')

    return render(request, 'portal/panel_admin.html')


# --- PANEL DE ADMINISTRACIÓN (ADMIN TI / GESTIÓN CENTRAL) ---
@login_required
def panel_gobierno_ti(request):
    User = get_user_model()

    # =========================================================
    # 1. SEGURIDAD DE PANTALLA POR ROL (CANDADO PRINCIPAL)
    # =========================================================
    roles_permitidos = ['ADMIN', 'SUPERVISOR', 'PERSONAL']
    if getattr(request.user, 'tipo_persona', None) not in roles_permitidos:
        return render(request, '403_prohibido.html', {
            'mensaje': 'ACCESO DENEGADO: Tu rol no tiene permisos para visualizar esta pantalla.'
        })

    # =========================================================
    # 2. SEGURIDAD EXTRA: FIREWALL ANTI-CURIOSOS
    # =========================================================
    if getattr(request.user, 'tipo_persona', None) != 'ADMIN':
        if request.session.get('sec_firewall', False):
            return render(request, '403_prohibido.html', {
                'mensaje': 'ALERTA DE SEGURIDAD: El Firewall interno está activo. Solo Administración de Sistema puede ingresar.'
            })

    # Log de entrada inteligente (1 vez por sesión)
    if not request.session.get('ha_registrado_login', False):
        AccessLog.objects.create(usuario=request.user, accion="Ingreso al Panel de Administración TI")
        request.session['ha_registrado_login'] = True

    # --- PROCESAMIENTO DE ACCIONES (POST / AJAX) ---
    if request.method == 'POST':
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        accion = request.POST.get('action_type')
        response_data = {'status': 'success', 'msg': 'Acción realizada'}

        try:
            # 1. CREAR NUEVA PERSONA
            if accion == 'create_user':
                email = request.POST.get('email')
                password = request.POST.get('password')
                nombre = request.POST.get('nombre')
                apellido_paterno = request.POST.get('apellido_paterno')
                apellido_materno = request.POST.get('apellido_materno', '')
                curp = request.POST.get('curp', '').upper()
                tipo_persona = request.POST.get('tipo_persona')
                num_empleado = request.POST.get('numero_empleado')

                # VALIDACIONES
                if User.objects.filter(email=email).exists():
                    if is_ajax:
                        return JsonResponse({'status': 'error', 'msg': 'El CORREO electrónico ya está registrado en el sistema.'})

                if curp and User.objects.filter(curp=curp).exists():
                    if is_ajax:
                        return JsonResponse({'status': 'error', 'msg': f'La CURP {curp} ya está asignada a otra persona.'})

                if num_empleado and User.objects.filter(numero_empleado=num_empleado).exists():
                    if is_ajax:
                        return JsonResponse({'status': 'error', 'msg': f'El Número de Empleado {num_empleado} ya existe.'})

                # CREACIÓN
                u = User.objects.create_user(username=email, email=email, password=password)
                u.nombre = nombre
                u.apellido_paterno = apellido_paterno
                u.apellido_materno = apellido_materno
                u.curp = curp
                u.tipo_persona = tipo_persona
                u.numero_empleado = num_empleado

                # PERMISOS BASE
                if tipo_persona == 'ADMIN':
                    u.is_superuser = True
                    u.is_staff = True
                elif tipo_persona in ['SUPERVISOR', 'PERSONAL']:
                    u.is_superuser = False
                    u.is_staff = True

                u.save()

                # AUDITORÍA
                AccessLog.objects.create(
                    usuario=request.user,
                    accion=f"CREACIÓN PERSONA: Registró a {nombre} {apellido_paterno} [{tipo_persona}] con CURP {curp}"
                )

                response_data['msg'] = f'Persona {nombre} registrada exitosamente.'

            # 2. ELIMINAR USUARIO
            elif accion == 'delete_user':
                user_id = request.POST.get('user_id')
                if int(user_id) != request.user.id:
                    User.objects.filter(id=user_id).delete()
                    response_data['msg'] = 'Persona eliminada del sistema.'
                else:
                    if is_ajax:
                        return JsonResponse({'status': 'error', 'msg': 'Seguridad: No puedes auto-eliminarte.'})

            # 3. CREAR ROL SECUNDARIO
            elif accion == 'create_role':
                nombre_rol = request.POST.get('nombre_rol')
                es_master = request.POST.get('permiso_total')
                if nombre_rol:
                    nombre_final = f"[MASTER] {nombre_rol}" if es_master else nombre_rol
                    Group.objects.get_or_create(name=nombre_final)
                    response_data['msg'] = f'Rol secundario "{nombre_rol}" creado.'

            # 4. ELIMINAR ROL SECUNDARIO
            elif accion == 'delete_role':
                Group.objects.filter(id=request.POST.get('rol_id')).delete()
                response_data['msg'] = 'Rol eliminado.'

            # 5. SEGURIDAD: APLICAR PROTOCOLOS
            elif accion == 'toggle_security':
                request.session['sec_encrypt'] = True if request.POST.get('toggle_encrypt') else False
                request.session['sec_manto'] = True if request.POST.get('toggle_manto') else False
                request.session['sec_firewall'] = True if request.POST.get('toggle_firewall') else False
                request.session['sec_inscrip'] = True if request.POST.get('toggle_inscrip') else False
                response_data['msg'] = 'Protocolos de seguridad aplicados en el servidor.'

            # 6. LIMPIAR HISTORIAL
            elif accion == 'clear_history':
                AccessLog.objects.exclude(accion__startswith="REL_CONF:").exclude(
                    accion__startswith="MASTER_CONF:").delete()
                response_data['msg'] = 'Historial de auditoría depurado.'

            if is_ajax:
                return JsonResponse(response_data)

        except Exception as e:
            if is_ajax:
                return JsonResponse({'status': 'error', 'msg': str(e)})
            else:
                messages.error(request, f'Error del sistema: {e}')

        return redirect('panel_gobierno_ti')

    # --- PREPARACIÓN DE DATOS PARA LA VISTA ---
    staff_list = User.objects.filter(is_staff=True).order_by('-date_joined')

    if request.session.get('sec_encrypt', False):
        for s in staff_list:
            s.email = enmascarar_datos(s.email)

    logs_gen = AccessLog.objects.all().order_by('-fecha_acceso')[:50]

    context = {
        'lista_staff': staff_list,
        'roles': Group.objects.all(),
        'logs': logs_gen,

        'encrypt_active': request.session.get('sec_encrypt', True),
        'manto_active': request.session.get('sec_manto', False),
        'firewall_active': request.session.get('sec_firewall', False),
        'inscrip_active': request.session.get('sec_inscrip', False),
    }

    return render(request, 'portal/panel_ti.html', context)


@login_required
def dashboard_medico(request):
    # Si existe rol, valida. Si no existe, permite staff o acceso básico
    rol = getattr(request.user, 'rol', None)
    if rol is not None:
        if rol not in ROLES_MEDICOS and rol not in ROLES_ADMINISTRATIVOS:
            return render(request, '403_prohibido.html')

    return render(request, 'dashboard/home_medico.html')


@login_required
def portal_padres_home(request):
    # Si existe rol, valida tutor
    rol = getattr(request.user, 'rol', None)
    if rol is not None and rol != 'tutor':
        return render(request, '403_prohibido.html')

    # ✅ En lugar de token, usaremos una Solicitud (por ID)
    solicitud_activa = None

    # Si tu modelo Solicitud tiene FK al usuario, usa esto (recomendado):
    # solicitud_activa = Solicitud.objects.filter(tutor=request.user).order_by("-id").first()

    # Temporal: toma la última global
    solicitud_activa = Solicitud.objects.order_by("-id").first()

    # Si no hay ninguna solicitud aún, intenta crear una (si se puede)
    if not solicitud_activa:
        kwargs = {}
        if "estado" in [f.name for f in Solicitud._meta.fields]:
            kwargs["estado"] = "CAPTURA"

        try:
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
            'folio': folio
        }
    )


# --- VISTA DE INSCRIPCIÓN (con bloqueo + validación tutor si existe rol) ---
@login_required
def registro_inscripcion(request):
    # Bloqueo por configuración TI
    if request.session.get('sec_inscrip', False):
        return render(request, '403_prohibido.html',
                      {'mensaje': 'El periodo de inscripciones a la estancia está cerrado.'})

    rol = getattr(request.user, 'rol', None)
    if rol is not None and rol != 'tutor':
        return render(request, '403_prohibido.html')

    return render(request, 'portal/registro_inscripcion.html')
