from django import forms
from datetime import date, timedelta
import re
from django.forms import Select, SelectMultiple

from .models import Solicitud


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
            "unidad_academica",
            "correo",
            "celular",
            "domicilio",
            "parentesco",
            "parentesco_otro",

            # Menor
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

            "unidad_academica": forms.TextInput(attrs={
                "placeholder": "Ej. Facultad de Ingeniería"
            }),

            "correo": forms.EmailInput(attrs={
                "placeholder": "correo@ejemplo.com"
            }),

            "celular": forms.TextInput(attrs={
                "placeholder": "10 dígitos"
            }),

            "domicilio": forms.TextInput(attrs={
                "placeholder": "Calle, número, colonia, ciudad"
            }),

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

    # ======================================================
    # BOOTSTRAP 5 (inputs y selects bien formateados)
    # ======================================================
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            css = field.widget.attrs.get("class", "")

            if isinstance(field.widget, (Select, SelectMultiple)):
                base_class = "form-select w-100"
            else:
                base_class = "form-control w-100"

            field.widget.attrs["class"] = f"{css} {base_class}".strip()

        # Campos obligatorios explícitos
        self.fields["nombres_tutor"].required = True
        self.fields["apellido_paterno_tutor"].required = True
        self.fields["parentesco"].required = True
        self.fields["fecha_nacimiento_menor"].required = True

    # ======================================================
    # VALIDACIONES POR CAMPO
    # ======================================================
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

        # Dominios permitidos
        dominios_permitidos = [
            "@gmail.com",
            "@hotmail.com",
            "@outlook.com",
            "@unach.mx",  # si quieres permitir institucional
        ]

        if "@" not in correo:
            raise forms.ValidationError(
                "El correo debe contener el símbolo @."
            )

        if not any(correo.endswith(d) for d in dominios_permitidos):
            raise forms.ValidationError(
                "El correo debe ser Gmail, Hotmail, Outlook o institucional UNACH."
            )

        return correo

    def clean_celular(self):
        cel = (self.cleaned_data.get("celular") or "").strip()
        if cel and not re.fullmatch(r"\d{10}", cel):
            raise forms.ValidationError(
                "El celular debe tener exactamente 10 dígitos."
            )
        return cel

    def clean_domicilio(self):
        dom = (self.cleaned_data.get("domicilio") or "").strip()
        if dom and len(dom) < 8:
            raise forms.ValidationError(
                "El domicilio es demasiado corto."
            )
        return dom

    def clean_curp_menor(self):
        curp = (self.cleaned_data.get("curp_menor") or "").strip().upper()
        if curp and not re.fullmatch(r"[A-Z0-9]{18}", curp):
            raise forms.ValidationError(
                "La CURP debe tener 18 caracteres (letras y números)."
            )
        return curp

    # ======================================================
    # VALIDACIONES GENERALES (dependen de varios campos)
    # ======================================================
    def clean(self):
        cleaned_data = super().clean()

        # Programa educativo = OTRO
        programa = cleaned_data.get("programa_educativo")
        programa_otro = (cleaned_data.get("programa_educativo_otro") or "").strip()
        if programa == "OTRO" and not programa_otro:
            self.add_error(
                "programa_educativo_otro",
                "Especifica el programa educativo."
            )

        # Parentesco = OTRO
        parentesco = cleaned_data.get("parentesco")
        parentesco_otro = (cleaned_data.get("parentesco_otro") or "").strip()
        if parentesco == "OTRO" and not parentesco_otro:
            self.add_error(
                "parentesco_otro",
                "Especifica el parentesco."
            )

        # Fecha nacimiento del menor (6 meses a 3 años)
        fecha = cleaned_data.get("fecha_nacimiento_menor")
        if fecha:
            hoy = date.today()
            min_fecha = hoy - timedelta(days=365 * 3)
            max_fecha = hoy - timedelta(days=30 * 6)

            if fecha < min_fecha or fecha > max_fecha:
                self.add_error(
                    "fecha_nacimiento_menor",
                    "La edad del menor debe estar entre 6 meses y 3 años."
                )

        def clean_nombres_tutor(self):
            nombre = (self.cleaned_data.get("nombres_tutor") or "").strip()

            if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+", nombre):
                raise forms.ValidationError(
                    "El nombre solo debe contener letras."
                )

            if len(nombre) < 2:
                raise forms.ValidationError(
                    "Ingresa un nombre válido."
                )

            return nombre

        def clean_apellido_paterno_tutor(self):
            apellido = (self.cleaned_data.get("apellido_paterno_tutor") or "").strip()

            if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+", apellido):
                raise forms.ValidationError(
                    "El apellido solo debe contener letras."
                )

            if len(apellido) < 2:
                raise forms.ValidationError(
                    "Ingresa un apellido válido."
                )

            return apellido

        def clean_apellido_materno_tutor(self):
            apellido = (self.cleaned_data.get("apellido_materno_tutor") or "").strip()

            if apellido and not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+", apellido):
                raise forms.ValidationError(
                    "El apellido solo debe contener letras."
                )

            return apellido

        return cleaned_data


class CrearSolicitudPanelForm(forms.Form):
    nombres_tutor = forms.CharField(max_length=80, required=True)
    apellido_paterno_tutor = forms.CharField(max_length=60, required=True)
    apellido_materno_tutor = forms.CharField(max_length=60, required=False)
    matricula = forms.CharField(max_length=20, required=False)
    correo = forms.EmailField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs["class"] = "form-control"

        self.fields["nombres_tutor"].widget.attrs["placeholder"] = "Ej. Juan Carlos"
        self.fields["apellido_paterno_tutor"].widget.attrs["placeholder"] = "Ej. Pérez"
        self.fields["apellido_materno_tutor"].widget.attrs["placeholder"] = "Ej. López"
        self.fields["matricula"].widget.attrs["placeholder"] = "Ej. A123456"
        self.fields["correo"].widget.attrs["placeholder"] = "Ej. correo@unach.mx"

    def _solo_letras(self, value, campo):
        value = (value or "").strip()
        if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+", value):
            raise forms.ValidationError(f"{campo}: solo letras y espacios (sin números ni caracteres especiales).")
        return value

    def clean_nombres_tutor(self):
        return self._solo_letras(self.cleaned_data.get("nombres_tutor"), "Nombre(s)")

    def clean_apellido_paterno_tutor(self):
        return self._solo_letras(self.cleaned_data.get("apellido_paterno_tutor"), "Apellido paterno")

    def clean_apellido_materno_tutor(self):
        val = (self.cleaned_data.get("apellido_materno_tutor") or "").strip()
        if not val:
            return val
        return self._solo_letras(val, "Apellido materno")

    class SolicitudBasicaForm(forms.ModelForm):
        class Meta:
            model = Solicitud
            fields = ["nombres_tutor", "apellido_paterno_tutor", "apellido_materno_tutor", "matricula", "correo"]
            widgets = {
                "nombres_tutor": forms.TextInput(attrs={"class": "form-control w-100", "placeholder": "Nombre(s)"}),
                "apellido_paterno_tutor": forms.TextInput(
                    attrs={"class": "form-control w-100", "placeholder": "Apellido paterno"}),
                "apellido_materno_tutor": forms.TextInput(
                    attrs={"class": "form-control w-100", "placeholder": "Apellido materno"}),
                "matricula": forms.TextInput(attrs={"class": "form-control w-100", "placeholder": "Matrícula"}),
                "correo": forms.EmailInput(attrs={"class": "form-control w-100", "placeholder": "correo@ejemplo.com"}),
            }


