def pais_actual(request):
    return {
        'pais_codigo': getattr(request, 'pais_codigo', 'CO'),
        'pais_nombre': getattr(request, 'pais_nombre', 'Colombia'),
    }