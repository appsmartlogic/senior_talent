from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone


# ──────────────────────────────────────────
# USUARIO BASE
# ──────────────────────────────────────────

class UsuarioManager(BaseUserManager):
    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError('El email es obligatorio')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra)


class Usuario(AbstractBaseUser, PermissionsMixin):
    TIPO_CANDIDATO = 'candidato'
    TIPO_EMPRESA   = 'empresa'
    TIPOS = [(TIPO_CANDIDATO, 'Candidato'), (TIPO_EMPRESA, 'Empresa')]

    email       = models.EmailField(unique=True)
    tipo        = models.CharField(max_length=10, choices=TIPOS)
    is_active   = models.BooleanField(default=True)
    is_staff    = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD  = 'email'
    REQUIRED_FIELDS = []
    objects = UsuarioManager()

    class Meta:
        verbose_name = 'usuario'

    def __str__(self):
        return self.email


# ──────────────────────────────────────────
# CATÁLOGOS
# ──────────────────────────────────────────

class Pais(models.Model):
    codigo               = models.CharField(max_length=2, unique=True)
    nombre               = models.CharField(max_length=100)
    moneda               = models.CharField(max_length=3, default='USD')
    num_tributario_label = models.CharField(max_length=20, default='NIT')
    zona_horaria        = models.CharField(max_length=50, default='America/Bogota', help_text='Ejemplo: America/Bogota, America/Mexico_City, Europe/Madrid')
    activo               = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        self.moneda = self.moneda.upper()
        self.codigo = self.codigo.upper()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name_plural = 'países'
        ordering = ['nombre']

    def __str__(self):
        return f'{self.nombre} ({self.codigo})'


class Sector(models.Model):
    nombre = models.CharField(max_length=100)
    slug   = models.SlugField(unique=True)

    def __str__(self):
        return self.nombre


# ──────────────────────────────────────────
# CANDIDATO
# ──────────────────────────────────────────

class Candidato(models.Model):
    ESTADO_PENDIENTE = 'pendiente'
    ESTADO_APROBADO  = 'aprobado'
    ESTADO_RECHAZADO = 'rechazado'
    ESTADOS = [
        (ESTADO_PENDIENTE, 'Pendiente de revisión'),
        (ESTADO_APROBADO,  'Aprobado'),
        (ESTADO_RECHAZADO, 'Rechazado'),
    ]

    DISPONIBILIDAD_INMEDIATA = 'inmediata'
    DISPONIBILIDAD_MES       = '1_mes'
    DISPONIBILIDAD_FREELANCE = 'freelance'
    DISPONIBILIDADES = [
        (DISPONIBILIDAD_INMEDIATA, 'Disponible ahora'),
        (DISPONIBILIDAD_MES,       'En 1 mes'),
        (DISPONIBILIDAD_FREELANCE, 'Solo freelance'),
    ]

    MODALIDAD_PRESENCIAL = 'presencial'
    MODALIDAD_REMOTO     = 'remoto'
    MODALIDAD_HIBRIDO    = 'hibrido'
    MODALIDADES = [
        (MODALIDAD_PRESENCIAL, 'Presencial'),
        (MODALIDAD_REMOTO,     'Remoto'),
        (MODALIDAD_HIBRIDO,    'Híbrido'),
    ]

    usuario          = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='candidato')
    nombre           = models.CharField(max_length=200)
    pais             = models.ForeignKey(Pais, on_delete=models.PROTECT)
    ciudad           = models.CharField(max_length=100)
    cargo_actual     = models.CharField(max_length=200)
    años_experiencia = models.PositiveSmallIntegerField(default=0)
    resumen          = models.TextField(blank=True)
    sectores         = models.ManyToManyField(Sector, blank=True)
    habilidades      = models.JSONField(default=list)
    disponibilidad   = models.CharField(max_length=20, choices=DISPONIBILIDADES, default=DISPONIBILIDAD_INMEDIATA)
    modalidad        = models.CharField(max_length=20, choices=MODALIDADES, default=MODALIDAD_HIBRIDO)
    foto             = models.ImageField(upload_to='fotos/', blank=True, null=True)
    estado           = models.CharField(max_length=15, choices=ESTADOS, default=ESTADO_PENDIENTE)
    nota_rechazo     = models.TextField(blank=True)
    creado_en        = models.DateTimeField(auto_now_add=True)
    actualizado_en   = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-creado_en']

    def __str__(self):
        return f'{self.nombre} — {self.cargo_actual}'

    @property
    def aprobado(self):
        return self.estado == self.ESTADO_APROBADO

    def iniciales(self):
        partes = self.nombre.strip().split()
        return ''.join(p[0] for p in partes if p).upper()


class ExperienciaLaboral(models.Model):
    candidato   = models.ForeignKey(Candidato, on_delete=models.CASCADE, related_name='experiencias')
    empresa     = models.CharField(max_length=200)
    cargo       = models.CharField(max_length=200)
    año_inicio  = models.PositiveSmallIntegerField()
    año_fin     = models.PositiveSmallIntegerField(null=True, blank=True)
    descripcion = models.TextField(blank=True)
    orden       = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['orden', '-año_inicio']

    def __str__(self):
        fin = self.año_fin or 'actualidad'
        return f'{self.cargo} en {self.empresa} ({self.año_inicio}–{fin})'


