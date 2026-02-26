from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.http import JsonResponse

from .models import AccessLog, RelacionDepartamentos

# ✅ Solicitud (admisiones)
try:
    from admisiones.models import Solicitud
except ImportError:
    pass


# --- FUNCIÓN AUXILIAR PARA ENCRIPTAR DATOS VISUALMENTE ---
def enmascarar_datos(texto):
    if not texto or len(texto) < 4:
        return "****"
    return texto[:2] + "****" + texto[-2:]


# --- VISTA SEMÁFORO (ROUTER DE SEGURIDAD LIMPIO) ---
@login_required
def root_redirect_view(request):
    user = request.user

    # SEGURIDAD: MODO MANTENIMIENTO
    if request.session.get('sec_manto', False) and not user.is_superuser:
        return render(request, '403_prohibido.html',
                      {'mensaje': 'El sistema está en Mantenimiento. Intente más tarde.'})

    # ✅ Superusuario (TI): va al panel de Gobierno TI
    if user.is_superuser:
        return redirect('panel_gobierno_ti')

    # ✅ Personal Interno (Staff): va al panel administrativo
    elif user.is_staff:
        return redirect('dashboard_admin')

    # ✅ Beneficiarios / Alumnos (Padres de familia): van al portal público
    else:
        return redirect('portal_padres_home')


# --- VISTAS PROTEGIDAS ---
@login_required
def dashboard_admin(request):
    # Solo el personal interno (is_staff) puede ver esto
    if not request.user.is_staff:
        return render(request, '403_prohibido.html', {'mensaje': 'Acceso denegado. Exclusivo para personal.'})

    return render(request, 'portal/panel_admin.html')


