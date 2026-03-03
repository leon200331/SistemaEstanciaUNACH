from django.urls import path
from . import views

urlpatterns = [
    path("panel/", views.panel_admisiones, name="panel_admisiones"),
    path("crear/", views.crear_solicitud_y_link, name="crear_solicitud_y_link"),
    path("captura/<str:token>/", views.captura_por_token, name="captura_por_token"),
    path("enviar-link/<int:solicitud_id>/", views.enviar_link_por_correo, name="enviar_link_por_correo"),
    path("editar/<int:solicitud_id>/", views.editar_solicitud, name="editar_solicitud"),
    path("pdf/<int:solicitud_id>/", views.descargar_pdf_solicitud, name="descargar_pdf_solicitud"),
    path("publica/nueva/", views.solicitud_publica_nueva, name="solicitud_publica_nueva"),
    path("admisiones/<int:pk>/revisar/", views.revisar_solicitud, name="revisar_solicitud"),
    path("admisiones/<int:pk>/dictaminar/", views.dictaminar_solicitud, name="dictaminar_solicitud"),

    # =========================================================
    # NUEVAS RUTAS: ELIMINAR SOLICITUDES DESDE EL PANEL
    # =========================================================
    path('admisiones/solicitud/eliminar/<int:pk>/', views.eliminar_solicitud, name='eliminar_solicitud'),
    path('admisiones/eliminar-todo/', views.eliminar_todas_solicitudes, name='eliminar_todas_solicitudes'),

    # =========================================================
    # SPRINT 2: PORTAL DE INSCRIPCIÓN (PADRES)
    # =========================================================
    path("mi-inscripcion/", views.portal_inscripcion, name="portal_inscripcion"),
]