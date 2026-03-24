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
    path("admisiones/solicitud/eliminar/<int:pk>/", views.eliminar_solicitud, name="eliminar_solicitud"),
    path("admisiones/eliminar-todo/", views.eliminar_todas_solicitudes, name="eliminar_todas_solicitudes"),

    # =========================================================
    # SPRINT 2: PORTAL DE INSCRIPCIÓN (PADRES)
    # =========================================================
    path("mi-inscripcion/", views.portal_inscripcion, name="portal_inscripcion"),

    # --- NUEVA RUTA PARA QUE EL PADRE DESCARGUE EL REPORTE FINAL ---
    path("mi-inscripcion/descargar-reporte/<int:inscripcion_id>/", views.descargar_reporte_final_padre,
         name="descargar_reporte_final_padre"),

    # =========================================================
    # FILTROS / DICTÁMENES POR ÁREA (PSICOLOGÍA / NUTRICIÓN / MÉDICO)
    # =========================================================
    path("psicologia/", views.psicologia_pendientes, name="psicologia_pendientes"),
    path("psicologia/<int:pk>/", views.psicologia_dictaminar, name="psicologia_dictaminar"),
    path("psicologia/registro/", views.psicologia_registro, name="psicologia_registro"),
    path("psicologia/<int:pk>/pdf/", views.psicologia_pdf, name="psicologia_pdf"),

    path("nutricion/", views.nutricion_pendientes, name="nutricion_pendientes"),
    path("nutricion/<int:pk>/", views.nutricion_dictaminar, name="nutricion_dictaminar"),
    path("nutricion/registro/", views.nutricion_registro, name="nutricion_registro"),
    path("nutricion/<int:pk>/pdf/", views.nutricion_pdf, name="nutricion_pdf"),

    path("medico/", views.medico_pendientes, name="medico_pendientes"),
    path("medico/<int:pk>/", views.medico_dictaminar, name="medico_dictaminar"),
    path("medico/registro/", views.medico_registro, name="medico_registro"),
    path("medico/<int:pk>/pdf/", views.medico_pdf, name="medico_pdf"),

    # =========================================================
    # REPORTE FINAL DE INGRESO (TRABAJO SOCIAL)
    # =========================================================
    path("reporte-final-ingreso/", views.reporte_final_pendientes, name="reporte_final_pendientes"),
    path("reporte-final-ingreso/<int:pk>/", views.dictaminar_reporte_final, name="dictaminar_reporte_final"),

    # =========================================================
    # VISTA FINAL DE DIRECTORA (ÉPICA 2)
    # =========================================================
    path('veredicto-final/<int:inscripcion_id>/', views.veredicto_final_directora, name='veredicto_final_directora'),

    # =========================================================
    # VALIDACIÓN DE PAGOS (TRABAJO SOCIAL)
    # =========================================================
    path('pagos/pendientes/', views.validacion_pagos_pendientes, name='validacion_pagos_pendientes'),
    path('pagos/validar/<int:pk>/', views.registrar_pago_valido, name='registrar_pago_valido'),
]