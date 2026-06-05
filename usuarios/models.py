from django.db import models
from django.contrib.auth.models import AbstractUser, Group
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator


class Usuario(AbstractUser):
    # =========================================================
    # 1. VALIDADORES ESTRICTOS (Condiciones de Seguridad)
    # =========================================================
    letras_validator = RegexValidator(
        regex=r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ\s]+$',
        message='Solo se permiten letras y espacios. No se aceptan números ni símbolos.'
    )

    curp_validator = RegexValidator(
        regex=r'^[A-Za-z0-9]{18}$',
        message='La CURP debe contener exactamente 18 caracteres (letras y números), sin símbolos ni espacios.'
    )

    numeros_validator = RegexValidator(
        regex=r'^\d+$',
        message='Este campo solo acepta números. No se permiten letras ni símbolos.'
    )

    # =========================================================
    # 2. DATOS DE ACCESO
    # =========================================================
    # Se redefine el correo para que sea único desde el modelo.
    # El username se seguirá llenando automáticamente con el correo en save().
    email = models.EmailField(
        unique=True,
        verbose_name='Correo electrónico',
        error_messages={
            'unique': 'Ya existe un usuario registrado con este correo electrónico.'
        }
    )

    # =========================================================
    # 3. ESTRUCTURA DE LA PERSONA (Reglas de Negocio)
    # =========================================================
    nombre = models.CharField(
        max_length=50,
        validators=[letras_validator],
        verbose_name='Nombre(s)',
        null=True,
        blank=True
    )

    apellido_paterno = models.CharField(
        max_length=50,
        validators=[letras_validator],
        verbose_name='Apellido Paterno',
        null=True,
        blank=True
    )

    apellido_materno = models.CharField(
        max_length=50,
        validators=[letras_validator],
        verbose_name='Apellido Materno',
        null=True,
        blank=True
    )

    curp = models.CharField(
        max_length=18,
        unique=True,
        validators=[curp_validator],
        verbose_name='CURP',
        null=True,
        blank=True,
        error_messages={
            'unique': 'Ya existe un usuario registrado con esta CURP.'
        }
    )

    numero_empleado = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        null=True,
        validators=[numeros_validator],
        verbose_name='No. Empleado',
        error_messages={
            'unique': 'Ya existe un usuario registrado con este número de empleado.'
        }
    )

    # =========================================================
    # 4. TIPOS DE PERSONA / ROLES BASE DEL SISTEMA
    # =========================================================
    TIPO_PERSONAL = 'PERSONAL'
    TIPO_SUPERVISOR = 'SUPERVISOR'
    TIPO_ADMIN = 'ADMIN'
    TIPO_BENEFICIARIO = 'BENEFICIARIO'
    TIPO_ALUMNO = 'ALUMNO'

    TIPO_CHOICES = [
        (TIPO_PERSONAL, '1. Personal de la estancia'),
        # Este rol corresponde a la Secretaria de Dirección / Supervisora General.
        # Es solo consulta: verá el avance general de la estancia, pero no modificará registros.
        (TIPO_SUPERVISOR, '2. Supervisora General'),
        (TIPO_ADMIN, '3. Administrador de Sistema'),
        (TIPO_BENEFICIARIO, '4. Beneficiario (Padre/Tutor)'),
        (TIPO_ALUMNO, '5. Alumno'),
    ]

    tipo_persona = models.CharField(
        max_length=20,
        choices=TIPO_CHOICES,
        verbose_name='Tipo de Persona'
    )

    estatus_operativo = models.BooleanField(
        default=True,
        verbose_name='¿Está Activo?'
    )

    telefono = models.CharField(
        max_length=15,
        blank=True,
        null=True
    )

    direccion = models.TextField(
        blank=True,
        null=True
    )

    # =========================================================
    # 5. ÁREA OPERATIVA DEL PERSONAL
    # =========================================================
    # Este campo sirve para el pase de lista, suplencias y permisos temporales.
    # NO reemplaza los grupos de Django, solo ayuda a identificar el área real
    # de trabajo dentro de la estancia.
    AREA_DIRECCION = 'DIRECCION'
    AREA_MEDICA = 'MEDICA'
    AREA_NUTRICION = 'NUTRICION'
    AREA_PSICOLOGIA = 'PSICOLOGIA'
    AREA_PEDAGOGICA = 'PEDAGOGICA'
    AREA_TRABAJO_SOCIAL = 'TRABAJO_SOCIAL'
    AREA_MAESTRA = 'MAESTRA'
    AREA_OTRA = 'OTRA'

    AREA_OPERATIVA_CHOICES = [
        (AREA_DIRECCION, 'Dirección'),
        (AREA_MEDICA, 'Médica'),
        (AREA_NUTRICION, 'Nutrición'),
        (AREA_PSICOLOGIA, 'Psicología'),
        (AREA_PEDAGOGICA, 'Pedagógica'),
        (AREA_TRABAJO_SOCIAL, 'Trabajo Social'),
        (AREA_MAESTRA, 'Maestra / Asistente de sala'),
        (AREA_OTRA, 'Otra área'),
    ]

    # Áreas que sí participan en suplencias.
    # Aquí NO se incluye supervisora, administrador, beneficiario ni alumno.
    AREAS_PERMITIDAS_SUPLENCIA = [
        AREA_DIRECCION,
        AREA_MEDICA,
        AREA_NUTRICION,
        AREA_PSICOLOGIA,
        AREA_PEDAGOGICA,
        AREA_TRABAJO_SOCIAL,
    ]

    # Áreas que aparecen en el pase de lista como personal operativo.
    # Dirección registra el pase de lista, por eso no se considera como titular ausente normal.
    AREAS_PASE_LISTA = [
        AREA_MEDICA,
        AREA_NUTRICION,
        AREA_PSICOLOGIA,
        AREA_PEDAGOGICA,
        AREA_TRABAJO_SOCIAL,
    ]

    area_operativa = models.CharField(
        max_length=30,
        choices=AREA_OPERATIVA_CHOICES,
        blank=True,
        null=True,
        verbose_name='Área operativa',
        help_text='Área interna del personal. Se usa para pase de lista y suplencias.'
    )

    # =========================================================
    # 6. PROPIEDADES DE APOYO
    # =========================================================
    @property
    def nombre_completo(self):
        """
        Devuelve el nombre completo del usuario sin mostrar valores None.
        """
        partes = [
            self.nombre or '',
            self.apellido_paterno or '',
            self.apellido_materno or '',
        ]
        return ' '.join(parte.strip() for parte in partes if parte and parte.strip()).strip()

    @property
    def nombre_visible(self):
        """
        Devuelve un nombre seguro para mostrar en paneles, tablas y bitácoras.
        """
        return self.nombre_completo or self.email or self.username

    @property
    def es_supervisora_general(self):
        """
        Identifica al perfil de Supervisora General.
        Este perfil es solo consulta y NO debe aparecer como suplente.
        """
        return self.tipo_persona == self.TIPO_SUPERVISOR

    @property
    def es_administrador_sistema(self):
        """
        Identifica al Administrador del Sistema.
        Este perfil NO debe aparecer en pase de lista ni suplencias.
        """
        return self.tipo_persona == self.TIPO_ADMIN

    @property
    def es_beneficiario(self):
        """
        Identifica al beneficiario, padre, madre o tutor.
        Este perfil NO participa en suplencias.
        """
        return self.tipo_persona == self.TIPO_BENEFICIARIO

    @property
    def es_alumno(self):
        """
        Identifica al alumno.
        Este perfil NO participa en suplencias.
        """
        return self.tipo_persona == self.TIPO_ALUMNO

    @property
    def es_personal_estancia(self):
        """
        Personal interno de la estancia.
        """
        return self.tipo_persona == self.TIPO_PERSONAL

    @property
    def es_directora(self):
        """
        Identifica a la Directora.

        Se usa area_operativa como fuente principal.
        También se revisa el grupo por compatibilidad con usuarios ya existentes.
        """
        if self.tipo_persona != self.TIPO_PERSONAL:
            return False

        if self.area_operativa == self.AREA_DIRECCION:
            return True

        return self._pertenece_a_grupo_con_texto('directora', 'direccion', 'dirección')

    @property
    def es_medica(self):
        return self.tipo_persona == self.TIPO_PERSONAL and self.area_operativa == self.AREA_MEDICA

    @property
    def es_nutriologa(self):
        return self.tipo_persona == self.TIPO_PERSONAL and self.area_operativa == self.AREA_NUTRICION

    @property
    def es_psicologa(self):
        return self.tipo_persona == self.TIPO_PERSONAL and self.area_operativa == self.AREA_PSICOLOGIA

    @property
    def es_pedagogica(self):
        return self.tipo_persona == self.TIPO_PERSONAL and self.area_operativa == self.AREA_PEDAGOGICA

    @property
    def es_trabajadora_social(self):
        return self.tipo_persona == self.TIPO_PERSONAL and self.area_operativa == self.AREA_TRABAJO_SOCIAL


    @property
    def es_maestra(self):
        """
        Identifica a maestra o asistente de sala.

        Este rol NO participa en suplencias de filtros, Trabajo Social o Dirección.
        Su apoyo se manejará con el módulo separado ApoyoSalaMaestra.
        """
        if self.tipo_persona != self.TIPO_PERSONAL:
            return False

        if self.area_operativa == self.AREA_MAESTRA:
            return True

        return self._pertenece_a_grupo_con_texto('maestra', 'asistente', 'sala')

    @property
    def puede_iniciar_apoyo_sala(self):
        """
        Define si una persona puede iniciar apoyo temporal en otra sala.
        Solo aplica para maestras o asistentes de sala activas.
        """
        return (
            self.tipo_persona == self.TIPO_PERSONAL
            and self.estatus_operativo
            and self.area_operativa == self.AREA_MAESTRA
        )

    @property
    def puede_aparecer_en_pase_lista(self):
        """
        Define qué personal aparece en el pase de lista diario.

        Solo aparecen:
        - Médica
        - Nutrióloga
        - Psicóloga
        - Pedagógica
        - Trabajadora Social

        No aparecen:
        - Directora
        - Supervisora
        - Administrador
        - Beneficiarios
        - Alumnos
        """
        return (
            self.tipo_persona == self.TIPO_PERSONAL
            and self.estatus_operativo
            and self.area_operativa in self.AREAS_PASE_LISTA
        )

    @property
    def puede_ser_suplente(self):
        """
        Define quién puede ser elegido como suplente.

        Sí pueden:
        - Directora
        - Médica
        - Nutrióloga
        - Psicóloga
        - Pedagógica
        - Trabajadora Social

        No pueden:
        - Supervisora
        - Administrador
        - Beneficiario
        - Alumno
        - Maestras, salvo que después se decida incluirlas
        """
        return (
            self.tipo_persona == self.TIPO_PERSONAL
            and self.estatus_operativo
            and self.area_operativa in self.AREAS_PERMITIDAS_SUPLENCIA
        )

    @property
    def puede_ser_titular_ausente(self):
        """
        Define quién puede marcarse como titular ausente para activar una suplencia.

        No se incluye Dirección porque la Directora es quien autoriza.
        """
        return (
            self.tipo_persona == self.TIPO_PERSONAL
            and self.estatus_operativo
            and self.area_operativa in self.AREAS_PASE_LISTA
        )

    @property
    def nombre_area_operativa(self):
        """
        Devuelve el nombre legible del área operativa.
        """
        if not self.area_operativa:
            return 'Sin área asignada'
        return self.get_area_operativa_display()

    def _pertenece_a_grupo_con_texto(self, *textos):
        """
        Busca coincidencias simples en los nombres de grupos.
        Sirve como respaldo para proyectos donde los roles ya estaban
        controlados por Group antes de agregar area_operativa.
        """
        if not self.pk:
            return False

        textos_normalizados = [texto.lower().strip() for texto in textos if texto]

        for grupo in self.groups.all():
            nombre_grupo = grupo.name.lower().strip()
            for texto in textos_normalizados:
                if texto in nombre_grupo:
                    return True

        return False

    # =========================================================
    # 7. MÉTODOS DE CONSULTA PARA SUPLENCIAS
    # =========================================================
    @classmethod
    def personal_para_pase_lista(cls):
        """
        Devuelve el personal que debe aparecer en el pase de lista diario.
        """
        return cls.objects.filter(
            tipo_persona=cls.TIPO_PERSONAL,
            estatus_operativo=True,
            area_operativa__in=cls.AREAS_PASE_LISTA
        ).order_by('area_operativa', 'apellido_paterno', 'apellido_materno', 'nombre')

    @classmethod
    def personal_para_suplencias(cls):
        """
        Devuelve el personal que puede ser seleccionado como suplente.
        Aquí se incluye Dirección y las áreas operativas permitidas.
        """
        return cls.objects.filter(
            tipo_persona=cls.TIPO_PERSONAL,
            estatus_operativo=True,
            area_operativa__in=cls.AREAS_PERMITIDAS_SUPLENCIA
        ).order_by('area_operativa', 'apellido_paterno', 'apellido_materno', 'nombre')

    @classmethod
    def titulares_para_suplencia(cls):
        """
        Devuelve el personal que puede ser marcado como titular ausente.
        """
        return cls.objects.filter(
            tipo_persona=cls.TIPO_PERSONAL,
            estatus_operativo=True,
            area_operativa__in=cls.AREAS_PASE_LISTA
        ).order_by('area_operativa', 'apellido_paterno', 'apellido_materno', 'nombre')


    @classmethod
    def maestras_para_apoyo_sala(cls):
        """
        Devuelve maestras/asistentes activas que pueden iniciar apoyo temporal de sala.
        """
        return cls.objects.filter(
            tipo_persona=cls.TIPO_PERSONAL,
            estatus_operativo=True,
            area_operativa=cls.AREA_MAESTRA,
        ).order_by('apellido_paterno', 'apellido_materno', 'nombre')

    # =========================================================
    # 8. VALIDACIONES ADICIONALES
    # =========================================================
    def clean(self):
        """
        Refuerza la validación para evitar duplicados con diferencias
        de mayúsculas/minúsculas. Esto ayuda especialmente con el correo,
        la CURP y el número de empleado.
        """
        super().clean()

        if self.email:
            self.email = self.email.lower().strip()
            existe_email = Usuario.objects.filter(email__iexact=self.email)
            if self.pk:
                existe_email = existe_email.exclude(pk=self.pk)
            if existe_email.exists():
                raise ValidationError({
                    'email': 'Ya existe un usuario registrado con este correo electrónico.'
                })

        if self.curp:
            self.curp = self.curp.upper().strip()
            existe_curp = Usuario.objects.filter(curp__iexact=self.curp)
            if self.pk:
                existe_curp = existe_curp.exclude(pk=self.pk)
            if existe_curp.exists():
                raise ValidationError({
                    'curp': 'Ya existe un usuario registrado con esta CURP.'
                })

        if self.numero_empleado:
            self.numero_empleado = self.numero_empleado.strip()
            existe_numero = Usuario.objects.filter(numero_empleado=self.numero_empleado)
            if self.pk:
                existe_numero = existe_numero.exclude(pk=self.pk)
            if existe_numero.exists():
                raise ValidationError({
                    'numero_empleado': 'Ya existe un usuario registrado con este número de empleado.'
                })

        # El área operativa solo aplica para PERSONAL de la estancia.
        # Supervisora, administrador, beneficiario y alumno no deben tener área operativa.
        if self.tipo_persona != self.TIPO_PERSONAL and self.area_operativa:
            raise ValidationError({
                'area_operativa': 'El área operativa solo aplica para personal de la estancia.'
            })

    # =========================================================
    # 9. NORMALIZACIÓN ANTES DE GUARDAR
    # =========================================================
    def save(self, *args, **kwargs):
        if self.nombre:
            self.nombre = self.nombre.title().strip()
            self.first_name = self.nombre

        if self.apellido_paterno:
            self.apellido_paterno = self.apellido_paterno.title().strip()

        if self.apellido_materno:
            self.apellido_materno = self.apellido_materno.title().strip()

        if self.apellido_paterno or self.apellido_materno:
            self.last_name = f"{self.apellido_paterno or ''} {self.apellido_materno or ''}".strip()

        if self.curp:
            self.curp = self.curp.upper().strip()

        if self.numero_empleado:
            self.numero_empleado = self.numero_empleado.strip()

        if self.email:
            self.email = self.email.lower().strip()
            self.username = self.email

        if self.area_operativa:
            self.area_operativa = self.area_operativa.strip().upper()

        # Seguridad adicional:
        # Si no es PERSONAL, no debe conservar área operativa.
        # Así se evita que supervisora, admin, beneficiarios o alumnos aparezcan en suplencias.
        if self.tipo_persona != self.TIPO_PERSONAL:
            self.area_operativa = None

        super().save(*args, **kwargs)

    class Meta:
        verbose_name = 'Usuario'
        verbose_name_plural = 'Usuarios'

    def __str__(self):
        nombre_visible = self.nombre_completo or self.email or self.username

        if self.tipo_persona == self.TIPO_PERSONAL and self.area_operativa:
            return f"{nombre_visible} - {self.get_area_operativa_display()}"

        return f"{nombre_visible} - {self.get_tipo_persona_display()}"


