import os
import pythoncom
from django.conf import settings
from docx import Document
from docx2pdf import convert
from django.utils import timezone

# --- NUEVAS HERRAMIENTAS PARA HTML A PDF ---
from django.template.loader import render_to_string
from xhtml2pdf import pisa


def link_callback(uri, rel):
    """
    Convierte rutas de HTML (como static/img/logo.png) en rutas absolutas del sistema
    para que xhtml2pdf pueda encontrar las imágenes físicamente en el disco.
    """
    if uri.startswith(settings.STATIC_URL):
        path = os.path.join(settings.BASE_DIR, uri.replace(settings.STATIC_URL, 'static/'))
    elif uri.startswith(settings.MEDIA_URL):
        path = os.path.join(settings.MEDIA_ROOT, uri.replace(settings.MEDIA_URL, ''))
    else:
        # Intento de respaldo para rutas directas como 'static/img/...'
        path = os.path.join(settings.BASE_DIR, uri)

    return path


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
        "{{fecha_nacimiento}}": solicitud.fecha_nacimiento_menor.strftime("%d/%m/%Y") if getattr(solicitud, 'fecha_nacimiento_menor', None) else "",
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

    # EL CAMBIO SE HIZO AQUÍ ABAJO: Devolver la ruta correcta
    return out_pdf_path


# =========================================================
# NUEVA FUNCIÓN OPTIMIZADA (SIN WORD, SOLO HTML)
# =========================================================
def generar_pdf_dictamen(solicitud):
    """
    Genera el dictamen de Aprobado/Rechazado directamente a PDF usando HTML.
    Cero basura de Word y 100% compatible con servidores web.
    """
    # 1. Preparamos los datos que irán en el PDF
    estado_texto = "APROBADA" if solicitud.estado == "APROBADA" else "RECHAZADA"
    comentarios = solicitud.comentario_respuesta if solicitud.comentario_respuesta else "Cumple con los requisitos establecidos por la EIU."
    nombre_tutor = f"{solicitud.nombres_tutor} {solicitud.apellido_paterno_tutor} {solicitud.apellido_materno_tutor}"

    context = {
        "solicitud": solicitud,
        "nombre_tutor": nombre_tutor,
        "dictamen": estado_texto,
        "comentarios": comentarios,
        "fecha_hoy": timezone.now(),
    }

    # 2. Renderizamos la plantilla HTML a código puro
    html = render_to_string("admisiones/dictamen_pdf.html", context)

    # 3. Preparamos la ruta limpia para guardar el PDF final
    out_pdf_dir = os.path.join(settings.MEDIA_ROOT, "dictamenes", "pdf")
    os.makedirs(out_pdf_dir, exist_ok=True)
    out_pdf_path = os.path.join(out_pdf_dir, f"Dictamen_{solicitud.folio}.pdf")

    # 4. Fabricamos el PDF en milisegundos con link_callback para los logos
    with open(out_pdf_path, "w+b") as result_file:
        pisa_status = pisa.CreatePDF(html, dest=result_file, link_callback=link_callback)

    if pisa_status.err:
        print(f"Error al generar el PDF HTML del dictamen {solicitud.folio}")
        return None

    return out_pdf_path


# =========================================================
# NUEVA VERSIÓN: HOJA DE INSCRIPCIÓN (USANDO HTML Y TABLAS)
# =========================================================
def generar_pdf_inscripcion_lleno(inscripcion):
    """
    Toma los datos del expediente y genera un PDF con diseño de cuadrícula (tablitas)
    usando HTML. Cero dependencias de Word.
    """
    s = inscripcion.solicitud_ingreso

    # Preparamos las direcciones
    calle = getattr(s, 'calle', '')
    num_ext = getattr(s, 'numero_exterior', '')
    num_int = getattr(s, 'numero_interior', '')
    cp = getattr(s, 'codigo_postal', '')
    ciudad = getattr(s, 'ciudad', '')
    estado_dom = getattr(s, 'estado_domicilio', '')
    domicilio_tutor = f"{calle} {num_ext} {num_int}, C.P. {cp}, {ciudad}, {estado_dom}".replace("None", "").replace("  ", " ").strip(", ")

    calle_p2 = getattr(inscripcion, 'calle_segundo_padre', '')
    num_ext_p2 = getattr(inscripcion, 'numero_exterior_segundo_padre', '')
    num_int_p2 = getattr(inscripcion, 'numero_interior_segundo_padre', '')
    cp_p2 = getattr(inscripcion, 'codigo_postal_segundo_padre', '')
    ciudad_p2 = getattr(inscripcion, 'ciudad_segundo_padre', '')
    estado_p2 = getattr(inscripcion, 'estado_domicilio_segundo_padre', '')
    domicilio_segundo = f"{calle_p2} {num_ext_p2} {num_int_p2}, C.P. {cp_p2}, {ciudad_p2}, {estado_p2}".replace("None", "").replace("  ", " ").strip(", ")

    # Empaquetamos todo para enviarlo al HTML
    context = {
        "inscripcion": inscripcion,
        "s": s,
        "domicilio_tutor": domicilio_tutor,
        "domicilio_segundo": domicilio_segundo if getattr(inscripcion, 'nombres_segundo_padre', '') else "No aplica",
        "fecha_hoy": timezone.now(),
    }

    # Renderizamos el nuevo HTML
    html = render_to_string("admisiones/hoja_inscripcion_pdf.html", context)

    # Preparamos la carpeta y el nombre del archivo
    out_pdf_dir = os.path.join(settings.MEDIA_ROOT, "expedientes_llenos", "pdf")
    os.makedirs(out_pdf_dir, exist_ok=True)

    nombre_base = f"Expediente_{s.folio}_{getattr(s, 'apellido_paterno_tutor', 'Usuario')}"
    out_pdf_path = os.path.join(out_pdf_dir, f"{nombre_base}.pdf")

    # Creamos el PDF mágicamente con link_callback para los logos
    with open(out_pdf_path, "w+b") as result_file:
        pisa_status = pisa.CreatePDF(html, dest=result_file, link_callback=link_callback)

    if pisa_status.err:
        print(f"Error fatal al convertir Expediente a PDF HTML: {s.folio}")
        return None

    return out_pdf_path