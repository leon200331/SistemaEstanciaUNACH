from django.urls import path, reverse
from django.shortcuts import redirect
import re
from . import views
from usuarios import views as user_views  # Vistas de la directora
from .models import Semestre, SalaSemestre



def redirigir_salas_semestre_a_detalle(request):
    """
    Corrige enlaces antiguos o botones de regreso que apuntan a:
        /admisiones/semestres/salas-semestre/?origen=ti

    Esa URL no muestra una sala específica; por eso se redirige al detalle
    del semestre correcto. Primero intenta detectar la sala desde la pantalla
    anterior, después usa semestre_id si viene en la URL y, como respaldo,
    manda al semestre activo o al último semestre creado.
    """
    origen = (request.GET.get("origen") or "").strip()
    semestre_id = (
        request.GET.get("semestre_id")
        or request.GET.get("semestre")
        or request.GET.get("id")
        or ""
    )

    if not semestre_id:
        referencia = request.META.get("HTTP_REFERER", "") or ""
        coincidencia = re.search(r"/semestres/salas-semestre/(\d+)/editar", referencia)

        if coincidencia:
            sala_semestre = (
                SalaSemestre.objects
                .select_related("semestre")
                .filter(pk=coincidencia.group(1))
                .first()
            )
            if sala_semestre:
                semestre_id = sala_semestre.semestre_id

    semestre = None

    if semestre_id:
        try:
            semestre = Semestre.objects.filter(pk=int(semestre_id)).first()
        except (TypeError, ValueError):
            semestre = None

    if semestre is None:
        try:
            estado_activo = Semestre.EstadoSemestre.ACTIVO
        except Exception:
            estado_activo = "ACTIVO"

        semestre = (
            Semestre.objects
            .filter(estado=estado_activo)
            .order_by("-fecha_inicio", "-id")
            .first()
        )

    if semestre is None:
        semestre = Semestre.objects.order_by("-fecha_inicio", "-id").first()

    if semestre:
        url = reverse("detalle_semestre", kwargs={"semestre_id": semestre.id})
    else:
        url = reverse("lista_semestres")

    if origen:
        separador = "&" if "?" in url else "?"
        url = f"{url}{separador}origen={origen}"

    return redirect(url)


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
    # PANEL SUPERVISORA GENERAL / SECRETARÍA DE DIRECCIÓN
    # Solo consulta en tiempo real. No modifica registros.
    # =========================================================
    path(
        "panel-supervisor/",
        views.panel_supervisor,
        name="panel_supervisor",
    ),
    path(
        "panel-supervisor/datos/",
        views.panel_supervisor_datos,
        name="panel_supervisor_datos",
    ),
    path(
        "panel-supervisor/reportes/<str:tipo_reporte>/",
        views.descargar_reporte_supervisor,
        name="descargar_reporte_supervisor",
    ),

    # =========================================================
    # PASE DE LISTA Y SUPLENCIAS TEMPORALES
    # Dirección registra asistencia del personal operativo.
    # Si alguien está ausente, Dirección puede autorizar cobertura temporal.
    # No se crean pantallas nuevas: las vistas regresan a los paneles existentes.
    # =========================================================
    path(
        "personal/asistencia/",
        views.registrar_asistencia_personal,
        name="registrar_asistencia_personal",
    ),
    path(
        "suplencias/",
        views.bitacora_suplencias,
        name="suplencias_panel",
    ),
    path(
        "suplencias/crear/",
        views.crear_suplencia,
        name="crear_suplencia",
    ),
    path(
        "suplencias/<int:autorizacion_id>/cancelar/",
        views.cancelar_suplencia,
        name="cancelar_suplencia",
    ),
    path(
        "suplencias/bitacora/",
        views.bitacora_suplencias,
        name="bitacora_suplencias",
    ),
    path(
        "suplencias/movimientos/<int:movimiento_id>/validar/",
        views.validar_movimiento_suplencia,
        name="validar_movimiento_suplencia",
    ),
    path(
        "suplencias/incidencias/<int:incidencia_id>/revisar/",
        views.revisar_incidencia_suplencia,
        name="revisar_incidencia_suplencia",
    ),
    path(
        "suplencias/trabajo-social/<int:inscripcion_id>/revisar/",
        views.revisar_trabajo_social_suplencia,
        name="revisar_trabajo_social_suplencia",
    ),

    # Bloqueos temporales de edición por expediente/objeto
    path(
        "suplencias/bloqueos/ping/",
        views.ping_bloqueo_edicion,
        name="ping_bloqueo_edicion",
    ),
    path(
        "suplencias/bloqueos/<int:bloqueo_id>/liberar/",
        views.liberar_bloqueo_edicion,
        name="liberar_bloqueo_edicion",
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
    # =========================================================
    # CÓDIGOS DE SEGURIDAD POR RESPONSABLE AUTORIZADO
    # Trabajo Social
    #
    # Regla actual:
    # - El código ya no es uno solo por alumno.
    # - Cada tutor o familiar autorizado tiene su propio código.
    # - La persona se selecciona desde la vista usando el parámetro:
    #       ?responsable_codigo_id=<id>
    #
    # Se conservan los mismos nombres de rutas para no romper templates,
    # botones existentes ni llamadas con reverse().
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
    path("semestres/<int:semestre_id>/clonar/", views.clonar_semestre, name="clonar_semestre"),
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
        "semestres/salas-semestre/",
        redirigir_salas_semestre_a_detalle,
        name="redirigir_salas_semestre_a_detalle",
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
    path(
        "semestres/<int:semestre_id>/encuesta/csv/",
        views.descargar_csv_encuesta_satisfaccion,
        name="descargar_csv_encuesta_satisfaccion",
    ),
    path(
        "semestres/encuesta/envio/<int:envio_id>/reenviar/",
        views.reenviar_encuesta_satisfaccion,
        name="reenviar_encuesta_satisfaccion",
    ),
    path(
        "semestres/encuesta/envio/<int:envio_id>/respuesta/",
        views.ver_respuesta_encuesta_satisfaccion,
        name="ver_respuesta_encuesta_satisfaccion",
    ),
    path(
        "encuesta-satisfaccion/<uuid:token>/",
        views.responder_encuesta_satisfaccion,
        name="responder_encuesta_satisfaccion",
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

    # Apoyo temporal de sala entre maestras
    path(
        "operacion-diaria/apoyar-sala/",
        views.iniciar_apoyo_sala,
        name="iniciar_apoyo_sala",
    ),
    path(
        "operacion-diaria/finalizar-apoyo-sala/",
        views.finalizar_apoyo_sala,
        name="finalizar_apoyo_sala",
    ),

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

    # Autorización de entrada por correo institucional o QR
    path(
        "operacion-diaria/autorizacion-entrada/<int:autorizacion_id>/cancelar/",
        views.cancelar_autorizacion_entrada_maestra,
        name="cancelar_autorizacion_entrada_maestra",
    ),
    path(
        "operacion-diaria/registro/<int:registro_id>/entrada/estado-autorizacion/",
        views.estado_autorizacion_entrada_maestra,
        name="estado_autorizacion_entrada_maestra",
    ),
    # Enlace público corto por token para autorizar entrada.
    # No expone datos personales en la URL; solo usa el token único.
    path(
        "a/e/<uuid:token>/",
        views.autorizar_entrada_responsable,
        name="autorizar_entrada_responsable",
    ),

    # Ruta anterior conservada solo por compatibilidad con enlaces ya generados.
    path(
        "operacion-diaria/entrada/autorizar/<uuid:token>/",
        views.autorizar_entrada_responsable,
        name="autorizar_entrada_responsable_legacy",
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

    # Autorización de salida por correo institucional o QR
    path(
        "operacion-diaria/autorizacion-salida/<int:autorizacion_id>/cancelar/",
        views.cancelar_autorizacion_salida_maestra,
        name="cancelar_autorizacion_salida_maestra",
    ),
    path(
        "operacion-diaria/registro/<int:registro_id>/salida/estado-autorizacion/",
        views.estado_autorizacion_salida_maestra,
        name="estado_autorizacion_salida_maestra",
    ),
    # Enlace público corto por token para autorizar salida.
    # No expone datos personales en la URL; solo usa el token único.
    path(
        "a/s/<uuid:token>/",
        views.autorizar_salida_responsable,
        name="autorizar_salida_responsable",
    ),

    # Ruta anterior conservada solo por compatibilidad con enlaces ya generados.
    path(
        "operacion-diaria/salida/autorizar/<uuid:token>/",
        views.autorizar_salida_responsable,
        name="autorizar_salida_responsable_legacy",
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