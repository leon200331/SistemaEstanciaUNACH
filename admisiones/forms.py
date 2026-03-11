from django import forms
from datetime import date, timedelta
import re
from django.forms import Select, SelectMultiple

# Se unificaron las importaciones conflictivas aquí:
from .models import Solicitud, HistoriaClinicaMedica


class CapturaSolicitudForm(forms.ModelForm):
    class Meta:
        model = Solicitud
        fields = [
            # Tutor
            "nombres_tutor",
            "apellido_paterno_tutor",
            "apellido_materno_tutor",
            "matricula",
            "programa_educativo",
            "programa_educativo_otro",

            # ¡OJO AQUI! Se eliminó "unidad_academica" para que el papá no la sobreescriba y se borre.
            "correo",
            "celular",

            # --- NUEVOS CAMPOS DE DOMICILIO ---
            "estado_domicilio",
            "ciudad",
            "codigo_postal",
            "calle",
            "numero_exterior",
            "numero_interior",

            "parentesco",
            "parentesco_otro",

            # Menor (solo fecha y CURP)
            "fecha_nacimiento_menor",
            "curp_menor",
        ]
        widgets = {
            "nombres_tutor": forms.TextInput(attrs={"placeholder": "Ej. Juan Carlos"}),
            "apellido_paterno_tutor": forms.TextInput(attrs={"placeholder": "Ej. Pérez"}),
            "apellido_materno_tutor": forms.TextInput(attrs={"placeholder": "Ej. López"}),
            "matricula": forms.TextInput(attrs={"placeholder": "Ej. A123456"}),

            "programa_educativo": forms.Select(),
            "programa_educativo_otro": forms.TextInput(attrs={
                "placeholder": "Especifica el programa educativo"
            }),

            "correo": forms.EmailInput(attrs={
                "placeholder": "correo@ejemplo.com"
            }),

            "celular": forms.TextInput(attrs={
                "placeholder": "10 dígitos"
            }),

            # --- WIDGETS DOMICILIO ---
            "estado_domicilio": forms.TextInput(attrs={"placeholder": "Ej. Chiapas"}),
            "ciudad": forms.TextInput(attrs={"placeholder": "Ej. Tuxtla Gutiérrez"}),
            "codigo_postal": forms.TextInput(attrs={"placeholder": "Ej. 29000"}),
            "calle": forms.TextInput(attrs={"placeholder": "Ej. Av. Central"}),
            "numero_exterior": forms.TextInput(attrs={"placeholder": "Ej. 123"}),
            "numero_interior": forms.TextInput(attrs={"placeholder": "Ej. A (Opcional)"}),

            "parentesco": forms.Select(),
            "parentesco_otro": forms.TextInput(attrs={
                "placeholder": "Especifica el parentesco"
            }),

            "fecha_nacimiento_menor": forms.DateInput(attrs={
                "type": "date"
            }),

            "curp_menor": forms.TextInput(attrs={
                "placeholder": "18 caracteres"
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for _, field in self.fields.items():
            css = field.widget.attrs.get("class", "")

            if isinstance(field.widget, (Select, SelectMultiple)):
                base_class = "form-select w-100"
            else:
                base_class = "form-control w-100"

            field.widget.attrs["class"] = f"{css} {base_class}".strip()

        self.fields["nombres_tutor"].required = True
        self.fields["apellido_paterno_tutor"].required = True
        self.fields["parentesco"].required = True
        self.fields["fecha_nacimiento_menor"].required = True

        self.fields["estado_domicilio"].required = True
        self.fields["ciudad"].required = True
        self.fields["calle"].required = True

    def clean_nombres_tutor(self):
        v = (self.cleaned_data.get("nombres_tutor") or "").strip()
        if len(v) < 2:
            raise forms.ValidationError("Ingresa un nombre válido.")
        return v

    def clean_apellido_paterno_tutor(self):
        v = (self.cleaned_data.get("apellido_paterno_tutor") or "").strip()
        if len(v) < 2:
            raise forms.ValidationError("Ingresa un apellido paterno válido.")
        return v

    def clean_correo(self):
        correo = (self.cleaned_data.get("correo") or "").strip().lower()

        dominios_permitidos = [
            "@gmail.com",
            "@hotmail.com",
            "@outlook.com",
            "@unach.mx",
        ]

        if correo and ("@" not in correo):
            raise forms.ValidationError("El correo debe contener el símbolo @.")

        if correo and (not any(correo.endswith(d) for d in dominios_permitidos)):
            raise forms.ValidationError("El correo debe ser Gmail, Hotmail, Outlook o institucional UNACH.")

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
            raise forms.ValidationError("La CURP debe tener 18 caracteres (letras y números).")
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


# ======================================================
# FORMULARIO MODIFICADO PARA SOPORTAR "OTRA" UNIDAD
# ======================================================
class CrearSolicitudPanelForm(forms.Form):
    UNIDADES_CHOICES = [
        ("", "Seleccione una opción..."),
        ("Facultad de Ingeniería", "Facultad de Ingeniería"),
        ("Facultad de Arquitectura", "Facultad de Arquitectura"),
        ("Facultad de Contaduría y Administración", "Facultad de Contaduría y Administración"),
        ("Facultad de Humanidades", "Facultad de Humanidades"),
        ("Facultad de Medicina Humana", "Facultad de Medicina Humana"),
        ("Facultad de Medicina Veterinaria y Zootecnia", "Facultad de Medicina Veterinaria y Zootecnia"),
        ("Facultad de Ciencias Químicas", "Facultad de Ciencias Químicas"),
        ("Facultad de Derecho", "Facultad de Derecho"),
        ("Facultad de Lenguas", "Facultad de Lenguas"),
        ("Otra", "Otra"),
    ]

    nombres_tutor = forms.CharField(max_length=80, required=True)
    apellido_paterno_tutor = forms.CharField(max_length=60, required=True)
    apellido_materno_tutor = forms.CharField(max_length=60, required=False)
    matricula = forms.CharField(max_length=20, required=False)

    unidad_academica = forms.ChoiceField(choices=UNIDADES_CHOICES, required=True)

    # --- CAMPO NUEVO PARA "OTRA" (Marcadores de Git eliminados) ---
    unidad_academica_otra = forms.CharField(max_length=100, required=False)

    correo = forms.EmailField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for f in self.fields.values():
            f.widget.attrs["class"] = "form-control"

        self.fields["unidad_academica"].widget.attrs["class"] = "form-select"

        # Le ponemos un evento JavaScript al Select para detectar cuando cambie
        self.fields["unidad_academica"].widget.attrs["onchange"] = "mostrarOtraUnidad(this.value)"

        # Ocultamos la caja de "Otra" por defecto con la clase 'd-none' de Bootstrap
        self.fields["unidad_academica_otra"].widget.attrs["class"] = "form-control d-none mt-2"
        self.fields["unidad_academica_otra"].widget.attrs["placeholder"] = "Especifica la unidad académica"
        self.fields["unidad_academica_otra"].widget.attrs["id"] = "input_unidad_otra"

        self.fields["nombres_tutor"].widget.attrs["placeholder"] = "Ej. Juan Carlos"
        self.fields["apellido_paterno_tutor"].widget.attrs["placeholder"] = "Ej. Pérez"
        self.fields["apellido_materno_tutor"].widget.attrs["placeholder"] = "Ej. López"
        self.fields["matricula"].widget.attrs["placeholder"] = "Ej. A123456"
        self.fields["correo"].widget.attrs["placeholder"] = "Ej. correo@unach.mx"

    # --- NUEVA VALIDACIÓN: Si elige "Otra", debe escribir a fuerzas ---
    def clean(self):
        cleaned_data = super().clean()
        unidad = cleaned_data.get("unidad_academica")
        unidad_otra = cleaned_data.get("unidad_academica_otra")

        if unidad == "Otra" and not unidad_otra:
            self.add_error("unidad_academica_otra", "Por favor especifica la unidad académica.")
        return cleaned_data

    def _solo_letras(self, value, campo):
        value = (value or "").strip()
        if not value:
            return value
        if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+", value):
            raise forms.ValidationError(f"{campo}: solo letras y espacios (sin números ni caracteres especiales).")
        return value

    def clean_nombres_tutor(self):
        return self._solo_letras(self.cleaned_data.get("nombres_tutor"), "Nombre(s)")

    def clean_apellido_paterno_tutor(self):
        return self._solo_letras(self.cleaned_data.get("apellido_paterno_tutor"), "Apellido paterno")

    def clean_apellido_materno_tutor(self):
        return self._solo_letras(self.cleaned_data.get("apellido_materno_tutor"), "Apellido materno")


class SolicitudBasicaForm(forms.ModelForm):
    class Meta:
        model = Solicitud
        fields = ["nombres_tutor", "apellido_paterno_tutor", "apellido_materno_tutor", "matricula", "correo"]
        widgets = {
            "nombres_tutor": forms.TextInput(attrs={"class": "form-control w-100", "placeholder": "Nombre(s)"}),
            "apellido_paterno_tutor": forms.TextInput(
                attrs={"class": "form-control w-100", "placeholder": "Apellido paterno"}
            ),
            "apellido_materno_tutor": forms.TextInput(
                attrs={"class": "form-control w-100", "placeholder": "Apellido materno"}
            ),
            "matricula": forms.TextInput(attrs={"class": "form-control w-100", "placeholder": "Matrícula"}),
            "correo": forms.EmailInput(
                attrs={"class": "form-control w-100", "placeholder": "correo@ejemplo.com"}
            ),
        }


from django import forms
from .models import Solicitud

SI_NO_CHOICES = [
    ("", "Seleccione..."),
    ("SI", "Sí"),
    ("NO", "No"),
]

ESTADO_PSICOLOGIA_CHOICES = [
    ("PENDIENTE", "Pendiente"),
    ("APROBADO", "Aprobado"),
    ("RECHAZADO", "Rechazado"),
]

TIPO_NACIMIENTO_CHOICES = [
    ("", "Seleccione..."),
    ("PARTO", "Parto"),
    ("CESAREA", "Cesárea"),
]

METODO_ALIMENTACION_CHOICES = [
    ("", "Seleccione..."),
    ("LME", "LME"),
    ("LM", "LM"),
    ("SLM", "SLM"),
]

LENGUAJE_ACTUAL_CHOICES = [
    ("", "Seleccione..."),
    ("SILENCIOSO", "Silencioso"),
    ("EXPLICITO", "Explícito"),
    ("REPETITIVO", "Repetitivo"),
]

CONTROL_CHOICES = [
    ("", "Seleccione..."),
    ("SI", "Sí"),
    ("NO", "No"),
    ("EN_PROCESO", "En proceso"),
]

ADAPTACION_CHOICES = [
    ("", "Seleccione..."),
    ("SI", "Sí"),
    ("NO", "No"),
    ("A_VECES", "A veces"),
]

COMPARTE_CHOICES = [
    ("", "Seleccione..."),
    ("SI", "Sí"),
    ("NO", "No"),
    ("A_VECES", "A veces"),
]

CONDUCTA_LIDER_CHOICES = [
    ("", "Seleccione..."),
    ("SI", "Sí"),
    ("NO", "No"),
    ("OCASIONALMENTE", "Ocasionalmente"),
]


class DictamenPsicologiaForm(forms.ModelForm):

    class Meta:
        model = Solicitud
        fields = [
            "fecha_aplicacion_psicologia",
            "como_lo_llaman_en_casa",
            "edad_psicologia",
            "lugar_nacimiento_menor_psicologia",

            "nombre_padre_psicologia",
            "edad_padre_psicologia",
            "nacionalidad_padre_psicologia",
            "estado_civil_padre_psicologia",
            "religion_padre_psicologia",
            "ocupacion_padre_psicologia",
            "lugar_trabajo_padre_psicologia",
            "horario_trabajo_padre_psicologia",
            "escolaridad_padre_psicologia",
            "estudiante_padre_psicologia",
            "licenciatura_padre_psicologia",
            "semestre_padre_psicologia",

            "nombre_madre_psicologia",
            "edad_madre_psicologia",
            "nacionalidad_madre_psicologia",
            "estado_civil_madre_psicologia",
            "religion_madre_psicologia",
            "ocupacion_madre_psicologia",
            "lugar_trabajo_madre_psicologia",
            "horario_trabajo_madre_psicologia",
            "escolaridad_madre_psicologia",
            "estudiante_madre_psicologia",
            "licenciatura_madre_psicologia",
            "semestre_madre_psicologia",

            "numero_gesta_psicologia",
            "embarazo_planeado_psicologia",
            "dificultad_embarazo_psicologia",
            "estado_animo_madre_embarazo_psicologia",
            "momento_supieron_sexo_bebe_psicologia",
            "quien_eligio_nombre_bebe_psicologia",
            "motivo_nombre_bebe_psicologia",

            "tipo_nacimiento_psicologia",
            "semanas_gestacion_psicologia",
            "dificultad_nacimiento_psicologia",
            "peso_al_nacer_psicologia",
            "talla_al_nacer_psicologia",
            "apego_inmediato_psicologia",
            "metodo_alimentacion_inicio_psicologia",

            "edad_destete_psicologia",
            "motivo_destete_psicologia",

            "edad_balbuceo_psicologia",
            "edad_primera_palabra_psicologia",
            "lenguaje_actual_psicologia",
            "dificultad_lenguaje_psicologia",

            "edad_se_sento_solo_psicologia",
            "gateo_psicologia",
            "edad_gateo_psicologia",
            "edad_marcha_independiente_psicologia",
            "dominancia_manual_psicologia",

            "comportamiento_general_psicologia",
            "relacion_otros_ninos_psicologia",
            "apego_figura_familiar_psicologia",
            "apego_con_quien_psicologia",
            "se_viste_solo_psicologia",
            "se_pone_prendas_solo_psicologia",
            "cuales_prendas_se_pone_psicologia",
            "se_quita_prendas_solo_psicologia",
            "cuales_prendas_se_quita_psicologia",
            "intenta_banarse_solo_psicologia",
            "se_cepilla_dientes_solo_psicologia",
            "come_solo_psicologia",
            "toma_vaso_solo_psicologia",
            "iniciativa_para_jugar_psicologia",

            "realiza_siestas_psicologia",
            "cuantas_siestas_psicologia",
            "con_quien_duerme_psicologia",
            "hora_duerme_noche_psicologia",
            "hora_despierta_manana_psicologia",
            "necesita_algo_para_dormir_psicologia",
            "que_necesita_para_dormir_psicologia",
            "despierta_con_frecuencia_psicologia",

            "actividades_tarde_psicologia",
            "actividad_extra_tarde_psicologia",
            "juego_favorito_psicologia",
            "cancion_favorita_psicologia",
            "personaje_favorito_psicologia",
            "tiempo_pantallas_psicologia",
            "socializa_tardes_con_quien_psicologia",
            "lugar_para_jugar_psicologia",
            "comparte_juguetes_psicologia",
            "conducta_lider_juego_psicologia",
            "relacion_con_otros_ninos_detalle_psicologia",
            "se_adapta_nuevos_entornos_psicologia",
            "actividades_fin_semana_psicologia",

            "controla_orinar_psicologia",
            "controla_defecar_psicologia",
            "edad_comenzo_avisar_psicologia",
            "donde_realiza_necesidades_psicologia",
            "algo_significativo_control_esfinteres_psicologia",
            "duerme_con_panal_noche_psicologia",
            "reaccion_no_controla_esfinteres_psicologia",
            "que_hace_responsable_cuando_sucede_psicologia",

            "persona_aparte_padres_crianza_psicologia",
            "persona_aparte_padres_cuidado_psicologia",
            "periodos_cuidado_psicologia",
            "relacion_padre_madre_con_nino_psicologia",
            "tiempo_papa_dia_psicologia",
            "tiempo_mama_dia_psicologia",
            "metodo_mejorar_conducta_casa_psicologia",
            "dificultad_actual_hogar_entorno_psicologia",
            "beneficio_esperado_hijo_estancia_psicologia",
            "beneficio_personal_estancia_psicologia",

            "estado_psicologia",
            "observaciones_psicologia",
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

        for name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs["class"] = "form-control"
            elif isinstance(field.widget, forms.DateInput):
                field.widget.attrs["class"] = "form-control"
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            else:
                field.widget.attrs["class"] = "form-control"

from django import forms
from .models import Solicitud

SI_NO_CHOICES = [
    ("", "Seleccione"),
    ("SI", "Sí"),
    ("NO", "No"),
]

SEXO_CHOICES = [
    ("", "Seleccione"),
    ("FEMENINO", "Femenino"),
    ("MASCULINO", "Masculino"),
    ("OTRO", "Otro"),
]

TIPO_ALIMENTACION_CHOICES = [
    ("", "Seleccione"),
    ("SENO_MATERNO", "Seno materno"),
    ("FORMULA_LACTEA", "Fórmula láctea"),
    ("MIXTA", "Mixta"),
    ("OTRA", "Otra"),
]

PRESENTACION_LECHE_CHOICES = [
    ("", "Seleccione"),
    ("BIBERON", "Biberón"),
    ("VASO_ENTRENADOR", "Vaso entrenador"),
    ("OTRA", "Otra"),
]

FORMA_FORMULA_CHOICES = [
    ("", "Seleccione"),
    ("PORTA_BEBE", "Porta bebé"),
    ("EN_BRAZOS", "En brazos"),
    ("OTRO", "Otro"),
]

TIPO_COMPLICACION_CHOICES = [
    ("", "Seleccione"),
    ("INTOLERANCIA_LACTOSA", "Intolerancia a la lactosa"),
    ("REFLUJO", "Reflujo"),
    ("DIFICULTAD_SUCCIONAR", "Dificultad para succionar"),
    ("ALERGIAS", "Alergias"),
    ("DIFICULTAD_DEGLUTIR", "Dificultad para deglutir"),
    ("OTRA", "Otra"),
]

PRESENTACION_ALIMENTOS_CHOICES = [
    ("", "Seleccione"),
    ("PURE", "Puré"),
    ("MACHACADO", "Machacado"),
    ("PICADO_FINO", "Picado fino"),
    ("PICADO_EXTRA_FINO", "Picado extra fino"),
    ("EN_TROZOS", "En trozos"),
]

ORDEN_ALIMENTOS_CHOICES = [
    ("", "Seleccione"),
    ("LECHE_LUEGO_SOLIDOS", "Primero leche y después sólidos"),
    ("SOLIDOS_LUEGO_LECHE", "Primero sólidos y después leche"),
]

FRECUENCIA_SOLIDOS_CHOICES = [
    ("", "Seleccione"),
    ("1_VEZ", "1 vez"),
    ("2_VECES", "2 veces"),
    ("3_VECES", "3 veces"),
    ("MAS_DE_3", "Más de 3 veces"),
    ("CON_CADA_TOMA", "Con cada toma de fórmula infantil"),
]

DONDE_CONSUME_CHOICES = [
    ("", "Seleccione"),
    ("PORTA_BEBE", "Porta bebé"),
    ("SILLA_PERIQUERA", "Silla periquera"),
    ("SILLA_MESA", "Silla y mesa"),
    ("OTRO", "Otro"),
]

COMPANIA_CHOICES = [
    ("", "Seleccione"),
    ("FAMILIA", "En compañía de la familia"),
    ("SOLO", "Solo"),
    ("TELEVISION", "Televisión"),
    ("JUGUETES", "Juguetes"),
    ("OTRO", "Otro"),
]

COME_CON_CHOICES = [
    ("", "Seleccione"),
    ("MANOS", "Las manos"),
    ("CUCHARA", "Cuchara"),
    ("TENEDOR", "Tenedor"),
    ("CUCHILLO", "Cuchillo"),
]

BEBIDAS_EN_CHOICES = [
    ("", "Seleccione"),
    ("BIBERON", "Biberón"),
    ("VASO_ENTRENADOR", "Vaso entrenador"),
    ("VASO", "Vaso"),
    ("OTRO", "Otro"),
]

COME_SOLO_CHOICES = [
    ("", "Seleccione"),
    ("SOLO", "Solo"),
    ("CON_AYUDA", "Con ayuda"),
]

class DictamenNutricionForm(forms.ModelForm):
    class Meta:
        model = Solicitud
        fields = [
            "edad_nutricion",
            "sexo_nutricion",
            "fecha_nacimiento_nutricion",
            "peso_nacer",
            "talla_nacer",
            "peso_actual",
            "talla_actual",

            "seno_materno",
            "tiempo_seno_materno",
            "motivo_no_seno",
            "acude_lactancia",
            "tipo_alimentacion_lactante",
            "formula_infantil",
            "cual_formula",
            "edad_inicio_formula",
            "formula_especial",
            "cual_formula_especial",
            "causa_formula_especial",
            "cantidad_leche_formula",
            "cada_cuantas_horas_leche",
            "presentacion_leche",
            "presentacion_leche_otra",
            "forma_proporcionar_formula",
            "forma_proporcionar_formula_otra",

            "complicaciones_alimentacion",
            "tipo_complicacion",
            "tipo_complicacion_otra",
            "agrega_alimento_formula",
            "cual_agrega_formula",
            "edad_cambio_leche",
            "edad_inicio_alimentacion_complementaria",

            "orden_verduras",
            "orden_frutas",
            "orden_carnes",
            "orden_jugo_frutas",
            "orden_yema_huevo",
            "orden_huevo_entero",
            "orden_arroz",
            "orden_galleta_pan",
            "orden_pastas",
            "orden_leguminosas",
            "orden_citricos",

            "alergia_alimentos",
            "cual_alergia",
            "reaccion_alergia",
            "restriccion_alimentaria_actual",
            "detalle_restriccion_alimentaria",

            "presentacion_alimentos",
            "orden_alimentos",
            "frecuencia_solidos",

            "alimentos_agrado_frutas",
            "alimentos_agrado_verduras",
            "alimentos_agrado_cereales",
            "alimentos_agrado_leguminosas",
            "alimentos_agrado_aoa",
            "alimentos_agrado_lacteos",

            "consume_agua",
            "cantidad_agua",

            "desayuna",
            "hora_desayuno",
            "come",
            "hora_comida",
            "cena",
            "hora_cena",
            "colacion",
            "hora_colacion",

            "acostumbra_comer_desayuno",
            "acostumbra_comer_comida",
            "acostumbra_comer_cena",
            "acostumbra_comer_colaciones",

            "misma_alimentacion_familia",
            "detalle_misma_alimentacion",

            "consume_golosinas",
            "frecuencia_golosinas",
            "cuales_golosinas",

            "consume_refrescos",
            "frecuencia_refrescos",
            "cuales_refrescos",

            "consume_jugos",
            "frecuencia_jugos",
            "cuales_jugos",

            "donde_consume_alimentos",
            "donde_consume_alimentos_otro",
            "compania_comida",
            "compania_comida_otro",
            "come_con",
            "consume_bebidas_en",
            "consume_bebidas_en_otro",
            "come_solo_o_ayuda",

            "observaciones_nutricion_clinica",
            "fecha_elaboracion_nutricion",
            "estado_nutricion",
            "observaciones_nutricion",
        ]

        widgets = {
            "sexo_nutricion": forms.Select(choices=SEXO_CHOICES),
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
            "alimentos_agrado_frutas": forms.Textarea(attrs={"rows": 2}),
            "alimentos_agrado_verduras": forms.Textarea(attrs={"rows": 2}),
            "alimentos_agrado_cereales": forms.Textarea(attrs={"rows": 2}),
            "alimentos_agrado_leguminosas": forms.Textarea(attrs={"rows": 2}),
            "alimentos_agrado_aoa": forms.Textarea(attrs={"rows": 2}),
            "alimentos_agrado_lacteos": forms.Textarea(attrs={"rows": 2}),
        }

        labels = {
            "edad_nutricion": "Edad",
            "sexo_nutricion": "Sexo",
            "fecha_nacimiento_nutricion": "Fecha de nacimiento",
            "peso_nacer": "Peso al nacer",
            "talla_nacer": "Talla al nacer",
            "peso_actual": "Peso actual",
            "talla_actual": "Talla actual",
            "seno_materno": "¿El niño es o fue alimentado con seno materno?",
            "tiempo_seno_materno": "¿Cuánto tiempo?",
            "motivo_no_seno": "Si la respuesta es NO, indique por qué",
            "acude_lactancia": "¿Acudirá a la estancia para proporcionar lactancia materna?",
            "tipo_alimentacion_lactante": "Tipo de alimentación que le proporciona",
            "formula_infantil": "¿Le da fórmula infantil?",
            "cual_formula": "¿Cuál?",
            "edad_inicio_formula": "¿A partir de qué edad comenzó a darle fórmula?",
            "formula_especial": "¿Le proporciona o proporcionó fórmula especial?",
            "cual_formula_especial": "¿Cuál?",
            "causa_formula_especial": "¿Cuál fue la causa?",
            "cantidad_leche_formula": "¿Cuántas onzas/ml por toma?",
            "cada_cuantas_horas_leche": "¿Cada cuántas horas le proporciona leche/fórmula?",
            "presentacion_leche": "La leche/fórmula se la proporciona en",
            "presentacion_leche_otra": "Otra presentación",
            "forma_proporcionar_formula": "¿Cómo le proporciona fórmula láctea?",
            "forma_proporcionar_formula_otra": "Otra forma",
            "complicaciones_alimentacion": "¿Ha presentado complicaciones con la alimentación?",
            "tipo_complicacion": "Tipo de complicación",
            "tipo_complicacion_otra": "Otra complicación",
            "agrega_alimento_formula": "¿Agrega algún alimento en la preparación de la fórmula o leche?",
            "cual_agrega_formula": "¿Cuál?",
            "edad_cambio_leche": "Edad del cambio de leche entera o de transición",
            "edad_inicio_alimentacion_complementaria": "Edad de inicio de alimentación complementaria",
            "orden_verduras": "Verduras",
            "orden_frutas": "Frutas",
            "orden_carnes": "Carnes",
            "orden_jugo_frutas": "Jugo de frutas",
            "orden_yema_huevo": "Yema de huevo",
            "orden_huevo_entero": "Huevo entero",
            "orden_arroz": "Arroz",
            "orden_galleta_pan": "Galleta o pan",
            "orden_pastas": "Pastas",
            "orden_leguminosas": "Leguminosas",
            "orden_citricos": "Cítricos",
            "alergia_alimentos": "¿Presentó intolerancia/alergia a algún alimento?",
            "cual_alergia": "¿A cuál?",
            "reaccion_alergia": "¿Qué tipo de reacción tuvo?",
            "restriccion_alimentaria_actual": "¿Actualmente presenta alergia o restricción alimentaria?",
            "detalle_restriccion_alimentaria": "Especifique",
            "presentacion_alimentos": "¿En qué presentación le ofrece los alimentos?",
            "orden_alimentos": "¿En qué orden acostumbra proporcionar los alimentos?",
            "frecuencia_solidos": "¿Con qué frecuencia consume alimentos sólidos al día?",
            "alimentos_agrado_frutas": "Frutas del agrado",
            "alimentos_agrado_verduras": "Verduras del agrado",
            "alimentos_agrado_cereales": "Cereales del agrado",
            "alimentos_agrado_leguminosas": "Leguminosas del agrado",
            "alimentos_agrado_aoa": "AOA del agrado",
            "alimentos_agrado_lacteos": "Lácteos del agrado",
            "consume_agua": "¿Consume agua natural?",
            "cantidad_agua": "Cantidad",
            "desayuna": "¿Desayuna?",
            "hora_desayuno": "Hora desayuno",
            "come": "¿Come?",
            "hora_comida": "Hora comida",
            "cena": "¿Cena?",
            "hora_cena": "Hora cena",
            "colacion": "¿Colación?",
            "hora_colacion": "Hora colación",
            "acostumbra_comer_desayuno": "¿Qué acostumbra comer en desayuno?",
            "acostumbra_comer_comida": "¿Qué acostumbra comer en comida?",
            "acostumbra_comer_cena": "¿Qué acostumbra comer en cena?",
            "acostumbra_comer_colaciones": "¿Qué acostumbra comer en colaciones?",
            "misma_alimentacion_familia": "¿Consume la misma alimentación que la familia?",
            "detalle_misma_alimentacion": "Especifique",
            "consume_golosinas": "¿Consume golosinas?",
            "frecuencia_golosinas": "Frecuencia golosinas",
            "cuales_golosinas": "¿Cuáles?",
            "consume_refrescos": "¿Consume refrescos embotellados?",
            "frecuencia_refrescos": "Frecuencia refrescos",
            "cuales_refrescos": "¿Cuál?",
            "consume_jugos": "¿Consume jugos?",
            "frecuencia_jugos": "Frecuencia jugos",
            "cuales_jugos": "¿Cuál?",
            "donde_consume_alimentos": "¿Dónde consume sus alimentos?",
            "donde_consume_alimentos_otro": "Otro lugar",
            "compania_comida": "El niño come",
            "compania_comida_otro": "Otro contexto",
            "come_con": "Al momento de comer, come con",
            "consume_bebidas_en": "Consume las bebidas en",
            "consume_bebidas_en_otro": "Otro recipiente",
            "come_solo_o_ayuda": "El niño come",
            "observaciones_nutricion_clinica": "Observaciones clínicas",
            "fecha_elaboracion_nutricion": "Fecha de elaboración",
            "estado_nutricion": "Dictamen final",
            "observaciones_nutricion": "Observaciones finales del dictamen",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for _, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs["class"] = "form-control"
            else:
                field.widget.attrs["class"] = "form-control"


from django import forms
from .models import Solicitud, HistoriaClinicaMedica


SI_NO_CHOICES = [
    ("", "Seleccione"),
    ("si", "Sí"),
    ("no", "No"),
]

SEXO_CHOICES = [
    ("", "Seleccione"),
    ("Masculino", "Masculino"),
    ("Femenino", "Femenino"),
]

TIPO_PARTO_CHOICES = [
    ("", "Seleccione"),
    ("Eutócico", "Eutócico"),
    ("Distócico", "Distócico"),
    ("Cesárea", "Cesárea"),
]


class DictamenMedicoForm(forms.ModelForm):
    class Meta:
        model = Solicitud
        fields = ["pdf", "estado_medico", "observaciones_medico"]
        widgets = {
            "pdf": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": "application/pdf"
            }),
            "estado_medico": forms.Select(attrs={"class": "form-select"}),
            "observaciones_medico": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Escriba observaciones médicas relevantes..."
            }),
        }


class HistoriaClinicaMedicaForm(forms.ModelForm):
    sexo = forms.ChoiceField(
        choices=SEXO_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    tipo_parto = forms.ChoiceField(
        choices=TIPO_PARTO_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    tabaquismo_padre = forms.ChoiceField(
        choices=SI_NO_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )
    alcoholismo_padre = forms.ChoiceField(
        choices=SI_NO_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )
    drogas_padre = forms.ChoiceField(
        choices=SI_NO_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    tabaquismo_madre = forms.ChoiceField(
        choices=SI_NO_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )
    alcoholismo_madre = forms.ChoiceField(
        choices=SI_NO_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )
    drogas_madre = forms.ChoiceField(
        choices=SI_NO_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    class Meta:
        model = HistoriaClinicaMedica
        exclude = ["inscripcion", "created_at", "updated_at"]
        widgets = {
            "fecha_nacimiento": forms.DateInput(attrs={"type": "date", "class": "form-control"}),

            "nombre_paciente": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre completo del menor"}),
            "edad": forms.TextInput(attrs={"class": "form-control", "placeholder": "Edad"}),
            "lugar_fecha_elaboracion": forms.TextInput(attrs={"class": "form-control", "placeholder": "Lugar y fecha de elaboración"}),
            "religion": forms.TextInput(attrs={"class": "form-control", "placeholder": "Religión"}),
            "quien_cuida_menor": forms.TextInput(attrs={"class": "form-control", "placeholder": "Persona responsable del menor"}),

            "nombre_padre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre del padre"}),
            "edad_padre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Edad"}),
            "enfermedades_actuales_padre": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Describa enfermedades actuales"}),
            "alergias_padre": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Describa alergias"}),

            "nombre_madre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre de la madre"}),
            "edad_madre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Edad"}),
            "enfermedades_actuales_madre": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Describa enfermedades actuales"}),
            "enfermedades_infancia_madre": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Describa enfermedades de la infancia"}),
            "alergias_madre": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Describa alergias"}),

            "numero_gestas": forms.TextInput(attrs={"class": "form-control", "placeholder": "Número de gestas"}),
            "complicaciones_embarazo": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Complicaciones durante el embarazo"}),
            "medicamentos_embarazo": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Medicamentos o vitaminas durante el embarazo"}),
            "exposicion_radiacion": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Exposición a radiación"}),
            "sufrimiento_fetal": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Sufrimiento fetal"}),
            "semanas_gestacion": forms.TextInput(attrs={"class": "form-control", "placeholder": "Semanas de gestación"}),
            "motivo_cesarea": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Motivo de cesárea"}),

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

            "diagnostico": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Diagnóstico médico"}),
            "pronostico": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Pronóstico"}),
            "elaborado_por": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre del médico"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            self.initial["tabaquismo_padre"] = "si" if self.instance.tabaquismo_padre else "no"
            self.initial["alcoholismo_padre"] = "si" if self.instance.alcoholismo_padre else "no"
            self.initial["drogas_padre"] = "si" if self.instance.drogas_padre else "no"
            self.initial["tabaquismo_madre"] = "si" if self.instance.tabaquismo_madre else "no"
            self.initial["alcoholismo_madre"] = "si" if self.instance.alcoholismo_madre else "no"
            self.initial["drogas_madre"] = "si" if self.instance.drogas_madre else "no"

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

        instance.tabaquismo_padre = self.cleaned_data.get("tabaquismo_padre") == "si"
        instance.alcoholismo_padre = self.cleaned_data.get("alcoholismo_padre") == "si"
        instance.drogas_padre = self.cleaned_data.get("drogas_padre") == "si"

        instance.tabaquismo_madre = self.cleaned_data.get("tabaquismo_madre") == "si"
        instance.alcoholismo_madre = self.cleaned_data.get("alcoholismo_madre") == "si"
        instance.drogas_madre = self.cleaned_data.get("drogas_madre") == "si"

        if commit:
            instance.save()
        return instance