# --- MODELO: AUDITORÍA DE SEGURIDAD ---
class AccessLog(models.Model):
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE
    )

    fecha_acceso = models.DateTimeField(
        auto_now_add=True
    )

    accion = models.CharField(
        max_length=255,
        default="Ingreso al sistema"
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True
    )

    class Meta:
        verbose_name = 'Registro de Acceso'
        verbose_name_plural = 'Registros de Acceso'
        ordering = ['-fecha_acceso']

    def __str__(self):
        usuario = self.usuario.nombre_completo or self.usuario.email or self.usuario.username
        return f"Log: {usuario} - {self.fecha_acceso}"


# --- MODELO: PERMISOS CRUZADOS ---
class RelacionDepartamentos(models.Model):
    rol_origen = models.ForeignKey(
        Group,
        related_name='permisos_otorgados',
        on_delete=models.CASCADE,
        verbose_name='Rol que entra (Origen)'
    )

    rol_destino = models.ForeignKey(
        Group,
        related_name='permisos_recibidos',
        on_delete=models.CASCADE,
        verbose_name='Módulo a visitar (Destino)'
    )

    puede_consultar = models.BooleanField(
        default=False,
        verbose_name='Solo Consultar'
    )

    puede_validar = models.BooleanField(
        default=False,
        verbose_name='Validar / Aprobar'
    )

    puede_observar = models.BooleanField(
        default=False,
        verbose_name='Hacer Observaciones'
    )

    puede_descargar = models.BooleanField(
        default=False,
        verbose_name='Descargar Copias'
    )

    class Meta:
        unique_together = ('rol_origen', 'rol_destino')
        verbose_name = 'Relación de Departamento'
        verbose_name_plural = 'Relaciones de Departamentos'

    def __str__(self):
        return f"{self.rol_origen.name} -> {self.rol_destino.name}"


