from django import forms
from datetime import date, timedelta
import re
import secrets
from django.forms import Select, SelectMultiple, RadioSelect
from django.utils import timezone
from django.contrib.auth import get_user_model

# Se unificaron las importaciones conflictivas aquí:
from .models import (
    Solicitud,
    SolicitudInscripcion,
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


class CapturaSolicitudForm(forms.ModelForm):
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
        correo = (self.cleaned_data.get("correo") or "").strip().lower()
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
    correo = forms.EmailField(required=False)

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
        correo = (self.cleaned_data.get("correo") or "").strip().lower()
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


# IMPORTANTE:
# Los datos de identidad del menor NO se editan desde Psicología.
# Se muestran en el HTML desde la Solicitud original y se protegen en views.py.
# Por eso no se incluyen en fields de este ModelForm.
class DictamenPsicologiaForm(forms.ModelForm):
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
class DictamenNutricionForm(forms.ModelForm):
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

        campos_bloqueados = ["nombres_menor", "apellido_paterno_menor", "apellido_materno_menor", "edad_nutricion",
                             "sexo_nutricion", "fecha_nacimiento_nutricion", "peso_nacer", "talla_nacer"]

        for name, field in self.fields.items():
            existing_class = field.widget.attrs.get("class", "")
            if isinstance(field.widget, forms.SelectMultiple):
                if "form-select" not in existing_class: field.widget.attrs[
                    "class"] = f"form-select {existing_class}".strip()
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs["class"] = "form-control"
                field.widget.attrs.setdefault("rows", 2)
            else:
                field.widget.attrs["class"] = "form-control"

            if name in campos_bloqueados:
                field.widget.attrs["readonly"] = "readonly"
                field.widget.attrs["style"] = "background-color: #e9ecef; pointer-events: none;"
                if isinstance(field.widget, forms.Select): field.widget.attrs["tabindex"] = "-1"


TIPO_PARTO_CHOICES = [("", "Seleccione"), ("Eutócico", "Eutócico"), ("Distócico", "Distócico"), ("Cesárea", "Cesárea")]
SEXO_CHOICES = [("", "Seleccione"), ("Masculino", "Masculino"), ("Femenino", "Femenino")]


# IMPORTANTE:
# Los datos de identidad del menor NO se editan desde Médico.
# Se muestran en el HTML desde la Solicitud original y se protegen en views.py.
# Por eso no se incluyen en fields de este ModelForm.
class DictamenMedicoForm(forms.ModelForm):
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

        if isinstance(field.widget, forms.CheckboxInput):
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


class SedeForm(forms.ModelForm):
    class Meta:
        model = Sede
        fields = [
            "clave",
            "nombre",
            "direccion",
            "telefono",
            "correo",
            "activa",
        ]
        widgets = {
            "clave": forms.TextInput(attrs={"placeholder": "Ej. TUXTLA"}),
            "nombre": forms.TextInput(attrs={"placeholder": "Ej. Estancia Infantil Universitaria Tuxtla"}),
            "direccion": forms.TextInput(attrs={"placeholder": "Dirección de la sede"}),
            "telefono": forms.TextInput(attrs={"placeholder": "Teléfono de contacto"}),
            "correo": forms.EmailInput(attrs={"placeholder": "correo@unach.mx"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)

    def clean_clave(self):
        clave = (self.cleaned_data.get("clave") or "").strip().upper()
        clave = re.sub(r"[^A-Z0-9_-]+", "_", clave)
        if not clave:
            raise forms.ValidationError("Captura la clave de la sede.")
        return clave


class SemestreForm(forms.ModelForm):
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

        return cleaned


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
        aplicar_clases_bootstrap(self)

    def clean_fecha(self):
        fecha = self.cleaned_data.get("fecha")

        if self.semestre and fecha:
            if fecha < self.semestre.fecha_inicio or fecha > self.semestre.fecha_fin:
                raise forms.ValidationError("La fecha debe estar dentro del periodo del semestre.")

        return fecha

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.semestre:
            obj.semestre = self.semestre
        if commit:
            obj.save()
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
            self.fields["sede"].required = False

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
            "actividad_pedagogica_personal",
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
            "actividad_pedagogica_personal": forms.TextInput(attrs={"placeholder": "Personal asignado"}),
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


class IncidenciaForm(forms.ModelForm):
    """
    Crea una incidencia del Sprint 5.

    Reglas:
    - La maestra no crea incidencias.
    - Coordinadora de Sala crea Pedagógica.
    - Nutrióloga crea Nutricional.
    - Médica crea Médica.
    - Psicóloga crea Psicológica.
    - Puede adjuntar archivos.
    - Se conecta con alumno, sala, semestre, día operativo y registro diario.
    """
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
            "accept": ".pdf,.jpg,.jpeg,.png,.doc,.docx"
        })
    )

    sintomas_medicos = forms.MultipleChoiceField(
        required=False,
        choices=SINTOMAS_MEDICOS_CHOICES,
        label="Síntomas / signos observados",
        widget=forms.SelectMultiple(attrs={"class": "form-select select2-multiple"})
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
            "alumno": forms.Select(),
            "registro_diario": forms.Select(),
            "tipo": forms.Select(),
            "subtipo": forms.TextInput(attrs={
                "placeholder": "Detalle opcional. Ej. Tos y fiebre / dificultad en actividad / alimento específico"
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

        self.fields["alumno"].queryset = alumnos.order_by(
            "solicitud_ingreso__apellido_paterno_menor",
            "solicitud_ingreso__nombres_menor"
        )
        self.fields["registro_diario"].queryset = registros
        self.fields["registro_diario"].required = False

        if self.registro_diario_inicial:
            self.fields["registro_diario"].initial = self.registro_diario_inicial
            self.fields["alumno"].initial = self.registro_diario_inicial.alumno

        tipo_actual = self.tipo_forzado or self.data.get("tipo") or self.initial.get("tipo") or getattr(self.instance, "tipo", "")

        if self.tipo_forzado:
            self.fields["tipo"].initial = self.tipo_forzado
            self.fields["tipo"].disabled = True

        self.fields["categoria"].choices = [("", "Seleccione...")] + INCIDENCIA_CATEGORIAS.get(tipo_actual, [])

        aplicar_clases_bootstrap(self)

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

    def clean(self):
        cleaned = super().clean()

        if self.tipo_forzado:
            cleaned["tipo"] = self.tipo_forzado

        registro_diario = cleaned.get("registro_diario")
        alumno = cleaned.get("alumno")

        if registro_diario and alumno and registro_diario.alumno_id != alumno.id:
            self.add_error("registro_diario", "El registro diario seleccionado no pertenece al alumno.")

        if registro_diario and registro_diario.dia_operativo and registro_diario.dia_operativo.semestre.estado == Semestre.EstadoSemestre.CERRADO:
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

        if tipo == "MEDICA" and categoria == "DIARREA":
            if cleaned.get("numero_evacuaciones") is None:
                self.add_error("numero_evacuaciones", "Captura el número de evacuaciones.")
            if not cleaned.get("consistencia_evacuacion"):
                self.add_error("consistencia_evacuacion", "Selecciona la consistencia.")

        if tipo == "NUTRICIONAL" and categoria in ["REACCION_ALERGICA", "INTOLERANCIA"] and not cleaned.get("alimento_relacionado"):
            self.add_error("alimento_relacionado", "Captura el alimento relacionado.")

        if tipo == "PSICOLOGICA" and not cleaned.get("conducta_observada"):
            self.add_error("conducta_observada", "Describe la conducta observada.")

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
            "consistencia_evacuacion": self.cleaned_data.get("consistencia_evacuacion") or "",
            "numero_evacuaciones": self.cleaned_data.get("numero_evacuaciones"),
            "alimento_relacionado": self.cleaned_data.get("alimento_relacionado") or "",
            "conducta_observada": self.cleaned_data.get("conducta_observada") or "",
            "contexto_observacion": self.cleaned_data.get("contexto_observacion") or "",
        }

        obj.datos_extra = datos_extra

        if commit:
            obj.save()

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
            "accept": ".pdf,.jpg,.jpeg,.png,.doc,.docx"
        })
    )

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

    def clean(self):
        cleaned = super().clean()

        if not self.incidencia:
            raise forms.ValidationError("No se encontró la incidencia.")

        if self.incidencia.estado == Incidencia.EstadoIncidencia.CERRADA:
            raise forms.ValidationError("No se puede agregar seguimiento a una incidencia cerrada.")

        if self.usuario and not self.incidencia.puede_agregar_seguimiento(self.usuario):
            raise forms.ValidationError("Solo la persona que creó la incidencia puede registrar seguimiento.")

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)

        if self.incidencia:
            obj.incidencia = self.incidencia

        if self.usuario:
            obj.creado_por = self.usuario

        if commit:
            obj.save()

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
    Formulario para envío de Encuesta de satisfacción B.
    La lógica de envío por correo se hará en views.py.
    """
    fecha_envio = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Fecha de envío"
    )
    correo_copia = forms.EmailField(
        required=True,
        label="Correo genérico en copia",
        widget=forms.EmailInput(attrs={"placeholder": "correo.generico@unach.mx"})
    )
    confirmar_envio = forms.BooleanField(
        required=True,
        label="Confirmo que deseo enviar la encuesta de satisfacción B"
    )

    def __init__(self, *args, **kwargs):
        semestre = kwargs.pop("semestre", None)
        super().__init__(*args, **kwargs)

        if semestre:
            self.fields["correo_copia"].initial = semestre.correo_copia_encuesta
            self.fields["fecha_envio"].initial = timezone.localdate()

        aplicar_clases_bootstrap(self)


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


class GenerarCodigoResponsableForm(forms.Form):
    """
    Trabajo Social genera o resetea el código de seguridad del responsable.

    Reglas:
    - Solo después de inscripción finalizada.
    - Solo después de pago validado.
    - Recomendado cuando ya tiene semestre y sala asignados.
    - Si ya existe código, se debe usar reset y capturar motivo.
    """
    confirmar = forms.BooleanField(
        required=True,
        label="Confirmo que deseo generar el código de seguridad del responsable"
    )
    motivo = forms.CharField(
        required=False,
        label="Motivo",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Ej. Código generado al finalizar inscripción / código extraviado por el responsable."
        })
    )

    def __init__(self, *args, **kwargs):
        self.alumno = kwargs.pop("alumno", None)
        self.es_reset = kwargs.pop("es_reset", False)
        super().__init__(*args, **kwargs)

        if self.es_reset:
            self.fields["confirmar"].label = "Confirmo que deseo resetear y generar un nuevo código"
            self.fields["motivo"].required = True
            self.fields["motivo"].label = "Motivo del reseteo"
            self.fields["motivo"].widget.attrs["placeholder"] = (
                "Describe por qué se genera un nuevo código. Ej. El responsable lo extravió."
            )
        else:
            self.fields["motivo"].label = "Observaciones de entrega"
            self.fields["motivo"].widget.attrs["placeholder"] = (
                "Opcional. Ej. Código entregado junto con credencial al responsable."
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
            pago_validado = bool(alumno.pago_validado)
        except Exception:
            pago_validado = False

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

        codigo_existente = bool(getattr(alumno, "codigo_responsable_hash", ""))

        if codigo_existente and not self.es_reset:
            raise forms.ValidationError(
                "Este alumno ya tiene un código generado. Si necesita otro, usa la opción de resetear código."
            )

        return cleaned

    def generar_codigo(self):
        return generar_codigo_responsable_seguro()


class ConfirmarEntregaCodigoResponsableForm(forms.Form):
    """
    Confirmación documental de que Trabajo Social entregó el código y la credencial.
    Este formulario es útil si deseas separar la generación del acto de entrega.
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
        required=True,
        max_length=180,
        label="Nombre del responsable que recibe",
        widget=forms.TextInput(attrs={
            "placeholder": "Nombre completo del responsable"
        })
    )
    parentesco = forms.ChoiceField(
        required=True,
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

        if len(nombre) < 5:
            raise forms.ValidationError("Captura el nombre completo del responsable.")

        if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s.]+", nombre):
            raise forms.ValidationError("El nombre solo debe contener letras y espacios.")

        return nombre.title()



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
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)


