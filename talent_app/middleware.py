import requests
from django.conf import settings


class PaisMiddleware:
    """
    Detecta el país del visitante por IP y lo guarda en la sesión.
    Si ya está guardado, no hace una nueva llamada a la API.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if 'pais_codigo' not in request.session:
            codigo = self._detectar_pais(request)
            request.session['pais_codigo'] = codigo
            request.session['pais_nombre'] = self._nombre_pais(codigo)

        request.pais_codigo = request.session.get('pais_codigo', settings.PAIS_DEFAULT)
        request.pais_nombre = request.session.get('pais_nombre', 'Colombia')
        return self.get_response(request)

    def _detectar_pais(self, request):
        ip = self._get_ip(request)
        if ip in ('127.0.0.1', 'localhost', '::1'):
            return settings.PAIS_DEFAULT
        try:
            url = settings.IPAPI_URL.format(ip=ip)
            resp = requests.get(url, timeout=2)
            data = resp.json()
            return data.get('country_code', settings.PAIS_DEFAULT)
        except Exception:
            return settings.PAIS_DEFAULT

    def _get_ip(self, request):
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        if xff:
            return xff.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '127.0.0.1')

    def _nombre_pais(self, codigo):
        nombres = {
            'CO': 'Colombia',
            'MX': 'México',
            'AR': 'Argentina',
            'CL': 'Chile',
            'PE': 'Perú',
            'ES': 'España',
            'US': 'Estados Unidos',
            'BR': 'Brasil',
        }
        return nombres.get(codigo, codigo)