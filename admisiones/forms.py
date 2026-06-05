from django import forms
from datetime import date, timedelta
import re
import secrets
import unicodedata
from django.forms import Select, SelectMultiple, RadioSelect
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db.models import Q

# Se unificaron las importaciones conflictivas aquí:
from .models import (
    Solicitud,
    SolicitudInscripcion,
    CodigoResponsableAutorizado,
    AutorizacionEntrada,
    AutorizacionSalida,
    es_correo_institucional,
    HistoriaClinicaMedica,
    Sede,
    Semestre,
    DiaFestivo,
    Sala,
    SalaSemestre,
    AsignacionMaestra,
    DiaOperativoSemestre,
    RegistroDiarioAlumno,
    BitacoraEntradaCasa,
    BitacoraEstancia,
    EncuestaSatisfaccion,
    Incidencia,
    IncidenciaArchivo,
    SeguimientoIncidencia,
    SeguimientoIncidenciaArchivo,
    AsistenciaPersonal,
    AutorizacionSuplencia,
    MovimientoSuplencia,
    BitacoraLactante,
    BitacoraMaternal,
)


# --- CLASE ESPECIAL PARA PERMITIR ETIQUETAS NUEVAS (SELECT2) ---
class DynamicMultipleChoiceField(forms.MultipleChoiceField):
    def valid_value(self, value):
        return True  # Permite guardar cualquier alimento que la nutrióloga escriba


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if not data:
            return []

        if isinstance(data, (list, tuple)):
            return [super(MultipleFileField, self).clean(d, initial) for d in data]

        return [super().clean(data, initial)]


# =========================================================
# AUXILIARES VISUALES PARA DATOS COMPARTIDOS ENTRE FILTROS
# =========================================================
def _valor_formulario_vacio(valor):
    """
    True cuando el dato todavía no tiene información útil.
    Sirve para desbloquear campos compartidos cuando ningún filtro los ha capturado.
    """
    if valor is None:
        return True

    valor = str(valor).strip()
    return valor == "" or valor.lower() in ["none", "null", "sin datos", "no capturado"]


def _agregar_estilo_widget(field, estilo_extra):
    estilo_actual = field.widget.attrs.get("style", "")
    if estilo_actual and not estilo_actual.endswith(";"):
        estilo_actual += ";"
    field.widget.attrs["style"] = f"{estilo_actual} {estilo_extra}".strip()


def _bloquear_widget_solo_lectura(field, titulo="Dato tomado de otro filtro"):
    """
    Bloqueo visual sin usar field.disabled=True.
    Así el valor sigue viajando en POST y views.py puede protegerlo en backend.
    """
    field.widget.attrs["readonly"] = "readonly"
    field.widget.attrs["data-solo-lectura"] = "true"
    field.widget.attrs["title"] = titulo
    _agregar_estilo_widget(field, "background-color: #e9ecef; pointer-events: none;")

    if isinstance(field.widget, (forms.Select, forms.SelectMultiple, forms.CheckboxSelectMultiple)):
        field.widget.attrs["tabindex"] = "-1"


def _marcar_widget_dato_compartido(field, clave=""):
    field.widget.attrs["data-dato-compartido"] = "true"
    if clave:
        field.widget.attrs["data-clave-compartida"] = clave


def limpiar_correo(valor):
    """
    Normaliza correos capturados en formularios:
    - Quita espacios al inicio y al final.
    - Quita espacios internos accidentales.
    - Convierte a minúsculas.

    Ejemplos:
    " mama@unach.mx "  -> "mama@unach.mx"
    "mama @unach.mx"   -> "mama@unach.mx"
    "mama@ unach.mx"   -> "mama@unach.mx"
    """
    correo = (valor or "").strip().lower()
    correo = re.sub(r"\s+", "", correo)
    return correo