@login_required
def dashboard_medico(request):
    # Solo el personal interno (is_staff) puede ver esto
    if not request.user.is_staff:
        return render(request, '403_prohibido.html', {'mensaje': 'Acceso denegado. Exclusivo para personal.'})

    return render(request, 'dashboard/home_medico.html')


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

    # ---------------------------------------------------------
    # ⚙️ CREACIÓN DINÁMICA DE LOS 4 PERMISOS EN LA BASE DE DATOS
    # ---------------------------------------------------------
    ct_group = ContentType.objects.get_for_model(Group)
    p_ver, _ = Permission.objects.get_or_create(codename='perm_consultar', name='Puede Consultar Todo',
                                                content_type=ct_group)
    p_val, _ = Permission.objects.get_or_create(codename='perm_validar', name='Puede Validar/Aprobar',
                                                content_type=ct_group)
    p_obs, _ = Permission.objects.get_or_create(codename='perm_observar', name='Puede Añadir Observaciones',
                                                content_type=ct_group)
    p_desc, _ = Permission.objects.get_or_create(codename='perm_descargar', name='Puede Descargar Copias',
                                                 content_type=ct_group)

    # --- PROCESAMIENTO DE ACCIONES (POST / AJAX) ---
    if request.method == 'POST':
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        accion = request.POST.get('action_type')
        response_data = {'status': 'success', 'msg': 'Acción realizada'}

        try:
            # ==========================================
            # 1. CREAR NUEVA PERSONA
            # ==========================================
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
                    if is_ajax: return JsonResponse(
                        {'status': 'error', 'msg': 'El CORREO electrónico ya está registrado en el sistema.'})

                if curp and User.objects.filter(curp=curp).exists():
                    if is_ajax: return JsonResponse(
                        {'status': 'error', 'msg': f'La CURP {curp} ya está asignada a otra persona.'})

                if num_empleado and User.objects.filter(numero_empleado=num_empleado).exists():
                    if is_ajax: return JsonResponse(
                        {'status': 'error', 'msg': f'El Número de Empleado {num_empleado} ya existe.'})

                # CREACIÓN
                u = User.objects.create_user(username=email, email=email, password=password)
                u.nombre = nombre
                u.apellido_paterno = apellido_paterno
                u.apellido_materno = apellido_materno
                u.curp = curp
                u.tipo_persona = tipo_persona
                u.numero_empleado = num_empleado

                # --- VALIDACIÓN DE ACCESO EN LOGIN (Requisito del Inge) ---
                u.estatus_operativo = True
                u.is_active = True

                # PERMISOS BASE
                if tipo_persona == 'ADMIN':
                    u.is_superuser = True
                    u.is_staff = True
                elif tipo_persona in ['SUPERVISOR', 'PERSONAL']:
                    u.is_superuser = False
                    u.is_staff = True

                u.save()

                # AUDITORÍA
                AccessLog.objects.create(usuario=request.user,
                                         accion=f"CREACIÓN PERSONA: Registró a {nombre} {apellido_paterno} [{tipo_persona}] con CURP {curp}")
                response_data['msg'] = f'Persona {nombre} registrada exitosamente.'

            # ==========================================
            # 2. EDITAR PERSONA
            # ==========================================
            elif accion == 'edit_user':
                user_id = request.POST.get('user_id')
                usr_edit = User.objects.get(id=user_id)

                email = request.POST.get('email')
                curp = request.POST.get('curp', '').upper()
                num = request.POST.get('numero_empleado')

                # Validar que no le robe los datos a OTRA persona
                if User.objects.filter(email=email).exclude(id=user_id).exists():
                    return JsonResponse({'status': 'error', 'msg': 'El correo ya está en uso por otra persona.'})
                if curp and User.objects.filter(curp=curp).exclude(id=user_id).exists():
                    return JsonResponse({'status': 'error', 'msg': 'La CURP ya está asignada a otra persona.'})
                if num and User.objects.filter(numero_empleado=num).exclude(id=user_id).exists():
                    return JsonResponse({'status': 'error', 'msg': 'Ese Número de Empleado ya existe en el sistema.'})

                # Actualizar información
                usr_edit.nombre = request.POST.get('nombre')
                usr_edit.apellido_paterno = request.POST.get('apellido_paterno')
                usr_edit.apellido_materno = request.POST.get('apellido_materno', '')
                usr_edit.curp = curp
                usr_edit.numero_empleado = num
                usr_edit.email = email
                usr_edit.username = email
                usr_edit.tipo_persona = request.POST.get('tipo_persona')

                # --- MAGIA DE BLOQUEO PARA EL LOGIN (Requisito del Inge) ---
                estatus = (request.POST.get('estatus_operativo') == 'true')
                usr_edit.estatus_operativo = estatus
                usr_edit.is_active = estatus

                # Asignar permisos según nuevo tipo
                if usr_edit.tipo_persona == 'ADMIN':
                    usr_edit.is_superuser = True
                    usr_edit.is_staff = True
                else:
                    usr_edit.is_superuser = False
                    usr_edit.is_staff = True

                # Si escribió una contraseña nueva, cambiarla
                nueva_pass = request.POST.get('password')
                if nueva_pass:
                    usr_edit.set_password(nueva_pass)

                usr_edit.save()
                AccessLog.objects.create(usuario=request.user,
                                         accion=f"EDICIÓN PERSONA: Actualizó datos de {usr_edit.nombre}")
                response_data['msg'] = 'Información actualizada correctamente.'

            # ==========================================
            # 3. ELIMINAR USUARIO
            # ==========================================
            elif accion == 'delete_user':
                user_id = request.POST.get('user_id')
                if int(user_id) != request.user.id:
                    User.objects.filter(id=user_id).delete()
                    response_data['msg'] = 'Persona eliminada del sistema.'
                else:
                    if is_ajax: return JsonResponse({'status': 'error', 'msg': 'Seguridad: No puedes auto-eliminarte.'})

            # ==========================================
            # 4. CREAR NUEVO PUESTO Y PERMISOS (Catálogo)
            # ==========================================
            elif accion == 'create_role':
                nombre_rol = request.POST.get('nombre_rol', '').strip().title()
                es_master = (request.POST.get('permiso_total') == 'on')

                if nombre_rol:
                    nombre_final = f"[MASTER] {nombre_rol}" if es_master else nombre_rol
                    if Group.objects.filter(name=nombre_final).exists():
                        if is_ajax: return JsonResponse(
                            {'status': 'error', 'msg': f'El puesto "{nombre_final}" ya existe.'})

                    grupo = Group.objects.create(name=nombre_final)

                    # Le inyectamos los permisos de las casillas
                    if request.POST.get('p_ver') == 'on': grupo.permissions.add(p_ver)
                    if request.POST.get('p_val') == 'on': grupo.permissions.add(p_val)
                    if request.POST.get('p_obs') == 'on': grupo.permissions.add(p_obs)
                    if request.POST.get('p_desc') == 'on': grupo.permissions.add(p_desc)

                    response_data['msg'] = f'Puesto "{nombre_rol}" guardado en el catálogo.'

            # ==========================================
            # 5. EDITAR PERMISOS DE UN PUESTO EXISTENTE
            # ==========================================
            elif accion == 'edit_role':
                rol_id = request.POST.get('rol_id')
                grupo = Group.objects.get(id=rol_id)

                # Borrar los viejos y actualizar con los nuevos
                grupo.permissions.clear()
                if request.POST.get('p_ver') == 'on': grupo.permissions.add(p_ver)
                if request.POST.get('p_val') == 'on': grupo.permissions.add(p_val)
                if request.POST.get('p_obs') == 'on': grupo.permissions.add(p_obs)
                if request.POST.get('p_desc') == 'on': grupo.permissions.add(p_desc)

                response_data['msg'] = f'Permisos actualizados para el puesto: {grupo.name}'

            # ==========================================
            # 6. ASIGNAR PUESTO A UN EMPLEADO
            # ==========================================
            elif accion == 'assign_role':
                usuario_id = request.POST.get('usuario_id')
                rol_id = request.POST.get('rol_id')

                if not usuario_id or not rol_id:
                    if is_ajax: return JsonResponse({'status': 'error', 'msg': 'Selecciona empleado y puesto.'})

                empleado = User.objects.get(id=usuario_id)
                nuevo_grupo = Group.objects.get(id=rol_id)

                # Validación de duplicados
                if empleado.groups.exists():
                    rol_actual = empleado.groups.first().name.replace('[MASTER] ', '')
                    if is_ajax: return JsonResponse({'status': 'error',
                                                     'msg': f'¡ALERTA! {empleado.nombre} ya es "{rol_actual}". No puede tener dos puestos a la vez.'})

                empleado.groups.add(nuevo_grupo)
                AccessLog.objects.create(usuario=request.user,
                                         accion=f"ASIGNÓ CARGO: '{nuevo_grupo.name}' a {empleado.nombre}")
                response_data['msg'] = f'Se vinculó a {empleado.nombre} como {nuevo_grupo.name}.'

            # ==========================================
            # 7. ELIMINAR ROL SECUNDARIO DEL CATÁLOGO
            # ==========================================
            elif accion == 'delete_role':
                Group.objects.filter(id=request.POST.get('rol_id')).delete()
                response_data['msg'] = 'Rol eliminado.'

            # ==========================================
            # 8. RELACIONAR DEPARTAMENTOS (PERMISOS CRUZADOS)
            # ==========================================
            elif accion == 'cross_relation':
                origen_id = request.POST.get('rol_origen')
                destino_id = request.POST.get('rol_destino')

                if not origen_id or not destino_id:
                    if is_ajax: return JsonResponse(
                        {'status': 'error', 'msg': 'Selecciona ambos puestos para vincularlos.'})

                if origen_id == destino_id:
                    if is_ajax: return JsonResponse(
                        {'status': 'error', 'msg': 'No puedes vincular un puesto consigo mismo.'})

                origen = Group.objects.get(id=origen_id)
                destino = Group.objects.get(id=destino_id)

                puede_ver = (request.POST.get('c_ver') == 'on')
                puede_val = (request.POST.get('c_val') == 'on')
                puede_obs = (request.POST.get('c_obs') == 'on')
                puede_desc = (request.POST.get('c_desc') == 'on')

                # Si la relación ya existe, la actualiza. Si no, la crea.
                relacion, created = RelacionDepartamentos.objects.update_or_create(
                    rol_origen=origen,
                    rol_destino=destino,
                    defaults={
                        'puede_consultar': puede_ver,
                        'puede_validar': puede_val,
                        'puede_observar': puede_obs,
                        'puede_descargar': puede_desc
                    }
                )

                verbo = "Creó" if created else "Actualizó"
                AccessLog.objects.create(usuario=request.user,
                                         accion=f"{verbo} permiso cruzado: {origen.name} -> {destino.name}")
                response_data['msg'] = f'Se configuró correctamente el permiso de {origen.name} sobre {destino.name}.'

            # ==========================================
            # 9. ELIMINAR RELACIÓN CRUZADA
            # ==========================================
            elif accion == 'delete_cross_relation':
                rel_id = request.POST.get('rel_id')
                RelacionDepartamentos.objects.filter(id=rel_id).delete()
                response_data['msg'] = 'Vínculo entre departamentos eliminado.'

            # ==========================================
            # 10. SEGURIDAD: APLICAR PROTOCOLOS
            # ==========================================
            elif accion == 'toggle_security':
                request.session['sec_encrypt'] = True if request.POST.get('toggle_encrypt') else False
                request.session['sec_manto'] = True if request.POST.get('toggle_manto') else False
                request.session['sec_firewall'] = True if request.POST.get('toggle_firewall') else False
                request.session['sec_inscrip'] = True if request.POST.get('toggle_inscrip') else False
                response_data['msg'] = 'Protocolos de seguridad aplicados en el servidor.'

            # ==========================================
            # 11. LIMPIAR HISTORIAL
            # ==========================================
            elif accion == 'clear_history':
                AccessLog.objects.exclude(accion__startswith="REL_CONF:").exclude(
                    accion__startswith="MASTER_CONF:").delete()
                response_data['msg'] = 'Historial de auditoría depurado.'

            if is_ajax: return JsonResponse(response_data)

        except Exception as e:
            if is_ajax:
                return JsonResponse({'status': 'error', 'msg': str(e)})
            else:
                messages.error(request, f'Error del sistema: {e}')

        return redirect('panel_gobierno_ti')

    # --- PREPARACIÓN DE DATOS PARA LA VISTA ---
    staff_list = User.objects.filter(is_staff=True).order_by('-date_joined')

    if request.session.get('sec_encrypt', False):
        for s in staff_list: s.email = enmascarar_datos(s.email)

    logs_gen = AccessLog.objects.all().order_by('-fecha_acceso')[:50]

    context = {
        'lista_staff': staff_list,
        'roles': Group.objects.all(),
        'relaciones_cruzadas': RelacionDepartamentos.objects.all(),  # <-- SE ENVIAN AL HTML
        'logs': logs_gen,
        'encrypt_active': request.session.get('sec_encrypt', True),
        'manto_active': request.session.get('sec_manto', False),
        'firewall_active': request.session.get('sec_firewall', False),
        'inscrip_active': request.session.get('sec_inscrip', False),
    }

    return render(request, 'portal/panel_ti.html', context)


# ==============================================================
# VISTAS DE PADRES (PÚBLICAS, COMO LO PEDISTE SIN INICIAR SESIÓN)
# ==============================================================
def portal_padres_home(request):
    solicitud_activa = None

    try:
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
            'folio': folio
        }
    )


def registro_inscripcion(request):
    return render(request, 'portal/registro_inscripcion.html')