class RegistroEntradaAlumnoForm(forms.ModelForm):
    """
    Entrada del menor.
    Valida responsable, credencial y código de 4 dígitos.
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
                "placeholder": "Nombre completo del adulto que entrega al menor"
            }),
            "responsable_entrada_parentesco": forms.Select(choices=RESPONSABLE_PARENTESCO_CHOICES),
            "responsable_entrada_telefono": forms.TextInput(attrs={
                "placeholder": "Teléfono del responsable",
                "inputmode": "numeric"
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

        aplicar_clases_bootstrap(self)

    def clean_responsable_entrada_nombre(self):
        nombre = (self.cleaned_data.get("responsable_entrada_nombre") or "").strip()
        if len(nombre) < 5:
            raise forms.ValidationError("Captura el nombre completo del adulto responsable.")
        return nombre.title()

    def clean_responsable_entrada_telefono(self):
        telefono = (self.cleaned_data.get("responsable_entrada_telefono") or "").strip()
        if telefono and not re.fullmatch(r"\d{10}", telefono):
            raise forms.ValidationError("El teléfono debe tener 10 dígitos.")
        return telefono

    def clean_codigo_responsable(self):
        codigo = (self.cleaned_data.get("codigo_responsable") or "").strip()

        if not re.fullmatch(r"\d{4}", codigo):
            raise forms.ValidationError("El código debe tener exactamente 4 dígitos.")

        registro = self.registro_diario or self.instance

        if registro and registro.alumno_id:
            if not getattr(registro.alumno, "codigo_responsable_hash", ""):
                raise forms.ValidationError(
                    "Este alumno aún no tiene código de seguridad generado por Trabajo Social."
                )

            if not registro.alumno.validar_codigo_responsable(codigo):
                raise forms.ValidationError("El código de seguridad no coincide con el registrado.")

        return codigo

    def clean(self):
        cleaned = super().clean()

        if not cleaned.get("credencial_entrada_validada"):
            self.add_error("credencial_entrada_validada", "Debes confirmar que la credencial fue verificada.")

        temperatura = cleaned.get("temperatura_entrada")
        if temperatura is not None and (temperatura < 30 or temperatura > 45):
            self.add_error("temperatura_entrada", "La temperatura debe estar entre 30.0 y 45.0 °C.")

        return cleaned


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
    Valida responsable, credencial y código de 4 dígitos.
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
                "placeholder": "Nombre completo del adulto que recoge al menor"
            }),
            "responsable_salida_parentesco": forms.Select(choices=RESPONSABLE_PARENTESCO_CHOICES),
            "responsable_salida_telefono": forms.TextInput(attrs={
                "placeholder": "Teléfono del responsable",
                "inputmode": "numeric"
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

        aplicar_clases_bootstrap(self)

    def clean_responsable_salida_nombre(self):
        nombre = (self.cleaned_data.get("responsable_salida_nombre") or "").strip()
        if len(nombre) < 5:
            raise forms.ValidationError("Captura el nombre completo del adulto responsable.")
        return nombre.title()

    def clean_responsable_salida_telefono(self):
        telefono = (self.cleaned_data.get("responsable_salida_telefono") or "").strip()
        if telefono and not re.fullmatch(r"\d{10}", telefono):
            raise forms.ValidationError("El teléfono debe tener 10 dígitos.")
        return telefono

    def clean_codigo_responsable(self):
        codigo = (self.cleaned_data.get("codigo_responsable") or "").strip()

        if not re.fullmatch(r"\d{4}", codigo):
            raise forms.ValidationError("El código debe tener exactamente 4 dígitos.")

        registro = self.registro_diario or self.instance

        if registro and registro.alumno_id:
            if not getattr(registro.alumno, "codigo_responsable_hash", ""):
                raise forms.ValidationError(
                    "Este alumno aún no tiene código de seguridad generado por Trabajo Social."
                )

            if not registro.alumno.validar_codigo_responsable(codigo):
                raise forms.ValidationError("El código de seguridad no coincide con el registrado.")

        return codigo

    def clean(self):
        cleaned = super().clean()

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
        super().__init__(*args, **kwargs)
        aplicar_clases_bootstrap(self)



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