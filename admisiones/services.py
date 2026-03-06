import os
import pythoncom
from django.conf import settings
from docx import Document
from docx2pdf import convert
from django.utils import timezone


def _replace(doc: Document, mapping: dict):
    """Función maestra que busca y reemplaza texto en párrafos y tablas del Word."""
    for p in doc.paragraphs:
        for k, v in mapping.items():
            if k in p.text:
                for run in p.runs:
                    if k in run.text:
                        run.text = run.text.replace(k, str(v))

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for k, v in mapping.items():
                        if k in p.text:
                            for run in p.runs:
                                if k in run.text:
                                    run.text = run.text.replace(k, str(v))


def generar_pdf_fo301(solicitud):
    template_path = os.path.join(settings.BASE_DIR, "plantillas", "FO-301-02-01_template.docx")
    doc = Document(template_path)

    mapping = {
        "{{identificador}}": f"EI-{solicitud.created_at.year}-{str(solicitud.folio).zfill(4)}",
        "{{fecha}}": solicitud.created_at.strftime("%d/%m/%Y"),

        "{{nombre_beneficiario}}": solicitud.nombre_tutor_completo(),
        "{{matricula}}": getattr(solicitud, 'matricula', ''),
        "{{programa_educativo}}": getattr(solicitud, 'programa_educativo', ''),
        "{{unidad_academica}}": getattr(solicitud, 'unidad_academica', ''),
        "{{correo_beneficiario}}": getattr(solicitud, 'correo', ''),
        "{{domicilio_beneficiario}}": f"{solicitud.calle} {solicitud.numero_exterior}, {solicitud.ciudad}, {solicitud.estado_domicilio}",
        "{{celular_beneficiario}}": getattr(solicitud, 'celular', ''),
        "{{parentesco_con_menor}}": getattr(solicitud, 'parentesco', ''),

        "{{nombre_menor}}": getattr(solicitud, 'nombres_menor', ''),
        "{{fecha_nacimiento}}": solicitud.fecha_nacimiento_menor.strftime("%d/%m/%Y") if getattr(solicitud,
                                                                                                 'fecha_nacimiento_menor',
                                                                                                 None) else "",
        "{{curp_menor}}": getattr(solicitud, 'curp_menor', ''),
    }

    _replace(doc, mapping)

    out_docx_dir = os.path.join(settings.MEDIA_ROOT, "solicitudes", "docx")
    out_pdf_dir = os.path.join(settings.MEDIA_ROOT, "solicitudes", "pdf")
    os.makedirs(out_docx_dir, exist_ok=True)
    os.makedirs(out_pdf_dir, exist_ok=True)

    out_docx_path = os.path.join(out_docx_dir, f"Solicitud_{solicitud.folio}.docx")
    out_pdf_path = os.path.join(out_pdf_dir, f"Solicitud_{solicitud.folio}.pdf")

    doc.save(out_docx_path)

    try:
        pythoncom.CoInitialize()
        convert(out_docx_path, out_pdf_path)

        if os.path.exists(out_docx_path):
            os.remove(out_docx_path)

    except Exception as e:
        print(f"Error en la conversión de DOCX a PDF: {e}")

    return f"solicitudes/pdf/Solicitud_{solicitud.folio}.pdf"


def generar_pdf_dictamen(solicitud):
    if solicitud.estado == "APROBADA":
        template_name = "Carta_Aceptacion_Template.docx"
        dictamen_texto = "APROBADO"
    else:
        template_name = "Carta_Rechazo_Template.docx"
        dictamen_texto = "RECHAZADA"

    template_path = os.path.join(settings.BASE_DIR, "plantillas", template_name)

    if not os.path.exists(template_path):
        print(f"ERROR: No se encontró la plantilla {template_path}")
        return None

    doc = Document(template_path)

    comentarios = solicitud.comentario_respuesta if solicitud.comentario_respuesta else "Cumple con los requisitos establecidos por la EIU."
    nombre_tutor = solicitud.nombre_tutor_completo() if hasattr(solicitud,
                                                                "nombre_tutor_completo") else f"{solicitud.nombres_tutor} {solicitud.apellido_paterno_tutor}"

    mapping = {
        "{{folio}}": str(solicitud.folio),
        "{{fecha}}": timezone.now().strftime("%d/%m/%Y"),
        "{{nombre_tutor}}": nombre_tutor,
        "{{dictamen}}": dictamen_texto,
        "{{comentarios}}": comentarios,
    }

    _replace(doc, mapping)

    out_docx_dir = os.path.join(settings.MEDIA_ROOT, "dictamenes", "docx")
    out_pdf_dir = os.path.join(settings.MEDIA_ROOT, "dictamenes", "pdf")
    os.makedirs(out_docx_dir, exist_ok=True)
    os.makedirs(out_pdf_dir, exist_ok=True)

    out_docx_path = os.path.join(out_docx_dir, f"Dictamen_{solicitud.folio}.docx")
    out_pdf_path = os.path.join(out_pdf_dir, f"Dictamen_{solicitud.folio}.pdf")

    doc.save(out_docx_path)

    try:
        pythoncom.CoInitialize()
        convert(out_docx_path, out_pdf_path)

        if os.path.exists(out_docx_path):
            os.remove(out_docx_path)

    except Exception as e:
        print(f"Error en la conversión de DOCX a PDF (Dictamen): {e}")

    return out_pdf_path


