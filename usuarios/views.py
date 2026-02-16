from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

# 👇 IMPORTA TU MODELO Solicitud
# Si Solicitud está en la app "usuarios", deja esto:
from admisiones.models import Solicitud


# Si Solicitud está en la app "admisiones", usa esto en su lugar:
# from admisiones.models import Solicitud


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
        return redirect('portal_padres_home')

    elif user.rol in ROLES_MEDICOS:
        return redirect('dashboard_medico')

    else:
        return redirect('portal_padres_home')


# --- VISTAS PROTEGIDAS ---
@login_required
def dashboard_admin(request):
    if request.user.rol not in ROLES_ADMINISTRATIVOS:
        return render(request, '403_prohibido.html')

    return render(request, 'dashboard/home_admin.html')


@login_required
def dashboard_medico(request):
    if request.user.rol not in ROLES_MEDICOS and request.user.rol not in ROLES_ADMINISTRATIVOS:
        return render(request, '403_prohibido.html')

    return render(request, 'dashboard/home_medico.html')


@login_required
def portal_padres_home(request):
    if request.user.rol != 'tutor':
        return render(request, '403_prohibido.html')

    # ✅ En lugar de token, usaremos una Solicitud (por ID)
    solicitud_activa = None

    # Si tu modelo Solicitud tiene FK al usuario, usa esto (recomendado):
    # solicitud_activa = Solicitud.objects.filter(tutor=request.user).order_by("-id").first()

    # Si aún NO tienes relación tutor->solicitud, solo toma la última global (temporal):
    solicitud_activa = Solicitud.objects.order_by("-id").first()

    # Si no hay ninguna solicitud aún, crea una (si tu modelo permite crear vacío)
    if not solicitud_activa:
        kwargs = {}
        # Si tu Solicitud tiene campo estado, opcional
        if "estado" in [f.name for f in Solicitud._meta.fields]:
            kwargs["estado"] = "CAPTURA"

        # Si tu Solicitud exige campos obligatorios, aquí te va a marcar error;
        # en ese caso NO la creamos y solo mostramos botón "Crear solicitud"
        try:
            solicitud_activa = Solicitud.objects.create(**kwargs)
        except Exception:
            solicitud_activa = None

    # ✅ Esto reemplaza token_activo:
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


# --- VISTA DEL FORMULARIO ---
@login_required
def registro_inscripcion(request):
    if request.user.rol != 'tutor':
        return render(request, '403_prohibido.html')

    return render(request, 'portal/registro_inscripcion.html')
