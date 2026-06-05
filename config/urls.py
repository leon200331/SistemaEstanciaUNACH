"""
URL configuration for config project.
"""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views

from usuarios import views as user_views
from admisiones import views as admisiones_views

from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    # 1. ADMIN DE DJANGO
    path("admin/", admin.site.urls),

    # =================================================================================
    # 2. LOGIN
    # =================================================================================
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True
        ),
        name="login",
    ),

    # 3. RAÍZ / REDIRECCIÓN POR ROL
    path("", user_views.root_redirect_view, name="root"),

    # 4. DESTINOS PRINCIPALES
    path("panel-administrativo/", user_views.dashboard_admin, name="dashboard_admin"),
    path("area-medica/", user_views.dashboard_medico, name="dashboard_medico"),
    path("portal-padres/", user_views.portal_padres_home, name="portal_padres_home"),

    # DIRECTORA
    path(
        "panel-directiva/",
        admisiones_views.panel_directiva,
        name="dashboard_directiva",
    ),

    # 5. LOGOUT
    path(
        "logout/",
        auth_views.LogoutView.as_view(next_page="login"),
        name="logout",
    ),

    # 6. RECUPERACIÓN DE CONTRASEÑA
    path(
        "reset-password/",
        auth_views.PasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "reset-password/done/",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),

    # 7. MÓDULO ADMISIONES
    # Ruta institucional recomendada para producción.
    path("sistema-eiu/", include("admisiones.urls")),

    path("solicitud/", include("admisiones.urls")),
    path("solicitud/admisiones/", include("admisiones.urls")),
    path("admisiones/", include("admisiones.urls")),

    # 8. PANEL GOBIERNO TI
    path("gobierno-ti/", user_views.panel_gobierno_ti, name="panel_gobierno_ti"),

    # 9. INCIDENCIAS PARA ADMINISTRADOR DEL SISTEMA
    path(
        "gobierno-ti/incidencias/",
        user_views.panel_incidencias_ti,
        name="panel_incidencias_ti",
    ),

    # 10. DESCARGA DE EXPEDIENTE DE CICLO EN PDF
    path(
        "gobierno-ti/ciclo/<int:ciclo_id>/pdf/",
        user_views.descargar_reporte_ciclo_pdf,
        name="descargar_reporte_ciclo_pdf",
    ),
]


# ARCHIVOS MEDIA EN DESARROLLO
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)