# =========================================================
# NUEVA FUNCIÓN: GENERAR HOJA DE INSCRIPCIÓN COMPLETADA
# =========================================================
def generar_pdf_inscripcion_lleno(inscripcion):
    """
    Toma los datos del expediente de inscripción (beneficiario, menor, contactos)
    y los plasma sobre la plantilla Word para generar un PDF listo para imprimir.
    """
    template_path = os.path.join(settings.BASE_DIR, "plantillas", "Hoja_Inscripcion_Template.docx")

    if not os.path.exists(template_path):
        print(f"ERROR: No se encontró la plantilla {template_path}")
        return None

    doc = Document(template_path)
    s = inscripcion.solicitud_ingreso  # Atajo para acceder a la info original rápida

    # Formateo de domicilios blindado (usando getattr para evitar crasheos si falta algo)
    calle = getattr(s, 'calle', '')
    num_ext = getattr(s, 'numero_exterior', '')
    num_int = getattr(s, 'numero_interior', '')
    cp = getattr(s, 'codigo_postal', '')
    ciudad = getattr(s, 'ciudad', '')
    estado_dom = getattr(s, 'estado_domicilio', '')

    domicilio_tutor = f"{calle} {num_ext} {num_int}, C.P. {cp}, {ciudad}, {estado_dom}"

    calle_p2 = getattr(inscripcion, 'calle_segundo_padre', '')
    num_ext_p2 = getattr(inscripcion, 'numero_exterior_segundo_padre', '')
    num_int_p2 = getattr(inscripcion, 'numero_interior_segundo_padre', '')
    cp_p2 = getattr(inscripcion, 'codigo_postal_segundo_padre', '')
    ciudad_p2 = getattr(inscripcion, 'ciudad_segundo_padre', '')
    estado_p2 = getattr(inscripcion, 'estado_domicilio_segundo_padre', '')

    domicilio_segundo = f"{calle_p2} {num_ext_p2} {num_int_p2}, C.P. {cp_p2}, {ciudad_p2}, {estado_p2}"

    # Diccionario de variables mágicas a reemplazar en el Word
    mapping = {
        "{{fecha_hoy}}": timezone.now().strftime("%d/%m/%Y"),
        "{{folio}}": str(s.folio),

        # 1. Beneficiario
        "{{t_nombre}}": getattr(s, 'nombres_tutor', ''),
        "{{t_ap_pat}}": getattr(s, 'apellido_paterno_tutor', ''),
        "{{t_ap_mat}}": getattr(s, 'apellido_materno_tutor', ''),
        "{{t_matri}}": getattr(s, 'matricula', ''),
        "{{t_prog}}": getattr(s, 'programa_educativo', ''),
        "{{t_uni}}": getattr(s, 'unidad_academica', ''),
        "{{t_avan}}": getattr(inscripcion, 'avance_academico', ''),
        "{{t_correo}}": getattr(s, 'correo', ''),
        "{{t_dom}}": domicilio_tutor.replace("None", "").replace("  ", " ").strip(", "),
        "{{t_cel}}": getattr(s, 'celular', ''),
        "{{t_civil}}": getattr(inscripcion, 'estado_civil_tutor', ''),
        "{{t_paren}}": getattr(inscripcion, 'parentesco_tutor', ''),

        # 2. Menor
        "{{m_nombre}}": getattr(s, 'nombres_menor', ''),
        "{{m_ap_pat}}": getattr(s, 'apellido_paterno_menor', ''),
        "{{m_ap_mat}}": getattr(s, 'apellido_materno_menor', ''),
        "{{m_edad_a}}": str(getattr(inscripcion, 'edad_anios_menor', '')),
        "{{m_edad_m}}": str(getattr(inscripcion, 'edad_meses_menor', '')),
        "{{m_lugar}}": f"{getattr(inscripcion, 'municipio_nacimiento_menor', '')}, {getattr(inscripcion, 'estado_nacimiento_menor', '')}",
        "{{m_fecha}}": s.fecha_nacimiento_menor.strftime("%d/%m/%Y") if getattr(s, 'fecha_nacimiento_menor',
                                                                                None) else "",
        "{{m_sexo}}": getattr(inscripcion, 'sexo_menor', ''),
        "{{m_sangre}}": getattr(inscripcion, 'tipo_sangre_menor', ''),
        "{{m_curp}}": getattr(s, 'curp_menor', ''),

        # 3. Segundo Padre
        "{{p2_nombre}}": getattr(inscripcion, 'nombres_segundo_padre', ''),
        "{{p2_ap_pat}}": getattr(inscripcion, 'apellido_paterno_segundo_padre', ''),
        "{{p2_ap_mat}}": getattr(inscripcion, 'apellido_materno_segundo_padre', ''),
        "{{p2_civil}}": getattr(inscripcion, 'estado_civil_segundo_padre', ''),
        "{{p2_ocupa}}": getattr(inscripcion, 'ocupacion_segundo_padre', ''),
        "{{p2_dom}}": domicilio_segundo.replace("None", "").replace("  ", " ").strip(", "),
        "{{p2_cel}}": getattr(inscripcion, 'celular_segundo_padre', ''),
        "{{p2_correo}}": getattr(inscripcion, 'correo_segundo_padre', ''),

        # 4. Familiares
        "{{f1_tel}}": getattr(inscripcion, 'contacto_1_telefono', ''),
        "{{f1_nom}}": getattr(inscripcion, 'contacto_1_nombres', ''),
        "{{f1_pat}}": getattr(inscripcion, 'contacto_1_apellido_paterno', ''),
        "{{f1_mat}}": getattr(inscripcion, 'contacto_1_apellido_materno', ''),
        "{{f1_par}}": getattr(inscripcion, 'contacto_1_parentesco', ''),

        "{{f2_tel}}": getattr(inscripcion, 'contacto_2_telefono', ''),
        "{{f2_nom}}": getattr(inscripcion, 'contacto_2_nombres', ''),
        "{{f2_pat}}": getattr(inscripcion, 'contacto_2_apellido_paterno', ''),
        "{{f2_mat}}": getattr(inscripcion, 'contacto_2_apellido_materno', ''),
        "{{f2_par}}": getattr(inscripcion, 'contacto_2_parentesco', ''),

        "{{f3_tel}}": getattr(inscripcion, 'contacto_3_telefono', ''),
        "{{f3_nom}}": getattr(inscripcion, 'contacto_3_nombres', ''),
        "{{f3_pat}}": getattr(inscripcion, 'contacto_3_apellido_paterno', ''),
        "{{f3_mat}}": getattr(inscripcion, 'contacto_3_apellido_materno', ''),
        "{{f3_par}}": getattr(inscripcion, 'contacto_3_parentesco', ''),
    }

    _replace(doc, mapping)

    # Creamos las carpetas si no existen
    out_docx_dir = os.path.join(settings.MEDIA_ROOT, "expedientes_llenos", "docx")
    out_pdf_dir = os.path.join(settings.MEDIA_ROOT, "expedientes_llenos", "pdf")
    os.makedirs(out_docx_dir, exist_ok=True)
    os.makedirs(out_pdf_dir, exist_ok=True)

    # Nombres de archivos finales
    nombre_base = f"Expediente_{s.folio}_{getattr(s, 'apellido_paterno_tutor', 'Usuario')}"
    out_docx_path = os.path.join(out_docx_dir, f"{nombre_base}.docx")
    out_pdf_path = os.path.join(out_pdf_dir, f"{nombre_base}.pdf")

    # Guardamos el Word temporal
    doc.save(out_docx_path)

    # Lo convertimos a PDF
    try:
        pythoncom.CoInitialize()
        convert(out_docx_path, out_pdf_path)

        # Borramos el Word para no llenar el servidor de basura
        if os.path.exists(out_docx_path):
            os.remove(out_docx_path)

    except Exception as e:
        print(f"Error fatal al convertir Expediente a PDF: {e}")
        return None

    # Devolvemos la ruta final para que views.py se la entregue al usuario
    return out_pdf_path