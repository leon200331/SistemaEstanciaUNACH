from django.urls import path
from . import views
from usuarios import views as user_views  # <--- AGREGADO: Importamos las vistas de la directora

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

    # RUTA PARA LA DESCARGA DIRECTA (USA ESTA EN TU HTML)
    path('expediente/descargar/<int:inscripcion_id>/<str:campo>/', views.descargar_archivo_expediente,
         name='descargar_archivo_expediente'),

    path("admisiones/solicitud/eliminar/<int:pk>/", views.eliminar_solicitud, name="eliminar_solicitud"),
    path("admisiones/eliminar-todo/", views.eliminar_todas_solicitudes, name="eliminar_todas_solicitudes"),
    path("mi-inscripcion/", views.portal_inscripcion, name="portal_inscripcion"),
    path("mi-inscripcion/descargar-reporte/<int:inscripcion_id>/", views.descargar_reporte_final_padre,
         name="descargar_reporte_final_padre"),

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

    path("reporte-final-ingreso/", views.reporte_final_pendientes, name="reporte_final_pendientes"),
    path("reporte-final-ingreso/<int:pk>/", views.dictaminar_reporte_final, name="dictaminar_reporte_final"),

    # =========================================================
    # RUTAS DE ASIGNACIÓN DE SALAS Y DIRECTIVA (AQUÍ ESTÁ LA SOLUCIÓN)
    # =========================================================
    path("asignacion-salas/", views.lista_asignacion_salas, name="lista_asignacion_salas"),
    path("asignar-sala/<int:inscripcion_id>/", views.asignar_sala_definitiva, name="asignar_sala_definitiva"),

    # --- CORRECCIÓN APLICADA AQUÍ: user_views ---
    path('veredicto-final/<int:inscripcion_id>/', user_views.veredicto_final_directora, name='veredicto_final_directora'),
    path('dictaminar-sala-directora/<int:inscripcion_id>/', user_views.dictaminar_sala_directora, name='dictaminar_sala_directora'),

    path('pagos/pendientes/', views.validacion_pagos_pendientes, name='validacion_pagos_pendientes'),
    path('pagos/validar/<int:pk>/', views.registrar_pago_valido, name='registrar_pago_valido'),
    path('semestres/', views.lista_semestres, name='lista_semestres'),
    path('semestres/nuevo/', views.crear_semestre, name='crear_semestre'),
    path('semestres/<int:semestre_id>/', views.detalle_semestre, name='detalle_semestre'),

    # =========================================================
    # NUEVAS RUTAS PARA ASISTENTES DE SALAS Y COORDINACIÓN
    # =========================================================
    path("dashboard-maestra/", views.dashboard_maestra, name="dashboard_maestra"),
    path("dashboard-coordinadora/", views.dashboard_coordinadora, name="dashboard_coordinadora"),
    path("expediente-bitacoras/<int:alumno_id>/", views.expediente_bitacoras, name="expediente_bitacoras"),
    path("nueva-bitacora/<int:alumno_id>/", views.crear_bitacora, name="crear_bitacora"),

    path("bitacora/enviar-coord/<int:bitacora_id>/<str:tipo>/", views.enviar_bitacora_coordinadora,
         name="enviar_bitacora_coordinadora"),
    path("bitacora/aprobar/<int:bitacora_id>/<str:tipo>/", views.aprobar_bitacora_coordinadora,
         name="aprobar_bitacora_coordinadora"),
    path("bitacora/corregir/<int:bitacora_id>/<str:tipo>/", views.corregir_bitacora_coordinadora,
         name="corregir_bitacora_coordinadora"),
    path("bitacora/enviar-directora/<int:bitacora_id>/<str:tipo>/", views.enviar_bitacora_directora,
         name="enviar_bitacora_directora"),
    path("bitacora/pdf/<int:bitacora_id>/<str:tipo>/", views.descargar_pdf_bitacora, name="descargar_pdf_bitacora"),
]