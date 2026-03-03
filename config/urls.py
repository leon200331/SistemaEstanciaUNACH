"""
URL configuration for config project.
"""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views

# --- IMPORTANTE: ESTA LÍNEA ES LA CLAVE ---
from usuarios import views as user_views

urlpatterns = [
    # 1. ADMIN DE DJANGO
    path('admin/', admin.site.urls),

    # 2. EL LOGIN
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),

    # 3. EL SEMÁFORO (Raíz)
    path('', user_views.root_redirect_view, name='root'),

    # 4. LOS DESTINOS
    path('panel-administrativo/', user_views.dashboard_admin, name='dashboard_admin'),
    path('area-medica/', user_views.dashboard_medico, name='dashboard_medico'),
    path('portal-padres/', user_views.portal_padres_home, name='portal_padres_home'),

    # 5. INSCRIPCIÓN
    path('inscripcion-nueva/', user_views.registro_inscripcion, name='registro_inscripcion'),

    # 6. SALIR
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),

    # --- RUTAS DE RECUPERACIÓN DE CONTRASEÑA ---
    path('reset-password/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('reset-password/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),

    # --- MÓDULO ADMISIONES ---
    path("solicitud/", include("admisiones.urls")),
    path("solicitud/admisiones/", include("admisiones.urls")),
    path("admisiones/", include("admisiones.urls")),

    # --- PANEL GOBIERNO TI ---
    path('gobierno-ti/', user_views.panel_gobierno_ti, name='panel_gobierno_ti'),

]
