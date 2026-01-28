from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
# No olvides importar esto para que funcionen los mensajes flash si los usas a futuro
from django.contrib import messages

# --- DEFINIMOS LOS GRUPOS DE PODER ---
ROLES_ADMINISTRATIVOS = [
    'admin', 'jefa_superior', 'directora', 'administrativo'
]

ROLES_MEDICOS = [
    'medica', 'psicologa', 'nutriologa', 'trabajo_social'
]


# --- VISTA SEMÁFORO (REDIRECCIÓN INICIAL) ---
@login_required
def root_redirect_view(request):
    user = request.user

    if user.rol in ROLES_ADMINISTRATIVOS:
        return redirect('dashboard_admin')

    elif user.rol == 'tutor':
        # Los padres/madres estudiantes van a su portal
        return redirect('portal_padres_home')

    elif user.rol in ROLES_MEDICOS:
        return redirect('dashboard_medico')

    else:
        # Por defecto, si el rol no coincide (seguridad), lo mandamos al home de padres o logout
        return redirect('portal_padres_home')


# --- VISTAS PROTEGIDAS (CON CANDADO DE SEGURIDAD) ---

@login_required
def dashboard_admin(request):
    # CANDADO: Solo para las 4 Jefas/Admin
    if request.user.rol not in ROLES_ADMINISTRATIVOS:
        return render(request, '403_prohibido.html')

    return render(request, 'dashboard/home_admin.html')


@login_required
def dashboard_medico(request):
    # CANDADO: Solo personal de salud y Administrativos (a veces requieren ver)
    if request.user.rol not in ROLES_MEDICOS and request.user.rol not in ROLES_ADMINISTRATIVOS:
        return render(request, '403_prohibido.html')

    return render(request, 'dashboard/home_medico.html')


@login_required
def portal_padres_home(request):
    # CANDADO: ESTRICTAMENTE SOLO PARA PADRE/MADRE (ALUMNOS)
    # Si entra una Directora o un Médico aquí, le saldrá prohibido (o lo rediriges a su panel)
    if request.user.rol != 'tutor':
        return render(request, '403_prohibido.html')

    return render(request, 'portal/home_padres.html')


# --- VISTA DEL FORMULARIO CON AUTOGUARDADO ---
@login_required
def registro_inscripcion(request):
    # CANDADO: Solo los padres pueden inscribir niños
    if request.user.rol != 'tutor':
        return render(request, '403_prohibido.html')

    return render(request, 'portal/registro_inscripcion.html')