class Educacion(models.Model):
    candidato   = models.ForeignKey(Candidato, on_delete=models.CASCADE, related_name='educaciones')
    titulo      = models.CharField(max_length=200)
    institucion = models.CharField(max_length=200)
    año_fin     = models.PositiveSmallIntegerField(null=True, blank=True)
    orden       = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['orden', '-año_fin']

    def __str__(self):
        return f'{self.titulo} — {self.institucion}'


class IdiomaCandiato(models.Model):
    NIVEL_NATIVO     = 'nativo'
    NIVEL_AVANZADO   = 'avanzado'
    NIVEL_INTERMEDIO = 'intermedio'
    NIVEL_BASICO     = 'basico'
    NIVELES = [
        (NIVEL_NATIVO,     'Nativo'),
        (NIVEL_AVANZADO,   'Avanzado (C1–C2)'),
        (NIVEL_INTERMEDIO, 'Intermedio (B1–B2)'),
        (NIVEL_BASICO,     'Básico (A1–A2)'),
    ]

    candidato = models.ForeignKey(Candidato, on_delete=models.CASCADE, related_name='idiomas')
    idioma    = models.CharField(max_length=50)
    nivel     = models.CharField(max_length=15, choices=NIVELES)

    def __str__(self):
        return f'{self.idioma} — {self.get_nivel_display()}'


# ──────────────────────────────────────────
# EMPRESA
# ──────────────────────────────────────────

EMAILS_BLOQUEADOS = ['gmail.com', 'hotmail.com', 'yahoo.com', 'outlook.com', 'icloud.com']


class Empresa(models.Model):
    ESTADO_PENDIENTE = 'pendiente'
    ESTADO_ACTIVA    = 'activa'
    ESTADO_BLOQUEADA = 'bloqueada'
    ESTADOS = [
        (ESTADO_PENDIENTE, 'Pendiente de verificación'),
        (ESTADO_ACTIVA,    'Activa'),
        (ESTADO_BLOQUEADA, 'Bloqueada'),
    ]

    usuario            = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='empresa')
    nombre             = models.CharField(max_length=200)
    pais               = models.ForeignKey(Pais, on_delete=models.PROTECT)
    num_tributario     = models.CharField(max_length=50)
    estado             = models.CharField(max_length=15, choices=ESTADOS, default=ESTADO_PENDIENTE)
    stripe_customer_id = models.CharField(max_length=100, blank=True)
    creado_en          = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre

    @property
    def activa(self):
        return self.estado == self.ESTADO_ACTIVA


# ──────────────────────────────────────────
# DESCARGA DE CV
# ──────────────────────────────────────────

class DescargaCV(models.Model):
    ESTADO_PENDIENTE = 'pendiente'
    ESTADO_PAGADO    = 'pagado'
    ESTADO_FALLIDO   = 'fallido'
    ESTADOS = [
        (ESTADO_PENDIENTE, 'Pendiente de pago'),
        (ESTADO_PAGADO,    'Pagado'),
        (ESTADO_FALLIDO,   'Fallido'),
    ]

    empresa            = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name='descargas')
    candidato          = models.ForeignKey(Candidato, on_delete=models.PROTECT, related_name='descargas')
    stripe_payment_id  = models.CharField(max_length=200, blank=True)
    stripe_session_id  = models.CharField(max_length=200, blank=True)
    monto_usd = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name='Monto')
    estado             = models.CharField(max_length=15, choices=ESTADOS, default=ESTADO_PENDIENTE)
    creado_en          = models.DateTimeField(auto_now_add=True)
    pagado_en          = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ['empresa', 'candidato']
        ordering = ['-creado_en']

    def __str__(self):
        return f'{self.empresa} → {self.candidato} [{self.estado}]'

    @property
    def pagado(self):
        return self.estado == self.ESTADO_PAGADO
    

class PasarelaPago(models.Model):
    STRIPE      = 'stripe'
    WOMPI       = 'wompi'
    MERCADOPAGO = 'mercadopago'
    PAYPAL      = 'paypal'
    PAYU        = 'payु'
    PASARELAS = [
        (STRIPE,      'Stripe'),
        (WOMPI,       'Wompi'),
        (MERCADOPAGO, 'MercadoPago'),
        (PAYPAL,      'PayPal'),
        (PAYU,        'PayU'),
    ]

    pais            = models.OneToOneField(Pais, on_delete=models.CASCADE, related_name='pasarela')
    pasarela        = models.CharField(max_length=20, choices=PASARELAS, default=STRIPE)
    public_key      = models.CharField(max_length=500, blank=True)
    secret_key      = models.CharField(max_length=500, blank=True)
    webhook_secret  = models.CharField(max_length=500, blank=True)
    moneda          = models.CharField(max_length=3, default='USD')
    precio_cv       = models.PositiveIntegerField(default=1, help_text='Indique monto en la moneda local)')    
    activa          = models.BooleanField(default=True)
    notas           = models.TextField(blank=True, help_text='Notas internas sobre esta configuración')
    creado_en       = models.DateTimeField(auto_now_add=True)
    actualizado_en  = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.moneda = self.moneda.upper()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = 'Pasarela de pago'
        verbose_name_plural = 'Pasarelas de pago'

    def __str__(self):
        return f'{self.pais.nombre} — {self.get_pasarela_display()}'