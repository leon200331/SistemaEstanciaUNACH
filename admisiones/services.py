import os
import pythoncom
from django.conf import settings
from docx import Document
from docx2pdf import convert
from django.utils import timezone  # <-- IMPORTACIÓN NUEVA (Necesaria para la fecha de la carta)


def _replace(doc: Document, mapping: dict):
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

    # CORRECCIÓN: Conectando con los nombres EXACTOS del models.py
    mapping = {
        "{{identificador}}": f"EI-{solicitud.created_at.year}-{str(solicitud.folio).zfill(4)}",
        "{{fecha}}": solicitud.created_at.strftime("%d/%m/%Y"),

        "{{nombre_beneficiario}}": solicitud.nombre_tutor_completo(),  # Corregido
        "{{matricula}}": getattr(solicitud, 'matricula', ''),
        "{{programa_educativo}}": getattr(solicitud, 'programa_educativo', ''),
        "{{unidad_academica}}": getattr(solicitud, 'unidad_academica', ''),
        "{{correo_beneficiario}}": getattr(solicitud, 'correo', ''),  # Corregido
        "{{domicilio_beneficiario}}": getattr(solicitud, 'domicilio', ''),  # Corregido
        "{{celular_beneficiario}}": getattr(solicitud, 'celular', ''),  # Corregido
        "{{parentesco_con_menor}}": getattr(solicitud, 'parentesco', ''),  # Corregido

        # Nota: En el models.py original no existía 'nombre_menor', usamos getattr para evitar que crashee
        "{{nombre_menor}}": getattr(solicitud, 'nombre_menor', ''),
        "{{fecha_nacimiento}}": solicitud.fecha_nacimiento_menor.strftime(
            "%d/%m/%Y") if solicitud.fecha_nacimiento_menor else "",  # Corregido
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
        # AQUÍ ESTÁ LA LÍNEA MÁGICA PARA WINDOWS
        pythoncom.CoInitialize()
        convert(out_docx_path, out_pdf_path)

        # --- LÍNEAS LIMPIADORAS: Borra el Word (docx) basura para ahorrar espacio ---
        if os.path.exists(out_docx_path):
            os.remove(out_docx_path)

    except Exception as e:
        print(f"Error en la conversión de DOCX a PDF: {e}")

    return f"solicitudes/pdf/Solicitud_{solicitud.folio}.pdf"


# =========================================================
# NUEVA FUNCIÓN: GENERAR CARTA DE DICTAMEN (ACEPTADA O RECHAZADA)
# =========================================================
def generar_pdf_dictamen(solicitud):
    # 1. Elegimos qué documento abrir según el estatus
    if solicitud.estado == "APROBADA":
        template_name = "Carta_Aceptacion_Template.docx"
        dictamen_texto = "APROBADO"
    else:
        template_name = "Carta_Rechazo_Template.docx"
        dictamen_texto = "RECHAZADA"

    template_path = os.path.join(settings.BASE_DIR, "plantillas", template_name)

    # Verificamos que el archivo exista para no dar error
    if not os.path.exists(template_path):
        print(f"ERROR: No se encontró la plantilla {template_path}")
        return None

    doc = Document(template_path)

    # 2. Preparamos las variables mágicas
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

    # 3. Guardamos el archivo
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

        # --- LÍNEAS LIMPIADORAS: Borra el Word (docx) basura para ahorrar espacio ---
        if os.path.exists(out_docx_path):
            os.remove(out_docx_path)

    except Exception as e:
        print(f"Error en la conversión de DOCX a PDF (Dictamen): {e}")

    # Retorna la ruta absoluta para poder adjuntarla en el correo de views.py
    return out_pdf_path