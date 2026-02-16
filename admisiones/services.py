import os
from django.conf import settings
from docx import Document
from docx2pdf import convert

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

    mapping = {
        "{{identificador}}": f"EI-{solicitud.created_at.year}-{str(solicitud.folio)[:8].upper()}",
        "{{fecha}}": solicitud.created_at.strftime("%d/%m/%Y"),

        "{{nombre_beneficiario}}": solicitud.nombre_beneficiario,
        "{{matricula}}": solicitud.matricula,
        "{{programa_educativo}}": solicitud.programa_educativo,
        "{{unidad_academica}}": solicitud.unidad_academica,
        "{{correo_beneficiario}}": solicitud.correo_beneficiario,
        "{{domicilio_beneficiario}}": solicitud.domicilio_beneficiario,
        "{{celular_beneficiario}}": solicitud.celular_beneficiario,
        "{{parentesco_con_menor}}": solicitud.parentesco_con_menor,

        "{{nombre_menor}}": solicitud.nombre_menor,
        "{{fecha_nacimiento}}": solicitud.fecha_nacimiento.strftime("%d/%m/%Y") if solicitud.fecha_nacimiento else "",
        "{{curp_menor}}": solicitud.curp_menor,
    }

    _replace(doc, mapping)

    out_docx_dir = os.path.join(settings.MEDIA_ROOT, "solicitudes", "docx")
    out_pdf_dir = os.path.join(settings.MEDIA_ROOT, "solicitudes", "pdf")
    os.makedirs(out_docx_dir, exist_ok=True)
    os.makedirs(out_pdf_dir, exist_ok=True)

    out_docx_path = os.path.join(out_docx_dir, f"Solicitud_{solicitud.folio}.docx")
    out_pdf_path = os.path.join(out_pdf_dir, f"Solicitud_{solicitud.folio}.pdf")

    doc.save(out_docx_path)
    convert(out_docx_path, out_pdf_path)

    return f"solicitudes/pdf/Solicitud_{solicitud.folio}.pdf"