# =================================================================
# MODELO PARA EL PUNTO 25: ASIGNACIÓN DE ROL POR CICLO
# =================================================================
class AsignacionRolCiclo(models.Model):
    """
    Guarda qué rol tiene un empleado en un semestre específico.
    """
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name='roles_por_ciclo'
    )

    rol = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        verbose_name='Rol Oficial'
    )

    # Apuntamos a Semestre que está en la otra app (admisiones).
    semestre = models.ForeignKey(
        'admisiones.Semestre',
        on_delete=models.CASCADE,
        verbose_name='Ciclo Escolar'
    )

    fecha_asignacion = models.DateTimeField(
        auto_now_add=True
    )

    # --- CAMPOS PARA LAS ASISTENTES DE SALAS (MAESTRAS) ---
    sala = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        verbose_name='Sala Asignada'
    )

    tipo_bitacora = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name='Tipo de Bitácora'
    )  # LACTANTE o MATERNAL

    class Meta:
        # Un usuario solo puede tener UN rol principal en un mismo semestre.
        unique_together = ('usuario', 'semestre')
        verbose_name = 'Asignación de Rol por Ciclo'
        verbose_name_plural = 'Asignaciones de Roles por Ciclo'

    def __str__(self):
        usuario = self.usuario.nombre_completo or self.usuario.email or self.usuario.username

        # Muestra la sala en el panel de admin si es que tiene una asignada.
        if self.sala:
            return f"{usuario} como {self.rol.name} (Sala: {self.sala}) en {self.semestre.nombre}"

        return f"{usuario} como {self.rol.name} en {self.semestre.nombre}"