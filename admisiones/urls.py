from django.urls import path
from . import views
from usuarios import views as user_views  # Vistas de la directora

urlpatterns = [
    # =========================================================
    # SOLICITUD DE INGRESO / ADMISIÓN
    # =========================================================
    path("panel/", views.panel_admisiones, name="panel_admisiones"),
    path("crear/", views.crear_solicitud_y_link, name="crear_solicitud_y_link"),
    path("captura/<str:token>/", views.captura_por_token, name="captura_por_token"),

    # AJAX: filtrar carreras por facultad
    path("obtener-carreras/", views.obtener_carreras, name="obtener_carreras"),

    path("enviar-link/<int:solicitud_id>/", views.enviar_link_por_correo, name="enviar_link_por_correo"),
    path("editar/<int:solicitud_id>/", views.editar_solicitud, name="editar_solicitud"),
    path("pdf/<int:solicitud_id>/", views.descargar_pdf_solicitud, name="descargar_pdf_solicitud"),
    path("publica/nueva/", views.solicitud_publica_nueva, name="solicitud_publica_nueva"),
    path("admisiones/<int:pk>/revisar/", views.revisar_solicitud, name="revisar_solicitud"),
    path("admisiones/<int:pk>/dictaminar/", views.dictaminar_solicitud, name="dictaminar_solicitud"),

    # =========================================================
    # EXPEDIENTE / ARCHIVOS DE INSCRIPCIÓN
    # =========================================================
    path(
        "expediente/descargar/<int:inscripcion_id>/<str:campo>/",
        views.descargar_archivo_expediente,
        name="descargar_archivo_expediente",
    ),

    path("admisiones/solicitud/eliminar/<int:pk>/", views.eliminar_solicitud, name="eliminar_solicitud"),
    path("admisiones/eliminar-todo/", views.eliminar_todas_solicitudes, name="eliminar_todas_solicitudes"),

    # =========================================================
    # PORTAL DE INSCRIPCIÓN DEL BENEFICIARIO
    # =========================================================
    path("mi-inscripcion/", views.portal_inscripcion, name="portal_inscripcion"),

    # Descargar Reporte Final de Ingreso desde el portal del beneficiario
    path(
        "mi-inscripcion/descargar-reporte/<int:inscripcion_id>/",
        views.descargar_reporte_final_padre,
        name="descargar_reporte_final_padre",
    ),

    # =========================================================
    # FILTRO PSICOLOGÍA
    # =========================================================
    path("psicologia/", views.psicologia_pendientes, name="psicologia_pendientes"),
    path("psicologia/<int:pk>/", views.psicologia_dictaminar, name="psicologia_dictaminar"),
    path("psicologia/registro/", views.psicologia_registro, name="psicologia_registro"),
    path("psicologia/<int:pk>/pdf/", views.psicologia_pdf, name="psicologia_pdf"),

    # =========================================================
    # FILTRO NUTRICIÓN
    # =========================================================
    path("nutricion/", views.nutricion_pendientes, name="nutricion_pendientes"),
    path("nutricion/<int:pk>/", views.nutricion_dictaminar, name="nutricion_dictaminar"),
    path("nutricion/registro/", views.nutricion_registro, name="nutricion_registro"),
    path("nutricion/<int:pk>/pdf/", views.nutricion_pdf, name="nutricion_pdf"),

    # =========================================================
    # FILTRO MÉDICO
    # =========================================================
    path("medico/", views.medico_pendientes, name="medico_pendientes"),
    path("medico/<int:pk>/", views.medico_dictaminar, name="medico_dictaminar"),
    path("medico/registro/", views.medico_registro, name="medico_registro"),
    path("medico/<int:pk>/pdf/", views.medico_pdf, name="medico_pdf"),

    # =========================================================
    # REPORTE FINAL DE INGRESO - TRABAJO SOCIAL
    # =========================================================
    path("reporte-final-ingreso/", views.reporte_final_pendientes, name="reporte_final_pendientes"),
    path("reporte-final-ingreso/<int:pk>/", views.dictaminar_reporte_final, name="dictaminar_reporte_final"),

    # =========================================================
    # COMPROBANTE DE PAGO - TRABAJO SOCIAL
    # =========================================================
    path("pagos/pendientes/", views.validacion_pagos_pendientes, name="validacion_pagos_pendientes"),
    path("pagos/validar/<int:pk>/", views.registrar_pago_valido, name="registrar_pago_valido"),

    # =========================================================
    # CÓDIGO DE SEGURIDAD DEL RESPONSABLE - TRABAJO SOCIAL
    # Se genera después de inscripción finalizada y pago validado.
    # =========================================================
    path(
        "codigos-responsable/",
        views.codigos_responsable_pendientes,
        name="codigos_responsable_pendientes",
    ),
    path(
        "codigos-responsable/<int:inscripcion_id>/generar/",
        views.generar_codigo_responsable,
        name="generar_codigo_responsable",
    ),
    path(
        "codigos-responsable/<int:inscripcion_id>/confirmar-entrega/",
        views.confirmar_entrega_codigo_responsable,
        name="confirmar_entrega_codigo_responsable",
    ),

    # =========================================================
    # SPRINT 5 - ÉPICA 3
    # INCIDENCIAS
    # Pedagógica, Nutricional, Médica y Psicológica
    # =========================================================
    path(
        "incidencias/",
        views.panel_incidencias,
        name="panel_incidencias",
    ),
    path(
        "incidencias/crear/",
        views.crear_incidencia,
        name="crear_incidencia",
    ),
    path(
        "incidencias/crear/<str:tipo>/",
        views.crear_incidencia,
        name="crear_incidencia_tipo",
    ),
    path(
        "incidencias/<int:incidencia_id>/detalle/",
        views.detalle_incidencia,
        name="detalle_incidencia",
    ),
    path(
        "incidencias/<int:incidencia_id>/seguimiento/",
        views.registrar_seguimiento_incidencia,
        name="registrar_seguimiento_incidencia",
    ),
    path(
        "incidencias/<int:incidencia_id>/cerrar/",
        views.cerrar_incidencia,
        name="cerrar_incidencia",
    ),

    # =========================================================
    # DIRECTORA
    # Estas se dejan activas porque pertenecen al flujo de aprobación
    # desde usuarios/views.py, no a los templates borrados de admisiones.
    # =========================================================
    path(
        "veredicto-final/<int:inscripcion_id>/",
        user_views.veredicto_final_directora,
        name="veredicto_final_directora",
    ),
    path(
        "dictaminar-sala-directora/<int:inscripcion_id>/",
        user_views.dictaminar_sala_directora,
        name="dictaminar_sala_directora",
    ),

    # =========================================================
    # SPRINT 4 - ÉPICA 3
    # CONFIGURACIÓN DE SEMESTRE - ADMINISTRADOR DEL SISTEMA
    # =========================================================

    # Panel principal de semestres
    path("semestres/", views.lista_semestres, name="lista_semestres"),

    # Sedes
    path("semestres/sedes/nueva/", views.crear_sede, name="crear_sede"),
    path("semestres/sedes/<int:sede_id>/editar/", views.editar_sede, name="editar_sede"),

    # Semestres
    path("semestres/nuevo/", views.crear_semestre, name="crear_semestre"),
    path("semestres/<int:semestre_id>/", views.detalle_semestre, name="detalle_semestre"),
    path("semestres/<int:semestre_id>/editar/", views.editar_semestre, name="editar_semestre"),
    path("semestres/<int:semestre_id>/iniciar/", views.iniciar_semestre, name="iniciar_semestre"),
    path("semestres/<int:semestre_id>/cerrar/", views.cerrar_semestre, name="cerrar_semestre"),
    path(
        "semestres/<int:semestre_id>/generar-dias-operativos/",
        views.generar_dias_operativos_semestre,
        name="generar_dias_operativos_semestre",
    ),

    # Días festivos / suspensiones
    path(
        "semestres/<int:semestre_id>/dias/agregar/",
        views.agregar_dia_festivo,
        name="agregar_dia_festivo",
    ),
    path(
        "semestres/dias/<int:dia_id>/eliminar/",
        views.eliminar_dia_festivo,
        name="eliminar_dia_festivo",
    ),
    path(
        "semestres/dias-operativos/<int:dia_id>/cerrar/",
        views.cerrar_dia_operativo,
        name="cerrar_dia_operativo",
    ),

    # Catálogo de salas
    path("semestres/salas/nueva/", views.crear_sala, name="crear_sala"),
    path("semestres/salas/<int:sala_id>/editar/", views.editar_sala, name="editar_sala"),

    # Salas configuradas por semestre
    path(
        "semestres/<int:semestre_id>/salas/agregar/",
        views.agregar_sala_semestre,
        name="agregar_sala_semestre",
    ),
    path(
        "semestres/salas-semestre/<int:sala_semestre_id>/editar/",
        views.editar_sala_semestre,
        name="editar_sala_semestre",
    ),

    # Maestras asignadas por sala
    path(
        "semestres/salas-semestre/<int:sala_semestre_id>/maestras/asignar/",
        views.asignar_maestra_sala,
        name="asignar_maestra_sala",
    ),
    path(
        "semestres/maestras/<int:asignacion_id>/editar/",
        views.editar_asignacion_maestra,
        name="editar_asignacion_maestra",
    ),
    path(
        "semestres/maestras/<int:asignacion_id>/eliminar/",
        views.eliminar_asignacion_maestra,
        name="eliminar_asignacion_maestra",
    ),

    # Encuesta de satisfacción B
    path(
        "semestres/<int:semestre_id>/encuesta/enviar/",
        views.enviar_encuesta_satisfaccion,
        name="enviar_encuesta_satisfaccion",
    ),

    # Incidencias de semestre
    path(
        "semestres/<int:semestre_id>/incidencias/nueva/",
        views.crear_incidencia_semestre,
        name="crear_incidencia_semestre",
    ),
    path(
        "semestres/incidencias/<int:incidencia_id>/cerrar/",
        views.cerrar_incidencia,
        name="cerrar_incidencia_semestre_legacy",
    ),

    # Asignación de salas a alumnos finalizados
    path("asignacion-salas/", views.lista_asignacion_salas, name="lista_asignacion_salas"),
    path("asignar-sala/<int:inscripcion_id>/", views.asignar_sala_definitiva, name="asignar_sala_definitiva"),

    # =========================================================
    # SPRINT 4 - SEGUNDA PARTE
    # OPERACIÓN DIARIA DE MAESTRAS
    # Abrir día, entrada, bitácora en casa, estancia, salida y cierre.
    # =========================================================

    # Panel principal de maestra
    path("dashboard-maestra/", views.dashboard_maestra, name="dashboard_maestra"),

    # Día operativo por maestra
    path(
        "operacion-diaria/dia/<int:dia_id>/abrir/",
        views.abrir_dia_maestra,
        name="abrir_dia_maestra",
    ),
    path(
        "operacion-diaria/dia/<int:dia_id>/alumnos/",
        views.lista_alumnos_dia_maestra,
        name="lista_alumnos_dia_maestra",
    ),
    path(
        "operacion-diaria/dia/<int:dia_id>/cerrar/",
        views.cerrar_dia_maestra,
        name="cerrar_dia_maestra",
    ),

    # Registro diario por alumno
    path(
        "operacion-diaria/registro/<int:registro_id>/entrada/",
        views.registrar_entrada_alumno,
        name="registrar_entrada_alumno",
    ),
    path(
        "operacion-diaria/registro/<int:registro_id>/bitacora-en-casa/",
        views.bitacora_entrada_casa_maestra,
        name="bitacora_entrada_casa_maestra",
    ),
    path(
        "operacion-diaria/registro/<int:registro_id>/bitacora-estancia/",
        views.bitacora_estancia_maestra,
        name="bitacora_estancia_maestra",
    ),
    path(
        "operacion-diaria/registro/<int:registro_id>/salida/",
        views.registrar_salida_alumno,
        name="registrar_salida_alumno",
    ),

    # Historial del alumno para maestra
    path(
        "operacion-diaria/alumno/<int:alumno_id>/historial/",
        views.historial_alumno_maestra,
        name="historial_alumno_maestra",
    ),

    # =========================================================
    # RUTAS LEGACY / COMPATIBILIDAD
    # Bitácoras antiguas y aprobación quedan desactivadas.
    # Las incidencias ya se operan desde Sprint 5 en /incidencias/.
    # =========================================================
    path("dashboard-coordinadora/", views.dashboard_coordinadora, name="dashboard_coordinadora"),
    path("expediente-bitacoras/<int:alumno_id>/", views.expediente_bitacoras, name="expediente_bitacoras"),
    path("nueva-bitacora/<int:alumno_id>/", views.crear_bitacora, name="crear_bitacora"),

    path(
        "bitacora/enviar-coord/<int:bitacora_id>/<str:tipo>/",
        views.enviar_bitacora_coordinadora,
        name="enviar_bitacora_coordinadora",
    ),
    path(
        "bitacora/aprobar/<int:bitacora_id>/<str:tipo>/",
        views.aprobar_bitacora_coordinadora,
        name="aprobar_bitacora_coordinadora",
    ),
    path(
        "bitacora/corregir/<int:bitacora_id>/<str:tipo>/",
        views.corregir_bitacora_coordinadora,
        name="corregir_bitacora_coordinadora",
    ),
    path(
        "bitacora/enviar-directora/<int:bitacora_id>/<str:tipo>/",
        views.enviar_bitacora_directora,
        name="enviar_bitacora_directora",
    ),
    path(
        "bitacora/pdf/<int:bitacora_id>/<str:tipo>/",
        views.descargar_pdf_bitacora,
        name="descargar_pdf_bitacora",
    ),
]