class CorreoInstitucionalField(forms.CharField):
    """
    Campo de correo institucional que limpia espacios antes de validar.
    Se usa en formularios donde el usuario puede escribir correos.
    La validación de dominio @unach.mx se mantiene en clean_correo()
    o clean_correo_copia*() de cada formulario.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", forms.EmailInput())
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        return limpiar_correo(value)


class CapturaSolicitudForm(forms.ModelForm):
    correo = CorreoInstitucionalField(
        required=False,
        widget=forms.EmailInput(attrs={
            "readonly": "readonly",
            "style": "background-color: #e9ecef; pointer-events: none;",
        })
    )

    # --- LÍNEAS AGREGADAS PARA QUITAR EL CANDADO ESTRICTO ---
    programa_educativo = forms.CharField(max_length=250, required=True)
    estado_domicilio = forms.CharField(max_length=100, required=True)
    ciudad = forms.CharField(max_length=100, required=True)

    class Meta:
        model = Solicitud
        fields = [
            "nombres_tutor", "apellido_paterno_tutor", "apellido_materno_tutor",
            "matricula", "programa_educativo", "programa_educativo_otro",
            "correo", "celular", "estado_domicilio", "ciudad", "codigo_postal",
            "calle", "numero_exterior", "numero_interior", "parentesco",
            "parentesco_otro", "nombres_menor", "apellido_paterno_menor",
            "apellido_materno_menor", "fecha_nacimiento_menor", "curp_menor",
        ]
        widgets = {
            # ✅ BLOQUEADOS: Datos del tutor y correo ya no se modifican
            "nombres_tutor": forms.TextInput(
                attrs={"readonly": "readonly", "style": "background-color: #e9ecef; pointer-events: none;"}),
            "apellido_paterno_tutor": forms.TextInput(
                attrs={"readonly": "readonly", "style": "background-color: #e9ecef; pointer-events: none;"}),
            "apellido_materno_tutor": forms.TextInput(
                attrs={"readonly": "readonly", "style": "background-color: #e9ecef; pointer-events: none;"}),
            "correo": forms.EmailInput(
                attrs={"readonly": "readonly", "style": "background-color: #e9ecef; pointer-events: none;"}),
            "matricula": forms.TextInput(
                attrs={"readonly": "readonly", "style": "background-color: #e9ecef; pointer-events: none;"}),

            "programa_educativo": forms.TextInput(attrs={
                "list": "lista_carreras", "placeholder": "Escribe o selecciona tu carrera...", "autocomplete": "off"
            }),
            "programa_educativo_otro": forms.TextInput(attrs={"placeholder": "Especifica el programa educativo"}),
            "celular": forms.TextInput(attrs={"placeholder": "10 dígitos"}),
            "estado_domicilio": forms.TextInput(attrs={"placeholder": "Ej. Chiapas"}),
            "ciudad": forms.TextInput(attrs={"placeholder": "Ej. Tuxtla Gutiérrez"}),
            "codigo_postal": forms.TextInput(attrs={"placeholder": "Ej. 29000"}),
            "calle": forms.TextInput(attrs={"placeholder": "Ej. Av. Central"}),
            "numero_exterior": forms.TextInput(attrs={"placeholder": "Solo números"}),
            "numero_interior": forms.TextInput(attrs={"placeholder": "Solo números (Opcional)"}),
            "parentesco": forms.Select(),
            "parentesco_otro": forms.TextInput(attrs={"placeholder": "Especifica el parentesco"}),

            # --- CAMPOS DEL MENOR ---
            "nombres_menor": forms.TextInput(attrs={"placeholder": "Ej. María Guadalupe"}),
            "apellido_paterno_menor": forms.TextInput(attrs={"placeholder": "Ej. Pérez"}),
            "apellido_materno_menor": forms.TextInput(attrs={"placeholder": "Ej. López"}),

            "fecha_nacimiento_menor": forms.DateInput(attrs={"type": "date"}),
            "curp_menor": forms.TextInput(attrs={"placeholder": "18 caracteres"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _, field in self.fields.items():
            css = field.widget.attrs.get("class", "")
            base_class = "form-select w-100" if isinstance(field.widget,
                                                           (Select, SelectMultiple)) else "form-control w-100"
            field.widget.attrs["class"] = f"{css} {base_class}".strip()

        # Requeridos Tutor
        self.fields["nombres_tutor"].required = True
        self.fields["apellido_paterno_tutor"].required = True
        self.fields["parentesco"].required = True

        # Requeridos Menor
        self.fields["nombres_menor"].required = True
        self.fields["apellido_paterno_menor"].required = True
        # ✅ AHORA ES OBLIGATORIO (Se activa el asterisco rojo en HTML)
        self.fields["apellido_materno_menor"].required = True

        self.fields["fecha_nacimiento_menor"].required = True
        self.fields["estado_domicilio"].required = True
        self.fields["ciudad"].required = True
        self.fields["calle"].required = True
        # ✅ AHORA ES OBLIGATORIO
        self.fields["numero_exterior"].required = True

    # Validaciones Tutor (Readonly, mantenemos por seguridad interna)
    def clean_nombres_tutor(self):
        v = (self.cleaned_data.get("nombres_tutor") or "").strip()
        return v.title()

    def clean_apellido_paterno_tutor(self):
        v = (self.cleaned_data.get("apellido_paterno_tutor") or "").strip()
        return v.title()

    def clean_apellido_materno_tutor(self):
        v = (self.cleaned_data.get("apellido_materno_tutor") or "").strip()
        return v.title() if v else v

    # ✅ VALIDACIONES PARA LOS NOMBRES DEL MENOR (Auto-capitalización y sin números)
    def clean_nombres_menor(self):
        v = (self.cleaned_data.get("nombres_menor") or "").strip()
        if len(v) < 2: raise forms.ValidationError("Ingresa un nombre válido.")
        if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+", v):
            raise forms.ValidationError("El nombre solo debe contener letras y espacios.")
        return v.title()

    def clean_apellido_paterno_menor(self):
        v = (self.cleaned_data.get("apellido_paterno_menor") or "").strip()
        if len(v) < 2: raise forms.ValidationError("Ingresa un apellido paterno válido.")
        if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+", v):
            raise forms.ValidationError("Solo letras y espacios.")
        return v.title()

    def clean_apellido_materno_menor(self):
        v = (self.cleaned_data.get("apellido_materno_menor") or "").strip()
        if not v: raise forms.ValidationError("Este campo es obligatorio.")
        if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+", v):
            raise forms.ValidationError("Solo letras y espacios.")
        return v.title()

    # ✅ VALIDACIONES DE DIRECCIÓN (Solo números)
    def clean_numero_exterior(self):
        v = (self.cleaned_data.get("numero_exterior") or "").strip()
        if not re.fullmatch(r"\d+", v):
            raise forms.ValidationError("Solo se permiten números en este campo.")
        return v

    def clean_numero_interior(self):
        v = (self.cleaned_data.get("numero_interior") or "").strip()
        if v and not re.fullmatch(r"\d+", v):
            raise forms.ValidationError("Solo se permiten números en este campo.")
        return v

    def clean_correo(self):
        correo = limpiar_correo(self.cleaned_data.get("correo"))
        if correo and ("@" not in correo):
            raise forms.ValidationError("El correo debe contener el símbolo @.")
        if correo and not correo.endswith("@unach.mx"):
            raise forms.ValidationError("Solo se permiten correos institucionales con terminación @unach.mx.")
        return correo

    def clean_celular(self):
        cel = (self.cleaned_data.get("celular") or "").strip()
        if cel and not re.fullmatch(r"\d{10}", cel):
            raise forms.ValidationError("El celular debe tener exactamente 10 dígitos.")
        return cel

    def clean_codigo_postal(self):
        cp = (self.cleaned_data.get("codigo_postal") or "").strip()
        if cp and not re.fullmatch(r"\d{5}", cp):
            raise forms.ValidationError("El código postal debe tener exactamente 5 dígitos.")
        return cp

    def clean_curp_menor(self):
        curp = (self.cleaned_data.get("curp_menor") or "").strip().upper()
        if curp and not re.fullmatch(r"[A-Z0-9]{18}", curp):
            raise forms.ValidationError("La CURP debe tener 18 caracteres.")
        return curp

    def clean(self):
        cleaned_data = super().clean()
        programa = cleaned_data.get("programa_educativo")
        programa_otro = (cleaned_data.get("programa_educativo_otro") or "").strip()
        if programa == "OTRO" and not programa_otro:
            self.add_error("programa_educativo_otro", "Especifica el programa educativo.")

        parentesco = cleaned_data.get("parentesco")
        parentesco_otro = (cleaned_data.get("parentesco_otro") or "").strip()
        if parentesco == "OTRO" and not parentesco_otro:
            self.add_error("parentesco_otro", "Especifica el parentesco.")

        fecha = cleaned_data.get("fecha_nacimiento_menor")
        if fecha:
            hoy = date.today()
            min_fecha = hoy - timedelta(days=365 * 3)
            max_fecha = hoy - timedelta(days=30 * 6)
            if fecha < min_fecha or fecha > max_fecha:
                self.add_error("fecha_nacimiento_menor", "La edad del menor debe estar entre 6 meses y 3 años.")
        return cleaned_data


class CrearSolicitudPanelForm(forms.Form):
    UNIDADES_CHOICES = [
        ("", "Seleccione una opción..."),
        ("Facultad de Contaduría y Administración, Campus I", "Facultad de Contaduría y Administración, Campus I"),
        ("Facultad de Ingeniería, Campus I", "Facultad de Ingeniería, Campus I"),
        ("Facultad de Arquitectura, Campus I", "Facultad de Arquitectura, Campus I"),
        ("Facultad de Medicina Humana Dr. Manuel Velasco Suárez, Campus II",
         "Facultad de Medicina Humana Dr. Manuel Velasco Suárez, Campus II"),
        ("Facultad de Medicina Veterinaria y Zootecnia, Campus II",
         "Facultad de Medicina Veterinaria y Zootecnia, Campus II"),
        ("Facultad de Derecho, Campus III", "Facultad de Derecho, Campus III"),
        ("Facultad de Ciencias Sociales, Campus III", "Facultad de Ciencias Sociales, Campus III"),
        ("Facultad de Negocios, Campus IV", "Facultad de Negocios, Campus IV"),
        ("Facultad de Ciencias de la Administración, Campus IV",
         "Facultad de Ciencias de la Administración, Campus IV"),
        ("Facultad de Ciencias Químicas, Campus IV", "Facultad de Ciencias Químicas, Campus IV"),
        ("Facultad de Ciencias Agrícolas, Campus IV", "Facultad de Ciencias Agrícolas, Campus IV"),
        ("Facultad de Ciencias Agronómicas, Campus V", "Facultad de Ciencias Agronómicas, Campus V"),
        ("Facultad de Humanidades, Campus VI", "Facultad de Humanidades, Campus VI"),
        ("Facultad de Ciencias Administrativas, Campus VIII", "Facultad de Ciencias Administrativas, Campus VIII"),
        ("Facultad de Lenguas, Campus Tuxtla", "Facultad de Lenguas, Campus Tuxtla"),
        ("Facultad de Ciencias en Física y Matemáticas", "Facultad de Ciencias en Física y Matemáticas"),
        ("Facultad Maya de Estudios Agropecuarios", "Facultad Maya de Estudios Agropecuarios"),
        ("Facultad de Medicina Humana Dr. Manuel Velasco Suárez, Campus IV",
         "Facultad de Medicina Humana Dr. Manuel Velasco Suárez, Campus IV"),
        ("Facultad de Ciencias Humanas para el Desarrollo Intercultural Sostenible",
         "Facultad de Ciencias Humanas para el Desarrollo Intercultural Sostenible"),
        ("Otra", "Otra unidad (especificar)"),
    ]

    nombres_tutor = forms.CharField(max_length=80, required=True)
    apellido_paterno_tutor = forms.CharField(max_length=60, required=True)
    apellido_materno_tutor = forms.CharField(max_length=60, required=False)
    matricula = forms.CharField(max_length=20, required=False)
    unidad_academica = forms.ChoiceField(choices=UNIDADES_CHOICES, required=True)
    unidad_academica_otra = forms.CharField(max_length=100, required=False)
    correo = CorreoInstitucionalField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs["class"] = "form-control"

        self.fields["unidad_academica"].widget.attrs["class"] = "form-select"
        self.fields["unidad_academica"].widget.attrs["onchange"] = "mostrarOtraUnidad(this.value)"
        self.fields["unidad_academica_otra"].widget.attrs["class"] = "form-control d-none mt-2"
        self.fields["unidad_academica_otra"].widget.attrs["placeholder"] = "Especifica la unidad académica"
        self.fields["unidad_academica_otra"].widget.attrs["id"] = "input_unidad_otra"
        self.fields["nombres_tutor"].widget.attrs["placeholder"] = "Ej. Juan Carlos"
        self.fields["apellido_paterno_tutor"].widget.attrs["placeholder"] = "Ej. Pérez"
        self.fields["apellido_materno_tutor"].widget.attrs["placeholder"] = "Ej. López"
        self.fields["matricula"].widget.attrs["placeholder"] = "Ej. A123456"
        self.fields["correo"].widget.attrs["placeholder"] = "Ej. correo@unach.mx"

    def clean_correo(self):
        correo = limpiar_correo(self.cleaned_data.get("correo"))
        if correo and not correo.endswith("@unach.mx"):
            raise forms.ValidationError("Solo se permiten correos institucionales con terminación @unach.mx")
        return correo

    def clean(self):
        cleaned_data = super().clean()
        unidad = cleaned_data.get("unidad_academica")
        unidad_otra = cleaned_data.get("unidad_academica_otra")
        if unidad == "Otra" and not unidad_otra:
            self.add_error("unidad_academica_otra", "Por favor especifica la unidad académica.")
        return cleaned_data

    def _solo_letras(self, value, campo):
        value = (value or "").strip()
        if not value: return value
        if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+", value):
            raise forms.ValidationError(f"{campo}: solo letras y espacios.")
        return value.title()

    def clean_nombres_tutor(self):
        return self._solo_letras(self.cleaned_data.get("nombres_tutor"), "Nombre(s)")

    def clean_apellido_paterno_tutor(self):
        return self._solo_letras(self.cleaned_data.get("apellido_paterno_tutor"), "Apellido paterno")

    def clean_apellido_materno_tutor(self):
        return self._solo_letras(self.cleaned_data.get("apellido_materno_tutor"), "Apellido materno")


SI_NO_CHOICES = [("", "Seleccione..."), ("SI", "Si"), ("NO", "No")]
ESTADO_PSICOLOGIA_CHOICES = [("", "Seleccione..."), ("APROBADO", "Aprobado"), ("RECHAZADO", "Rechazado")]
TIPO_NACIMIENTO_CHOICES = [("", "Seleccione..."), ("PARTO", "Parto"), ("CESAREA", "Cesárea")]
METODO_ALIMENTACION_CHOICES = [("", "Seleccione..."), ("LME", "LME"), ("LM", "LM"), ("SLM", "SLM")]
LENGUAJE_ACTUAL_CHOICES = [("", "Seleccione..."), ("SILENCIOSO", "Silencioso"), ("EXPLICITO", "Explícito"),
                           ("REPETITIVO", "Repetitivo")]
CONTROL_CHOICES = [("", "Seleccione..."), ("SI", "Si"), ("NO", "No"), ("EN_PROCESO", "En proceso")]
ADAPTACION_CHOICES = [("", "Seleccione..."), ("SI", "Si"), ("NO", "No"), ("A_VECES", "A veces")]
COMPARTE_CHOICES = [("", "Seleccione..."), ("SI", "Si"), ("NO", "No"), ("A_VECES", "A veces")]
CONDUCTA_LIDER_CHOICES = [("", "Seleccione..."), ("SI", "Si"), ("NO", "No"), ("OCASIONALMENTE", "Ocasionalmente")]



# =========================================================
# AUXILIARES PARA SUPLENCIAS EN DICTÁMENES
# =========================================================
class SuplenciaDictamenMixin:
    """
    Mixin reutilizable para que los formularios de dictamen acepten una
    autorización temporal sin cambiar el rol real del usuario.

    La vista puede pasar:
    - usuario=request.user
    - autorizacion_suplencia=<AutorizacionSuplencia activa>

    Si no se pasa autorización, el formulario trabaja de forma normal.
    """

    AREA_DICTAMEN_SUPLENCIA = ""
    PREFIJO_DICTAMEN_SUPLENCIA = ""

    def _extraer_kwargs_suplencia(self, kwargs):
        self.usuario = kwargs.pop("usuario", None)
        self.autorizacion_suplencia = kwargs.pop("autorizacion_suplencia", None)

    def _validar_autorizacion_dictamen(self, cleaned):
        autorizacion = getattr(self, "autorizacion_suplencia", None)

        if not autorizacion:
            return cleaned

        if not getattr(autorizacion, "esta_activa", False):
            raise forms.ValidationError("La autorización de suplencia ya no está activa o está fuera de vigencia.")

        if getattr(autorizacion, "area_cubierta", "") != self.AREA_DICTAMEN_SUPLENCIA:
            raise forms.ValidationError("La autorización de suplencia no corresponde a esta área de dictamen.")

        if not autorizacion.permite_accion("DICTAMEN"):
            raise forms.ValidationError("La autorización de suplencia no permite crear dictamen preliminar.")

        usuario = getattr(self, "usuario", None)
        if usuario and getattr(autorizacion, "suplente_id", None) and autorizacion.suplente_id != usuario.id:
            raise forms.ValidationError("Tu usuario no coincide con la persona autorizada para esta suplencia.")

        return cleaned

    def clean(self):
        cleaned = super().clean()
        return self._validar_autorizacion_dictamen(cleaned)

    def _marcar_dictamen_suplencia(self, obj):
        autorizacion = getattr(self, "autorizacion_suplencia", None)
        prefijo = self.PREFIJO_DICTAMEN_SUPLENCIA

        if not autorizacion or not prefijo:
            return obj

        campos_actualizados = []

        valores = {
            f"{prefijo}_es_suplencia": True,
            f"{prefijo}_autorizacion_suplencia": autorizacion,
            f"{prefijo}_pendiente_revision_titular": True,
        }

        usuario = getattr(self, "usuario", None)
        if prefijo == "psicologia":
            valores["psicologia_por"] = usuario
            valores["psicologia_en"] = timezone.now()
        elif prefijo == "nutricion":
            valores["nutricion_por"] = usuario
            valores["nutricion_en"] = timezone.now()
        elif prefijo == "medico":
            valores["medico_por"] = usuario
            valores["medico_en"] = timezone.now()

        for campo, valor in valores.items():
            if hasattr(obj, campo):
                setattr(obj, campo, valor)
                campos_actualizados.append(campo)

        # Si la vista usa form.save(commit=False), conserva los cambios en el objeto.
        # Si usa commit=True, se guardan automáticamente abajo.
        obj._campos_suplencia_dictamen = campos_actualizados
        return obj

    def save(self, commit=True):
        obj = super().save(commit=False)
        self._marcar_dictamen_suplencia(obj)

        if commit:
            obj.save()

            autorizacion = getattr(self, "autorizacion_suplencia", None)
            if autorizacion:
                try:
                    MovimientoSuplencia.objects.create(
                        autorizacion=autorizacion,
                        usuario=getattr(self, "usuario", None),
                        titular_area=autorizacion.titular_ausente,
                        area_cubierta=autorizacion.area_cubierta,
                        accion=MovimientoSuplencia.TipoAccion.DICTAMEN_PRELIMINAR,
                        descripcion="Dictamen preliminar registrado mediante suplencia autorizada por Dirección.",
                        solicitud=obj,
                        objeto_modelo=obj.__class__.__name__,
                        objeto_id=obj.pk,
                    )
                except Exception:
                    pass

        return obj

# IMPORTANTE:
# Los datos de identidad del menor NO se editan desde Psicología.
# Se muestran en el HTML desde la Solicitud original y se protegen en views.py.
# Por eso no se incluyen en fields de este ModelForm.
class DictamenPsicologiaForm(SuplenciaDictamenMixin, forms.ModelForm):
    AREA_DICTAMEN_SUPLENCIA = AutorizacionSuplencia.AreaCubierta.PSICOLOGIA
    PREFIJO_DICTAMEN_SUPLENCIA = "psicologia"
    estado_psicologia = forms.ChoiceField(
        choices=ESTADO_PSICOLOGIA_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
        required=True
    )

    class Meta:
        model = Solicitud
        fields = [
            "fecha_aplicacion_psicologia", "como_lo_llaman_en_casa", "edad_psicologia",
            "lugar_nacimiento_menor_psicologia", "nombre_padre_psicologia", "edad_padre_psicologia",
            "nacionalidad_padre_psicologia", "estado_civil_padre_psicologia", "religion_padre_psicologia",
            "ocupacion_padre_psicologia", "lugar_trabajo_padre_psicologia", "horario_trabajo_padre_psicologia",
            "escolaridad_padre_psicologia", "estudiante_padre_psicologia", "licenciatura_padre_psicologia",
            "semestre_padre_psicologia", "nombre_madre_psicologia", "edad_madre_psicologia",
            "nacionalidad_madre_psicologia", "estado_civil_madre_psicologia", "religion_madre_psicologia",
            "ocupacion_madre_psicologia", "lugar_trabajo_madre_psicologia", "horario_trabajo_madre_psicologia",
            "escolaridad_madre_psicologia", "estudiante_madre_psicologia", "licenciatura_madre_psicologia",
            "semestre_madre_psicologia", "numero_gesta_psicologia", "embarazo_planeado_psicologia",
            "dificultad_embarazo_psicologia", "estado_animo_madre_embarazo_psicologia",
            "momento_supieron_sexo_bebe_psicologia",
            "quien_eligio_nombre_bebe_psicologia", "motivo_nombre_bebe_psicologia", "tipo_nacimiento_psicologia",
            "semanas_gestacion_psicologia", "dificultad_nacimiento_psicologia", "peso_al_nacer_psicologia",
            "talla_al_nacer_psicologia", "apego_inmediato_psicologia", "metodo_alimentacion_inicio_psicologia",
            "edad_destete_psicologia", "motivo_destete_psicologia", "edad_balbuceo_psicologia",
            "edad_primera_palabra_psicologia", "lenguaje_actual_psicologia", "dificultad_lenguaje_psicologia",
            "edad_se_sento_solo_psicologia", "gateo_psicologia", "edad_gateo_psicologia",
            "edad_marcha_independiente_psicologia", "dominancia_manual_psicologia", "comportamiento_general_psicologia",
            "relacion_otros_ninos_psicologia", "apego_figura_familiar_psicologia", "apego_con_quien_psicologia",
            "se_viste_solo_psicologia", "se_pone_prendas_solo_psicologia", "cuales_prendas_se_pone_psicologia",
            "se_quita_prendas_solo_psicologia", "cuales_prendas_se_quita_psicologia", "intenta_banarse_solo_psicologia",
            "se_cepilla_dientes_solo_psicologia", "come_solo_psicologia", "toma_vaso_solo_psicologia",
            "iniciativa_para_jugar_psicologia", "realiza_siestas_psicologia", "cuantas_siestas_psicologia",
            "con_quien_duerme_psicologia", "hora_duerme_noche_psicologia", "hora_despierta_manana_psicologia",
            "necesita_algo_para_dormir_psicologia", "que_necesita_para_dormir_psicologia",
            "despierta_con_frecuencia_psicologia",
            "actividades_tarde_psicologia", "actividad_extra_tarde_psicologia", "juego_favorito_psicologia",
            "cancion_favorita_psicologia", "personaje_favorito_psicologia", "tiempo_pantallas_psicologia",
            "socializa_tardes_con_quien_psicologia", "lugar_para_jugar_psicologia", "comparte_juguetes_psicologia",
            "conducta_lider_juego_psicologia", "relacion_con_otros_ninos_detalle_psicologia",
            "se_adapta_nuevos_entornos_psicologia",
            "actividades_fin_semana_psicologia", "controla_orinar_psicologia", "controla_defecar_psicologia",
            "edad_comenzo_avisar_psicologia", "donde_realiza_necesidades_psicologia",
            "algo_significativo_control_esfinteres_psicologia",
            "duerme_con_panal_noche_psicologia", "reaccion_no_controla_esfinteres_psicologia",
            "que_hace_responsable_cuando_sucede_psicologia",
            "persona_aparte_padres_crianza_psicologia", "persona_aparte_padres_cuidado_psicologia",
            "periodos_cuidado_psicologia",
            "relacion_padre_madre_con_nino_psicologia", "tiempo_papa_dia_psicologia", "tiempo_mama_dia_psicologia",
            "metodo_mejorar_conducta_casa_psicologia", "dificultad_actual_hogar_entorno_psicologia",
            "beneficio_esperado_hijo_estancia_psicologia",
            "beneficio_personal_estancia_psicologia", "estado_psicologia", "observaciones_psicologia",
        ]
        widgets = {
            "fecha_aplicacion_psicologia": forms.DateInput(attrs={"type": "date"}),
            "embarazo_planeado_psicologia": forms.Select(choices=SI_NO_CHOICES),
            "tipo_nacimiento_psicologia": forms.Select(choices=TIPO_NACIMIENTO_CHOICES),
            "metodo_alimentacion_inicio_psicologia": forms.Select(choices=METODO_ALIMENTACION_CHOICES),
            "lenguaje_actual_psicologia": forms.Select(choices=LENGUAJE_ACTUAL_CHOICES),
            "gateo_psicologia": forms.Select(choices=SI_NO_CHOICES),
            "apego_figura_familiar_psicologia": forms.Select(choices=SI_NO_CHOICES),
            "se_viste_solo_psicologia": forms.Select(choices=SI_NO_CHOICES),
            "se_pone_prendas_solo_psicologia": forms.Select(choices=SI_NO_CHOICES),
            "se_quita_prendas_solo_psicologia": forms.Select(choices=SI_NO_CHOICES),
            "intenta_banarse_solo_psicologia": forms.Select(choices=SI_NO_CHOICES),
            "se_cepilla_dientes_solo_psicologia": forms.Select(choices=SI_NO_CHOICES),
            "come_solo_psicologia": forms.Select(choices=SI_NO_CHOICES),
            "toma_vaso_solo_psicologia": forms.Select(choices=SI_NO_CHOICES),
            "iniciativa_para_jugar_psicologia": forms.Select(choices=SI_NO_CHOICES),
            "realiza_siestas_psicologia": forms.Select(choices=SI_NO_CHOICES),
            "necesita_algo_para_dormir_psicologia": forms.Select(choices=SI_NO_CHOICES),
            "despierta_con_frecuencia_psicologia": forms.Select(choices=SI_NO_CHOICES),
            "comparte_juguetes_psicologia": forms.Select(choices=COMPARTE_CHOICES),
            "conducta_lider_juego_psicologia": forms.Select(choices=CONDUCTA_LIDER_CHOICES),
            "se_adapta_nuevos_entornos_psicologia": forms.Select(choices=ADAPTACION_CHOICES),
            "controla_orinar_psicologia": forms.Select(choices=CONTROL_CHOICES),
            "controla_defecar_psicologia": forms.Select(choices=CONTROL_CHOICES),
            "duerme_con_panal_noche_psicologia": forms.Select(choices=SI_NO_CHOICES),
            "estado_psicologia": forms.Select(choices=ESTADO_PSICOLOGIA_CHOICES),
            "dificultad_embarazo_psicologia": forms.Textarea(attrs={"rows": 3}),
            "estado_animo_madre_embarazo_psicologia": forms.Textarea(attrs={"rows": 3}),
            "momento_supieron_sexo_bebe_psicologia": forms.Textarea(attrs={"rows": 3}),
            "quien_eligio_nombre_bebe_psicologia": forms.Textarea(attrs={"rows": 3}),
            "motivo_nombre_bebe_psicologia": forms.Textarea(attrs={"rows": 3}),
            "dificultad_nacimiento_psicologia": forms.Textarea(attrs={"rows": 3}),
            "motivo_destete_psicologia": forms.Textarea(attrs={"rows": 3}),
            "dificultad_lenguaje_psicologia": forms.Textarea(attrs={"rows": 3}),
            "comportamiento_general_psicologia": forms.Textarea(attrs={"rows": 3}),
            "relacion_otros_ninos_psicologia": forms.Textarea(attrs={"rows": 3}),
            "actividades_tarde_psicologia": forms.Textarea(attrs={"rows": 3}),
            "actividad_extra_tarde_psicologia": forms.Textarea(attrs={"rows": 3}),
            "relacion_con_otros_ninos_detalle_psicologia": forms.Textarea(attrs={"rows": 3}),
            "actividades_fin_semana_psicologia": forms.Textarea(attrs={"rows": 3}),
            "algo_significativo_control_esfinteres_psicologia": forms.Textarea(attrs={"rows": 3}),
            "reaccion_no_controla_esfinteres_psicologia": forms.Textarea(attrs={"rows": 3}),
            "que_hace_responsable_cuando_sucede_psicologia": forms.Textarea(attrs={"rows": 3}),
            "persona_aparte_padres_crianza_psicologia": forms.Textarea(attrs={"rows": 3}),
            "persona_aparte_padres_cuidado_psicologia": forms.Textarea(attrs={"rows": 3}),
            "periodos_cuidado_psicologia": forms.Textarea(attrs={"rows": 3}),
            "relacion_padre_madre_con_nino_psicologia": forms.Textarea(attrs={"rows": 3}),
            "metodo_mejorar_conducta_casa_psicologia": forms.Textarea(attrs={"rows": 3}),
            "dificultad_actual_hogar_entorno_psicologia": forms.Textarea(attrs={"rows": 3}),
            "beneficio_esperado_hijo_estancia_psicologia": forms.Textarea(attrs={"rows": 3}),
            "beneficio_personal_estancia_psicologia": forms.Textarea(attrs={"rows": 3}),
            "observaciones_psicologia": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        self._extraer_kwargs_suplencia(kwargs)
        super().__init__(*args, **kwargs)
        campos_identidad = ["nombres_menor", "apellido_paterno_menor", "apellido_materno_menor"]
        for name, field in self.fields.items():
            if name in campos_identidad:
                field.widget.attrs["readonly"] = "readonly"
                field.widget.attrs["style"] = "background-color: #e9ecef; pointer-events: none;"
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs["class"] = "form-control"
            elif isinstance(field.widget, forms.DateInput):
                field.widget.attrs["class"] = "form-control"
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            else:
                field.widget.attrs["class"] = "form-control"


SEXO_CHOICES_NUTRI = [("", "Seleccione"), ("FEMENINO", "Femenino"), ("MASCULINO", "Masculino"), ("OTRO", "Otro")]
TIPO_ALIMENTACION_CHOICES = [("", "Seleccione"), ("SENO_MATERNO", "Seno materno"), ("FORMULA_LACTEA", "Fórmula láctea"),
                             ("MIXTA", "Mixta"), ("OTRA", "Otra")]
PRESENTACION_LECHE_CHOICES = [("", "Seleccione"), ("BIBERON", "Biberón"), ("VASO_ENTRENADOR", "Vaso entrenador"),
                              ("OTRA", "Otra")]
FORMA_FORMULA_CHOICES = [("", "Seleccione"), ("PORTA_BEBE", "Porta bebé"), ("EN_BRAZOS", "En brazos"), ("OTRO", "Otro")]
TIPO_COMPLICACION_CHOICES = [("", "Seleccione"), ("INTOLERANCIA_LACTOSA", "Intolerancia a la lactosa"),
                             ("REFLUJO", "Reflujo"), ("DIFICULTAD_SUCCIONAR", "Dificultad para succionar"),
                             ("ALERGIAS", "Alergias"), ("DIFICULTAD_DEGLUTIR", "Dificultad para deglutir"),
                             ("OTRA", "Otra")]
PRESENTACION_ALIMENTOS_CHOICES = [("", "Seleccione"), ("PURE", "Puré"), ("MACHACADO", "Machacado"),
                                  ("PICADO_FINO", "Picado extra fino"), ("PICADO_EXTRA_FINO", "Picado extra fino"),
                                  ("EN_TROZOS", "En trozos")]
ORDEN_ALIMENTOS_CHOICES = [("", "Seleccione"), ("LECHE_LUEGO_SOLIDOS", "Primero leche y después sólidos"),
                           ("SOLIDOS_LUEGO_LECHE", "Primero sólidos y después leche")]
FRECUENCIA_SOLIDOS_CHOICES = [("", "Seleccione"), ("1_VEZ", "1 vez"), ("2_VECES", "2 veces"), ("3_VECES", "3 veces"),
                              ("MAS_DE_3", "Más de 3 veces"), ("CON_CADA_TOMA", "Con cada toma de fórmula infantil")]
DONDE_CONSUME_CHOICES = [("", "Seleccione"), ("PORTA_BEBE", "Porta bebé"), ("SILLA_PERIQUERA", "Silla periquera"),
                         ("SILLA_MESA", "Silla y mesa"), ("OTRO", "Otro")]
COMPANIA_CHOICES = [("", "Seleccione"), ("FAMILIA", "En compañía de la familia"), ("SOLO", "Solo"),
                    ("TELEVISION", "Televisión"), ("JUGUETES", "Juguetes"), ("OTRO", "Otro")]
COME_CON_CHOICES = [("", "Seleccione"), ("MANOS", "Las manos"), ("CUCHARA", "Cuchara"), ("TENEDOR", "Tenedor"),
                    ("CUCHILLO", "Cuchillo")]
BEBIDAS_EN_CHOICES = [("", "Seleccione"), ("BIBERON", "Biberón"), ("VASO_ENTRENADOR", "Vaso entrenador"),
                      ("VASO", "Vaso"), ("OTRO", "Otro")]
COME_SOLO_CHOICES = [("", "Seleccione"), ("SOLO", "Solo"), ("CON_AYUDA", "Con ayuda")]

FRUTAS_CHOICES = [(x, x) for x in
                  ["Manzana", "Pera", "Plátano", "Melón", "Sandía", "Papaya", "Mango", "Naranja", "Fresa", "Uva",
                   "Guayaba", "Piña"]]
VERDURAS_CHOICES = [(x, x) for x in
                    ["Zanahoria", "Calabaza", "Chayote", "Brócoli", "Espinaca", "Tomate", "Cebolla", "Papa", "Chícharo",
                     "Lechuga", "Nopal"]]
CEREALES_CHOICES = [(x, x) for x in
                    ["Avena", "Arroz", "Maíz", "Trigo", "Amaranto", "Tortilla", "Pan", "Galletas", "Pasta",
                     "Cereal de caja"]]
LEGUMINOSAS_CHOICES = [(x, x) for x in ["Frijol", "Lenteja", "Garbanzo", "Haba", "Soya", "Alubia"]]
AOA_CHOICES = [(x, x) for x in ["Pollo", "Res", "Cerdo", "Pescado", "Huevo", "Atún", "Pavo", "Salchicha", "Jamón"]]
LACTEOS_CHOICES = [(x, x) for x in
                   ["Leche", "Yogur", "Queso fresco", "Queso panela", "Queso oaxaca", "Mantequilla", "Crema"]]


# IMPORTANTE:
# Los datos de identidad del menor NO se editan desde Nutrición.
# Se muestran en el HTML desde la Solicitud original y se protegen en views.py.
# Por eso no se incluyen en fields de este ModelForm.
class DictamenNutricionForm(SuplenciaDictamenMixin, forms.ModelForm):
    AREA_DICTAMEN_SUPLENCIA = AutorizacionSuplencia.AreaCubierta.NUTRICION
    PREFIJO_DICTAMEN_SUPLENCIA = "nutricion"
    estado_nutricion = forms.ChoiceField(
        choices=[("", "Seleccione..."), ("APROBADO", "Aprobado"), ("RECHAZADO", "Rechazado")],
        widget=forms.Select(attrs={"class": "form-select"}),
        required=True
    )
    alimentos_agrado_frutas = DynamicMultipleChoiceField(choices=FRUTAS_CHOICES, required=False,
                                                         widget=forms.SelectMultiple(
                                                             attrs={'class': 'form-select select2-multiple'}))
    alimentos_agrado_verduras = DynamicMultipleChoiceField(choices=VERDURAS_CHOICES, required=False,
                                                           widget=forms.SelectMultiple(
                                                               attrs={'class': 'form-select select2-multiple'}))
    alimentos_agrado_cereales = DynamicMultipleChoiceField(choices=CEREALES_CHOICES, required=False,
                                                           widget=forms.SelectMultiple(
                                                               attrs={'class': 'form-select select2-multiple'}))
    alimentos_agrado_leguminosas = DynamicMultipleChoiceField(choices=LEGUMINOSAS_CHOICES, required=False,
                                                              widget=forms.SelectMultiple(
                                                                  attrs={'class': 'form-select select2-multiple'}))
    alimentos_agrado_aoa = DynamicMultipleChoiceField(choices=AOA_CHOICES, required=False, widget=forms.SelectMultiple(
        attrs={'class': 'form-select select2-multiple'}))
    alimentos_agrado_lacteos = DynamicMultipleChoiceField(choices=LACTEOS_CHOICES, required=False,
                                                          widget=forms.SelectMultiple(
                                                              attrs={'class': 'form-select select2-multiple'}))

    class Meta:
        model = Solicitud
        fields = [
            "edad_nutricion", "sexo_nutricion", "fecha_nacimiento_nutricion", "peso_nacer",
            "talla_nacer", "peso_actual", "talla_actual", "seno_materno", "tiempo_seno_materno",
            "motivo_no_seno", "acude_lactancia", "tipo_alimentacion_lactante", "formula_infantil",
            "cual_formula", "edad_inicio_formula", "formula_especial", "cual_formula_especial",
            "causa_formula_especial", "cantidad_leche_formula", "cada_cuantas_horas_leche",
            "presentacion_leche", "presentacion_leche_otra", "forma_proporcionar_formula",
            "forma_proporcionar_formula_otra", "complicaciones_alimentacion", "tipo_complicacion",
            "tipo_complicacion_otra", "agrega_alimento_formula", "cual_agrega_formula",
            "edad_cambio_leche", "edad_inicio_alimentacion_complementaria", "orden_verduras",
            "orden_frutas", "orden_carnes", "orden_jugo_frutas", "orden_yema_huevo",
            "orden_huevo_entero", "orden_arroz", "orden_galleta_pan", "orden_pastas",
            "orden_leguminosas", "orden_citricos", "alergia_alimentos", "cual_alergia",
            "reaccion_alergia", "restriccion_alimentaria_actual", "detalle_restriccion_alimentaria",
            "presentacion_alimentos", "orden_alimentos", "frecuencia_solidos", "alimentos_agrado_frutas",
            "alimentos_agrado_verduras", "alimentos_agrado_cereales", "alimentos_agrado_leguminosas",
            "alimentos_agrado_aoa", "alimentos_agrado_lacteos", "consume_agua", "cantidad_agua",
            "desayuna", "hora_desayuno", "come", "hora_comida", "cena", "hora_cena", "colacion",
            "hora_colacion", "acostumbra_comer_desayuno", "acostumbra_comer_comida",
            "acostumbra_comer_cena", "acostumbra_comer_colaciones", "misma_alimentacion_familia",
            "detalle_misma_alimentacion", "consume_golosinas", "frecuencia_golosinas", "cuales_golosinas",
            "consume_refrescos", "frecuencia_refrescos", "cuales_refrescos", "consume_jugos",
            "frecuencia_jugos", "cuales_jugos", "donde_consume_alimentos", "donde_consume_alimentos_otro",
            "compania_comida", "compania_comida_otro", "come_con", "consume_bebidas_en",
            "consume_bebidas_en_otro", "come_solo_o_ayuda", "observaciones_nutricion_clinica",
            "fecha_elaboracion_nutricion", "estado_nutricion", "observaciones_nutricion",
        ]
        widgets = {
            "sexo_nutricion": forms.Select(choices=SEXO_CHOICES_NUTRI),
            "seno_materno": forms.Select(choices=SI_NO_CHOICES),
            "acude_lactancia": forms.Select(choices=SI_NO_CHOICES),
            "tipo_alimentacion_lactante": forms.Select(choices=TIPO_ALIMENTACION_CHOICES),
            "formula_infantil": forms.Select(choices=SI_NO_CHOICES),
            "formula_especial": forms.Select(choices=SI_NO_CHOICES),
            "presentacion_leche": forms.Select(choices=PRESENTACION_LECHE_CHOICES),
            "forma_proporcionar_formula": forms.Select(choices=FORMA_FORMULA_CHOICES),
            "complicaciones_alimentacion": forms.Select(choices=SI_NO_CHOICES),
            "tipo_complicacion": forms.Select(choices=TIPO_COMPLICACION_CHOICES),
            "agrega_alimento_formula": forms.Select(choices=SI_NO_CHOICES),
            "alergia_alimentos": forms.Select(choices=SI_NO_CHOICES),
            "restriccion_alimentaria_actual": forms.Select(choices=SI_NO_CHOICES),
            "presentacion_alimentos": forms.Select(choices=PRESENTACION_ALIMENTOS_CHOICES),
            "orden_alimentos": forms.Select(choices=ORDEN_ALIMENTOS_CHOICES),
            "frecuencia_solidos": forms.Select(choices=FRECUENCIA_SOLIDOS_CHOICES),
            "consume_agua": forms.Select(choices=SI_NO_CHOICES),
            "desayuna": forms.Select(choices=SI_NO_CHOICES),
            "come": forms.Select(choices=SI_NO_CHOICES),
            "cena": forms.Select(choices=SI_NO_CHOICES),
            "colacion": forms.Select(choices=SI_NO_CHOICES),
            "misma_alimentacion_familia": forms.Select(choices=SI_NO_CHOICES),
            "consume_golosinas": forms.Select(choices=SI_NO_CHOICES),
            "consume_refrescos": forms.Select(choices=SI_NO_CHOICES),
            "consume_jugos": forms.Select(choices=SI_NO_CHOICES),
            "donde_consume_alimentos": forms.Select(choices=DONDE_CONSUME_CHOICES),
            "compania_comida": forms.Select(choices=COMPANIA_CHOICES),
            "come_con": forms.Select(choices=COME_CON_CHOICES),
            "consume_bebidas_en": forms.Select(choices=BEBIDAS_EN_CHOICES),
            "come_solo_o_ayuda": forms.Select(choices=COME_SOLO_CHOICES),
            "motivo_no_seno": forms.Textarea(attrs={"rows": 2}),
            "causa_formula_especial": forms.Textarea(attrs={"rows": 2}),
            "reaccion_alergia": forms.Textarea(attrs={"rows": 2}),
            "detalle_restriccion_alimentaria": forms.Textarea(attrs={"rows": 2}),
            "observaciones_nutricion_clinica": forms.Textarea(attrs={"rows": 4}),
            "observaciones_nutricion": forms.Textarea(attrs={"rows": 4}),
            "acostumbra_comer_desayuno": forms.Textarea(attrs={"rows": 2}),
            "acostumbra_comer_comida": forms.Textarea(attrs={"rows": 2}),
            "acostumbra_comer_cena": forms.Textarea(attrs={"rows": 2}),
            "acostumbra_comer_colaciones": forms.Textarea(attrs={"rows": 2}),
            "peso_actual": forms.NumberInput(attrs={"step": "0.01", "min": "0", "placeholder": "kg"}),
            "talla_actual": forms.NumberInput(attrs={"step": "0.01", "min": "0", "placeholder": "cm"}),
            "hora_desayuno": forms.TimeInput(attrs={"type": "time"}),
            "hora_comida": forms.TimeInput(attrs={"type": "time"}),
            "hora_cena": forms.TimeInput(attrs={"type": "time"}),
            "hora_colacion": forms.TimeInput(attrs={"type": "time"}),
        }

    def clean_alimentos_agrado_frutas(self):
        return ", ".join(self.cleaned_data.get("alimentos_agrado_frutas") or [])

    def clean_alimentos_agrado_verduras(self):
        return ", ".join(self.cleaned_data.get("alimentos_agrado_verduras") or [])

    def clean_alimentos_agrado_cereales(self):
        return ", ".join(self.cleaned_data.get("alimentos_agrado_cereales") or [])

    def clean_alimentos_agrado_leguminosas(self):
        return ", ".join(self.cleaned_data.get("alimentos_agrado_leguminosas") or [])

    def clean_alimentos_agrado_aoa(self):
        return ", ".join(self.cleaned_data.get("alimentos_agrado_aoa") or [])

    def clean_alimentos_agrado_lacteos(self):
        return ", ".join(self.cleaned_data.get("alimentos_agrado_lacteos") or [])

    def __init__(self, *args, **kwargs):
        self._extraer_kwargs_suplencia(kwargs)
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            insc = getattr(self.instance, 'inscripcion_oficial', None)
            if not self.initial.get("fecha_nacimiento_nutricion") and self.instance.fecha_nacimiento_menor:
                self.initial["fecha_nacimiento_nutricion"] = self.instance.fecha_nacimiento_menor.strftime("%d/%m/%Y")
            if insc:
                if not self.initial.get("edad_nutricion"):
                    self.initial[
                        "edad_nutricion"] = f"{insc.edad_anios_menor or 0} años, {insc.edad_meses_menor or 0} meses"
                if not self.initial.get("sexo_nutricion"):
                    self.initial[
                        "sexo_nutricion"] = "MASCULINO" if insc.sexo_menor == "M" else "FEMENINO" if insc.sexo_menor == "F" else ""
            if not self.initial.get("peso_nacer") and self.instance.peso_al_nacer_psicologia:
                self.initial["peso_nacer"] = f"{self.instance.peso_al_nacer_psicologia} kg"
            if not self.initial.get("talla_nacer") and self.instance.talla_al_nacer_psicologia:
                self.initial["talla_nacer"] = f"{self.instance.talla_al_nacer_psicologia} cm"

            multi_fields = ["alimentos_agrado_frutas", "alimentos_agrado_verduras", "alimentos_agrado_cereales",
                            "alimentos_agrado_leguminosas", "alimentos_agrado_aoa", "alimentos_agrado_lacteos"]
            for f in multi_fields:
                val = getattr(self.instance, f)
                if val: self.initial[f] = [x.strip() for x in val.split(',') if x.strip()]

        # Datos compartidos entre filtros.
        # Antes estos campos se bloqueaban siempre. Ahora solo se bloquean cuando
        # realmente vienen precargados desde otro filtro o desde el expediente base.
        # Si están vacíos, Nutrición puede capturarlos y views.py registrará el origen.
        campos_identidad = [
            "nombres_menor",
            "apellido_paterno_menor",
            "apellido_materno_menor",
        ]
        campos_compartidos_nutricion = [
            "edad_nutricion",
            "sexo_nutricion",
            "fecha_nacimiento_nutricion",
            "peso_nacer",
            "talla_nacer",
            "peso_actual",
            "talla_actual",
            "tipo_alimentacion_lactante",
            "seno_materno",
            "tiempo_seno_materno",
            "formula_infantil",
            "cual_formula",
            "alergia_alimentos",
            "cual_alergia",
        ]

        campos_bloqueados_por_origen = set(campos_identidad)

        if self.instance and self.instance.pk:
            # Estos datos son informativos si vienen del expediente o Psicología.
            if self.instance.fecha_nacimiento_menor and _valor_formulario_vacio(getattr(self.instance, "fecha_nacimiento_nutricion", "")):
                campos_bloqueados_por_origen.add("fecha_nacimiento_nutricion")

            insc = getattr(self.instance, "inscripcion_oficial", None)
            if insc:
                if _valor_formulario_vacio(getattr(self.instance, "edad_nutricion", "")):
                    campos_bloqueados_por_origen.add("edad_nutricion")
                if _valor_formulario_vacio(getattr(self.instance, "sexo_nutricion", "")):
                    campos_bloqueados_por_origen.add("sexo_nutricion")

            if self.instance.peso_al_nacer_psicologia and _valor_formulario_vacio(getattr(self.instance, "peso_nacer", "")):
                campos_bloqueados_por_origen.add("peso_nacer")

            if self.instance.talla_al_nacer_psicologia and _valor_formulario_vacio(getattr(self.instance, "talla_nacer", "")):
                campos_bloqueados_por_origen.add("talla_nacer")

        for name, field in self.fields.items():
            existing_class = field.widget.attrs.get("class", "")
            if isinstance(field.widget, forms.SelectMultiple):
                if "form-select" not in existing_class:
                    field.widget.attrs["class"] = f"form-select {existing_class}".strip()
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs["class"] = "form-control"
                field.widget.attrs.setdefault("rows", 2)
            else:
                field.widget.attrs["class"] = "form-control"

            if name in campos_compartidos_nutricion:
                _marcar_widget_dato_compartido(field, name)
                field.widget.attrs.setdefault(
                    "placeholder",
                    "Captura el dato si todavía no existe en otro filtro"
                )

            if name in campos_bloqueados_por_origen:
                _bloquear_widget_solo_lectura(
                    field,
                    "Dato tomado del expediente base o de otro filtro. No se modifica desde esta captura."
                )


TIPO_PARTO_CHOICES = [("", "Seleccione"), ("Eutócico", "Eutócico"), ("Distócico", "Distócico"), ("Cesárea", "Cesárea")]
SEXO_CHOICES = [("", "Seleccione"), ("Masculino", "Masculino"), ("Femenino", "Femenino")]


# IMPORTANTE:
# Los datos de identidad del menor NO se editan desde Médico.
# Se muestran en el HTML desde la Solicitud original y se protegen en views.py.
# Por eso no se incluyen en fields de este ModelForm.
class DictamenMedicoForm(SuplenciaDictamenMixin, forms.ModelForm):
    AREA_DICTAMEN_SUPLENCIA = AutorizacionSuplencia.AreaCubierta.MEDICA
    PREFIJO_DICTAMEN_SUPLENCIA = "medico"
    estado_medico = forms.ChoiceField(
        choices=[("", "Seleccione..."), ("APROBADO", "Aprobado"), ("RECHAZADO", "Rechazado")],
        widget=forms.Select(attrs={"class": "form-select"}),
        required=True
    )

    class Meta:
        model = Solicitud
        fields = ["pdf", "estado_medico", "observaciones_medico"]
        widgets = {
            "pdf": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "application/pdf"}),
            "observaciones_medico": forms.Textarea(attrs={"class": "form-control", "rows": 4,
                                                          "placeholder": "Escriba observaciones médicas relevantes..."}),
        }

    def __init__(self, *args, **kwargs):
        self._extraer_kwargs_suplencia(kwargs)
        super().__init__(*args, **kwargs)
        campos_identidad = ["nombres_menor", "apellido_paterno_menor", "apellido_materno_menor"]
        for name, field in self.fields.items():
            if name in campos_identidad:
                field.widget.attrs["readonly"] = "readonly"
                field.widget.attrs["style"] = "background-color: #e9ecef; pointer-events: none;"
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs["class"] = "form-control"
            elif isinstance(field.widget, forms.DateInput):
                field.widget.attrs["class"] = "form-control"
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            elif isinstance(field.widget, forms.ClearableFileInput):
                pass
            else:
                field.widget.attrs["class"] = "form-control"


SI_NO_BOOL = [("", "Seleccione..."), ("SI", "Si"), ("NO", "No")]


class HistoriaClinicaMedicaForm(forms.ModelForm):
    nombres_paciente = forms.CharField(label="Nombre(s)", required=False)
    apellido_paterno_paciente = forms.CharField(label="Apellido paterno", required=False)
    apellido_materno_paciente = forms.CharField(label="Apellido materno", required=False)
    nombres_padre = forms.CharField(label="Nombre(s) del padre", required=False)
    apellido_paterno_padre = forms.CharField(label="Apellido paterno", required=False)
    apellido_materno_padre = forms.CharField(label="Apellido materno", required=False)
    nombres_madre = forms.CharField(label="Nombre(s) de la madre", required=False)
    apellido_paterno_madre = forms.CharField(label="Apellido paterno", required=False)
    apellido_materno_madre = forms.CharField(label="Apellido materno", required=False)

    sexo = forms.ChoiceField(choices=SEXO_CHOICES, required=False, widget=forms.Select(attrs={"class": "form-select"}))
    tipo_parto = forms.ChoiceField(choices=TIPO_PARTO_CHOICES, required=False,
                                   widget=forms.Select(attrs={"class": "form-select"}))

    tabaquismo_padre = forms.TypedChoiceField(choices=SI_NO_BOOL, coerce=lambda x: x == 'SI', empty_value=False,
                                              required=True, widget=forms.Select(attrs={"class": "form-select"}))
    alcoholismo_padre = forms.TypedChoiceField(choices=SI_NO_BOOL, coerce=lambda x: x == 'SI', empty_value=False,
                                               required=True, widget=forms.Select(attrs={"class": "form-select"}))
    drogas_padre = forms.TypedChoiceField(choices=SI_NO_BOOL, coerce=lambda x: x == 'SI', empty_value=False,
                                          required=True, widget=forms.Select(attrs={"class": "form-select"}))
    tabaquismo_madre = forms.TypedChoiceField(choices=SI_NO_BOOL, coerce=lambda x: x == 'SI', empty_value=False,
                                              required=True, widget=forms.Select(attrs={"class": "form-select"}))
    alcoholismo_madre = forms.TypedChoiceField(choices=SI_NO_BOOL, coerce=lambda x: x == 'SI', empty_value=False,
                                               required=True, widget=forms.Select(attrs={"class": "form-select"}))
    drogas_madre = forms.TypedChoiceField(choices=SI_NO_BOOL, coerce=lambda x: x == 'SI', empty_value=False,
                                          required=True, widget=forms.Select(attrs={"class": "form-select"}))

    class Meta:
        model = HistoriaClinicaMedica
        exclude = ["inscripcion", "created_at", "updated_at", "nombre_paciente", "nombre_padre", "nombre_madre"]
        widgets = {
            "fecha_nacimiento": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "edad": forms.TextInput(attrs={"class": "form-control", "placeholder": "Edad"}),
            "lugar_fecha_elaboracion": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Lugar y fecha de elaboración"}),
            "religion": forms.TextInput(attrs={"class": "form-control", "placeholder": "Religión"}),
            "quien_cuida_menor": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Persona responsable del menor"}),
            "edad_padre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Edad"}),
            "enfermedades_actuales_padre": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Describa enfermedades actuales"}),
            "alergias_padre": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Describa alergias"}),
            "edad_madre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Edad"}),
            "enfermedades_actuales_madre": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Describa enfermedades actuales"}),
            "enfermedades_infancia_madre": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Describa enfermedades de la infancia"}),
            "alergias_madre": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Describa alergias"}),
            "numero_gestas": forms.TextInput(attrs={"class": "form-control", "placeholder": "Número de gestas"}),
            "complicaciones_embarazo": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Complicaciones durante el embarazo"}),
            "medicamentos_embarazo": forms.Textarea(attrs={"class": "form-control", "rows": 2,
                                                           "placeholder": "Medicamentos o vitaminas durante el embarazo"}),
            "exposicion_radiacion": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Exposición a radiación"}),
            "sufrimiento_fetal": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Sufrimiento fetal"}),
            "semanas_gestacion": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Semanas de gestación"}),
            "motivo_cesarea": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Motivo de cesárea"}),
            "enfermedades_actuales": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "enfermedades_neonatales": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "enfermedades_exantematicas": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "internamientos_quirurgicos": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "alergia_medicamentos": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "alergia_alimentos": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "personas_enfermas_casa": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "vomitos": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "excreta_acuosa": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "fiebre": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "tos": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "rinorrea": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "erupciones": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "dificultad_respiratoria": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "peso_actual": forms.TextInput(attrs={"class": "form-control", "placeholder": "kg"}),
            "talla": forms.TextInput(attrs={"class": "form-control", "placeholder": "cm"}),
            "temperatura": forms.TextInput(attrs={"class": "form-control", "placeholder": "°C"}),
            "frecuencia_cardiaca": forms.TextInput(attrs={"class": "form-control", "placeholder": "lpm"}),
            "frecuencia_respiratoria": forms.TextInput(attrs={"class": "form-control", "placeholder": "rpm"}),
            "tension_arterial": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej. 90/60"}),
            "estado_nutricional": forms.TextInput(attrs={"class": "form-control", "placeholder": "Estado nutricional"}),
            "diagnostico": forms.Textarea(
                attrs={"class": "form-control", "rows": 3, "placeholder": "Diagnóstico médico"}),
            "pronostico": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Pronóstico"}),
            "elaborado_por": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre del médico"}),
        }

    def clean_numero_gestas(self):
        val = self.cleaned_data.get('numero_gestas') or ''
        if len(val) > 10:
            if "1" in val:
                val = "1"
            elif "2" in val:
                val = "2"
            elif "3" in val:
                val = "3"
            elif "4" in val:
                val = "4 o mas"
            else:
                val = val[:10]
        return val

    def clean_semanas_gestacion(self):
        val = self.cleaned_data.get('semanas_gestacion') or ''
        if len(val) > 20:
            if "Menos" in val:
                val = "< 37 sem"
            elif "37 a 41" in val:
                val = "37 a 41 sem"
            elif "42" in val:
                val = "> 42 sem"
            elif "Desconoce" in val:
                val = "Desconoce"
            else:
                val = val[:20]
        return val

    def __init__(self, *args, **kwargs):
        sol = kwargs.pop('solicitud', None)
        # Si la historia clínica acaba de crearse, los campos Sí/No deben iniciar vacíos.
        # Esto evita que Tabaquismo, Alcoholismo y Drogas aparezcan como "No" automáticamente.
        historia_nueva = kwargs.pop('historia_nueva', False)
        super().__init__(*args, **kwargs)

        campos_compartidos_medico = [
            "edad",
            "sexo",
            "fecha_nacimiento",
            "peso_actual",
            "talla",
            "numero_gestas",
            "semanas_gestacion",
            "tipo_parto",
            "complicaciones_embarazo",
            "alergia_alimentos",
            "alergia_medicamentos",
            "enfermedades_actuales",
            "estado_nutricional",
        ]
        for campo in campos_compartidos_medico:
            if campo in self.fields:
                _marcar_widget_dato_compartido(self.fields[campo], campo)

        if sol:
            if not self.initial.get('nombres_paciente'):
                self.initial['nombres_paciente'] = sol.nombres_menor
                self.initial['apellido_paterno_paciente'] = sol.apellido_paterno_menor
                self.initial['apellido_materno_paciente'] = sol.apellido_materno_menor
            if not self.initial.get('numero_gestas'):
                self.initial['numero_gestas'] = sol.numero_gesta_psicologia
            if not self.initial.get('semanas_gestacion'):
                self.initial['semanas_gestacion'] = sol.semanas_gestacion_psicologia
            if not self.initial.get('peso_actual'):
                self.initial['peso_actual'] = sol.peso_actual or sol.peso_al_nacer_psicologia
            if not self.initial.get('talla'):
                self.initial['talla'] = sol.talla_actual or sol.talla_al_nacer_psicologia

            parto = (sol.tipo_nacimiento_psicologia or "").upper()
            if not self.initial.get('tipo_parto'):
                if "CESAREA" in parto:
                    self.initial['tipo_parto'] = "Cesárea"
                elif "PARTO" in parto:
                    self.initial['tipo_parto'] = "Eutócico"

            if sol.nombre_padre_psicologia and not self.initial.get('nombres_padre'):
                parts = sol.nombre_padre_psicologia.split()
                if len(parts) >= 3:
                    self.initial['nombres_padre'] = " ".join(parts[:-2])
                    self.initial['apellido_paterno_padre'] = parts[-2]
                    self.initial['apellido_materno_padre'] = parts[-1]
                else:
                    self.initial['nombres_padre'] = sol.nombre_padre_psicologia
                self.initial['edad_padre'] = sol.edad_padre_psicologia

            if sol.nombre_madre_psicologia and not self.initial.get('nombres_madre'):
                parts = sol.nombre_madre_psicologia.split()
                if len(parts) >= 3:
                    self.initial['nombres_madre'] = " ".join(parts[:-2])
                    self.initial['apellido_paterno_madre'] = parts[-2]
                    self.initial['apellido_materno_madre'] = parts[-1]
                else:
                    self.initial['nombres_madre'] = sol.nombre_madre_psicologia
                self.initial['edad_madre'] = sol.edad_madre_psicologia

        if self.instance and self.instance.pk and not historia_nueva:
            self.initial["tabaquismo_padre"] = "SI" if self.instance.tabaquismo_padre else "NO"
            self.initial["alcoholismo_padre"] = "SI" if self.instance.alcoholismo_padre else "NO"
            self.initial["drogas_padre"] = "SI" if self.instance.drogas_padre else "NO"
            self.initial["tabaquismo_madre"] = "SI" if self.instance.tabaquismo_madre else "NO"
            self.initial["alcoholismo_madre"] = "SI" if self.instance.alcoholismo_madre else "NO"
            self.initial["drogas_madre"] = "SI" if self.instance.drogas_madre else "NO"
        elif historia_nueva:
            # En primera captura médica se muestran vacíos para obligar selección manual.
            self.initial.setdefault("tabaquismo_padre", "")
            self.initial.setdefault("alcoholismo_padre", "")
            self.initial.setdefault("drogas_padre", "")
            self.initial.setdefault("tabaquismo_madre", "")
            self.initial.setdefault("alcoholismo_madre", "")
            self.initial.setdefault("drogas_madre", "")

            if self.instance.nombre_paciente and not self.initial.get("nombres_paciente"):
                parts = self.instance.nombre_paciente.split()
                if len(parts) >= 3:
                    self.initial["nombres_paciente"] = " ".join(parts[:-2])
                    self.initial["apellido_paterno_paciente"] = parts[-2]
                    self.initial["apellido_materno_paciente"] = parts[-1]
                elif len(parts) == 2:
                    self.initial["nombres_paciente"] = parts[0]
                    self.initial["apellido_paterno_paciente"] = parts[1]
                else:
                    self.initial["nombres_paciente"] = self.instance.nombre_paciente

            if self.instance.nombre_padre and not self.initial.get("nombres_padre"):
                parts = self.instance.nombre_padre.split()
                if len(parts) >= 3:
                    self.initial["nombres_padre"] = " ".join(parts[:-2])
                    self.initial["apellido_paterno_padre"] = parts[-2]
                    self.initial["apellido_materno_padre"] = parts[-1]
                elif len(parts) == 2:
                    self.initial["nombres_padre"] = parts[0]
                    self.initial["apellido_paterno_padre"] = parts[1]
                else:
                    self.initial["nombres_padre"] = self.instance.nombre_padre

            if self.instance.nombre_madre and not self.initial.get("nombres_madre"):
                parts = self.instance.nombre_madre.split()
                if len(parts) >= 3:
                    self.initial["nombres_madre"] = " ".join(parts[:-2])
                    self.initial["apellido_paterno_madre"] = parts[-2]
                    self.initial["apellido_materno_madre"] = parts[-1]
                elif len(parts) == 2:
                    self.initial["nombres_madre"] = parts[0]
                    self.initial["apellido_paterno_madre"] = parts[1]
                else:
                    self.initial["nombres_madre"] = self.instance.nombre_madre

        for name, field in self.fields.items():
            if "class" not in field.widget.attrs:
                if isinstance(field.widget, forms.Select):
                    field.widget.attrs["class"] = "form-select"
                elif isinstance(field.widget, forms.Textarea):
                    field.widget.attrs["class"] = "form-control"
                    field.widget.attrs.setdefault("rows", 2)
                else:
                    field.widget.attrs["class"] = "form-control"

    def save(self, commit=True):
        instance = super().save(commit=False)

        np = self.cleaned_data.get("nombres_paciente", "").strip()
        app = self.cleaned_data.get("apellido_paterno_paciente", "").strip()
        amp = self.cleaned_data.get("apellido_materno_paciente", "").strip()
        instance.nombre_paciente = f"{np} {app} {amp}".strip()

        npad = self.cleaned_data.get("nombres_padre", "").strip()
        appad = self.cleaned_data.get("apellido_paterno_padre", "").strip()
        ampad = self.cleaned_data.get("apellido_materno_padre", "").strip()
        instance.nombre_padre = f"{npad} {appad} {ampad}".strip()

        nmad = self.cleaned_data.get("nombres_madre", "").strip()
        apmad = self.cleaned_data.get("apellido_paterno_madre", "").strip()
        ammad = self.cleaned_data.get("apellido_materno_madre", "").strip()
        instance.nombre_madre = f"{nmad} {apmad} {ammad}".strip()

        if commit: instance.save()
        return instance


# =========================================================
# SPRINT 4 - FORMULARIOS DE CONFIGURACIÓN DE SEMESTRE
# Rol principal: Administrador del Sistema
# =========================================================

def aplicar_clases_bootstrap(form):
    """
    Aplica estilos Bootstrap de forma uniforme.
    """
    for name, field in form.fields.items():
        existing = field.widget.attrs.get("class", "")

        if isinstance(field.widget, forms.CheckboxSelectMultiple):
            field.widget.attrs["class"] = f"{existing} form-check-input".strip()
        elif isinstance(field.widget, forms.CheckboxInput):
            field.widget.attrs["class"] = f"{existing} form-check-input".strip()
        elif isinstance(field.widget, forms.SelectMultiple):
            field.widget.attrs["class"] = f"{existing} form-select".strip()
        elif isinstance(field.widget, forms.Select):
            field.widget.attrs["class"] = f"{existing} form-select".strip()
        elif isinstance(field.widget, forms.Textarea):
            field.widget.attrs["class"] = f"{existing} form-control".strip()
            field.widget.attrs.setdefault("rows", 3)
        else:
            field.widget.attrs["class"] = f"{existing} form-control".strip()



def fecha_es_fin_de_semana(fecha):
    """
    Regla operativa de la estancia:
    sábado y domingo son inhábiles automáticos.
    Esto NO bloquea el inicio de sesión; solo bloquea operación diaria.
    """
    return bool(fecha and fecha.weekday() in (5, 6))


def dia_operativo_no_laborable(dia):
    """
    True cuando un día no debe permitir operación diaria:
    sábado, domingo, festivo, suspensión, consejo técnico o día no hábil.
    """
    if not dia:
        return False

    try:
        if getattr(dia, "es_fin_de_semana", False):
            return True
    except Exception:
        pass

    fecha = getattr(dia, "fecha", None)

    return bool(
        fecha_es_fin_de_semana(fecha)
        or not getattr(dia, "es_habil", True)
    )


def mensaje_dia_no_laborable(dia):
    """
    Mensaje claro para maestras y formularios de operación diaria.
    """
    if not dia:
        return "No existe día operativo para la fecha seleccionada."

    try:
        mensaje_modelo = getattr(dia, "mensaje_no_operativo", "")
        if mensaje_modelo:
            return mensaje_modelo
    except Exception:
        pass

    fecha = getattr(dia, "fecha", None)

    if fecha_es_fin_de_semana(fecha):
        return (
            "La estancia no opera sábados ni domingos. "
            "Puedes iniciar sesión y consultar información, pero no abrir operación diaria, "
            "registrar entradas, salidas ni bitácoras."
        )

    if not getattr(dia, "es_habil", True):
        return "Este día está marcado como inhábil. No se permite operación diaria."

    return "Este día no permite operación diaria."


def usuarios_por_rol(*palabras_clave):
    """
    Devuelve usuarios activos cuyo tipo_persona o grupo coincida con alguna palabra.
    Sirve para médica, nutrióloga, psicóloga y maestras.
    Si no encuentra coincidencias, devuelve todos los usuarios activos para no bloquear el alta inicial.
    """
    User = get_user_model()
    qs = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")

    try:
        from django.db.models import Q

        q = Q()
        for palabra in palabras_clave:
            q |= Q(groups__name__icontains=palabra)
            if "tipo_persona" in [f.name for f in User._meta.fields]:
                q |= Q(tipo_persona__icontains=palabra)

        filtrados = qs.filter(q).distinct()

        if filtrados.exists():
            return filtrados

    except Exception:
        pass

    return qs



# =========================================================
# SUPLENCIAS OPERATIVAS
# Pase de lista, autorización temporal y revisión de movimientos.
# =========================================================

def usuario_nombre_visible(usuario):
    if not usuario:
        return "Sin usuario"

    for attr in ["nombre_visible", "nombre_completo"]:
        try:
            valor = getattr(usuario, attr)
            if callable(valor):
                valor = valor()
            if valor:
                return str(valor)
        except Exception:
            pass

    try:
        nombre = usuario.get_full_name()
        if nombre:
            return nombre
    except Exception:
        pass

    return getattr(usuario, "email", "") or getattr(usuario, "username", "") or str(usuario)


AREAS_OPERATIVAS_PASE_LISTA = [
    "MEDICA",
    "NUTRICION",
    "PSICOLOGIA",
    "PEDAGOGICA",
    "TRABAJO_SOCIAL",
]

AREAS_OPERATIVAS_SUPLENTE = [
    "DIRECCION",
    "MEDICA",
    "NUTRICION",
    "PSICOLOGIA",
    "PEDAGOGICA",
    "TRABAJO_SOCIAL",
]

AREA_OPERATIVA_DISPLAY = {
    "DIRECCION": "Dirección",
    "MEDICA": "Médica",
    "NUTRICION": "Nutrición",
    "PSICOLOGIA": "Psicología",
    "PEDAGOGICA": "Pedagógica",
    "TRABAJO_SOCIAL": "Trabajo Social",
}


def normalizar_texto_area(valor):
    valor = str(valor or "").strip().lower()
    valor = unicodedata.normalize("NFD", valor)
    valor = "".join(c for c in valor if unicodedata.category(c) != "Mn")
    valor = re.sub(r"[^a-z0-9]+", " ", valor)
    return re.sub(r"\s+", " ", valor).strip()


def inferir_area_operativa_usuario(usuario):
    """
    Devuelve el área operativa real del usuario.

    Primero usa usuario.area_operativa. Si todavía no se llenó ese campo en el
    admin, intenta inferirla por grupos, correo o nombre para que el pase de
    lista no aparezca como "Sin área asignada" y pueda autorizar suplencias.
    """
    if not usuario:
        return ""

    area = str(getattr(usuario, "area_operativa", "") or "").strip().upper()
    if area in AREAS_OPERATIVAS_SUPLENTE:
        return area

    textos = [
        getattr(usuario, "username", ""),
        getattr(usuario, "email", ""),
        getattr(usuario, "first_name", ""),
        getattr(usuario, "last_name", ""),
        getattr(usuario, "nombre", ""),
        getattr(usuario, "apellido_paterno", ""),
        getattr(usuario, "apellido_materno", ""),
    ]

    try:
        textos.extend([g.name for g in usuario.groups.all()])
    except Exception:
        pass

    texto = normalizar_texto_area(" ".join(str(t or "") for t in textos))

    if "trabajo social" in texto or "trabajadora social" in texto or "trabajador social" in texto or "trabajadorasocial" in texto:
        return "TRABAJO_SOCIAL"
    if "nutri" in texto:
        return "NUTRICION"
    if "psicolog" in texto or "psicologa" in texto or "psicologo" in texto:
        return "PSICOLOGIA"
    if "medic" in texto or "medica" in texto or "medico" in texto:
        return "MEDICA"
    if "pedagog" in texto or "coordinadora" in texto or "coordinador" in texto:
        return "PEDAGOGICA"
    if "directora" in texto or "direccion" in texto:
        return "DIRECCION"

    return ""


def nombre_area_operativa_usuario(usuario):
    area = inferir_area_operativa_usuario(usuario)
    return AREA_OPERATIVA_DISPLAY.get(area, "Área pendiente en usuario")


def actualizar_area_operativa_usuario_si_falta(usuario, areas_validas=None):
    """
    Guarda en Usuario.area_operativa el área inferida cuando el usuario todavía
    no la tiene capturada en el admin.

    Esto evita que el HTML muestre correctamente el área por correo/grupo, pero
    al guardar la suplencia el modelo rechace a la persona por tener
    area_operativa vacío.

    No cambia roles, grupos, contraseñas ni permisos de inicio de sesión.
    Solo llena area_operativa si el modelo Usuario tiene ese campo.
    """
    if not usuario:
        return ""

    area = inferir_area_operativa_usuario(usuario)
    areas_validas = list(areas_validas or AREAS_OPERATIVAS_SUPLENTE)

    if area not in areas_validas:
        return area

    try:
        campos_usuario = {campo.name for campo in usuario._meta.fields}
    except Exception:
        campos_usuario = set()

    if "area_operativa" not in campos_usuario:
        return area

    area_actual = str(getattr(usuario, "area_operativa", "") or "").strip().upper()

    if area_actual != area:
        try:
            setattr(usuario, "area_operativa", area)
            usuario.save(update_fields=["area_operativa"])
        except Exception:
            # Si por alguna razón no se puede guardar aquí, la validación del
            # formulario seguirá usando el área inferida y mostrará un error claro
            # si el modelo no acepta el registro.
            pass

    return area


def personal_operativo_pase_lista_queryset():
    """
    Personal que aparece en el pase de lista diario.
    No incluye Directora, Supervisora, Administrador, Beneficiarios ni Alumnos.

    Acepta usuarios con area_operativa asignada y también usuarios que aún
    conservan solo grupos/roles antiguos, para evitar que aparezcan como
    "Sin área asignada" mientras se completa el admin.
    """
    User = get_user_model()
    qs = User.objects.filter(is_active=True)
    campos = {campo.name for campo in User._meta.fields}

    if "tipo_persona" in campos:
        qs = qs.filter(tipo_persona="PERSONAL")

    if "estatus_operativo" in campos:
        qs = qs.filter(estatus_operativo=True)

    q_grupos = (
        Q(groups__name__icontains="medic") |
        Q(groups__name__icontains="médic") |
        Q(groups__name__icontains="nutri") |
        Q(groups__name__icontains="psicolog") |
        Q(groups__name__icontains="psicólog") |
        Q(groups__name__icontains="pedagog") |
        Q(groups__name__icontains="pedagóg") |
        Q(groups__name__icontains="coordinador") |
        Q(groups__name__icontains="coordinadora") |
        Q(groups__name__icontains="trabajadora social") |
        Q(groups__name__icontains="trabajador social") |
        Q(username__icontains="medic") |
        Q(username__icontains="nutri") |
        Q(username__icontains="psicolog") |
        Q(username__icontains="coordinador") |
        Q(username__icontains="trabajadorasocial") |
        Q(email__icontains="medic") |
        Q(email__icontains="nutri") |
        Q(email__icontains="psicolog") |
        Q(email__icontains="coordinador") |
        Q(email__icontains="trabajadorasocial")
    )

    if "area_operativa" in campos:
        qs = qs.filter(Q(area_operativa__in=AREAS_OPERATIVAS_PASE_LISTA) | q_grupos)
    else:
        qs = qs.filter(q_grupos)

    return qs.distinct().order_by("first_name", "last_name", "username")


def personal_suplente_queryset(fecha=None, solo_disponibles=False, excluir_ids=None):
    """
    Personal que puede cubrir temporalmente un área.
    Incluye Dirección y áreas operativas autorizadas.
    No incluye Supervisora, Administrador, Beneficiarios ni Alumnos.

    Si solo_disponibles=True, solo devuelve personal marcado como PRESENTE
    o RETARDO en el pase de lista del día. Así no aparece como suplente
    quien no llegó o tiene permiso/incapacidad.
    """
    User = get_user_model()
    fecha = fecha or timezone.localdate()
    excluir_ids = list(excluir_ids or [])

    qs = User.objects.filter(is_active=True)
    campos = {campo.name for campo in User._meta.fields}

    if "tipo_persona" in campos:
        qs = qs.filter(tipo_persona="PERSONAL")

    if "estatus_operativo" in campos:
        qs = qs.filter(estatus_operativo=True)

    q_grupos = (
        Q(groups__name__icontains="directora") |
        Q(groups__name__icontains="direccion") |
        Q(groups__name__icontains="dirección") |
        Q(groups__name__icontains="medic") |
        Q(groups__name__icontains="médic") |
        Q(groups__name__icontains="nutri") |
        Q(groups__name__icontains="psicolog") |
        Q(groups__name__icontains="psicólog") |
        Q(groups__name__icontains="pedagog") |
        Q(groups__name__icontains="pedagóg") |
        Q(groups__name__icontains="coordinador") |
        Q(groups__name__icontains="coordinadora") |
        Q(groups__name__icontains="trabajadora social") |
        Q(groups__name__icontains="trabajador social") |
        Q(username__icontains="directora") |
        Q(username__icontains="direccion") |
        Q(username__icontains="medic") |
        Q(username__icontains="nutri") |
        Q(username__icontains="psicolog") |
        Q(username__icontains="coordinador") |
        Q(username__icontains="trabajadorasocial") |
        Q(email__icontains="directora") |
        Q(email__icontains="direccion") |
        Q(email__icontains="medic") |
        Q(email__icontains="nutri") |
        Q(email__icontains="psicolog") |
        Q(email__icontains="coordinador") |
        Q(email__icontains="trabajadorasocial")
    )

    if "area_operativa" in campos:
        qs = qs.filter(Q(area_operativa__in=AREAS_OPERATIVAS_SUPLENTE) | q_grupos)
    else:
        qs = qs.filter(q_grupos)

    if solo_disponibles:
        disponibles_ids = AsistenciaPersonal.objects.filter(
            fecha=fecha,
            estado__in=[
                AsistenciaPersonal.EstadoAsistencia.PRESENTE,
                AsistenciaPersonal.EstadoAsistencia.RETARDO,
            ],
        ).values_list("trabajador_id", flat=True)

        # Dirección puede cubrir aunque no aparezca en el pase de lista operativo,
        # porque la Directora es quien registra el pase de lista y no se marca
        # como titular ausente normal.
        q_direccion_disponible = (
            Q(groups__name__icontains="directora") |
            Q(groups__name__icontains="direccion") |
            Q(groups__name__icontains="dirección") |
            Q(username__icontains="directora") |
            Q(username__icontains="direccion") |
            Q(email__icontains="directora") |
            Q(email__icontains="direccion")
        )

        if "area_operativa" in campos:
            q_direccion_disponible |= Q(area_operativa="DIRECCION")

        qs = qs.filter(Q(id__in=disponibles_ids) | q_direccion_disponible)

    if excluir_ids:
        qs = qs.exclude(id__in=excluir_ids)

    return qs.distinct().order_by("first_name", "last_name", "username")


class PersonalOperativoChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        area = nombre_area_operativa_usuario(obj)
        nombre = usuario_nombre_visible(obj)
        return f"{nombre} — {area}" if area else nombre


class AsistenciaPersonalForm(forms.ModelForm):
    """
    Formulario individual para el pase de lista del personal.
    La directora marca si cada trabajadora está presente, ausente, con permiso,
    incapacidad o retardo.
    """

    trabajador = PersonalOperativoChoiceField(
        queryset=get_user_model().objects.none(),
        required=True,
        label="Personal operativo",
        empty_label="Seleccione personal...",
        widget=forms.Select()
    )

    class Meta:
        model = AsistenciaPersonal
        fields = [
            "fecha",
            "trabajador",
            "estado",
            "observaciones",
        ]
        widgets = {
            "fecha": forms.DateInput(attrs={"type": "date"}),
            "estado": forms.Select(),
            "observaciones": forms.Textarea(attrs={
                "rows": 2,
                "placeholder": "Opcional. Ej. Permiso autorizado, incapacidad, retardo justificado."
            }),
        }
        labels = {
            "fecha": "Fecha",
            "estado": "Estado del personal",
            "observaciones": "Observaciones",
        }

    def __init__(self, *args, **kwargs):
        self.usuario = kwargs.pop("usuario", None)
        self.semestre = kwargs.pop("semestre", None)
        super().__init__(*args, **kwargs)
        self.fields["trabajador"].queryset = personal_operativo_pase_lista_queryset()
        self.fields["fecha"].initial = self.initial.get("fecha") or timezone.localdate()
        aplicar_clases_bootstrap(self)

    def clean_trabajador(self):
        trabajador = self.cleaned_data.get("trabajador")
        if not trabajador:
            return trabajador

        tipo_persona = str(getattr(trabajador, "tipo_persona", "") or "").upper()
        area = inferir_area_operativa_usuario(trabajador)

        if tipo_persona != "PERSONAL" or area not in AREAS_OPERATIVAS_PASE_LISTA:
            raise forms.ValidationError(
                "Solo se permite registrar asistencia de Médica, Nutrición, Psicología, Pedagógica y Trabajo Social."
            )

        actualizar_area_operativa_usuario_si_falta(
            trabajador,
            areas_validas=AREAS_OPERATIVAS_PASE_LISTA,
        )

        return trabajador

    def save(self, commit=True):
        obj = super().save(commit=False)
        trabajador = self.cleaned_data.get("trabajador")

        if trabajador:
            obj.area_operativa = inferir_area_operativa_usuario(trabajador)

        if self.semestre:
            obj.semestre = self.semestre

        if not obj.pk:
            obj.registrado_por = self.usuario

        obj.actualizado_por = self.usuario

        if commit:
            obj.save()

        return obj


class PaseListaPersonalForm(forms.Form):
    """
    Formulario compacto para registrar el pase de lista completo desde el panel
    de Dirección sin crear pantallas extras.

    La vista debe recibir los campos con el patrón:
    estado_<usuario_id> y observaciones_<usuario_id>.
    """

    confirmar = forms.BooleanField(
        required=True,
        label="Confirmo que deseo guardar el pase de lista del personal"
    )

    def __init__(self, *args, **kwargs):
        self.usuario = kwargs.pop("usuario", None)
        self.semestre = kwargs.pop("semestre", None)
        self.fecha = kwargs.pop("fecha", timezone.localdate())
        self.personal = list(kwargs.pop("personal", None) or personal_operativo_pase_lista_queryset())
        super().__init__(*args, **kwargs)

        for trabajador in self.personal:
            nombre = usuario_nombre_visible(trabajador)
            self.fields[f"estado_{trabajador.id}"] = forms.ChoiceField(
                choices=AsistenciaPersonal.EstadoAsistencia.choices,
                required=True,
                label=nombre,
                initial=AsistenciaPersonal.EstadoAsistencia.NO_REGISTRADO,
                widget=forms.Select()
            )
            self.fields[f"observaciones_{trabajador.id}"] = forms.CharField(
                required=False,
                label=f"Observaciones de {nombre}",
                widget=forms.Textarea(attrs={"rows": 2})
            )

        aplicar_clases_bootstrap(self)

    def guardar(self):
        if not self.is_valid():
            raise ValueError("El formulario de pase de lista no es válido.")

        registros = []

        for trabajador in self.personal:
            estado = self.cleaned_data.get(f"estado_{trabajador.id}")
            observaciones = self.cleaned_data.get(f"observaciones_{trabajador.id}") or ""
            area = actualizar_area_operativa_usuario_si_falta(
                trabajador,
                areas_validas=AREAS_OPERATIVAS_PASE_LISTA,
            )

            registro, creado = AsistenciaPersonal.objects.update_or_create(
                fecha=self.fecha,
                trabajador=trabajador,
                defaults={
                    "semestre": self.semestre,
                    "area_operativa": area,
                    "estado": estado,
                    "observaciones": observaciones,
                    "actualizado_por": self.usuario,
                }
            )

            # Si se acaba de crear, también guardamos quién registró el pase.
            if creado and not registro.registrado_por_id:
                registro.registrado_por = self.usuario
                registro.save(update_fields=["registrado_por"])

            registros.append(registro)

        return registros


class AutorizacionSuplenciaForm(forms.ModelForm):
    """
    La directora autoriza una suplencia solo cuando el pase de lista indica
    ausencia, permiso o incapacidad de la titular.
    """

    titular_ausente = PersonalOperativoChoiceField(
        queryset=get_user_model().objects.none(),
        required=True,
        label="Titular ausente",
        empty_label="Seleccione titular ausente...",
        widget=forms.Select()
    )

    suplente = PersonalOperativoChoiceField(
        queryset=get_user_model().objects.none(),
        required=True,
        label="Persona que cubrirá temporalmente",
        empty_label="Seleccione suplente...",
        widget=forms.Select()
    )

    class Meta:
        model = AutorizacionSuplencia
        fields = [
            "titular_ausente",
            "suplente",
            "tipo_cobertura",
            "inicio",
            "fin",
            "motivo",
            "observaciones",
        ]
        widgets = {
            "tipo_cobertura": forms.Select(),
            "inicio": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "fin": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "motivo": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Ej. Personal ausente, permiso autorizado o incapacidad."
            }),
            "observaciones": forms.Textarea(attrs={
                "rows": 2,
                "placeholder": "Opcional. Detalles internos de la autorización."
            }),
        }
        labels = {
            "tipo_cobertura": "Tipo de cobertura",
            "inicio": "Inicio de vigencia",
            "fin": "Fin de vigencia",
            "motivo": "Motivo",
            "observaciones": "Observaciones",
        }

    def __init__(self, *args, **kwargs):
        self.usuario = kwargs.pop("usuario", None)
        self.fecha = kwargs.pop("fecha", timezone.localdate())
        self.semestre = kwargs.pop("semestre", None)
        self.asistencia_personal = kwargs.pop("asistencia_personal", None)
        super().__init__(*args, **kwargs)

        estados_ausencia = [
            AsistenciaPersonal.EstadoAsistencia.AUSENTE,
            AsistenciaPersonal.EstadoAsistencia.PERMISO,
            AsistenciaPersonal.EstadoAsistencia.INCAPACIDAD,
        ]

        ausentes_ids = list(
            AsistenciaPersonal.objects.filter(
                fecha=self.fecha,
                estado__in=estados_ausencia,
            ).values_list("trabajador_id", flat=True)
        )

        titular_id = None
        if self.asistencia_personal:
            titular_id = self.asistencia_personal.trabajador_id
            titulares_qs = get_user_model().objects.filter(pk=titular_id)
        else:
            if self.data:
                titular_id = self.data.get(self.add_prefix("titular_ausente")) or self.data.get("titular_ausente")
            titulares_ids = list(ausentes_ids)
            if titular_id:
                try:
                    titular_id_int = int(titular_id)
                    if titular_id_int not in titulares_ids:
                        titulares_ids.append(titular_id_int)
                except (TypeError, ValueError):
                    pass
            titulares_qs = personal_operativo_pase_lista_queryset().filter(id__in=titulares_ids)

        excluir_suplentes = []
        if titular_id:
            try:
                excluir_suplentes.append(int(titular_id))
            except (TypeError, ValueError):
                pass

        self.fields["titular_ausente"].queryset = titulares_qs.distinct()
        self.fields["suplente"].queryset = personal_suplente_queryset(
            fecha=self.fecha,
            solo_disponibles=True,
            excluir_ids=excluir_suplentes,
        )

        if self.asistencia_personal:
            self.fields["titular_ausente"].initial = self.asistencia_personal.trabajador
            self.fields["titular_ausente"].disabled = True

        self.fields["titular_ausente"].help_text = "Solo aparecen trabajadoras marcadas como ausentes, con permiso o incapacidad."
        self.fields["suplente"].help_text = "Solo aparece personal presente o con retardo; nunca aparece quien faltó."
        self.fields["inicio"].initial = self.initial.get("inicio") or timezone.localtime(timezone.now()).strftime("%Y-%m-%dT%H:%M")

        aplicar_clases_bootstrap(self)

    def _area_desde_usuario(self, usuario):
        area_usuario = inferir_area_operativa_usuario(usuario)
        return AutorizacionSuplencia.AREAS_USUARIO_A_CUBIERTA.get(area_usuario, "")

    def clean_titular_ausente(self):
        titular = self.cleaned_data.get("titular_ausente")

        if self.asistencia_personal:
            titular = self.asistencia_personal.trabajador

        if not titular:
            return titular

        area = inferir_area_operativa_usuario(titular)
        if area not in AREAS_OPERATIVAS_PASE_LISTA:
            raise forms.ValidationError(
                "La titular ausente debe pertenecer a Médica, Nutrición, Psicología, Pedagógica o Trabajo Social. "
                "Asigna el área operativa en el admin o revisa su grupo/rol."
            )

        actualizar_area_operativa_usuario_si_falta(
            titular,
            areas_validas=AREAS_OPERATIVAS_PASE_LISTA,
        )

        return titular

    def clean_suplente(self):
        suplente = self.cleaned_data.get("suplente")

        if not suplente:
            return suplente

        area = inferir_area_operativa_usuario(suplente)
        if area not in AREAS_OPERATIVAS_SUPLENTE:
            raise forms.ValidationError(
                "La suplente debe ser Dirección o personal operativo autorizado. "
                "No se permite supervisora, administrador, beneficiarios ni alumnos."
            )

        actualizar_area_operativa_usuario_si_falta(
            suplente,
            areas_validas=AREAS_OPERATIVAS_SUPLENTE,
        )

        asistencia = AsistenciaPersonal.objects.filter(
            fecha=self.fecha,
            trabajador=suplente,
        ).order_by("-id").first()

        if asistencia and asistencia.estado in [
            AsistenciaPersonal.EstadoAsistencia.AUSENTE,
            AsistenciaPersonal.EstadoAsistencia.PERMISO,
            AsistenciaPersonal.EstadoAsistencia.INCAPACIDAD,
            AsistenciaPersonal.EstadoAsistencia.NO_REGISTRADO,
        ]:
            raise forms.ValidationError("La suplente debe estar presente; no puede elegirse personal ausente, con permiso, incapacidad o sin registro.")

        if not asistencia and area != "DIRECCION":
            raise forms.ValidationError("Primero marca como presente a la persona suplente en el pase de lista.")

        return suplente

    def clean_motivo(self):
        motivo = (self.cleaned_data.get("motivo") or "").strip()
        if len(motivo) < 5:
            raise forms.ValidationError("Captura un motivo claro para la suplencia.")
        return motivo

    def clean(self):
        cleaned = super().clean()
        titular = cleaned.get("titular_ausente")
        suplente = cleaned.get("suplente")
        tipo_cobertura = cleaned.get("tipo_cobertura")
        inicio = cleaned.get("inicio")
        fin = cleaned.get("fin")

        if self.asistencia_personal:
            asistencia = self.asistencia_personal
        elif titular:
            asistencia = AsistenciaPersonal.objects.filter(
                fecha=self.fecha,
                trabajador=titular,
            ).order_by("-id").first()
        else:
            asistencia = None

        if not asistencia:
            self.add_error("titular_ausente", "Primero debe registrarse el pase de lista de esta persona.")
        elif asistencia.estado == AsistenciaPersonal.EstadoAsistencia.NO_REGISTRADO:
            self.add_error("titular_ausente", "Primero debe completarse el pase de lista de esta persona.")
        elif asistencia.estado == AsistenciaPersonal.EstadoAsistencia.PRESENTE:
            self.add_error("titular_ausente", "No se puede autorizar suplencia porque la titular está marcada como presente.")
        elif not asistencia.permite_suplencia:
            self.add_error("titular_ausente", "Solo se puede autorizar suplencia si la titular está ausente, con permiso o incapacidad.")

        if titular and suplente and titular.id == suplente.id:
            self.add_error("suplente", "La suplente no puede ser la misma persona titular ausente.")

        area_cubierta = self._area_desde_usuario(titular) if titular else ""

        if area_cubierta == AutorizacionSuplencia.AreaCubierta.TRABAJO_SOCIAL:
            if tipo_cobertura != AutorizacionSuplencia.TipoCobertura.PROCESO_SOCIAL_COMPLETO:
                cleaned["tipo_cobertura"] = AutorizacionSuplencia.TipoCobertura.PROCESO_SOCIAL_COMPLETO
        elif tipo_cobertura == AutorizacionSuplencia.TipoCobertura.PROCESO_SOCIAL_COMPLETO:
            self.add_error("tipo_cobertura", "La cobertura completa solo aplica para Trabajo Social.")

        if inicio and fin and fin <= inicio:
            self.add_error("fin", "La fecha/hora final debe ser posterior al inicio.")

        if titular and area_cubierta:
            activa = AutorizacionSuplencia.activas_por_area(area_cubierta, fecha=self.fecha)
            if self.instance and self.instance.pk:
                activa = activa.exclude(pk=self.instance.pk)
            if activa.exists():
                self.add_error("titular_ausente", "Ya existe una suplencia activa para esta área en la fecha seleccionada.")

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        titular = self.cleaned_data.get("titular_ausente")

        if self.asistencia_personal:
            obj.asistencia_personal = self.asistencia_personal
            titular = self.asistencia_personal.trabajador
        else:
            obj.asistencia_personal = AsistenciaPersonal.objects.filter(
                fecha=self.fecha,
                trabajador=titular,
            ).order_by("-id").first()

        obj.fecha = self.fecha
        obj.titular_ausente = titular
        obj.area_cubierta = self._area_desde_usuario(titular)
        obj.autorizada_por = self.usuario
        obj.estado = AutorizacionSuplencia.EstadoAutorizacion.ACTIVA

        if obj.area_cubierta == AutorizacionSuplencia.AreaCubierta.TRABAJO_SOCIAL:
            obj.tipo_cobertura = AutorizacionSuplencia.TipoCobertura.PROCESO_SOCIAL_COMPLETO

        # Importante:
        # El modelo AutorizacionSuplencia valida usando propiedades estrictas
        # del Usuario como puede_ser_suplente y puede_ser_titular_ausente.
        # Si el área solo se infirió por correo/grupo para mostrarla en pantalla,
        # aquí la dejamos guardada antes de ejecutar full_clean().
        actualizar_area_operativa_usuario_si_falta(
            titular,
            areas_validas=AREAS_OPERATIVAS_PASE_LISTA,
        )
        actualizar_area_operativa_usuario_si_falta(
            obj.suplente,
            areas_validas=AREAS_OPERATIVAS_SUPLENTE,
        )

        if commit:
            obj.full_clean()
            obj.save()

        return obj


class CancelarSuplenciaForm(forms.Form):
    motivo_cancelacion = forms.CharField(
        required=True,
        label="Motivo de cancelación",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Explica por qué se cancela la autorización."
        })
    )
    confirmar = forms.BooleanField(
        required=True,
        label="Confirmo que deseo cancelar esta autorización"
    )

    def __init__(self, *args, **kwargs):
        self.autorizacion = kwargs.pop("autorizacion", None)
        self.usuario = kwargs.pop("usuario", None)
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)

    def clean_motivo_cancelacion(self):
        motivo = (self.cleaned_data.get("motivo_cancelacion") or "").strip()
        if len(motivo) < 5:
            raise forms.ValidationError("Captura un motivo claro de cancelación.")
        return motivo

    def clean(self):
        cleaned = super().clean()
        if not self.autorizacion:
            raise forms.ValidationError("No se encontró la autorización de suplencia.")
        if self.autorizacion.estado != AutorizacionSuplencia.EstadoAutorizacion.ACTIVA:
            raise forms.ValidationError("La autorización ya no está activa.")
        return cleaned

    def cancelar(self):
        if not self.is_valid():
            raise ValueError("El formulario de cancelación no es válido.")
        return self.autorizacion.cancelar(
            usuario=self.usuario,
            motivo=self.cleaned_data.get("motivo_cancelacion") or "",
        )


class RevisionMovimientoSuplenciaForm(forms.ModelForm):
    """
    La titular del área revisa o valida movimientos hechos durante su ausencia.
    También sirve para que Supervisora consulte el estado, sin darle permisos de edición.
    """

    class Meta:
        model = MovimientoSuplencia
        fields = [
            "estado",
            "observaciones_revision",
        ]
        widgets = {
            "estado": forms.Select(),
            "observaciones_revision": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Observaciones de revisión o validación."
            }),
        }
        labels = {
            "estado": "Estado de revisión",
            "observaciones_revision": "Observaciones",
        }

    def __init__(self, *args, **kwargs):
        self.usuario = kwargs.pop("usuario", None)
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)

    def clean(self):
        cleaned = super().clean()
        movimiento = self.instance
        usuario = self.usuario

        if not movimiento or not movimiento.pk:
            raise forms.ValidationError("No se encontró el movimiento de suplencia.")

        # Si la vista quiere permitir a Dirección validar, puede pasar usuario con área DIRECCION.
        area_usuario = str(getattr(usuario, "area_operativa", "") or "").upper() if usuario else ""
        es_titular = bool(usuario and movimiento.titular_area_id == usuario.id)
        es_direccion = area_usuario == "DIRECCION"

        if usuario and not (es_titular or es_direccion or getattr(usuario, "is_superuser", False)):
            raise forms.ValidationError("Solo la titular del área o Dirección puede validar este movimiento.")

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.revisado_por = self.usuario
        obj.revisado_en = timezone.now()
        if commit:
            obj.save()
        return obj


class FiltroBitacoraSuplenciaForm(forms.Form):
    fecha_inicio = forms.DateField(
        required=False,
        label="Desde",
        widget=forms.DateInput(attrs={"type": "date"})
    )
    fecha_fin = forms.DateField(
        required=False,
        label="Hasta",
        widget=forms.DateInput(attrs={"type": "date"})
    )
    area_cubierta = forms.ChoiceField(
        required=False,
        choices=[("", "Todas las áreas")] + list(AutorizacionSuplencia.AreaCubierta.choices),
        label="Área cubierta"
    )
    estado = forms.ChoiceField(
        required=False,
        choices=[("", "Todos los estados")] + list(MovimientoSuplencia.EstadoMovimiento.choices),
        label="Estado"
    )
    usuario = PersonalOperativoChoiceField(
        queryset=get_user_model().objects.none(),
        required=False,
        label="Persona que cubrió",
        empty_label="Todas las personas",
        widget=forms.Select()
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["usuario"].queryset = personal_suplente_queryset()
        aplicar_clases_bootstrap(self)

    def clean(self):
        cleaned = super().clean()
        fecha_inicio = cleaned.get("fecha_inicio")
        fecha_fin = cleaned.get("fecha_fin")

        if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
            self.add_error("fecha_fin", "La fecha final no puede ser anterior a la inicial.")

        return cleaned


class RevisarIncidenciaSuplenciaForm(forms.Form):
    observacion_revision = forms.CharField(
        required=False,
        label="Observaciones de revisión",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Opcional. Agrega observaciones o ajustes realizados por el área titular."
        })
    )
    confirmar = forms.BooleanField(
        required=True,
        label="Confirmo que revisé esta incidencia registrada por suplencia"
    )

    def __init__(self, *args, **kwargs):
        self.incidencia = kwargs.pop("incidencia", None)
        self.usuario = kwargs.pop("usuario", None)
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)

    def clean(self):
        cleaned = super().clean()
        incidencia = self.incidencia
        usuario = self.usuario

        if not incidencia:
            raise forms.ValidationError("No se encontró la incidencia.")

        if not getattr(incidencia, "creada_por_suplencia", False):
            raise forms.ValidationError("Esta incidencia no fue creada por suplencia.")

        autorizacion = getattr(incidencia, "autorizacion_suplencia", None)
        if autorizacion and usuario and autorizacion.titular_ausente_id != usuario.id:
            area_usuario = str(getattr(usuario, "area_operativa", "") or "").upper()
            if area_usuario != "DIRECCION" and not getattr(usuario, "is_superuser", False):
                raise forms.ValidationError("Solo la titular del área o Dirección puede revisar esta incidencia.")

        return cleaned

    def revisar(self):
        if not self.is_valid():
            raise ValueError("El formulario de revisión no es válido.")
        return self.incidencia.marcar_revisada_por_titular(
            usuario=self.usuario,
            observacion=self.cleaned_data.get("observacion_revision") or "",
        )


class RevisarTrabajoSocialSuplenciaForm(forms.Form):
    observacion_revision = forms.CharField(
        required=False,
        label="Observaciones de revisión",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Opcional. Agrega observaciones de revisión del proceso social."
        })
    )
    confirmar = forms.BooleanField(
        required=True,
        label="Confirmo que revisé los movimientos de Trabajo Social realizados por suplencia"
    )

    def __init__(self, *args, **kwargs):
        self.inscripcion = kwargs.pop("inscripcion", None)
        self.usuario = kwargs.pop("usuario", None)
        self.autorizacion_suplencia = kwargs.pop("autorizacion_suplencia", None)
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)

    def clean(self):
        cleaned = super().clean()
        if not self.inscripcion:
            raise forms.ValidationError("No se encontró el expediente.")
        if not getattr(self.inscripcion, "trabajo_social_es_suplencia", False):
            raise forms.ValidationError("Este expediente no tiene movimientos de Trabajo Social por suplencia.")
        return cleaned

    def revisar(self):
        if not self.is_valid():
            raise ValueError("El formulario de revisión no es válido.")
        return self.inscripcion.revisar_trabajo_social_suplencia(
            usuario=self.usuario,
            observacion=self.cleaned_data.get("observacion_revision") or "",
        )


ESTADO_SEDE_CHOICES = [
    ("", "Seleccione estado..."),
    ("Aguascalientes", "Aguascalientes"),
    ("Baja California", "Baja California"),
    ("Baja California Sur", "Baja California Sur"),
    ("Campeche", "Campeche"),
    ("Chiapas", "Chiapas"),
    ("Chihuahua", "Chihuahua"),
    ("Ciudad de México", "Ciudad de México"),
    ("Coahuila", "Coahuila"),
    ("Colima", "Colima"),
    ("Durango", "Durango"),
    ("Estado de México", "Estado de México"),
    ("Guanajuato", "Guanajuato"),
    ("Guerrero", "Guerrero"),
    ("Hidalgo", "Hidalgo"),
    ("Jalisco", "Jalisco"),
    ("Michoacán", "Michoacán"),
    ("Morelos", "Morelos"),
    ("Nayarit", "Nayarit"),
    ("Nuevo León", "Nuevo León"),
    ("Oaxaca", "Oaxaca"),
    ("Puebla", "Puebla"),
    ("Querétaro", "Querétaro"),
    ("Quintana Roo", "Quintana Roo"),
    ("San Luis Potosí", "San Luis Potosí"),
    ("Sinaloa", "Sinaloa"),
    ("Sonora", "Sonora"),
    ("Tabasco", "Tabasco"),
    ("Tamaulipas", "Tamaulipas"),
    ("Tlaxcala", "Tlaxcala"),
    ("Veracruz", "Veracruz"),
    ("Yucatán", "Yucatán"),
    ("Zacatecas", "Zacatecas"),
]

MUNICIPIO_SELECT_CHOICES = [
    ("", "Seleccione municipio..."),
]


class SedeForm(forms.ModelForm):
    correo = CorreoInstitucionalField(
        required=False,
        widget=forms.EmailInput(attrs={
            "placeholder": "correo@unach.mx",
            "autocomplete": "email",
        })
    )

    """
    Formulario de sede con dirección estructurada.

    La dirección completa no se escribe manualmente.
    Se captura por partes y el modelo Sede la arma automáticamente
    en el campo direccion para conservar compatibilidad con reportes.
    """

    class Meta:
        model = Sede
        fields = [
            "clave",
            "nombre",
            "estado",
            "municipio",
            "ciudad_localidad",
            "colonia",
            "codigo_postal",
            "tipo_vialidad",
            "calle_avenida",
            "referencia",
            "telefono",
            "correo",
            "activa",
        ]
        widgets = {
            "clave": forms.TextInput(attrs={
                "placeholder": "Ej. TUXTLA",
                "autocomplete": "off",
                "maxlength": "30",
            }),
            "nombre": forms.TextInput(attrs={
                "placeholder": "Ej. Estancia Infantil Universitaria Tuxtla",
                "autocomplete": "organization",
            }),
            "estado": forms.Select(choices=ESTADO_SEDE_CHOICES),
            "municipio": forms.Select(choices=MUNICIPIO_SELECT_CHOICES, attrs={
                "data-initial": "",
            }),
            "ciudad_localidad": forms.TextInput(attrs={
                "placeholder": "Ej. Tuxtla Gutiérrez",
                "autocomplete": "address-level2",
            }),
            "colonia": forms.TextInput(attrs={
                "placeholder": "Ej. Centro",
                "autocomplete": "address-level3",
            }),
            "codigo_postal": forms.TextInput(attrs={
                "placeholder": "Ej. 29000",
                "inputmode": "numeric",
                "maxlength": "5",
                "autocomplete": "postal-code",
            }),
            "tipo_vialidad": forms.Select(),
            "calle_avenida": forms.TextInput(attrs={
                "placeholder": "Ej. Avenida Central",
                "autocomplete": "address-line1",
            }),
            "referencia": forms.TextInput(attrs={
                "placeholder": "Ej. Frente a, junto a, entre calles...",
                "maxlength": "255",
            }),
            "telefono": forms.TextInput(attrs={
                "placeholder": "10 dígitos",
                "inputmode": "numeric",
                "maxlength": "10",
                "autocomplete": "tel",
            }),
            "correo": forms.EmailInput(attrs={
                "placeholder": "correo@unach.mx",
                "autocomplete": "email",
            }),
        }
        labels = {
            "clave": "Clave de sede",
            "nombre": "Nombre de la sede",
            "estado": "Estado",
            "municipio": "Municipio",
            "ciudad_localidad": "Ciudad / Localidad",
            "colonia": "Colonia",
            "codigo_postal": "Código postal",
            "tipo_vialidad": "Tipo de vialidad",
            "calle_avenida": "Calle / Avenida",
            "referencia": "Referencia",
            "telefono": "Teléfono de sede",
            "correo": "Correo de sede",
            "activa": "Sede activa",
        }
        help_texts = {
            "clave": "Usa una clave corta, por ejemplo TUXTLA o TAPACHULA.",
            "telefono": "Solo 10 dígitos, sin espacios, letras ni guiones.",
            "codigo_postal": "Debe tener exactamente 5 dígitos.",
            "referencia": "Dato opcional para ubicar mejor la sede.",
            "municipio": "Selecciona el municipio según el estado elegido.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        municipio_actual = ""
        if self.instance and getattr(self.instance, "pk", None):
            municipio_actual = getattr(self.instance, "municipio", "") or ""

        if self.data:
            municipio_actual = self.data.get(self.add_prefix("municipio"), municipio_actual)

        self.fields["estado"].initial = self.initial.get("estado") or getattr(self.instance, "estado", "") or "Chiapas"
        self.fields["estado"].required = True
        self.fields["municipio"].required = True
        self.fields["municipio"].widget.attrs["data-initial"] = municipio_actual
        self.fields["ciudad_localidad"].required = True
        self.fields["colonia"].required = True
        self.fields["codigo_postal"].required = True
        self.fields["tipo_vialidad"].required = True
        self.fields["calle_avenida"].required = True
        self.fields["telefono"].required = True

        aplicar_clases_bootstrap(self)

    def clean_clave(self):
        clave = (self.cleaned_data.get("clave") or "").strip().upper()
        clave = re.sub(r"[^A-Z0-9_-]+", "_", clave)

        if not clave:
            raise forms.ValidationError("Captura la clave de la sede.")

        sedes = Sede.objects.filter(clave__iexact=clave)

        if self.instance and self.instance.pk:
            sedes = sedes.exclude(pk=self.instance.pk)

        if sedes.exists():
            raise forms.ValidationError(
                "Ya existe una sede con esta clave. Usa otra clave o edita la sede existente."
            )

        return clave

    def clean_nombre(self):
        nombre = (self.cleaned_data.get("nombre") or "").strip()

        if not nombre:
            raise forms.ValidationError("Captura el nombre de la sede.")

        sedes = Sede.objects.filter(nombre__iexact=nombre)

        if self.instance and self.instance.pk:
            sedes = sedes.exclude(pk=self.instance.pk)

        if sedes.exists():
            raise forms.ValidationError(
                "Ya existe una sede con este nombre. Revisa si debes editar la sede existente."
            )

        return nombre

    def clean_estado(self):
        estado = (self.cleaned_data.get("estado") or "").strip()

        if not estado:
            raise forms.ValidationError("Selecciona el estado.")

        return estado

    def clean_municipio(self):
        municipio = (self.cleaned_data.get("municipio") or "").strip()

        if not municipio:
            raise forms.ValidationError("Selecciona el municipio.")

        return municipio

    def clean_ciudad_localidad(self):
        ciudad = (self.cleaned_data.get("ciudad_localidad") or "").strip()

        if not ciudad:
            raise forms.ValidationError("Captura la ciudad o localidad.")

        if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9\s.\-]+", ciudad):
            raise forms.ValidationError("La ciudad/localidad contiene caracteres no válidos.")

        return ciudad.title()

    def clean_colonia(self):
        colonia = (self.cleaned_data.get("colonia") or "").strip()

        if not colonia:
            raise forms.ValidationError("Captura la colonia.")

        return colonia.title()

    def clean_codigo_postal(self):
        cp = (self.cleaned_data.get("codigo_postal") or "").strip()

        if not re.fullmatch(r"\d{5}", cp):
            raise forms.ValidationError("El código postal debe tener exactamente 5 dígitos.")

        return cp

    def clean_calle_avenida(self):
        calle = (self.cleaned_data.get("calle_avenida") or "").strip()

        if not calle:
            raise forms.ValidationError("Captura la calle o avenida.")

        return calle.title()

    def clean_telefono(self):
        telefono = (self.cleaned_data.get("telefono") or "").strip()

        if not re.fullmatch(r"\d{10}", telefono):
            raise forms.ValidationError("El teléfono debe tener exactamente 10 dígitos y solo números.")

        return telefono

    def clean_correo(self):
        correo = limpiar_correo(self.cleaned_data.get("correo"))

        if correo and "@" not in correo:
            raise forms.ValidationError("Captura un correo válido para la sede.")

        if correo and not correo.endswith("@unach.mx"):
            raise forms.ValidationError("El correo de sede debe ser institucional y terminar en @unach.mx.")

        return correo

class SemestreForm(forms.ModelForm):
    correo_copia_encuesta = CorreoInstitucionalField(
        required=False,
        widget=forms.EmailInput(attrs={"placeholder": "correo.generico@unach.mx"})
    )

    """
    Formulario principal de semestre.
    Permite crear/modificar el semestre, la sede y el personal institucional asignado.
    """
    class Meta:
        model = Semestre
        fields = [
            "nombre",
            "sede_configurada",
            "sede",
            "fecha_inicio",
            "fecha_fin",
            "medico_asignado",
            "nutriologa_asignada",
            "psicologa_asignada",
            "fecha_encuesta_satisfaccion",
            "correo_copia_encuesta",
            "observaciones",
        ]
        widgets = {
            "nombre": forms.TextInput(attrs={"placeholder": "Ej. Enero - Junio 2026"}),
            "sede_configurada": forms.Select(),
            "sede": forms.Select(),
            "fecha_inicio": forms.DateInput(attrs={"type": "date"}),
            "fecha_fin": forms.DateInput(attrs={"type": "date"}),
            "fecha_encuesta_satisfaccion": forms.DateInput(attrs={"type": "date"}),
            "correo_copia_encuesta": forms.EmailInput(attrs={"placeholder": "correo.generico@unach.mx"}),
            "observaciones": forms.Textarea(attrs={"rows": 3, "placeholder": "Observaciones internas del semestre"}),
        }
        labels = {
            "sede_configurada": "Sede",
            "sede": "Sede anterior / compatibilidad",
            "fecha_encuesta_satisfaccion": "Fecha de generación de Encuesta de satisfacción B",
            "correo_copia_encuesta": "Correo genérico para copia de encuesta",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["sede_configurada"].queryset = Sede.objects.filter(activa=True).order_by("nombre")
        self.fields["sede_configurada"].required = True
        self.fields["sede"].required = False

        self.fields["medico_asignado"].queryset = usuarios_por_rol("medic", "médic")
        self.fields["nutriologa_asignada"].queryset = usuarios_por_rol("nutri", "nutriolog")
        self.fields["psicologa_asignada"].queryset = usuarios_por_rol("psicolog", "psicóloga", "psicologo")

        self.fields["medico_asignado"].required = True
        self.fields["nutriologa_asignada"].required = True
        self.fields["psicologa_asignada"].required = True

        aplicar_clases_bootstrap(self)

    def clean_correo_copia_encuesta(self):
        correo = limpiar_correo(self.cleaned_data.get("correo_copia_encuesta"))

        if correo and not correo.endswith("@unach.mx"):
            raise forms.ValidationError("El correo genérico de encuesta debe terminar en @unach.mx.")

        return correo

    def clean(self):
        cleaned = super().clean()
        fecha_inicio = cleaned.get("fecha_inicio")
        fecha_fin = cleaned.get("fecha_fin")
        fecha_encuesta = cleaned.get("fecha_encuesta_satisfaccion")

        if fecha_inicio and fecha_fin and fecha_inicio > fecha_fin:
            self.add_error("fecha_inicio", "La fecha de inicio no puede ser posterior a la fecha fin.")

        if fecha_encuesta and fecha_inicio and fecha_fin:
            if fecha_encuesta < fecha_inicio or fecha_encuesta > fecha_fin:
                self.add_error(
                    "fecha_encuesta_satisfaccion",
                    "La fecha de encuesta debe estar dentro del periodo del semestre."
                )

        nombre = (cleaned.get("nombre") or "").strip()
        sede_configurada = cleaned.get("sede_configurada")

        if nombre and sede_configurada:
            duplicados = Semestre.objects.filter(
                nombre__iexact=nombre,
                sede_configurada=sede_configurada,
            )

            if self.instance and self.instance.pk:
                duplicados = duplicados.exclude(pk=self.instance.pk)

            if duplicados.exists():
                self.add_error(
                    "nombre",
                    "Ya existe un semestre con ese nombre para la sede seleccionada."
                )

        return cleaned


class ClonarSemestreForm(forms.Form):
    """
    Formulario para crear un nuevo semestre usando como base un semestre cerrado.

    Solo captura los datos que sí deben cambiar:
    nombre del nuevo semestre, fechas, fecha de encuesta, correo de copia
    y observaciones. La configuración operativa se copia desde el semestre origen.
    """
    nombre = forms.CharField(
        max_length=100,
        required=True,
        label="Nombre del nuevo semestre",
        widget=forms.TextInput(attrs={
            "placeholder": "Ej. Agosto - Diciembre 2026",
            "autocomplete": "off",
        })
    )
    fecha_inicio = forms.DateField(
        required=True,
        label="Fecha de inicio",
        widget=forms.DateInput(attrs={"type": "date"})
    )
    fecha_fin = forms.DateField(
        required=True,
        label="Fecha de fin",
        widget=forms.DateInput(attrs={"type": "date"})
    )
    fecha_encuesta_satisfaccion = forms.DateField(
        required=False,
        label="Fecha de Encuesta B",
        widget=forms.DateInput(attrs={"type": "date"})
    )
    correo_copia_encuesta = CorreoInstitucionalField(
        required=False,
        label="Correo genérico para copia de encuesta",
        widget=forms.EmailInput(attrs={"placeholder": "correo.generico@unach.mx"})
    )
    observaciones = forms.CharField(
        required=False,
        label="Observaciones",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Opcional. Ej. Semestre clonado para nuevo periodo."
        })
    )
    confirmar = forms.BooleanField(
        required=True,
        label="Confirmo que deseo clonar la configuración del semestre cerrado"
    )

    def __init__(self, *args, **kwargs):
        self.semestre_origen = kwargs.pop("semestre_origen", None)
        super().__init__(*args, **kwargs)

        if self.semestre_origen:
            self.fields["correo_copia_encuesta"].initial = getattr(
                self.semestre_origen,
                "correo_copia_encuesta",
                ""
            )
            self.fields["observaciones"].initial = f"Clonado desde {self.semestre_origen.nombre}."

        aplicar_clases_bootstrap(self)

    def clean_correo_copia_encuesta(self):
        correo = limpiar_correo(self.cleaned_data.get("correo_copia_encuesta"))

        if correo and not correo.endswith("@unach.mx"):
            raise forms.ValidationError("El correo genérico de encuesta debe terminar en @unach.mx.")

        return correo

    def clean(self):
        cleaned = super().clean()
        origen = self.semestre_origen

        if not origen:
            raise forms.ValidationError("No se encontró el semestre origen para clonar.")

        if origen.estado != Semestre.EstadoSemestre.CERRADO:
            raise forms.ValidationError("Solo se puede clonar un semestre cerrado.")

        if Semestre.objects.filter(estado=Semestre.EstadoSemestre.ACTIVO).exists():
            raise forms.ValidationError(
                "No se puede clonar mientras exista un semestre activo. Primero cierra el semestre activo."
            )

        fecha_inicio = cleaned.get("fecha_inicio")
        fecha_fin = cleaned.get("fecha_fin")
        fecha_encuesta = cleaned.get("fecha_encuesta_satisfaccion")

        if fecha_inicio and fecha_fin and fecha_inicio > fecha_fin:
            self.add_error("fecha_inicio", "La fecha de inicio no puede ser posterior a la fecha fin.")

        if fecha_encuesta and fecha_inicio and fecha_fin:
            if fecha_encuesta < fecha_inicio or fecha_encuesta > fecha_fin:
                self.add_error(
                    "fecha_encuesta_satisfaccion",
                    "La fecha de Encuesta B debe estar dentro del periodo del semestre."
                )

        nombre = (cleaned.get("nombre") or "").strip()

        if nombre:
            duplicados = Semestre.objects.filter(
                nombre__iexact=nombre,
                sede_configurada=origen.sede_configurada,
            )
            if duplicados.exists():
                self.add_error(
                    "nombre",
                    "Ya existe un semestre con ese nombre para la misma sede."
                )

        return cleaned

    def crear_semestre_clonado(self, usuario=None):
        """
        Ejecuta la clonación usando el método del modelo Semestre.
        Debe llamarse después de form.is_valid().
        """
        if not self.is_valid():
            raise ValueError("El formulario de clonación no es válido.")

        nuevo = self.semestre_origen.clonar_configuracion(
            nombre=self.cleaned_data["nombre"],
            fecha_inicio=self.cleaned_data["fecha_inicio"],
            fecha_fin=self.cleaned_data["fecha_fin"],
            fecha_encuesta_satisfaccion=self.cleaned_data.get("fecha_encuesta_satisfaccion"),
            usuario=usuario,
            observaciones=self.cleaned_data.get("observaciones") or "",
        )

        nuevo.correo_copia_encuesta = limpiar_correo(self.cleaned_data.get("correo_copia_encuesta"))
        nuevo.save(update_fields=["correo_copia_encuesta", "updated_at"])

        return nuevo


class DiaFestivoForm(forms.ModelForm):
    class Meta:
        model = DiaFestivo
        fields = [
            "fecha",
            "tipo",
            "motivo",
            "afecta_recepcion",
        ]
        widgets = {
            "fecha": forms.DateInput(attrs={"type": "date"}),
            "tipo": forms.Select(),
            "motivo": forms.TextInput(attrs={"placeholder": "Ej. Día festivo, suspensión, consejo técnico"}),
        }

    def __init__(self, *args, **kwargs):
        self.semestre = kwargs.pop("semestre", None)
        super().__init__(*args, **kwargs)

        # La opción "Otro" se retira para evitar confusión.
        # Los tipos permitidos deben ser claros: festivo, suspensión o consejo técnico.
        if "tipo" in self.fields:
            self.fields["tipo"].choices = [
                (value, label)
                for value, label in self.fields["tipo"].choices
                if str(value).upper() != "OTRO"
            ]

        aplicar_clases_bootstrap(self)

    def clean_fecha(self):
        fecha = self.cleaned_data.get("fecha")

        if self.semestre and fecha:
            if fecha < self.semestre.fecha_inicio or fecha > self.semestre.fecha_fin:
                raise forms.ValidationError("La fecha debe estar dentro del periodo del semestre.")

        if fecha_es_fin_de_semana(fecha):
            raise forms.ValidationError(
                "No es necesario registrar sábados o domingos. "
                "El sistema los marca automáticamente como días inhábiles."
            )

        return fecha

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.semestre:
            obj.semestre = self.semestre
        if commit:
            obj.save()

            # Si el calendario ya estaba generado, se recalcula para reflejar
            # el nuevo día inhábil sin duplicar días.
            try:
                obj.semestre.generar_dias_operativos()
            except Exception:
                pass

        return obj


class SalaForm(forms.ModelForm):
    class Meta:
        model = Sala
        fields = [
            "sede",
            "nombre",
            "tipo_sala",
            "capacidad_maxima",
            "descripcion",
            "activa",
        ]
        widgets = {
            "sede": forms.Select(),
            "nombre": forms.TextInput(attrs={"placeholder": "Ej. Lactantes 1, Maternal 2"}),
            "tipo_sala": forms.Select(),
            "capacidad_maxima": forms.NumberInput(attrs={"min": 1}),
            "descripcion": forms.Textarea(attrs={"rows": 3, "placeholder": "Descripción opcional de la sala"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "sede" in self.fields:
            self.fields["sede"].queryset = Sede.objects.filter(activa=True).order_by("nombre")
            self.fields["sede"].required = True
            self.fields["sede"].empty_label = "Seleccione una sede..."

        aplicar_clases_bootstrap(self)

    def clean_nombre(self):
        nombre = (self.cleaned_data.get("nombre") or "").strip()
        if not nombre:
            raise forms.ValidationError("Captura el nombre de la sala.")
        return nombre.upper()

    def clean(self):
        cleaned = super().clean()
        sede = cleaned.get("sede")
        nombre = cleaned.get("nombre")

        if nombre:
            duplicadas = Sala.objects.filter(nombre__iexact=nombre)

            if sede:
                duplicadas = duplicadas.filter(sede=sede)
            else:
                duplicadas = duplicadas.filter(sede__isnull=True)

            if self.instance and self.instance.pk:
                duplicadas = duplicadas.exclude(pk=self.instance.pk)

            if duplicadas.exists():
                self.add_error(
                    "nombre",
                    "Ya existe una sala con ese nombre para la sede seleccionada."
                )

        return cleaned


class SalaSemestreForm(forms.ModelForm):
    """
    Configuración completa de sala por semestre:
    cupo, horarios de recepción, alimentos, actividades, recreo, siesta y salida.
    """
    class Meta:
        model = SalaSemestre
        fields = [
            "sala",
            "activa",
            "cupo",
            "entrada_maestras",
            "recepcion_inicio",
            "recepcion_fin",
            "desayuno_inicio",
            "desayuno_fin",
            "actividad_pedagogica_nombre",
            "actividad_pedagogica_inicio",
            "actividad_pedagogica_fin",
            "recreo_inicio",
            "recreo_fin",
            "colacion_inicio",
            "colacion_fin",
            "siesta_inicio",
            "siesta_fin",
            "comida_inicio",
            "comida_fin",
            "salida_maestras",
        ]
        widgets = {
            "sala": forms.Select(),
            "cupo": forms.NumberInput(attrs={"min": 1, "placeholder": "Cupo del semestre"}),
            "entrada_maestras": forms.TimeInput(attrs={"type": "time"}),
            "recepcion_inicio": forms.TimeInput(attrs={"type": "time"}),
            "recepcion_fin": forms.TimeInput(attrs={"type": "time"}),
            "desayuno_inicio": forms.TimeInput(attrs={"type": "time"}),
            "desayuno_fin": forms.TimeInput(attrs={"type": "time"}),
            "actividad_pedagogica_nombre": forms.TextInput(attrs={"placeholder": "Nombre de actividad"}),
            "actividad_pedagogica_inicio": forms.TimeInput(attrs={"type": "time"}),
            "actividad_pedagogica_fin": forms.TimeInput(attrs={"type": "time"}),
            "recreo_inicio": forms.TimeInput(attrs={"type": "time"}),
            "recreo_fin": forms.TimeInput(attrs={"type": "time"}),
            "colacion_inicio": forms.TimeInput(attrs={"type": "time"}),
            "colacion_fin": forms.TimeInput(attrs={"type": "time"}),
            "siesta_inicio": forms.TimeInput(attrs={"type": "time"}),
            "siesta_fin": forms.TimeInput(attrs={"type": "time"}),
            "comida_inicio": forms.TimeInput(attrs={"type": "time"}),
            "comida_fin": forms.TimeInput(attrs={"type": "time"}),
            "salida_maestras": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        self.semestre = kwargs.pop("semestre", None)
        super().__init__(*args, **kwargs)

        salas = Sala.objects.filter(activa=True).order_by("nombre")

        if self.semestre and getattr(self.semestre, "sede_configurada_id", None):
            # Se muestran las salas propias de la sede y las salas generales sin sede.
            salas = salas.filter(
                Q(sede=self.semestre.sede_configurada) | Q(sede__isnull=True)
            )

        self.fields["sala"].queryset = salas
        self.fields["sala"].required = True

        aplicar_clases_bootstrap(self)

    def clean(self):
        cleaned = super().clean()

        pares_horario = [
            ("recepcion_inicio", "recepcion_fin", "recepción de niños"),
            ("desayuno_inicio", "desayuno_fin", "desayuno"),
            ("actividad_pedagogica_inicio", "actividad_pedagogica_fin", "actividad pedagógica"),
            ("recreo_inicio", "recreo_fin", "recreo"),
            ("colacion_inicio", "colacion_fin", "colación"),
            ("siesta_inicio", "siesta_fin", "siesta"),
            ("comida_inicio", "comida_fin", "comida"),
        ]

        for inicio, fin, etiqueta in pares_horario:
            hi = cleaned.get(inicio)
            hf = cleaned.get(fin)

            if hi and hf and hi >= hf:
                self.add_error(fin, f"El horario fin de {etiqueta} debe ser posterior al inicio.")

        actividad = (cleaned.get("actividad_pedagogica_nombre") or "").strip()
        actividad_inicio = cleaned.get("actividad_pedagogica_inicio")
        actividad_fin = cleaned.get("actividad_pedagogica_fin")

        if actividad and (not actividad_inicio or not actividad_fin):
            self.add_error("actividad_pedagogica_inicio", "Captura horario de inicio y fin de la actividad pedagógica.")

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.semestre:
            obj.semestre = self.semestre
        if commit:
            obj.save()
        return obj


class AsignacionMaestraForm(forms.ModelForm):
    class Meta:
        model = AsignacionMaestra
        fields = [
            "maestra",
            "rol",
            "activo",
            "horario_entrada",
            "horario_salida",
            "desayuno_inicio",
            "desayuno_fin",
            "tiempo_fuera_inicio",
            "tiempo_fuera_fin",
        ]
        widgets = {
            "maestra": forms.Select(),
            "rol": forms.Select(),
            "horario_entrada": forms.TimeInput(attrs={"type": "time"}),
            "horario_salida": forms.TimeInput(attrs={"type": "time"}),
            "desayuno_inicio": forms.TimeInput(attrs={"type": "time"}),
            "desayuno_fin": forms.TimeInput(attrs={"type": "time"}),
            "tiempo_fuera_inicio": forms.TimeInput(attrs={"type": "time"}),
            "tiempo_fuera_fin": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        self.sala_semestre = kwargs.pop("sala_semestre", None)
        super().__init__(*args, **kwargs)

        self.fields["maestra"].queryset = usuarios_por_rol("maestra", "maestro", "asistente")
        self.fields["maestra"].required = True

        aplicar_clases_bootstrap(self)

    def clean(self):
        cleaned = super().clean()

        pares = [
            ("horario_entrada", "horario_salida", "jornada de la maestra"),
            ("desayuno_inicio", "desayuno_fin", "desayuno de la maestra"),
            ("tiempo_fuera_inicio", "tiempo_fuera_fin", "tiempo fuera"),
        ]

        for inicio, fin, etiqueta in pares:
            hi = cleaned.get(inicio)
            hf = cleaned.get(fin)

            if hi and hf and hi >= hf:
                self.add_error(fin, f"El horario fin de {etiqueta} debe ser posterior al inicio.")

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.sala_semestre:
            obj.sala_semestre = self.sala_semestre
        if commit:
            obj.save()
        return obj


class AsignarAlumnoSalaForm(forms.ModelForm):
    """
    Asigna un alumno finalizado a un semestre y sala del semestre.
    """
    class Meta:
        model = SolicitudInscripcion
        fields = [
            "semestre",
            "sala_semestre_asignada",
            "sala_bloqueada",
        ]
        widgets = {
            "semestre": forms.Select(),
            "sala_semestre_asignada": forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        semestre = kwargs.pop("semestre", None)
        super().__init__(*args, **kwargs)

        self.fields["semestre"].queryset = Semestre.objects.exclude(
            estado=Semestre.EstadoSemestre.CERRADO
        ).order_by("-fecha_inicio")

        salas = SalaSemestre.objects.filter(activa=True).select_related("sala", "semestre")

        if semestre:
            salas = salas.filter(semestre=semestre)
            self.fields["semestre"].initial = semestre

        self.fields["sala_semestre_asignada"].queryset = salas.order_by("sala__nombre")

        aplicar_clases_bootstrap(self)

    def clean(self):
        cleaned = super().clean()
        semestre = cleaned.get("semestre")
        sala_semestre = cleaned.get("sala_semestre_asignada")

        if sala_semestre and semestre and sala_semestre.semestre_id != semestre.id:
            self.add_error("sala_semestre_asignada", "La sala seleccionada no pertenece al semestre.")

        if sala_semestre:
            cupo = sala_semestre.cupo_real
            inscritos = sala_semestre.alumnos_asignados_semestre.count()

            if self.instance and self.instance.pk and self.instance.sala_semestre_asignada_id == sala_semestre.id:
                inscritos = max(0, inscritos - 1)

            if cupo and inscritos >= cupo:
                self.add_error("sala_semestre_asignada", "La sala seleccionada ya alcanzó su cupo.")

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)

        if obj.sala_semestre_asignada:
            obj.sala_asignada = obj.sala_semestre_asignada.sala
            obj.semestre = obj.sala_semestre_asignada.semestre

        if commit:
            obj.save()

        return obj


class DiaOperativoSemestreForm(forms.ModelForm):
    class Meta:
        model = DiaOperativoSemestre
        fields = [
            "fecha",
            "es_habil",
            "estado",
            "observaciones",
        ]
        widgets = {
            "fecha": forms.DateInput(attrs={"type": "date"}),
            "estado": forms.Select(),
            "observaciones": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)

    def clean(self):
        cleaned = super().clean()
        fecha = cleaned.get("fecha")
        es_habil = cleaned.get("es_habil")
        estado = cleaned.get("estado")

        if fecha_es_fin_de_semana(fecha):
            if es_habil:
                self.add_error(
                    "es_habil",
                    "Sábado y domingo son inhábiles automáticos; no pueden marcarse como hábiles."
                )

            if estado == DiaOperativoSemestre.EstadoDia.ABIERTO:
                self.add_error(
                    "estado",
                    "No se puede abrir operación diaria en sábado o domingo."
                )

        return cleaned


class CerrarDiaOperativoForm(forms.ModelForm):
    class Meta:
        model = DiaOperativoSemestre
        fields = [
            "observaciones",
        ]
        widgets = {
            "observaciones": forms.Textarea(attrs={"rows": 3, "placeholder": "Observaciones del cierre del día"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)


# =========================================================
# SPRINT 5 - ÉPICA 3: FORMULARIOS DE INCIDENCIAS
# Pedagógica, Nutricional, Médica y Psicológica
# =========================================================

INCIDENCIA_CATEGORIAS = {
    "PEDAGOGICA": [
        ("NO_TRAJO_MATERIAL", "No trajo material"),
        ("SIN_CAJA_EMERGENCIA", "No cuenta con artículos de caja de emergencia"),
        ("DIFICULTAD_ACTIVIDAD", "Presenta dificultades en la realización de actividades"),
        ("CONDUCTA_EN_ACTIVIDAD", "Conducta observada durante actividad pedagógica"),
        ("OTRO", "Otro"),
    ],
    "NUTRICIONAL": [
        ("REACCION_ALERGICA", "Reacción alérgica"),
        ("INTOLERANCIA", "Intolerancia a alimento"),
        ("ATRAGANTAMIENTO", "Atragantamiento"),
        ("RECHAZO_ALIMENTO", "Rechazo de alimento"),
        ("RESTRICCION_ALIMENTARIA", "Restricción alimentaria"),
        ("OTRO", "Otro"),
    ],
    "MEDICA": [
        ("SINTOMAS_GRIPE", "Síntomas de gripe"),
        ("DIARREA", "Diarrea"),
        ("GOLPE_CAIDA", "Golpe o caída"),
        ("ATRAGANTAMIENTO", "Atragantamiento"),
        ("ATAQUE_ESTADO_GENERAL", "Ataque al estado general"),
        ("FIEBRE", "Fiebre"),
        ("VOMITO", "Vómito"),
        ("OTRO", "Otro"),
    ],
    "PSICOLOGICA": [
        ("ADAPTATIVA", "Adaptativa"),
        ("SOCIOEMOCIONAL", "Socioemocional"),
        ("COGNITIVA", "Cognitiva"),
        ("CONDUCTUAL", "Conductual"),
        ("OTRO", "Otro"),
    ],
}

SINTOMAS_MEDICOS_CHOICES = [
    ("RINORREA", "Rinorrea"),
    ("TOS", "Tos"),
    ("ESTORNUDOS", "Estornudos"),
    ("FIEBRE", "Fiebre"),
    ("VOMITO", "Vómito"),
    ("GINGIVORRAGIA", "Gingivorragia"),
    ("HEMATOMA", "Hematoma"),
    ("PERDIDA_CONOCIMIENTO", "Pérdida de conocimiento"),
    ("CONVULSION", "Convulsión"),
    ("FRACTURA", "Fractura"),
    ("OBSTRUCCION_LEVE", "Obstrucción leve"),
    ("OBSTRUCCION_TOTAL", "Obstrucción total"),
    ("ASTENIA", "Astenia"),
    ("DOLOR_MUSCULAR", "Dolor muscular"),
    ("CEFALEA", "Cefalea"),
    ("PERDIDA_APETITO", "Pérdida de apetito"),
    ("OTRO", "Otro"),
]

CONSISTENCIA_EVACUACION_CHOICES = [
    ("", "Seleccione..."),
    ("SOLIDA", "Sólida"),
    ("PASTOSA", "Pastosa"),
    ("LIQUIDA", "Líquida"),
    ("MUCOSA", "Con moco"),
    ("SANGRE", "Con sangre"),
]

INCIDENCIA_MEDIO_AVISO_CHOICES = [
    ("NO_APLICA", "No aplica"),
    ("PRESENCIAL", "Presencial"),
    ("TELEFONO", "Teléfono"),
    ("MENSAJE", "Mensaje"),
    ("CORREO", "Correo"),
    ("OTRO", "Otro"),
]


# =========================================================
# CAMPOS ESPECIALES PARA QUE EL SELECT MUESTRE NOMBRES REALES
# =========================================================

def _texto_campo_o_metodo(objeto, *nombres):
    """
    Lee un atributo o método y siempre devuelve texto limpio.
    Corrige el caso donde Django imprimía:
    <Bound Method Solicitud.Nombre_Menor_Completo Of ...>
    porque el método del modelo se estaba mostrando sin ejecutarlo.
    """
    if not objeto:
        return ""

    for nombre in nombres:
        valor = getattr(objeto, nombre, None)

        if callable(valor):
            try:
                valor = valor()
            except TypeError:
                valor = ""
            except Exception:
                valor = ""

        valor = str(valor or "").strip()

        if valor and "bound method" not in valor.lower():
            return valor

    return ""


def _nombre_menor_desde_inscripcion(inscripcion):
    """
    Obtiene el nombre real del menor desde SolicitudInscripcion.solicitud_ingreso.
    Evita que el select muestre textos técnicos como:
    "Expediente de Inscripción..." o "<Bound Method ...>".
    """
    nombre = _texto_campo_o_metodo(
        inscripcion,
        "nombre_menor_completo",
        "nombre_completo_menor",
        "menor_nombre_completo",
    )

    if nombre:
        return nombre.title()

    solicitud = getattr(inscripcion, "solicitud_ingreso", None)

    nombre = _texto_campo_o_metodo(
        solicitud,
        "nombre_menor_completo",
        "Nombre_Menor_Completo",
        "nombre_completo_menor",
        "menor_nombre_completo",
    )

    if nombre:
        return nombre.title()

    if solicitud:
        partes = [
            getattr(solicitud, "nombres_menor", "") or "",
            getattr(solicitud, "apellido_paterno_menor", "") or "",
            getattr(solicitud, "apellido_materno_menor", "") or "",
        ]
        nombre = " ".join(str(p).strip() for p in partes if p and str(p).strip()).strip()
        if nombre:
            return nombre.title()

        folio = getattr(solicitud, "folio", "") or getattr(solicitud, "id", "") or ""
        return f"Alumno sin nombre - Solicitud {folio}".strip()

    return f"Alumno sin nombre #{getattr(inscripcion, 'pk', '')}".strip()


class AlumnoInscritoChoiceField(forms.ModelChoiceField):
    """Muestra el nombre del niño/a en el select de incidencias."""

    def label_from_instance(self, obj):
        return _nombre_menor_desde_inscripcion(obj)


class RegistroDiarioIncidenciaChoiceField(forms.ModelChoiceField):
    """Muestra solo fecha/estado del registro diario, sin dejar fijo el nombre de un menor."""

    def label_from_instance(self, obj):
        dia = getattr(obj, "dia_operativo", None)
        fecha = getattr(dia, "fecha", None)

        if fecha:
            try:
                fecha_txt = fecha.strftime("%d/%m/%Y")
            except Exception:
                fecha_txt = str(fecha)
        else:
            fecha_txt = "Sin fecha"

        try:
            estado_txt = obj.get_estado_display()
        except Exception:
            estado_txt = getattr(obj, "estado", "") or "Registro diario"

        sala_semestre = getattr(obj, "sala_semestre", None)
        sala = getattr(sala_semestre, "sala", None)
        sala_txt = getattr(sala, "nombre", "") or ""

        if sala_txt:
            return f"{fecha_txt} — {sala_txt} — {estado_txt}"
        return f"{fecha_txt} — {estado_txt}"


def validar_lista_archivos(archivos, extensiones_permitidas=None, limite_mb_archivo=10, limite_mb_total=20):
    """
    Valida adjuntos para incidencias y seguimientos.
    - Evita archivos demasiado pesados.
    - Evita extensiones no permitidas.
    """
    archivos = archivos or []
    extensiones_permitidas = extensiones_permitidas or {"pdf", "jpg", "jpeg", "png", "doc", "docx"}

    if not isinstance(archivos, (list, tuple)):
        archivos = [archivos]

    total_bytes = 0
    for archivo in archivos:
        nombre = getattr(archivo, "name", "") or ""
        extension = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
        size = getattr(archivo, "size", 0) or 0
        total_bytes += size

        if extension not in extensiones_permitidas:
            raise forms.ValidationError(
                "Solo se permiten archivos PDF, JPG, JPEG, PNG, DOC o DOCX."
            )

        if size > limite_mb_archivo * 1024 * 1024:
            raise forms.ValidationError(
                f"El archivo {nombre} supera el límite de {limite_mb_archivo} MB."
            )

    if total_bytes > limite_mb_total * 1024 * 1024:
        raise forms.ValidationError(
            f"El total de archivos adjuntos no debe superar {limite_mb_total} MB."
        )

    return list(archivos)


class IncidenciaForm(forms.ModelForm):
    """
    Crea una incidencia del Sprint 5.

    Cambios aplicados:
    - El select de alumno muestra nombres reales del menor.
    - El registro diario se busca automáticamente según el alumno y la fecha actual.
    - Si el registro inicial pertenece a otro menor, se reemplaza por el registro del alumno seleccionado.
    - La opción OTRO obliga a escribir el detalle en subtipo.
    - Los adjuntos tienen límite de tamaño y tipo.
    """

    alumno = AlumnoInscritoChoiceField(
        queryset=SolicitudInscripcion.objects.none(),
        required=True,
        label="Nombre del niño/a",
        empty_label="Buscar niño/a inscrito...",
        widget=forms.Select(attrs={
            "class": "form-select select2-single",
            "data-placeholder": "Buscar niño/a inscrito...",
            "data-allow-clear": "true",
        })
    )

    registro_diario = RegistroDiarioIncidenciaChoiceField(
        queryset=RegistroDiarioAlumno.objects.none(),
        required=False,
        label="Día / registro diario",
        empty_label="Automático: usar el registro diario disponible del día actual",
        widget=forms.Select(attrs={
            "class": "form-select select2-single registro-diario-auto",
            "data-placeholder": "Automático según el alumno seleccionado",
        })
    )

    categoria = forms.ChoiceField(
        required=True,
        choices=[("", "Seleccione...")],
        label="Categoría de la incidencia"
    )

    archivos = MultipleFileField(
        required=False,
        label="Archivos adjuntos",
        widget=MultipleFileInput(attrs={
            "class": "form-control",
            "multiple": True,
            "accept": ".pdf,.jpg,.jpeg,.png,.doc,.docx",
            "data-max-file-mb": "10",
            "data-max-total-mb": "20",
        })
    )

    sintomas_medicos = forms.MultipleChoiceField(
        required=False,
        choices=SINTOMAS_MEDICOS_CHOICES,
        label="Síntomas / signos observados",
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input sintomas-medicos-check"})
    )

    sintomas_medicos_otro = forms.CharField(
        required=False,
        max_length=180,
        label="Especifica otro síntoma o signo",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Especifica el otro síntoma, signo o causa médica"
        })
    )

    consistencia_evacuacion = forms.ChoiceField(
        required=False,
        choices=CONSISTENCIA_EVACUACION_CHOICES,
        label="Consistencia de evacuación"
    )

    numero_evacuaciones = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=20,
        label="Número de evacuaciones"
    )

    alimento_relacionado = forms.CharField(
        required=False,
        max_length=180,
        label="Alimento relacionado",
        widget=forms.TextInput(attrs={
            "placeholder": "Ej. Leche, huevo, fruta, papilla, alimento específico"
        })
    )

    conducta_observada = forms.CharField(
        required=False,
        label="Conducta observada",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Describe la conducta observada en el menor."
        })
    )

    contexto_observacion = forms.CharField(
        required=False,
        label="Contexto de observación",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Ej. Durante actividad, comida, descanso, interacción con otros niños."
        })
    )

    extensiones_archivo_permitidas = {"pdf", "jpg", "jpeg", "png", "doc", "docx"}
    limite_mb_archivo = 10
    limite_mb_total = 20

    class Meta:
        model = Incidencia
        fields = [
            "alumno",
            "registro_diario",
            "tipo",
            "categoria",
            "subtipo",
            "nivel",
            "descripcion",
            "intervencion_personal",
            "responsable_informado",
            "medio_aviso_responsable",
            "responsable_informado_nombre",
        ]
        widgets = {
            "tipo": forms.Select(),
            "subtipo": forms.TextInput(attrs={
                "placeholder": "Si seleccionaste Otro, escribe aquí el detalle de la incidencia"
            }),
            "nivel": forms.Select(),
            "descripcion": forms.Textarea(attrs={
                "rows": 4,
                "placeholder": "Describe claramente qué ocurrió, cuándo y cómo se observó."
            }),
            "intervencion_personal": forms.Textarea(attrs={
                "rows": 4,
                "placeholder": "Describe qué hizo el personal ante la incidencia."
            }),
            "responsable_informado": forms.CheckboxInput(),
            "medio_aviso_responsable": forms.Select(choices=INCIDENCIA_MEDIO_AVISO_CHOICES),
            "responsable_informado_nombre": forms.TextInput(attrs={
                "placeholder": "Nombre del responsable informado"
            }),
        }
        labels = {
            "alumno": "Nombre del niño/a",
            "registro_diario": "Día / registro diario",
            "tipo": "Tipo de incidencia",
            "subtipo": "Subtipo / detalle",
            "nivel": "Nivel de riesgo",
            "descripcion": "Descripción de la incidencia",
            "intervencion_personal": "Intervención del personal",
            "responsable_informado": "¿Se informó al responsable?",
            "medio_aviso_responsable": "Medio de aviso",
            "responsable_informado_nombre": "Responsable informado",
        }

    def __init__(self, *args, **kwargs):
        self.semestre = kwargs.pop("semestre", None)
        self.usuario = kwargs.pop("usuario", None)
        self.tipo_forzado = kwargs.pop("tipo_forzado", None)
        self.registro_diario_inicial = kwargs.pop("registro_diario", None)
        self.autorizacion_suplencia = kwargs.pop("autorizacion_suplencia", None)

        if self.autorizacion_suplencia and not self.tipo_forzado:
            area_a_tipo = {
                AutorizacionSuplencia.AreaCubierta.MEDICA: Incidencia.TipoIncidencia.MEDICA,
                AutorizacionSuplencia.AreaCubierta.NUTRICION: Incidencia.TipoIncidencia.NUTRICIONAL,
                AutorizacionSuplencia.AreaCubierta.PSICOLOGIA: Incidencia.TipoIncidencia.PSICOLOGICA,
                AutorizacionSuplencia.AreaCubierta.PEDAGOGICA: Incidencia.TipoIncidencia.PEDAGOGICA,
            }
            self.tipo_forzado = area_a_tipo.get(self.autorizacion_suplencia.area_cubierta)

        super().__init__(*args, **kwargs)

        alumnos = (
            SolicitudInscripcion.objects
            .filter(estado="FINALIZADA")
            .select_related("solicitud_ingreso", "semestre", "sala_semestre_asignada", "sala_semestre_asignada__sala")
        )

        registros = (
            RegistroDiarioAlumno.objects
            .select_related(
                "alumno__solicitud_ingreso",
                "dia_operativo",
                "sala_semestre",
                "sala_semestre__sala",
            )
            .order_by("-dia_operativo__fecha", "alumno__solicitud_ingreso__apellido_paterno_menor")
        )

        if self.semestre:
            alumnos = alumnos.filter(semestre=self.semestre)
            registros = registros.filter(dia_operativo__semestre=self.semestre)

        try:
            registros = registros.filter(dia_operativo__es_habil=True).exclude(
                dia_operativo__fecha__week_day__in=[1, 7]
            )
        except Exception:
            pass

        self.fields["alumno"].queryset = alumnos.order_by(
            "solicitud_ingreso__apellido_paterno_menor",
            "solicitud_ingreso__apellido_materno_menor",
            "solicitud_ingreso__nombres_menor",
        )
        self.fields["alumno"].empty_label = "Buscar niño/a inscrito..."

        self.fields["registro_diario"].queryset = registros
        self.fields["registro_diario"].required = False
        self.fields["registro_diario"].empty_label = "Automático: usar registro diario disponible del día actual"

        if self.registro_diario_inicial:
            self.fields["registro_diario"].initial = self.registro_diario_inicial
            self.fields["alumno"].initial = self.registro_diario_inicial.alumno

        tipo_actual = self.tipo_forzado or self.data.get("tipo") or self.initial.get("tipo") or getattr(self.instance, "tipo", "")

        if self.tipo_forzado:
            self.fields["tipo"].initial = self.tipo_forzado
            self.fields["tipo"].disabled = True

        self.fields["categoria"].choices = [("", "Seleccione...")] + INCIDENCIA_CATEGORIAS.get(tipo_actual, [])

        aplicar_clases_bootstrap(self)

        # Se agregan estas clases después de aplicar Bootstrap para no perder Select2.
        self.fields["alumno"].widget.attrs["class"] = "form-select select2-single"
        self.fields["alumno"].widget.attrs["data-placeholder"] = "Buscar niño/a inscrito..."
        self.fields["alumno"].widget.attrs["data-allow-clear"] = "true"

        self.fields["registro_diario"].widget.attrs["class"] = "form-select select2-single registro-diario-auto"
        self.fields["registro_diario"].widget.attrs["data-placeholder"] = "Automático según el alumno seleccionado"

        self.fields["subtipo"].widget.attrs["data-otro-field"] = "true"
        self.fields["categoria"].widget.attrs["data-categoria-incidencia"] = "true"

    def _buscar_registro_diario_actual(self, alumno):
        """
        Busca el registro diario del alumno para la fecha actual del sistema.
        Si existe, se vincula automáticamente. Si no existe, la incidencia puede
        guardarse solo con alumno, semestre y sala.
        """
        if not alumno:
            return None

        try:
            hoy = timezone.localdate()
            qs = RegistroDiarioAlumno.objects.select_related(
                "alumno",
                "dia_operativo",
                "sala_semestre",
                "sala_semestre__sala",
            ).filter(
                alumno=alumno,
                dia_operativo__fecha=hoy,
                dia_operativo__es_habil=True,
            )

            if self.semestre:
                qs = qs.filter(dia_operativo__semestre=self.semestre)

            return qs.order_by("-id").first()
        except Exception:
            return None

    def clean_categoria(self):
        categoria = (self.cleaned_data.get("categoria") or "").strip()
        tipo = self.tipo_forzado or self.cleaned_data.get("tipo")

        opciones_validas = [value for value, _ in INCIDENCIA_CATEGORIAS.get(tipo, [])]

        if not categoria:
            raise forms.ValidationError("Selecciona la categoría de la incidencia.")

        if opciones_validas and categoria not in opciones_validas:
            raise forms.ValidationError("La categoría seleccionada no corresponde al tipo de incidencia.")

        return categoria

    def clean_descripcion(self):
        descripcion = (self.cleaned_data.get("descripcion") or "").strip()

        if len(descripcion) < 10:
            raise forms.ValidationError("Describe la incidencia con mayor detalle.")

        return descripcion

    def clean_intervencion_personal(self):
        intervencion = (self.cleaned_data.get("intervencion_personal") or "").strip()

        if len(intervencion) < 10:
            raise forms.ValidationError("Describe la intervención realizada por el personal.")

        return intervencion

    def clean_responsable_informado_nombre(self):
        nombre = (self.cleaned_data.get("responsable_informado_nombre") or "").strip()

        if nombre and not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s.]+", nombre):
            raise forms.ValidationError("El nombre solo debe contener letras y espacios.")

        return nombre.title() if nombre else nombre

    def clean_archivos(self):
        return validar_lista_archivos(
            self.cleaned_data.get("archivos") or [],
            extensiones_permitidas=self.extensiones_archivo_permitidas,
            limite_mb_archivo=self.limite_mb_archivo,
            limite_mb_total=self.limite_mb_total,
        )

    def clean(self):
        cleaned = super().clean()

        if self.tipo_forzado:
            cleaned["tipo"] = self.tipo_forzado

        registro_diario = cleaned.get("registro_diario")
        alumno = cleaned.get("alumno")

        # Si el campo de registro diario llega vacío, se intenta vincular automáticamente
        # el registro del menor en el día operativo actual.
        if not registro_diario and alumno:
            registro_diario = self._buscar_registro_diario_actual(alumno)
            if registro_diario:
                cleaned["registro_diario"] = registro_diario

        # Si venía un registro inicial de otro menor, no se bloquea el formulario:
        # se reemplaza por el registro diario actual del alumno seleccionado.
        if registro_diario and alumno and registro_diario.alumno_id != alumno.id:
            registro_actual = self._buscar_registro_diario_actual(alumno)
            if registro_actual:
                cleaned["registro_diario"] = registro_actual
                registro_diario = registro_actual
            else:
                cleaned["registro_diario"] = None
                registro_diario = None

        if registro_diario and registro_diario.dia_operativo:
            if dia_operativo_no_laborable(registro_diario.dia_operativo):
                self.add_error(
                    "registro_diario",
                    mensaje_dia_no_laborable(registro_diario.dia_operativo)
                )

            if registro_diario.dia_operativo.semestre.estado == Semestre.EstadoSemestre.CERRADO:
                self.add_error("registro_diario", "No se puede crear incidencia en un semestre cerrado.")

        if alumno and alumno.semestre and alumno.semestre.estado == Semestre.EstadoSemestre.CERRADO:
            self.add_error("alumno", "No se puede crear incidencia para un alumno de semestre cerrado.")

        responsable_informado = cleaned.get("responsable_informado")
        medio = cleaned.get("medio_aviso_responsable")
        responsable = (cleaned.get("responsable_informado_nombre") or "").strip()

        if responsable_informado:
            if not medio or medio == "NO_APLICA":
                self.add_error("medio_aviso_responsable", "Selecciona el medio por el que se informó al responsable.")
            if not responsable:
                self.add_error("responsable_informado_nombre", "Captura el nombre del responsable informado.")

        if cleaned.get("nivel") == "ALTO" and not responsable_informado:
            self.add_error(
                "responsable_informado",
                "Para una incidencia de riesgo alto debes marcar que se informó al responsable."
            )

        categoria = cleaned.get("categoria")
        tipo = cleaned.get("tipo")
        subtipo = (cleaned.get("subtipo") or "").strip()

        if categoria == "OTRO" and len(subtipo) < 3:
            self.add_error("subtipo", "Seleccionaste Otro. Escribe el detalle de la incidencia.")

        if tipo == "MEDICA":
            sintomas = cleaned.get("sintomas_medicos") or []
            sintomas_otro = (cleaned.get("sintomas_medicos_otro") or "").strip()

            if "OTRO" in sintomas and len(sintomas_otro) < 3:
                self.add_error(
                    "sintomas_medicos_otro",
                    "Seleccionaste Otro. Especifica el síntoma, signo o causa médica."
                )

            if categoria == "DIARREA":
                if cleaned.get("numero_evacuaciones") is None:
                    self.add_error("numero_evacuaciones", "Captura el número de evacuaciones.")
                if not cleaned.get("consistencia_evacuacion"):
                    self.add_error("consistencia_evacuacion", "Selecciona la consistencia.")

        if tipo == "NUTRICIONAL" and categoria in ["REACCION_ALERGICA", "INTOLERANCIA"] and not cleaned.get("alimento_relacionado"):
            self.add_error("alimento_relacionado", "Captura el alimento relacionado.")

        if tipo == "PSICOLOGICA" and not cleaned.get("conducta_observada"):
            self.add_error("conducta_observada", "Describe la conducta observada.")

        autorizacion = getattr(self, "autorizacion_suplencia", None)
        if autorizacion:
            if not getattr(autorizacion, "esta_activa", False):
                raise forms.ValidationError("La autorización de suplencia ya no está activa o está fuera de vigencia.")

            if not autorizacion.permite_accion("INCIDENCIA"):
                raise forms.ValidationError("La autorización de suplencia no permite crear incidencias.")

            if self.usuario and autorizacion.suplente_id != self.usuario.id:
                raise forms.ValidationError("Tu usuario no coincide con la persona autorizada para esta suplencia.")

            area_a_tipo = {
                AutorizacionSuplencia.AreaCubierta.MEDICA: Incidencia.TipoIncidencia.MEDICA,
                AutorizacionSuplencia.AreaCubierta.NUTRICION: Incidencia.TipoIncidencia.NUTRICIONAL,
                AutorizacionSuplencia.AreaCubierta.PSICOLOGIA: Incidencia.TipoIncidencia.PSICOLOGICA,
                AutorizacionSuplencia.AreaCubierta.PEDAGOGICA: Incidencia.TipoIncidencia.PEDAGOGICA,
            }
            tipo_esperado = area_a_tipo.get(autorizacion.area_cubierta)
            if tipo_esperado and cleaned.get("tipo") != tipo_esperado:
                self.add_error("tipo", "El tipo de incidencia no corresponde al área cubierta por la suplencia.")

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)

        if self.tipo_forzado:
            obj.tipo = self.tipo_forzado

        if obj.registro_diario_id:
            obj.alumno = obj.registro_diario.alumno
            obj.dia_operativo = obj.registro_diario.dia_operativo
            obj.sala_semestre = obj.registro_diario.sala_semestre
            obj.semestre = obj.registro_diario.dia_operativo.semestre
        elif obj.alumno_id:
            obj.semestre = getattr(obj.alumno, "semestre", None)
            obj.sala_semestre = getattr(obj.alumno, "sala_semestre_asignada", None)

        datos_extra = {
            "sintomas_medicos": self.cleaned_data.get("sintomas_medicos") or [],
            "sintomas_medicos_otro": self.cleaned_data.get("sintomas_medicos_otro") or "",
            "consistencia_evacuacion": self.cleaned_data.get("consistencia_evacuacion") or "",
            "numero_evacuaciones": self.cleaned_data.get("numero_evacuaciones"),
            "alimento_relacionado": self.cleaned_data.get("alimento_relacionado") or "",
            "conducta_observada": self.cleaned_data.get("conducta_observada") or "",
            "contexto_observacion": self.cleaned_data.get("contexto_observacion") or "",
        }

        obj.datos_extra = datos_extra

        autorizacion = getattr(self, "autorizacion_suplencia", None)
        if autorizacion:
            obj.es_suplencia = True
            obj.autorizacion_suplencia = autorizacion
            obj.pendiente_revision_titular = True
            obj.registrada_por = getattr(self, "usuario", None) or autorizacion.suplente

            area_a_tipo = {
                AutorizacionSuplencia.AreaCubierta.MEDICA: Incidencia.TipoIncidencia.MEDICA,
                AutorizacionSuplencia.AreaCubierta.NUTRICION: Incidencia.TipoIncidencia.NUTRICIONAL,
                AutorizacionSuplencia.AreaCubierta.PSICOLOGIA: Incidencia.TipoIncidencia.PSICOLOGICA,
                AutorizacionSuplencia.AreaCubierta.PEDAGOGICA: Incidencia.TipoIncidencia.PEDAGOGICA,
            }
            obj.area_original_suplencia = area_a_tipo.get(autorizacion.area_cubierta, obj.tipo) or obj.tipo

        if commit:
            obj.save()

            if autorizacion:
                try:
                    MovimientoSuplencia.objects.create(
                        autorizacion=autorizacion,
                        usuario=getattr(self, "usuario", None) or autorizacion.suplente,
                        titular_area=autorizacion.titular_ausente,
                        area_cubierta=autorizacion.area_cubierta,
                        accion=MovimientoSuplencia.TipoAccion.CREACION_INCIDENCIA,
                        descripcion="Incidencia registrada mediante suplencia autorizada por Dirección.",
                        inscripcion=obj.alumno,
                        incidencia=obj,
                        objeto_modelo=obj.__class__.__name__,
                        objeto_id=obj.pk,
                    )
                except Exception:
                    pass

        return obj


class SeguimientoIncidenciaForm(forms.ModelForm):
    """
    Seguimiento de incidencia:
    - Nota de texto abierto.
    - Solo la persona que creó la incidencia puede registrar seguimiento.
    - Puede adjuntar archivos.
    """
    archivos = MultipleFileField(
        required=False,
        label="Archivos adjuntos",
        widget=MultipleFileInput(attrs={
            "class": "form-control",
            "multiple": True,
            "accept": ".pdf,.jpg,.jpeg,.png,.doc,.docx",
            "data-max-file-mb": "10",
            "data-max-total-mb": "20",
        })
    )

    extensiones_archivo_permitidas = {"pdf", "jpg", "jpeg", "png", "doc", "docx"}
    limite_mb_archivo = 10
    limite_mb_total = 20

    class Meta:
        model = SeguimientoIncidencia
        fields = [
            "nota",
        ]
        widgets = {
            "nota": forms.Textarea(attrs={
                "rows": 5,
                "placeholder": "Escribe la nota de seguimiento de la incidencia."
            }),
        }
        labels = {
            "nota": "Seguimiento",
        }

    def __init__(self, *args, **kwargs):
        self.incidencia = kwargs.pop("incidencia", None)
        self.usuario = kwargs.pop("usuario", None)
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)

    def clean_nota(self):
        nota = (self.cleaned_data.get("nota") or "").strip()

        if len(nota) < 10:
            raise forms.ValidationError("Captura una nota de seguimiento más detallada.")

        return nota

    def clean_archivos(self):
        return validar_lista_archivos(
            self.cleaned_data.get("archivos") or [],
            extensiones_permitidas=self.extensiones_archivo_permitidas,
            limite_mb_archivo=self.limite_mb_archivo,
            limite_mb_total=self.limite_mb_total,
        )

    def clean(self):
        cleaned = super().clean()

        if not self.incidencia:
            raise forms.ValidationError("No se encontró la incidencia.")

        if self.incidencia.estado == Incidencia.EstadoIncidencia.CERRADA:
            raise forms.ValidationError("No se puede agregar seguimiento a una incidencia cerrada.")

        if self.usuario and not self.incidencia.puede_agregar_seguimiento(self.usuario):
            autorizacion = getattr(self.incidencia, "autorizacion_suplencia", None)
            es_titular_suplencia = bool(
                autorizacion
                and getattr(autorizacion, "titular_ausente_id", None) == self.usuario.id
                and getattr(self.incidencia, "creada_por_suplencia", False)
            )
            if not es_titular_suplencia:
                raise forms.ValidationError("Solo la persona que creó la incidencia o la titular del área cubierta puede registrar seguimiento.")

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)

        if self.incidencia:
            obj.incidencia = self.incidencia

        if self.usuario:
            obj.creado_por = self.usuario

        autorizacion = None
        if self.incidencia and getattr(self.incidencia, "autorizacion_suplencia_id", None):
            autorizacion = self.incidencia.autorizacion_suplencia
            obj.es_suplencia = True
            obj.autorizacion_suplencia = autorizacion
            obj.pendiente_revision_titular = True

        if commit:
            obj.save()

            if autorizacion:
                try:
                    MovimientoSuplencia.objects.create(
                        autorizacion=autorizacion,
                        usuario=self.usuario,
                        titular_area=autorizacion.titular_ausente,
                        area_cubierta=autorizacion.area_cubierta,
                        accion=MovimientoSuplencia.TipoAccion.SEGUIMIENTO_INCIDENCIA,
                        descripcion="Seguimiento de incidencia registrado dentro de una suplencia.",
                        inscripcion=self.incidencia.alumno,
                        incidencia=self.incidencia,
                        objeto_modelo=obj.__class__.__name__,
                        objeto_id=obj.pk,
                    )
                except Exception:
                    pass

        return obj

class CerrarIncidenciaForm(forms.ModelForm):
    """
    Cierre de incidencia:
    - Debe tener mínimo un seguimiento.
    - Solo puede cerrar quien creó la incidencia o el Administrador del Sistema.
    - No debe permitir cierre si el semestre ya fue cerrado.
    """
    confirmar = forms.BooleanField(
        required=True,
        label="Confirmo que deseo cerrar la incidencia"
    )

    class Meta:
        model = Incidencia
        fields = [
            "resolucion",
        ]
        widgets = {
            "resolucion": forms.Textarea(attrs={
                "rows": 5,
                "placeholder": "Describe la resolución final de la incidencia."
            }),
        }
        labels = {
            "resolucion": "Resolución",
        }

    def __init__(self, *args, **kwargs):
        self.incidencia = kwargs.pop("incidencia", None)
        self.usuario = kwargs.pop("usuario", None)
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)

    def clean_resolucion(self):
        resolucion = (self.cleaned_data.get("resolucion") or "").strip()

        if len(resolucion) < 10:
            raise forms.ValidationError("Captura una resolución más detallada.")

        return resolucion

    def clean(self):
        cleaned = super().clean()
        incidencia = self.incidencia or self.instance

        if not incidencia:
            raise forms.ValidationError("No se encontró la incidencia.")

        errores = incidencia.validar_para_cerrar(usuario=self.usuario)

        if errores:
            raise forms.ValidationError(errores)

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)

        if self.usuario:
            obj.cerrada_por = self.usuario

        obj.estado = Incidencia.EstadoIncidencia.CERRADA
        obj.resuelta = True
        obj.cerrada_en = timezone.now()
        obj.comentario_cierre = obj.resolucion

        if commit:
            obj.save()

        return obj


class EnviarEncuestaSatisfaccionForm(forms.Form):
    """
    Formulario para envío de Encuesta de Satisfacción B.

    La fecha de envío ya no se captura aquí.
    La fecha programada se configura desde el formulario del semestre
    en fecha_encuesta_satisfaccion.
    """
    correo_copia = CorreoInstitucionalField(
        required=True,
        label="Correo genérico en copia",
        widget=forms.EmailInput(attrs={
            "placeholder": "correo.generico@unach.mx",
            "autocomplete": "email",
        })
    )
    confirmar_envio = forms.BooleanField(
        required=True,
        label="Confirmo que deseo enviar la Encuesta de Satisfacción B"
    )

    def __init__(self, *args, **kwargs):
        semestre = kwargs.pop("semestre", None)
        super().__init__(*args, **kwargs)

        if semestre:
            self.fields["correo_copia"].initial = semestre.correo_copia_encuesta

        aplicar_clases_bootstrap(self)

    def clean_correo_copia(self):
        correo = limpiar_correo(self.cleaned_data.get("correo_copia"))

        if not correo:
            raise forms.ValidationError("Captura el correo genérico en copia.")

        if not correo.endswith("@unach.mx"):
            raise forms.ValidationError(
                "El correo genérico en copia debe ser institucional y terminar en @unach.mx."
            )

        return correo


class IniciarSemestreForm(forms.Form):
    confirmar = forms.BooleanField(
        required=True,
        label="Confirmo que deseo iniciar el semestre"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)


class CerrarSemestreForm(forms.Form):
    confirmar = forms.BooleanField(
        required=True,
        label="Confirmo que deseo cerrar el semestre"
    )
    observaciones = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Observaciones finales del cierre"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)






# =========================================================
# COMPROBANTE DE PAGO PRESENCIAL
# Rol principal: Trabajo Social
# =========================================================

class RegistrarComprobantePresencialForm(forms.Form):
    """
    Formulario para registrar el comprobante de pago entregado presencialmente.

    Flujo:
    - El beneficiario entrega el comprobante físico a Trabajo Social.
    - Trabajo Social adjunta una foto o PDF del comprobante.
    - Se guarda la evidencia digital en doc_tutor_pago.
    - El estado queda como ENTREGADO_PRESENCIAL.
    - Este formulario NO valida el pago automáticamente.
    """

    comprobante_pago = forms.FileField(
        required=True,
        label="Comprobante de pago digitalizado",
        widget=forms.ClearableFileInput(attrs={
            "class": "form-control",
            "accept": ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png",
        }),
        help_text="Adjunta foto o PDF del comprobante entregado presencialmente."
    )

    observaciones = forms.CharField(
        required=False,
        label="Observaciones",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Opcional. Ej. Recibido presencialmente en ventanilla de Trabajo Social.",
        })
    )

    confirmar = forms.BooleanField(
        required=True,
        label="Confirmo que recibí presencialmente el comprobante de pago"
    )

    extensiones_permitidas = {"pdf", "jpg", "jpeg", "png"}
    limite_mb = 5

    def __init__(self, *args, **kwargs):
        self.inscripcion = kwargs.pop("inscripcion", None)
        self.usuario = kwargs.pop("usuario", None)
        self.autorizacion_suplencia = kwargs.pop("autorizacion_suplencia", None)
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)

        self.fields["comprobante_pago"].widget.attrs.update({
            "class": "form-control",
        })

    def clean_comprobante_pago(self):
        archivo = self.cleaned_data.get("comprobante_pago")

        if not archivo:
            raise forms.ValidationError("Adjunta el comprobante en foto o PDF.")

        nombre = archivo.name or ""
        extension = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""

        if extension not in self.extensiones_permitidas:
            raise forms.ValidationError("Solo se permite PDF, JPG, JPEG o PNG.")

        if archivo.size > self.limite_mb * 1024 * 1024:
            raise forms.ValidationError(f"El comprobante no debe superar {self.limite_mb} MB.")

        return archivo

    def clean_observaciones(self):
        observaciones = (self.cleaned_data.get("observaciones") or "").strip()
        return observaciones

    def clean(self):
        cleaned = super().clean()

        if not self.inscripcion:
            raise forms.ValidationError("No se encontró la inscripción para registrar el comprobante.")

        estado = getattr(self.inscripcion, "estado_pago", "")

        if estado == "VALIDADO":
            raise forms.ValidationError("Este pago ya está validado. No se puede registrar otro comprobante presencial.")

        autorizacion = getattr(self, "autorizacion_suplencia", None)
        if autorizacion:
            if not getattr(autorizacion, "esta_activa", False):
                raise forms.ValidationError("La autorización de suplencia ya no está activa o está fuera de vigencia.")
            if autorizacion.area_cubierta != AutorizacionSuplencia.AreaCubierta.TRABAJO_SOCIAL:
                raise forms.ValidationError("Esta autorización no corresponde a Trabajo Social.")
            if autorizacion.suplente_id and self.usuario and autorizacion.suplente_id != self.usuario.id:
                raise forms.ValidationError("Tu usuario no coincide con la persona autorizada para esta suplencia.")

        return cleaned

    def registrar(self):
        """
        Registra el comprobante presencial en la inscripción.
        Debe llamarse después de form.is_valid().
        """
        if not self.is_valid():
            raise ValueError("El formulario de comprobante presencial no es válido.")

        archivo = self.cleaned_data.get("comprobante_pago")
        observaciones = self.cleaned_data.get("observaciones") or ""

        if hasattr(self.inscripcion, "registrar_comprobante_presencial"):
            self.inscripcion.registrar_comprobante_presencial(
                usuario=self.usuario,
                archivo=archivo,
                observaciones=observaciones,
            )
        else:
            # Compatibilidad si aún no se agregó el método al modelo.
            self.inscripcion.doc_tutor_pago = archivo
            self.inscripcion.estado_pago = "ENTREGADO_PRESENCIAL"
            self.inscripcion.pago_entregado_presencial = True
            self.inscripcion.pago_subido_por_beneficiario = False
            self.inscripcion.pago_recibido_presencial_por = self.usuario
            self.inscripcion.pago_recibido_presencial_en = timezone.now()
            self.inscripcion.pago_observaciones = observaciones or getattr(
                self.inscripcion,
                "pago_observaciones",
                ""
            )

            self.inscripcion.save(update_fields=[
                "doc_tutor_pago",
                "estado_pago",
                "pago_entregado_presencial",
                "pago_subido_por_beneficiario",
                "pago_recibido_presencial_por",
                "pago_recibido_presencial_en",
                "pago_observaciones",
                "updated_at",
            ])

        if getattr(self, "autorizacion_suplencia", None) and hasattr(self.inscripcion, "marcar_trabajo_social_por_suplencia"):
            self.inscripcion.marcar_trabajo_social_por_suplencia(
                autorizacion=self.autorizacion_suplencia,
                usuario=self.usuario,
            )
            try:
                MovimientoSuplencia.objects.create(
                    autorizacion=self.autorizacion_suplencia,
                    usuario=self.usuario,
                    titular_area=self.autorizacion_suplencia.titular_ausente,
                    area_cubierta=self.autorizacion_suplencia.area_cubierta,
                    accion=MovimientoSuplencia.TipoAccion.PAGO,
                    descripcion="Comprobante presencial registrado durante cobertura temporal de Trabajo Social.",
                    inscripcion=self.inscripcion,
                    objeto_modelo=self.inscripcion.__class__.__name__,
                    objeto_id=self.inscripcion.pk,
                )
            except Exception:
                pass

        return self.inscripcion


# Alias de compatibilidad por si alguna vista lo importa con nombre corto.
PagoPresencialForm = RegistrarComprobantePresencialForm


# =========================================================
# SPRINT 4 - CÓDIGO DE SEGURIDAD DEL RESPONSABLE
# Rol principal: Trabajo Social
# =========================================================

CODIGOS_RESPONSABLE_DEBILES = {
    "0000", "1111", "2222", "3333", "4444",
    "5555", "6666", "7777", "8888", "9999",
    "1234", "4321", "0123", "3210", "9876",
    "6789", "2580", "0852",
}


RESPONSABLE_PARENTESCO_CODIGO_CHOICES = [
    ("", "Seleccione..."),
    ("MADRE", "Madre"),
    ("PADRE", "Padre"),
    ("TUTOR", "Tutor"),
    ("ABUELO", "Abuelo(a)"),
    ("AUTORIZADO", "Persona autorizada"),
    ("OTRO", "Otro"),
]


def generar_codigo_responsable_seguro():
    """
    Genera un código numérico de 4 dígitos evitando combinaciones demasiado débiles.
    El código visible solo debe mostrarse al momento de entregarlo al responsable.
    En el modelo debe guardarse usando set_codigo_responsable(), que aplica hash.
    """
    for _ in range(100):
        codigo = f"{secrets.randbelow(10000):04d}"

        if codigo not in CODIGOS_RESPONSABLE_DEBILES:
            return codigo

    return "7391"

class ResponsableAutorizadoChoiceField(forms.ModelChoiceField):
    """
    Campo para seleccionar al tutor o familiar autorizado del menor.
    Muestra el estado del código para evitar confusiones en entrada/salida.
    """

    def label_from_instance(self, obj):
        try:
            tipo = obj.get_tipo_responsable_display()
        except Exception:
            tipo = getattr(obj, "tipo_responsable", "") or "Responsable"

        parentesco = getattr(obj, "parentesco", "") or tipo

        if getattr(obj, "codigo_entregado", False):
            estado = "código entregado"
        elif getattr(obj, "tiene_codigo", False):
            estado = "código generado, pendiente de entrega"
        else:
            estado = "sin código"

        correo = limpiar_correo(getattr(obj, "correo", "") or "")
        if es_correo_institucional(correo):
            metodo = "correo institucional"
        else:
            metodo = "QR presencial"

        return f"{obj.nombre_completo} — {parentesco} ({estado}, {metodo})"


def obtener_responsables_autorizados_para_form(registro_diario):
    """
    Devuelve los responsables autorizados activos del alumno para formularios
    de entrada/salida. Si aún no existen, intenta sincronizarlos desde el expediente.
    """
    if not registro_diario or not getattr(registro_diario, "alumno_id", None):
        return CodigoResponsableAutorizado.objects.none()

    inscripcion = registro_diario.alumno

    try:
        if hasattr(inscripcion, "sincronizar_responsables_autorizados"):
            inscripcion.sincronizar_responsables_autorizados()
    except Exception:
        pass

    return (
        CodigoResponsableAutorizado.objects
        .filter(inscripcion=inscripcion, activo=True)
        .order_by("tipo_responsable", "nombre_completo")
    )


class GenerarCodigoResponsableForm(forms.Form):
    """
    Trabajo Social genera o resetea el código de seguridad de una persona autorizada.

    Regla actual:
    - El código NO es por alumno.
    - Cada tutor o familiar autorizado tiene su propio código.
    - La vista selecciona el responsable autorizado y este formulario valida
      que el alumno esté finalizado, con pago validado, semestre y sala.
    """
    confirmar = forms.BooleanField(
        required=True,
        label="Confirmo que deseo generar el código de seguridad del responsable"
    )
    motivo = forms.CharField(
        required=False,
        label="Motivo / observaciones",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Ej. Código generado para tutor autorizado / código extraviado por el responsable."
        })
    )

    def __init__(self, *args, **kwargs):
        self.alumno = kwargs.pop("alumno", None)
        self.es_reset = kwargs.pop("es_reset", False)
        self.responsable_autorizado = kwargs.pop("responsable_autorizado", None)
        super().__init__(*args, **kwargs)

        if self.es_reset:
            self.fields["confirmar"].label = "Confirmo que deseo resetear y generar un nuevo código"
            self.fields["motivo"].required = True
            self.fields["motivo"].label = "Motivo del reseteo"
            self.fields["motivo"].widget.attrs["placeholder"] = (
                "Describe por qué se genera un nuevo código. Ej. El responsable lo extravió."
            )
        else:
            self.fields["motivo"].label = "Observaciones"
            self.fields["motivo"].widget.attrs["placeholder"] = (
                "Opcional. Ej. Código generado para entregar junto con credencial."
            )

        aplicar_clases_bootstrap(self)

    def clean_motivo(self):
        motivo = (self.cleaned_data.get("motivo") or "").strip()

        if self.es_reset and len(motivo) < 10:
            raise forms.ValidationError("Captura un motivo claro para resetear el código.")

        return motivo

    def clean(self):
        cleaned = super().clean()
        alumno = self.alumno

        if not alumno:
            raise forms.ValidationError("No se encontró el alumno para generar el código.")

        if getattr(alumno, "estado", "") != "FINALIZADA":
            raise forms.ValidationError(
                "Solo se puede generar el código cuando la inscripción está finalizada."
            )

        pago_validado = False

        try:
            pago_validado = bool(getattr(alumno, "pago_validado", False))
        except Exception:
            pago_validado = False

        if not pago_validado:
            pago_validado = bool(getattr(alumno, "pago_validado_en", None))

        if getattr(alumno, "estado_pago", "") == "VALIDADO":
            pago_validado = True

        if not pago_validado:
            raise forms.ValidationError(
                "No se puede generar el código hasta que Trabajo Social valide el pago."
            )

        if not getattr(alumno, "semestre_id", None):
            raise forms.ValidationError(
                "Antes de generar el código, el alumno debe estar asignado a un semestre."
            )

        if not getattr(alumno, "sala_semestre_asignada_id", None):
            raise forms.ValidationError(
                "Antes de generar el código, el alumno debe estar asignado a una sala."
            )

        # La validación de si es generación o reseteo se hace por persona autorizada
        # en la vista. Ya no se bloquea por un código general del alumno.
        return cleaned

    def generar_codigo(self):
        return generar_codigo_responsable_seguro()


class ConfirmarEntregaCodigoResponsableForm(forms.Form):
    """
    Confirmación documental de que Trabajo Social entregó el código y la credencial.

    En el flujo nuevo, el responsable ya viene seleccionado desde la vista.
    Por eso nombre y parentesco son opcionales de compatibilidad.
    """
    credencial_entregada = forms.BooleanField(
        required=True,
        label="Confirmo que la credencial fue entregada al responsable"
    )
    codigo_entregado = forms.BooleanField(
        required=True,
        label="Confirmo que el código fue entregado al responsable"
    )
    responsable_recibe = forms.CharField(
        required=False,
        max_length=180,
        label="Nombre del responsable que recibe",
        widget=forms.TextInput(attrs={
            "placeholder": "Se toma del responsable autorizado seleccionado"
        })
    )
    parentesco = forms.ChoiceField(
        required=False,
        choices=RESPONSABLE_PARENTESCO_CODIGO_CHOICES,
        label="Parentesco"
    )
    observaciones = forms.CharField(
        required=False,
        label="Observaciones",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Opcional. Observaciones de entrega."
        })
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)

    def clean_responsable_recibe(self):
        nombre = (self.cleaned_data.get("responsable_recibe") or "").strip()

        if nombre and len(nombre) < 5:
            raise forms.ValidationError("Captura el nombre completo del responsable.")

        if nombre and not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s.]+", nombre):
            raise forms.ValidationError("El nombre solo debe contener letras y espacios.")

        return nombre.title() if nombre else nombre



# =========================================================
# SPRINT 4 - SEGUNDA PARTE
# OPERACIÓN DIARIA DE MAESTRAS
# Abrir día, entrada, bitácora en casa, estancia, salida y cierre.
# =========================================================

RESPONSABLE_PARENTESCO_CHOICES = [
    ("", "Seleccione..."),
    ("MADRE", "Madre"),
    ("PADRE", "Padre"),
    ("TUTOR", "Tutor"),
    ("ABUELO", "Abuelo(a)"),
    ("AUTORIZADO", "Persona autorizada"),
    ("OTRO", "Otro"),
]

COMO_AMANECIO_CHOICES = [
    ("", "Seleccione..."),
    ("TRANQUILO", "Tranquilo(a)"),
    ("ALEGRE", "Alegre"),
    ("IRRITADO", "Irritado(a)"),
    ("SOMNOLIENTO", "Somnoliento(a)"),
    ("ENFERMO", "Con malestar"),
    ("OTRO", "Otro"),
]

ESTADO_NINO_CHOICES = [
    ("CONTENTO", "Contento"),
    ("TRISTE", "Triste"),
    ("ENOJADO", "Enojado"),
    ("JUGUETON", "Juguetón"),
    ("MOLESTO", "Molesto"),
    ("FLOJO", "Flojo"),
    ("DORMILON", "Dormilón"),
    ("TRAVIESO", "Travieso"),
    ("LLORON", "Llorón"),
]

ACEPTACION_ALIMENTO_CHOICES = [
    ("", "Seleccione..."),
    ("TODO", "Comió todo"),
    ("MITAD", "Comió la mitad"),
    ("POCO", "Comió poco"),
    ("NADA", "No comió"),
    ("NO_APLICA", "No aplica"),
]

TIPO_SALIDA_DIARIA_CHOICES = [
    ("SALIDA_NORMAL", "Salida normal"),
    ("SALIDA_ANTICIPADA", "Salida anticipada"),
    ("SALIDA_POR_INCIDENCIA", "Salida por incidencia"),
]


class AbrirDiaOperativoMaestraForm(forms.Form):
    """
    La maestra abre el día operativo de la sede.
    El día debe existir en el calendario operativo y estar programado.
    """
    confirmar = forms.BooleanField(
        required=True,
        label="Confirmo que deseo abrir la operación del día"
    )
    observaciones = forms.CharField(
        required=False,
        label="Observaciones de apertura",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Opcional. Ej. Apertura normal de operación diaria."
        })
    )

    def __init__(self, *args, **kwargs):
        self.dia_operativo = kwargs.pop("dia_operativo", None) or kwargs.pop("dia", None)
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)

    def clean(self):
        cleaned = super().clean()

        if self.dia_operativo and dia_operativo_no_laborable(self.dia_operativo):
            raise forms.ValidationError(mensaje_dia_no_laborable(self.dia_operativo))

        if (
            self.dia_operativo
            and getattr(self.dia_operativo, "estado", None) == DiaOperativoSemestre.EstadoDia.CERRADO
        ):
            raise forms.ValidationError("Este día ya está cerrado. Solo puede consultarse.")

        return cleaned


class RegistroEntradaAlumnoForm(forms.ModelForm):
    """
    Entrada del menor.
    Valida que el código pertenezca a la persona autorizada seleccionada.
    """
    responsable_codigo_id = ResponsableAutorizadoChoiceField(
        queryset=CodigoResponsableAutorizado.objects.none(),
        required=True,
        label="Responsable autorizado que entrega al menor",
        empty_label="Seleccione tutor o familiar autorizado...",
        widget=forms.Select()
    )

    codigo_responsable = forms.CharField(
        required=True,
        max_length=4,
        min_length=4,
        label="Código de seguridad de 4 dígitos",
        widget=forms.PasswordInput(attrs={
            "placeholder": "****",
            "inputmode": "numeric",
            "maxlength": "4",
            "autocomplete": "off"
        })
    )

    class Meta:
        model = RegistroDiarioAlumno
        fields = [
            "responsable_entrada_nombre",
            "responsable_entrada_parentesco",
            "responsable_entrada_telefono",
            "credencial_entrada_validada",
            "temperatura_entrada",
        ]
        widgets = {
            "responsable_entrada_nombre": forms.TextInput(attrs={
                "placeholder": "Se llenará automáticamente con el responsable seleccionado",
                "readonly": "readonly"
            }),
            "responsable_entrada_parentesco": forms.Select(choices=RESPONSABLE_PARENTESCO_CHOICES),
            "responsable_entrada_telefono": forms.TextInput(attrs={
                "placeholder": "Se llenará automáticamente",
                "inputmode": "numeric",
                "readonly": "readonly"
            }),
            "credencial_entrada_validada": forms.CheckboxInput(),
            "temperatura_entrada": forms.NumberInput(attrs={
                "step": "0.1",
                "min": "30",
                "max": "45",
                "placeholder": "Ej. 36.5"
            }),
        }
        labels = {
            "responsable_entrada_nombre": "Responsable que deja al niño",
            "responsable_entrada_parentesco": "Parentesco",
            "responsable_entrada_telefono": "Teléfono",
            "credencial_entrada_validada": "Credencial verificada",
            "temperatura_entrada": "Temperatura de entrada",
        }

    def __init__(self, *args, **kwargs):
        self.registro_diario = kwargs.pop("registro_diario", None)
        super().__init__(*args, **kwargs)

        if self.registro_diario and not self.instance.pk:
            self.instance = self.registro_diario

        responsables = obtener_responsables_autorizados_para_form(self.registro_diario or self.instance)
        self.fields["responsable_codigo_id"].queryset = responsables

        # Estos datos se llenan desde el responsable autorizado seleccionado.
        self.fields["responsable_entrada_nombre"].required = False
        self.fields["responsable_entrada_parentesco"].required = False
        self.fields["responsable_entrada_telefono"].required = False

        if responsables.count() == 1 and not self.data:
            responsable = responsables.first()
            self.fields["responsable_codigo_id"].initial = responsable
            self.fields["responsable_entrada_nombre"].initial = responsable.nombre_completo
            self.fields["responsable_entrada_parentesco"].initial = responsable.parentesco
            self.fields["responsable_entrada_telefono"].initial = responsable.telefono

        aplicar_clases_bootstrap(self)

    def clean_codigo_responsable(self):
        codigo = (self.cleaned_data.get("codigo_responsable") or "").strip()

        if not re.fullmatch(r"\d{4}", codigo):
            raise forms.ValidationError("El código debe tener exactamente 4 dígitos.")

        return codigo

    def clean_responsable_entrada_telefono(self):
        telefono = (self.cleaned_data.get("responsable_entrada_telefono") or "").strip()

        if telefono and not re.fullmatch(r"\d{10,15}", telefono):
            raise forms.ValidationError("El teléfono debe contener solo números.")

        return telefono

    def clean(self):
        cleaned = super().clean()

        registro = self.registro_diario or self.instance
        dia = getattr(registro, "dia_operativo", None)

        if dia_operativo_no_laborable(dia):
            raise forms.ValidationError(mensaje_dia_no_laborable(dia))

        responsable = cleaned.get("responsable_codigo_id")
        codigo = cleaned.get("codigo_responsable")

        if not responsable:
            self.add_error("responsable_codigo_id", "Selecciona el tutor o familiar autorizado que entrega al menor.")
        else:
            registro = self.registro_diario or self.instance

            if registro and getattr(registro, "alumno_id", None) and responsable.inscripcion_id != registro.alumno_id:
                self.add_error("responsable_codigo_id", "El responsable seleccionado no pertenece a este alumno.")

            if not responsable.tiene_codigo:
                self.add_error("responsable_codigo_id", "Este responsable todavía no tiene código generado por Trabajo Social.")
            elif not responsable.codigo_entregado:
                self.add_error("responsable_codigo_id", "El código de este responsable aún no está marcado como entregado.")
            elif codigo and not responsable.validar_codigo(codigo):
                self.add_error("codigo_responsable", "El código no coincide con el responsable seleccionado.")

            cleaned["responsable_entrada_nombre"] = responsable.nombre_completo
            cleaned["responsable_entrada_parentesco"] = responsable.parentesco or ""
            cleaned["responsable_entrada_telefono"] = responsable.telefono or ""

        if not cleaned.get("credencial_entrada_validada"):
            self.add_error("credencial_entrada_validada", "Debes confirmar que la credencial fue verificada.")

        temperatura = cleaned.get("temperatura_entrada")
        if temperatura is not None and (temperatura < 30 or temperatura > 45):
            self.add_error("temperatura_entrada", "La temperatura debe estar entre 30.0 y 45.0 °C.")

        return cleaned


class SolicitarAutorizacionEntradaForm(forms.ModelForm):
    """
    Solicitud de autorización remota para registrar entrada.

    Flujo nuevo:
    - La maestra captura los datos de entrada y selecciona al responsable.
    - La maestra NO captura el código en su tableta.
    - Si el responsable tiene correo institucional UNACH, el sistema enviará enlace por correo.
    - Si no tiene correo institucional, el sistema mostrará un QR presencial.
    - El responsable valida desde su celular con su código de 4 dígitos.
    """
    responsable_autorizado = ResponsableAutorizadoChoiceField(
        queryset=CodigoResponsableAutorizado.objects.none(),
        required=True,
        label="Responsable autorizado que entrega al menor",
        empty_label="Seleccione tutor o familiar autorizado...",
        widget=forms.Select(attrs={
            "data-responsable-autorizado": "true",
        })
    )

    class Meta:
        model = AutorizacionEntrada
        fields = [
            "responsable_autorizado",
            "credencial_entrada_validada",
            "temperatura_entrada",
            "observaciones_maestra",
        ]
        widgets = {
            "credencial_entrada_validada": forms.CheckboxInput(),
            "temperatura_entrada": forms.NumberInput(attrs={
                "step": "0.1",
                "min": "30",
                "max": "45",
                "placeholder": "Ej. 36.5"
            }),
            "observaciones_maestra": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Observaciones de entrada antes de solicitar autorización."
            }),
        }
        labels = {
            "responsable_autorizado": "Responsable autorizado que deja al niño/a",
            "credencial_entrada_validada": "Credencial verificada por la maestra",
            "temperatura_entrada": "Temperatura de entrada",
            "observaciones_maestra": "Observaciones de la maestra",
        }

    def __init__(self, *args, **kwargs):
        self.registro_diario = kwargs.pop("registro_diario", None)
        self.usuario = kwargs.pop("usuario", None)
        super().__init__(*args, **kwargs)

        responsables = obtener_responsables_autorizados_para_form(self.registro_diario)
        self.fields["responsable_autorizado"].queryset = responsables

        if responsables.count() == 1 and not self.data:
            self.fields["responsable_autorizado"].initial = responsables.first()

        aplicar_clases_bootstrap(self)
        self.fields["responsable_autorizado"].widget.attrs["class"] = "form-select"

    def clean(self):
        cleaned = super().clean()
        registro = self.registro_diario
        dia = getattr(registro, "dia_operativo", None)
        responsable = cleaned.get("responsable_autorizado")

        if not registro:
            raise forms.ValidationError("No se encontró el registro diario del alumno.")

        if dia_operativo_no_laborable(dia):
            raise forms.ValidationError(mensaje_dia_no_laborable(dia))

        if getattr(registro, "entrada_en", None):
            raise forms.ValidationError("Este alumno ya tiene entrada registrada.")

        if not getattr(registro, "dia_esta_editable", False):
            raise forms.ValidationError("El día no está abierto o no permite registrar entradas.")

        pendiente = AutorizacionEntrada.objects.filter(
            registro_diario=registro,
            estado__in=[
                AutorizacionEntrada.EstadoAutorizacion.PENDIENTE,
                AutorizacionEntrada.EstadoAutorizacion.ENVIADA,
            ]
        )

        if self.instance and self.instance.pk:
            pendiente = pendiente.exclude(pk=self.instance.pk)

        if pendiente.exists():
            raise forms.ValidationError(
                "Ya existe una solicitud de autorización pendiente para este alumno. "
                "Cancela o espera la respuesta antes de enviar otra."
            )

        if not responsable:
            self.add_error("responsable_autorizado", "Selecciona al responsable autorizado.")
        else:
            if getattr(registro, "alumno_id", None) and responsable.inscripcion_id != registro.alumno_id:
                self.add_error("responsable_autorizado", "El responsable seleccionado no pertenece a este alumno.")

            if not getattr(responsable, "activo", False):
                self.add_error("responsable_autorizado", "Este responsable autorizado está inactivo.")

            if not getattr(responsable, "tiene_codigo", False):
                self.add_error("responsable_autorizado", "Este responsable todavía no tiene código generado por Trabajo Social.")
            elif not getattr(responsable, "codigo_entregado", False):
                self.add_error("responsable_autorizado", "El código de este responsable aún no está marcado como entregado.")

            # Si el responsable no tiene correo institucional UNACH, no se bloquea.
            # En ese caso el modelo asignará automáticamente el método QR presencial.

        if not cleaned.get("credencial_entrada_validada"):
            self.add_error("credencial_entrada_validada", "Debes confirmar que la credencial fue verificada.")

        temperatura = cleaned.get("temperatura_entrada")
        if temperatura is not None and (temperatura < 30 or temperatura > 45):
            self.add_error("temperatura_entrada", "La temperatura debe estar entre 30.0 y 45.0 °C.")

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.registro_diario = self.registro_diario
        obj.solicitada_por = self.usuario
        obj.estado = AutorizacionEntrada.EstadoAutorizacion.PENDIENTE

        if obj.responsable_autorizado:
            obj.responsable_nombre = obj.responsable_autorizado.nombre_completo or ""
            obj.responsable_parentesco = obj.responsable_autorizado.parentesco or ""
            obj.responsable_telefono = obj.responsable_autorizado.telefono or ""
            obj.correo_destino = limpiar_correo(obj.responsable_autorizado.correo)

        if commit:
            obj.save()

        return obj


class AutorizarEntradaResponsableForm(forms.Form):
    """
    Formulario que ve el responsable autorizado desde su celular.
    El responsable ingresa su código de 4 dígitos para autorizar la entrada.
    """
    codigo_responsable = forms.CharField(
        required=True,
        max_length=4,
        min_length=4,
        label="Código de seguridad de 4 dígitos",
        widget=forms.PasswordInput(attrs={
            "placeholder": "****",
            "inputmode": "numeric",
            "maxlength": "4",
            "autocomplete": "one-time-code",
        })
    )
    comentario_responsable = forms.CharField(
        required=False,
        label="Comentario opcional",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Opcional. Comentario del responsable."
        })
    )
    confirmar = forms.BooleanField(
        required=True,
        label="Confirmo que autorizo la entrada del menor a la estancia"
    )

    def __init__(self, *args, **kwargs):
        self.autorizacion = kwargs.pop("autorizacion", None)
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)

    def clean_codigo_responsable(self):
        codigo = (self.cleaned_data.get("codigo_responsable") or "").strip()

        if not re.fullmatch(r"\d{4}", codigo):
            raise forms.ValidationError("El código debe tener exactamente 4 dígitos.")

        return codigo

    def clean_comentario_responsable(self):
        return (self.cleaned_data.get("comentario_responsable") or "").strip()

    def clean(self):
        cleaned = super().clean()
        autorizacion = self.autorizacion

        if not autorizacion:
            raise forms.ValidationError("No se encontró la solicitud de autorización.")

        try:
            autorizacion.expirar_si_corresponde()
        except Exception:
            pass

        if not getattr(autorizacion, "esta_vigente", False):
            raise forms.ValidationError("La solicitud ya expiró o ya no está disponible.")

        registro = getattr(autorizacion, "registro_diario", None)
        if getattr(registro, "entrada_en", None):
            raise forms.ValidationError("El alumno ya tiene entrada registrada.")

        return cleaned

    def autorizar(self, ip=None, user_agent=""):
        if not self.is_valid():
            raise ValueError("El formulario de autorización no es válido.")

        return self.autorizacion.autorizar(
            codigo=self.cleaned_data["codigo_responsable"],
            ip=ip,
            user_agent=user_agent,
            comentario=self.cleaned_data.get("comentario_responsable") or "",
        )


class RechazarAutorizacionEntradaForm(forms.Form):
    """
    Formulario opcional para que el responsable rechace la entrada desde el enlace.
    """
    comentario_responsable = forms.CharField(
        required=True,
        label="Motivo del rechazo",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Escribe brevemente por qué rechazas esta entrada."
        })
    )
    confirmar = forms.BooleanField(
        required=True,
        label="Confirmo que deseo rechazar esta solicitud de entrada"
    )

    def __init__(self, *args, **kwargs):
        self.autorizacion = kwargs.pop("autorizacion", None)
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)

    def clean_comentario_responsable(self):
        comentario = (self.cleaned_data.get("comentario_responsable") or "").strip()

        if len(comentario) < 5:
            raise forms.ValidationError("Escribe un motivo breve para rechazar la autorización.")

        return comentario

    def clean(self):
        cleaned = super().clean()
        autorizacion = self.autorizacion

        if not autorizacion:
            raise forms.ValidationError("No se encontró la solicitud de autorización.")

        try:
            autorizacion.expirar_si_corresponde()
        except Exception:
            pass

        if not getattr(autorizacion, "esta_vigente", False):
            raise forms.ValidationError("La solicitud ya expiró o ya no está disponible.")

        return cleaned

    def rechazar(self, ip=None, user_agent=""):
        if not self.is_valid():
            raise ValueError("El formulario de rechazo no es válido.")

        return self.autorizacion.rechazar(
            comentario=self.cleaned_data.get("comentario_responsable") or "",
            ip=ip,
            user_agent=user_agent,
        )


class SolicitarAutorizacionSalidaForm(forms.ModelForm):
    """
    Solicitud de autorización remota para registrar salida.

    Flujo nuevo:
    - La maestra captura los datos de salida y selecciona al responsable.
    - La maestra NO captura el código en su tableta.
    - Si el responsable tiene correo institucional UNACH, el sistema enviará enlace por correo.
    - Si no tiene correo institucional, el sistema mostrará un QR presencial.
    - El responsable valida desde su celular con su código de 4 dígitos.
    """
    responsable_autorizado = ResponsableAutorizadoChoiceField(
        queryset=CodigoResponsableAutorizado.objects.none(),
        required=True,
        label="Responsable autorizado que recoge al menor",
        empty_label="Seleccione tutor o familiar autorizado...",
        widget=forms.Select(attrs={
            "data-responsable-autorizado": "true",
        })
    )

    tipo_salida = forms.ChoiceField(
        choices=TIPO_SALIDA_DIARIA_CHOICES,
        required=True,
        label="Tipo de salida"
    )

    class Meta:
        model = AutorizacionSalida
        fields = [
            "responsable_autorizado",
            "credencial_salida_validada",
            "tipo_salida",
            "motivo_salida",
            "observacion_salida",
        ]
        widgets = {
            "credencial_salida_validada": forms.CheckboxInput(),
            "motivo_salida": forms.TextInput(attrs={
                "placeholder": "Ej. Salida normal, cita médica, salida anticipada"
            }),
            "observacion_salida": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Comentario de salida opcional"
            }),
        }
        labels = {
            "responsable_autorizado": "Responsable autorizado que recoge al niño/a",
            "credencial_salida_validada": "Credencial verificada por la maestra",
            "tipo_salida": "Tipo de salida",
            "motivo_salida": "Motivo de salida",
            "observacion_salida": "Comentario de salida",
        }

    def __init__(self, *args, **kwargs):
        self.registro_diario = kwargs.pop("registro_diario", None)
        self.usuario = kwargs.pop("usuario", None)
        super().__init__(*args, **kwargs)

        responsables = obtener_responsables_autorizados_para_form(self.registro_diario)
        self.fields["responsable_autorizado"].queryset = responsables

        if responsables.count() == 1 and not self.data:
            self.fields["responsable_autorizado"].initial = responsables.first()

        aplicar_clases_bootstrap(self)
        self.fields["responsable_autorizado"].widget.attrs["class"] = "form-select"

    def clean(self):
        cleaned = super().clean()
        registro = self.registro_diario
        dia = getattr(registro, "dia_operativo", None)
        responsable = cleaned.get("responsable_autorizado")

        if not registro:
            raise forms.ValidationError("No se encontró el registro diario del alumno.")

        if dia_operativo_no_laborable(dia):
            raise forms.ValidationError(mensaje_dia_no_laborable(dia))

        if not getattr(registro, "entrada_en", None):
            raise forms.ValidationError("No se puede solicitar salida si el alumno no tiene entrada registrada.")

        if getattr(registro, "salida_en", None):
            raise forms.ValidationError("Este alumno ya tiene salida registrada.")

        if not getattr(registro, "dia_esta_editable", False):
            raise forms.ValidationError("El día no está abierto o no permite registrar salidas.")

        pendiente = AutorizacionSalida.objects.filter(
            registro_diario=registro,
            estado__in=[
                AutorizacionSalida.EstadoAutorizacion.PENDIENTE,
                AutorizacionSalida.EstadoAutorizacion.ENVIADA,
                AutorizacionSalida.EstadoAutorizacion.QR_GENERADO,
            ]
        )

        if self.instance and self.instance.pk:
            pendiente = pendiente.exclude(pk=self.instance.pk)

        if pendiente.exists():
            raise forms.ValidationError(
                "Ya existe una solicitud de autorización pendiente para la salida de este alumno. "
                "Cancela o espera la respuesta antes de enviar otra."
            )

        if not responsable:
            self.add_error("responsable_autorizado", "Selecciona al responsable autorizado.")
        else:
            if getattr(registro, "alumno_id", None) and responsable.inscripcion_id != registro.alumno_id:
                self.add_error("responsable_autorizado", "El responsable seleccionado no pertenece a este alumno.")

            if not getattr(responsable, "activo", False):
                self.add_error("responsable_autorizado", "Este responsable autorizado está inactivo.")

            if not getattr(responsable, "tiene_codigo", False):
                self.add_error("responsable_autorizado", "Este responsable todavía no tiene código generado por Trabajo Social.")
            elif not getattr(responsable, "codigo_entregado", False):
                self.add_error("responsable_autorizado", "El código de este responsable aún no está marcado como entregado.")

            # Si el responsable no tiene correo institucional UNACH, no se bloquea.
            # En ese caso el modelo asignará automáticamente el método QR presencial.

        if not cleaned.get("credencial_salida_validada"):
            self.add_error("credencial_salida_validada", "Debes confirmar que la credencial fue verificada.")

        tipo_salida = cleaned.get("tipo_salida")
        motivo = (cleaned.get("motivo_salida") or "").strip()

        if tipo_salida in ["SALIDA_ANTICIPADA", "SALIDA_POR_INCIDENCIA"] and not motivo:
            self.add_error("motivo_salida", "Captura el motivo de la salida especial.")

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.registro_diario = self.registro_diario
        obj.solicitada_por = self.usuario
        obj.estado = AutorizacionSalida.EstadoAutorizacion.PENDIENTE

        if obj.responsable_autorizado:
            obj.responsable_nombre = obj.responsable_autorizado.nombre_completo or ""
            obj.responsable_parentesco = obj.responsable_autorizado.parentesco or ""
            obj.responsable_telefono = obj.responsable_autorizado.telefono or ""
            obj.correo_destino = limpiar_correo(obj.responsable_autorizado.correo)

        if commit:
            obj.save()

        return obj


class AutorizarSalidaResponsableForm(forms.Form):
    """
    Formulario que ve el responsable autorizado desde su celular.
    El responsable ingresa su código de 4 dígitos para autorizar la salida.
    """
    codigo_responsable = forms.CharField(
        required=True,
        max_length=4,
        min_length=4,
        label="Código de seguridad de 4 dígitos",
        widget=forms.PasswordInput(attrs={
            "placeholder": "****",
            "inputmode": "numeric",
            "maxlength": "4",
            "autocomplete": "one-time-code",
        })
    )
    comentario_responsable = forms.CharField(
        required=False,
        label="Comentario opcional",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Opcional. Comentario del responsable."
        })
    )
    confirmar = forms.BooleanField(
        required=True,
        label="Confirmo que autorizo la salida del menor de la estancia"
    )

    def __init__(self, *args, **kwargs):
        self.autorizacion = kwargs.pop("autorizacion", None)
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)

    def clean_codigo_responsable(self):
        codigo = (self.cleaned_data.get("codigo_responsable") or "").strip()

        if not re.fullmatch(r"\d{4}", codigo):
            raise forms.ValidationError("El código debe tener exactamente 4 dígitos.")

        return codigo

    def clean_comentario_responsable(self):
        return (self.cleaned_data.get("comentario_responsable") or "").strip()

    def clean(self):
        cleaned = super().clean()
        autorizacion = self.autorizacion

        if not autorizacion:
            raise forms.ValidationError("No se encontró la solicitud de autorización.")

        try:
            autorizacion.expirar_si_corresponde()
        except Exception:
            pass

        if not getattr(autorizacion, "esta_vigente", False):
            raise forms.ValidationError("La solicitud ya expiró o ya no está disponible.")

        registro = getattr(autorizacion, "registro_diario", None)
        if not getattr(registro, "entrada_en", None):
            raise forms.ValidationError("El alumno no tiene entrada registrada.")

        if getattr(registro, "salida_en", None):
            raise forms.ValidationError("El alumno ya tiene salida registrada.")

        return cleaned

    def autorizar(self, ip=None, user_agent=""):
        if not self.is_valid():
            raise ValueError("El formulario de autorización no es válido.")

        return self.autorizacion.autorizar(
            codigo=self.cleaned_data["codigo_responsable"],
            ip=ip,
            user_agent=user_agent,
            comentario=self.cleaned_data.get("comentario_responsable") or "",
        )


class RechazarAutorizacionSalidaForm(forms.Form):
    """
    Formulario opcional para que el responsable rechace la salida desde el enlace o QR.
    """
    comentario_responsable = forms.CharField(
        required=True,
        label="Motivo del rechazo",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Escribe brevemente por qué rechazas esta salida."
        })
    )
    confirmar = forms.BooleanField(
        required=True,
        label="Confirmo que deseo rechazar esta solicitud de salida"
    )

    def __init__(self, *args, **kwargs):
        self.autorizacion = kwargs.pop("autorizacion", None)
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)

    def clean_comentario_responsable(self):
        comentario = (self.cleaned_data.get("comentario_responsable") or "").strip()

        if len(comentario) < 5:
            raise forms.ValidationError("Escribe un motivo breve para rechazar la autorización.")

        return comentario

    def clean(self):
        cleaned = super().clean()
        autorizacion = self.autorizacion

        if not autorizacion:
            raise forms.ValidationError("No se encontró la solicitud de autorización.")

        try:
            autorizacion.expirar_si_corresponde()
        except Exception:
            pass

        if not getattr(autorizacion, "esta_vigente", False):
            raise forms.ValidationError("La solicitud ya expiró o ya no está disponible.")

        return cleaned

    def rechazar(self, ip=None, user_agent=""):
        if not self.is_valid():
            raise ValueError("El formulario de rechazo no es válido.")

        return self.autorizacion.rechazar(
            comentario=self.cleaned_data.get("comentario_responsable") or "",
            ip=ip,
            user_agent=user_agent,
        )


class BitacoraEntradaCasaForm(forms.ModelForm):
    """
    Primera parte de la bitácora:
    información proporcionada por el adulto responsable al dejar al menor.
    """
    marcar_completa = forms.BooleanField(
        required=False,
        label="Marcar bitácora en casa como completa"
    )

    estado_en_casa_multiple = forms.MultipleChoiceField(
        choices=ESTADO_NINO_CHOICES,
        required=False,
        label="En casa estuve",
        widget=forms.SelectMultiple(attrs={"class": "form-select select2-multiple"})
    )

    class Meta:
        model = BitacoraEntradaCasa
        fields = [
            "desperto_a_las",
            "como_amanecio",
            "ultimo_alimento_hora",
            "leche_descripcion",
            "alimentos_descripcion",
            "hizo_popo",
            "observaciones",
        ]
        widgets = {
            "desperto_a_las": forms.TimeInput(attrs={"type": "time"}),
            "como_amanecio": forms.Select(choices=COMO_AMANECIO_CHOICES),
            "ultimo_alimento_hora": forms.TimeInput(attrs={"type": "time"}),
            "leche_descripcion": forms.TextInput(attrs={
                "placeholder": "Ej. 6 oz / 180 ml / no tomó"
            }),
            "alimentos_descripcion": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Ej. Papilla, alimentos completos, cantidad aproximada"
            }),
            "hizo_popo": forms.Select(choices=[
                ("", "Seleccione..."),
                ("True", "Sí"),
                ("False", "No"),
            ]),
            "observaciones": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Observaciones reportadas por el adulto responsable"
            }),
        }
        labels = {
            "desperto_a_las": "Hoy desperté a las",
            "como_amanecio": "Hoy amanecí",
            "ultimo_alimento_hora": "Mi último alimento fue a las",
            "leche_descripcion": "Leche / cantidad",
            "alimentos_descripcion": "Papilla o alimentos completos",
            "hizo_popo": "¿Hice popó?",
            "observaciones": "Observaciones",
        }

    def __init__(self, *args, **kwargs):
        self.registro_diario = kwargs.pop("registro_diario", None)
        self.tipo_formulario = kwargs.pop("tipo_formulario", "")
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk and self.instance.estado_en_casa:
            self.initial["estado_en_casa_multiple"] = [
                x.strip() for x in self.instance.estado_en_casa.split(",") if x.strip()
            ]

        aplicar_clases_bootstrap(self)

    def clean(self):
        cleaned = super().clean()

        dia = getattr(getattr(self, "registro_diario", None), "dia_operativo", None)
        if dia_operativo_no_laborable(dia):
            raise forms.ValidationError(mensaje_dia_no_laborable(dia))

        if cleaned.get("marcar_completa"):
            requeridos = [
                ("desperto_a_las", "Captura a qué hora despertó."),
                ("como_amanecio", "Selecciona cómo amaneció."),
                ("ultimo_alimento_hora", "Captura la hora del último alimento."),
            ]

            for campo, mensaje in requeridos:
                if not cleaned.get(campo):
                    self.add_error(campo, mensaje)

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)

        if self.registro_diario:
            obj.registro_diario = self.registro_diario

        estados = self.cleaned_data.get("estado_en_casa_multiple") or []
        obj.estado_en_casa = ", ".join(estados)

        if self.cleaned_data.get("marcar_completa"):
            obj.completa = True
            obj.capturada_en = timezone.now()

        if commit:
            obj.save()

        return obj


class BitacoraEstanciaForm(forms.ModelForm):
    """
    Segunda parte de la bitácora:
    información capturada por la maestra durante la estancia del menor.
    """
    marcar_completa = forms.BooleanField(
        required=False,
        label="Marcar bitácora durante estancia como completa"
    )

    estado_durante_dia_multiple = forms.MultipleChoiceField(
        choices=ESTADO_NINO_CHOICES,
        required=False,
        label="Hoy durante el día estuve",
        widget=forms.SelectMultiple(attrs={"class": "form-select select2-multiple"})
    )

    class Meta:
        model = BitacoraEstancia
        fields = [
            "hidratacion",
            "desayuno",
            "colacion",
            "comida",
            "siesta",
            "panal",
            "control_esfinteres",
            "actividad_pedagogica",
            "comentario_general",
        ]
        widgets = {
            "hidratacion": forms.TextInput(attrs={"placeholder": "Ej. Tomó agua adecuadamente"}),
            "desayuno": forms.Select(choices=ACEPTACION_ALIMENTO_CHOICES),
            "colacion": forms.Select(choices=ACEPTACION_ALIMENTO_CHOICES),
            "comida": forms.Select(choices=ACEPTACION_ALIMENTO_CHOICES),
            "siesta": forms.TextInput(attrs={"placeholder": "Ej. Durmió de 10:30 a 11:15"}),
            "panal": forms.TextInput(attrs={"placeholder": "Lactantes: cambios de pañal"}),
            "control_esfinteres": forms.TextInput(attrs={"placeholder": "Maternal: control de esfínteres"}),
            "actividad_pedagogica": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Describe participación en actividad pedagógica"
            }),
            "comentario_general": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Comentario general del día"
            }),
        }

    def __init__(self, *args, **kwargs):
        self.registro_diario = kwargs.pop("registro_diario", None)
        self.tipo_formulario = kwargs.pop("tipo_formulario", "")
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk and self.instance.estado_durante_dia:
            self.initial["estado_durante_dia_multiple"] = [
                x.strip() for x in self.instance.estado_durante_dia.split(",") if x.strip()
            ]

        # El formulario se adapta visualmente según la sala.
        # Lactantes usa pañal; Maternal usa control de esfínteres.
        if self.tipo_formulario == "LACTANTES":
            self.fields["control_esfinteres"].required = False
            self.fields["control_esfinteres"].widget.attrs["placeholder"] = "No aplica para lactantes"
        elif self.tipo_formulario == "MATERNAL":
            self.fields["panal"].required = False
            self.fields["panal"].widget.attrs["placeholder"] = "No aplica para maternal"

        aplicar_clases_bootstrap(self)

    def clean(self):
        cleaned = super().clean()

        dia = getattr(getattr(self, "registro_diario", None), "dia_operativo", None)
        if dia_operativo_no_laborable(dia):
            raise forms.ValidationError(mensaje_dia_no_laborable(dia))

        if cleaned.get("marcar_completa"):
            if not (cleaned.get("estado_durante_dia_multiple") or []):
                self.add_error("estado_durante_dia_multiple", "Selecciona cómo estuvo el menor durante el día.")

            if not cleaned.get("actividad_pedagogica"):
                self.add_error("actividad_pedagogica", "Captura la actividad pedagógica o participación del menor.")

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)

        if self.registro_diario:
            obj.registro_diario = self.registro_diario

        estados = self.cleaned_data.get("estado_durante_dia_multiple") or []
        obj.estado_durante_dia = ", ".join(estados)

        leche_tomas = {}
        # Se deja preparado para que el template envíe tomas dinámicas:
        # leche_1_hora, leche_1_cantidad, leche_2_hora, etc.
        for i in range(1, 4):
            hora = self.data.get(f"leche_{i}_hora")
            cantidad = self.data.get(f"leche_{i}_cantidad")
            if hora or cantidad:
                leche_tomas[str(i)] = {
                    "hora": hora or "",
                    "cantidad": cantidad or "",
                }
        obj.leche_tomas = leche_tomas

        if self.cleaned_data.get("marcar_completa"):
            obj.completa = True
            obj.capturada_en = timezone.now()

        if commit:
            obj.save()

        return obj


class RegistroSalidaAlumnoForm(forms.ModelForm):
    """
    Salida del menor.
    Valida que el código pertenezca a la persona autorizada seleccionada.
    """
    responsable_codigo_id = ResponsableAutorizadoChoiceField(
        queryset=CodigoResponsableAutorizado.objects.none(),
        required=True,
        label="Responsable autorizado que recoge al menor",
        empty_label="Seleccione tutor o familiar autorizado...",
        widget=forms.Select()
    )

    codigo_responsable = forms.CharField(
        required=True,
        max_length=4,
        min_length=4,
        label="Código de seguridad de 4 dígitos",
        widget=forms.PasswordInput(attrs={
            "placeholder": "****",
            "inputmode": "numeric",
            "maxlength": "4",
            "autocomplete": "off"
        })
    )

    tipo_salida = forms.ChoiceField(
        choices=TIPO_SALIDA_DIARIA_CHOICES,
        required=True,
        label="Tipo de salida"
    )

    class Meta:
        model = RegistroDiarioAlumno
        fields = [
            "responsable_salida_nombre",
            "responsable_salida_parentesco",
            "responsable_salida_telefono",
            "credencial_salida_validada",
            "motivo_salida",
            "observacion_salida",
        ]
        widgets = {
            "responsable_salida_nombre": forms.TextInput(attrs={
                "placeholder": "Se llenará automáticamente con el responsable seleccionado",
                "readonly": "readonly"
            }),
            "responsable_salida_parentesco": forms.Select(choices=RESPONSABLE_PARENTESCO_CHOICES),
            "responsable_salida_telefono": forms.TextInput(attrs={
                "placeholder": "Se llenará automáticamente",
                "inputmode": "numeric",
                "readonly": "readonly"
            }),
            "credencial_salida_validada": forms.CheckboxInput(),
            "motivo_salida": forms.TextInput(attrs={
                "placeholder": "Ej. Salida normal, cita médica, salida anticipada"
            }),
            "observacion_salida": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Comentario de salida opcional"
            }),
        }
        labels = {
            "responsable_salida_nombre": "Responsable que recoge al niño",
            "responsable_salida_parentesco": "Parentesco",
            "responsable_salida_telefono": "Teléfono",
            "credencial_salida_validada": "Credencial verificada",
            "motivo_salida": "Motivo de salida",
            "observacion_salida": "Comentario de salida",
        }

    def __init__(self, *args, **kwargs):
        self.registro_diario = kwargs.pop("registro_diario", None)
        super().__init__(*args, **kwargs)

        if self.registro_diario and not self.instance.pk:
            self.instance = self.registro_diario

        responsables = obtener_responsables_autorizados_para_form(self.registro_diario or self.instance)
        self.fields["responsable_codigo_id"].queryset = responsables

        # Estos datos se llenan desde el responsable autorizado seleccionado.
        self.fields["responsable_salida_nombre"].required = False
        self.fields["responsable_salida_parentesco"].required = False
        self.fields["responsable_salida_telefono"].required = False

        if responsables.count() == 1 and not self.data:
            responsable = responsables.first()
            self.fields["responsable_codigo_id"].initial = responsable
            self.fields["responsable_salida_nombre"].initial = responsable.nombre_completo
            self.fields["responsable_salida_parentesco"].initial = responsable.parentesco
            self.fields["responsable_salida_telefono"].initial = responsable.telefono

        aplicar_clases_bootstrap(self)

    def clean_codigo_responsable(self):
        codigo = (self.cleaned_data.get("codigo_responsable") or "").strip()

        if not re.fullmatch(r"\d{4}", codigo):
            raise forms.ValidationError("El código debe tener exactamente 4 dígitos.")

        return codigo

    def clean_responsable_salida_telefono(self):
        telefono = (self.cleaned_data.get("responsable_salida_telefono") or "").strip()

        if telefono and not re.fullmatch(r"\d{10,15}", telefono):
            raise forms.ValidationError("El teléfono debe contener solo números.")

        return telefono

    def clean(self):
        cleaned = super().clean()

        registro = self.registro_diario or self.instance
        dia = getattr(registro, "dia_operativo", None)

        if dia_operativo_no_laborable(dia):
            raise forms.ValidationError(mensaje_dia_no_laborable(dia))

        responsable = cleaned.get("responsable_codigo_id")
        codigo = cleaned.get("codigo_responsable")

        if not responsable:
            self.add_error("responsable_codigo_id", "Selecciona el tutor o familiar autorizado que recoge al menor.")
        else:
            registro = self.registro_diario or self.instance

            if registro and getattr(registro, "alumno_id", None) and responsable.inscripcion_id != registro.alumno_id:
                self.add_error("responsable_codigo_id", "El responsable seleccionado no pertenece a este alumno.")

            if not responsable.tiene_codigo:
                self.add_error("responsable_codigo_id", "Este responsable todavía no tiene código generado por Trabajo Social.")
            elif not responsable.codigo_entregado:
                self.add_error("responsable_codigo_id", "El código de este responsable aún no está marcado como entregado.")
            elif codigo and not responsable.validar_codigo(codigo):
                self.add_error("codigo_responsable", "El código no coincide con el responsable seleccionado.")

            cleaned["responsable_salida_nombre"] = responsable.nombre_completo
            cleaned["responsable_salida_parentesco"] = responsable.parentesco or ""
            cleaned["responsable_salida_telefono"] = responsable.telefono or ""

        if not cleaned.get("credencial_salida_validada"):
            self.add_error("credencial_salida_validada", "Debes confirmar que la credencial fue verificada.")

        tipo_salida = cleaned.get("tipo_salida")
        motivo = (cleaned.get("motivo_salida") or "").strip()

        if tipo_salida in ["SALIDA_ANTICIPADA", "SALIDA_POR_INCIDENCIA"] and not motivo:
            self.add_error("motivo_salida", "Captura el motivo de la salida especial.")

        return cleaned


class CerrarDiaOperacionMaestraForm(forms.Form):
    confirmar = forms.BooleanField(
        required=True,
        label="Confirmo que deseo cerrar la operación del día"
    )
    observaciones = forms.CharField(
        required=False,
        label="Observaciones del cierre",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Opcional. Observaciones generales del cierre del día."
        })
    )

    def __init__(self, *args, **kwargs):
        self.dia_operativo = kwargs.pop("dia_operativo", None) or kwargs.pop("dia", None)
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)

    def clean(self):
        cleaned = super().clean()

        if self.dia_operativo and dia_operativo_no_laborable(self.dia_operativo):
            raise forms.ValidationError(
                "No se puede cerrar operación diaria en un día inhábil; "
                "sábado, domingo y festivos quedan cerrados automáticamente."
            )

        return cleaned



# =========================================================
# OPCIONES COMPARTIDAS (LACTANTES Y MATERNALES)
# =========================================================
MEDIDA_CHOICES = [('', 'Seleccione...'), ('ONZAS', 'Onzas'), ('MILILITROS', 'Mililitros')]
CANTIDAD_MEDIDA_CHOICES = [('', 'Seleccione...')] + [(str(i), f"{i} onzas") for i in range(1, 11)] + [
    (str(i), f"{i} ml") for i in range(100, 1001, 100)]
ESTADO_ANIMO_CHOICES = [
    ('Contento', 'Contento'), ('Triste', 'Triste'), ('Enojado', 'Enojado'),
    ('Juguetón', 'Juguetón'), ('Molesto', 'Molesto'), ('Flojo', 'Flojo'),
    ('Dormilón', 'Dormilón'), ('Travieso', 'Travieso'), ('Llorón', 'Llorón')
]
RADIO_CUANTAS = [('0', 'Ninguna'), ('1', '1'), ('2', '2'), ('3', '3')]  # <-- OPCIÓN NINGUNA AGREGADA
COMIDA_ACEPTACION_CHOICES = [
    ('', 'Seleccione...'), ('Todo', 'Comí todo'), ('La mitad', 'La mitad'),
    ('Poco', 'Poco'), ('Nada', 'Nada')
]
PANAL_CHOICES = [('', 'Seleccione...')] + [(str(i), f"{i}ª vez") for i in range(1, 8)]
ACT_PEDAGOGICA_CHOICES = [
    ('', 'Seleccione...'), ('Participé', 'Participé'), ('No participe', 'No participe'),
    ('Interesado', 'Interesado'), ('Desinteresado', 'Desinteresado')
]
INCIDENCIA_TIPO_CHOICES = [
    ('', 'Seleccione...'), ('Médica', 'a) Médica'), ('Psicológica', 'b) Psicológica'),
    ('Conceptual/Pedagógica', 'c) Conceptual/Pedagógica'), ('Nutrición', 'd) Nutrición'),
    ('No hubo', 'e) No hubo ninguna incidencia.')
]
SI_NO_SIMPLE_CHOICES = [('', 'Seleccione...'), ('SI', 'Si'), ('NO', 'No')]


class BitacoraLactanteForm(forms.ModelForm):
    # Formulario de lactantes sin cambios para esta instrucción
    pass  # Este modelo se dejó intacto ya que la modificación fue pedida explícitamente para Maternal


# =========================================================
# BITÁCORA MATERNALES (ESTRUCTURA EXACTA REVISADA)
# =========================================================
class BitacoraMaternalForm(forms.ModelForm):
    # ==========================
    # DATOS GENERALES (Lectura)
    # ==========================
    fecha_str = forms.CharField(label="Fecha", required=False)
    nombre_completo_menor = forms.CharField(label="Nombre", required=False)
    sexo_str = forms.CharField(label="Sexo", required=False)
    edad_str = forms.CharField(label="Edad", required=False)
    fecha_nacimiento_str = forms.CharField(label="Fecha de nacimiento", required=False)

    # DATOS DE ENTRADA
    hora_entrada = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}), required=False,
                                   label="Hora de entrada")
    hora_salida = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}), required=False,
                                  label="Hora de salida")
    comentario_entrada = forms.CharField(widget=forms.Textarea(attrs={'rows': 2}), required=False,
                                         label="Comentario de entrada")

    # ==========================
    # EN CASA
    # ==========================
    desperte_hora = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}), required=False,
                                    label="Hoy desperté a las:")
    ultimo_alimento_hora = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}), required=False,
                                           label="Mi último alimento en casa fue a las:")

    # PAPILLA Y ALIMENTOS (NUEVA ESTRUCTURA EXACTA)
    papilla_casa = forms.ChoiceField(choices=SI_NO_SIMPLE_CHOICES, required=False, label="Papilla:")
    papilla_casa_cantidad = forms.CharField(required=False,
                                            widget=forms.TextInput(attrs={'placeholder': 'Ej. Medio plato'}))

    alimentos_completos_casa = forms.ChoiceField(choices=SI_NO_SIMPLE_CHOICES, required=False,
                                                 label="Alimentos completos:")
    alimentos_casa_especifique = forms.CharField(required=False,
                                                 widget=forms.TextInput(attrs={'placeholder': 'Ej. Huevo con jamón'}))
    alimentos_casa_cantidad = forms.CharField(required=False, widget=forms.TextInput(attrs={'placeholder': 'Ej. Todo'}))

    animo_casa = forms.MultipleChoiceField(
        choices=ESTADO_ANIMO_CHOICES, required=False, label="En casa estuve:",
        widget=forms.SelectMultiple(attrs={'class': 'form-select select2-multiple'})
    )

    # ==========================
    # DURANTE MI ESTANCIA EN LA EIU
    # ==========================
    animo_eiu = forms.MultipleChoiceField(
        choices=ESTADO_ANIMO_CHOICES, required=False, label="Hoy durante el día estuve:",
        widget=forms.SelectMultiple(attrs={'class': 'form-select select2-multiple'})
    )

    # LECHE DINÁMICA (RadioButtons con opción 0 "Ninguna")
    leche_cuantas = forms.ChoiceField(choices=RADIO_CUANTAS, required=False, widget=forms.RadioSelect,
                                      label="Tomé leche: ¿Cuántas?")
    leche_1_hora = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}), required=False,
                                   label="1ª vez, Hora:")
    leche_1_cant = forms.CharField(required=False, label="Cantidad:")
    leche_2_hora = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}), required=False,
                                   label="2ª vez, Hora:")
    leche_2_cant = forms.CharField(required=False, label="Cantidad:")
    leche_3_hora = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}), required=False,
                                   label="3ª vez, Hora:")
    leche_3_cant = forms.CharField(required=False, label="Cantidad:")

    # COMIDA
    comida_desayuno = forms.ChoiceField(choices=COMIDA_ACEPTACION_CHOICES, required=False, label="Desayuno:")
    comida_colacion = forms.ChoiceField(choices=COMIDA_ACEPTACION_CHOICES, required=False, label="Colación:")
    comida_comida = forms.ChoiceField(choices=COMIDA_ACEPTACION_CHOICES, required=False, label="Comida:")

    # SIESTAS DINÁMICAS (RadioButtons con opción 0 "Ninguna")
    siesta_cuantas = forms.ChoiceField(choices=RADIO_CUANTAS, required=False, widget=forms.RadioSelect,
                                       label="Tome mi siesta: ¿Cuántas?")
    siesta_1_de = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}), required=False, label="1ª De:")
    siesta_1_a = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}), required=False, label="A:")
    siesta_2_de = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}), required=False, label="2ª De:")
    siesta_2_a = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}), required=False, label="A:")
    siesta_3_de = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}), required=False, label="3ª De:")
    siesta_3_a = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}), required=False, label="A:")

    # CONTROL DE ESFÍNTERES (DUAL: Selector SI/NO y campo de texto para veces)
    aviso_pipi = forms.ChoiceField(choices=SI_NO_SIMPLE_CHOICES, required=False, label="Avise para hacer pipí:")
    aviso_pipi_veces = forms.IntegerField(min_value=0, required=False,
                                          widget=forms.NumberInput(attrs={'style': 'width: 80px; text-align: center;'}))

    aviso_popo = forms.ChoiceField(choices=SI_NO_SIMPLE_CHOICES, required=False, label="Avise para hacer popó:")
    aviso_popo_veces = forms.IntegerField(min_value=0, required=False,
                                          widget=forms.NumberInput(attrs={'style': 'width: 80px; text-align: center;'}))

    hizo_pipi = forms.ChoiceField(choices=SI_NO_SIMPLE_CHOICES, required=False, label="Hice pipí:")
    hizo_pipi_veces = forms.IntegerField(min_value=0, required=False,
                                         widget=forms.NumberInput(attrs={'style': 'width: 80px; text-align: center;'}))

    hizo_popo = forms.ChoiceField(choices=SI_NO_SIMPLE_CHOICES, required=False, label="Hice popó:")
    hizo_popo_veces = forms.IntegerField(min_value=0, required=False,
                                         widget=forms.NumberInput(attrs={'style': 'width: 80px; text-align: center;'}))

    # PEDAGÓGICA E INCIDENCIAS
    actividad_pedagogica = forms.ChoiceField(choices=ACT_PEDAGOGICA_CHOICES, required=False,
                                             label="En la actividad pedagógica:")
    hubo_incidencia = forms.ChoiceField(choices=SI_NO_SIMPLE_CHOICES, required=False,
                                        label="¿Hubo registro de alguna incidencia?")
    tipo_incidencia = forms.ChoiceField(choices=INCIDENCIA_TIPO_CHOICES, required=False,
                                        label="¿Qué tipo de incidencia fue?")

    comentarios_incidencias = forms.CharField(widget=forms.Textarea(
        attrs={'rows': 2, 'placeholder': 'Espacio libre para redactar. Es valido dejarlo en blanco...'}),
                                              required=False, label="Comentarios o incidencias:")
    anotaciones_internas = forms.CharField(widget=forms.Textarea(
        attrs={'rows': 2, 'placeholder': 'Espacio libre para redactar. Es valido dejarlo en blanco...'}),
                                           required=False, label="Anotaciones internas:")

    class Meta:
        model = BitacoraMaternal
        fields = ['estado', 'comentarios_coordinadora']
        widgets = {
            'estado': forms.Select(attrs={'class': 'form-select'}),
            'comentarios_coordinadora': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Observaciones de corrección...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name in ['animo_casa', 'animo_eiu']:
                pass
            elif isinstance(field.widget, forms.RadioSelect):
                pass  # Se renderiza a mano en el HTML para dar el estilo ( )
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = 'form-select'
            elif not isinstance(field.widget, forms.NumberInput):
                field.widget.attrs['class'] = 'form-control'
            else:
                field.widget.attrs['class'] = field.widget.attrs.get('class', '') + ' form-control'

        # IDs para control JavaScript
        self.fields['leche_cuantas'].widget.attrs['id'] = 'id_leche_cuantas'
        self.fields['siesta_cuantas'].widget.attrs['id'] = 'id_siesta_cuantas'
        self.fields['hubo_incidencia'].widget.attrs['id'] = 'id_hubo_incidencia'

        campos_bloqueados = ['fecha_str', 'nombre_completo_menor', 'sala_str', 'sexo_str', 'edad_str',
                             'fecha_nacimiento_str']
        for name in campos_bloqueados:
            if name in self.fields:
                self.fields[name].widget.attrs['readonly'] = 'readonly'
                self.fields[name].widget.attrs['style'] = 'background-color: #e9ecef; pointer-events: none;'
                self.fields[name].widget.attrs['tabindex'] = '-1'