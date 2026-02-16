"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views

# --- IMPORTANTE: ESTA LÍNEA ARREGLA EL ERROR ROJO ---
# Traemos tus vistas desde la carpeta 'usuarios'
from usuarios import views as user_views

urlpatterns = [
    # 1. ADMIN DE DJANGO
    path('admin/', admin.site.urls),

    # 2. EL LOGIN (Ahora vive en /login/)
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),

    # 3. EL SEMÁFORO (La Raíz "/")
    # Cuando entran a la página principal, el semáforo decide a dónde van
    path('', user_views.root_redirect_view, name='root'),

    # 4. LOS DESTINOS (Tienen que existir para que el semáforo funcione)
    path('panel-administrativo/', user_views.dashboard_admin, name='dashboard_admin'),
    path('area-medica/', user_views.dashboard_medico, name='dashboard_medico'),
    path('portal-padres/', user_views.portal_padres_home, name='portal_padres_home'),

    # 5. TU NUEVO FORMULARIO DE INSCRIPCIÓN
    path('inscripcion-nueva/', user_views.registro_inscripcion, name='registro_inscripcion'),

    # 6. SALIR
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),

# ... tus otras rutas (admin, login, etc) ...

    # --- RUTAS DE RECUPERACIÓN DE CONTRASEÑA ---
    path('reset-password/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('reset-password/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
    path("solicitud/", include("admisiones.urls")),
    path("solicitud/admisiones/", include("admisiones.urls")),

]