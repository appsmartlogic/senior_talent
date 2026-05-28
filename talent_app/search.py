"""
Lógica de construcción del campo texto_busqueda del Candidato.
Este archivo es independiente — se puede borrar sin romper nada
que ya funcione, solo deja de mantenerse texto_busqueda actualizado.

Filosofía:
- Funciones puras donde sea posible
- try/except defensivo en el punto de entrada
- Sin llamadas a IA (esto es solo manipulación de texto)
- Sin consultas extra a la base de datos: usa lo que ya está cargado
"""
import logging
import unicodedata

logger = logging.getLogger('talent_app')


def _normalizar(texto):
    """Quita tildes, baja a minúsculas, colapsa espacios."""
    if not texto:
        return ''
    texto = str(texto).lower().strip()
    # Quitar tildes y caracteres combinantes
    nfd = unicodedata.normalize('NFD', texto)
    sin_tildes = ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')
    # Colapsar espacios múltiples
    return ' '.join(sin_tildes.split())


def construir_texto_busqueda(candidato):
    """
    Construye el texto unificado de búsqueda para un Candidato.
    Función pura — no toca la base de datos, solo lee del objeto.

    Si algo falla, devuelve cadena vacía. NUNCA lanza excepción
    porque se llama desde editar_perfil y no puede romper el guardado.
    """
    try:
        partes = []

        # Campos directos del candidato
        partes.append(_normalizar(candidato.nombre))
        partes.append(_normalizar(candidato.cargo_actual))
        partes.append(_normalizar(candidato.ciudad))
        partes.append(_normalizar(candidato.resumen))
        partes.append(_normalizar(candidato.get_disponibilidad_display()))
        partes.append(_normalizar(candidato.get_modalidad_display()))

        # País (relación)
        if candidato.pais_id:
            partes.append(_normalizar(candidato.pais.nombre))

        # Años de experiencia como texto buscable
        partes.append(f'{candidato.años_experiencia} anios experiencia')

        # Habilidades (JSON)
        for habilidad in (candidato.habilidades or []):
            partes.append(_normalizar(habilidad))

        # Sectores (M2M) — usamos all() porque ya están cargados
        for sector in candidato.sectores.all():
            partes.append(_normalizar(sector.nombre))

        # Idiomas (FK inverso)
        for idioma in candidato.idiomas.all():
            partes.append(_normalizar(idioma.idioma))
            partes.append(_normalizar(idioma.get_nivel_display()))

        # Experiencia laboral — solo cargos y empresas (no descripciones largas)
        for exp in candidato.experiencias.all():
            partes.append(_normalizar(exp.cargo))
            partes.append(_normalizar(exp.empresa))

        # Educación
        for edu in candidato.educaciones.all():
            partes.append(_normalizar(edu.titulo))
            partes.append(_normalizar(edu.institucion))

        # Unir todo, quitar vacíos, deduplicar palabras conservando orden
        texto = ' '.join(p for p in partes if p)
        palabras_vistas = set()
        palabras_unicas = []
        for palabra in texto.split():
            if palabra not in palabras_vistas:
                palabras_vistas.add(palabra)
                palabras_unicas.append(palabra)

        resultado = ' '.join(palabras_unicas)
        # Límite defensivo de tamaño — un perfil normal no pasa de 2 KB
        return resultado[:8000]

    except Exception as e:
        logger.error(f'Error construyendo texto_busqueda para candidato {candidato.pk}: {e}')
        return ''


def actualizar_texto_busqueda(candidato):
    """
    Recalcula texto_busqueda del candidato y lo guarda.
    Usa update_fields para evitar disparar auto_now en actualizado_en
    y para no recargar todo el objeto.

    Si falla, no propaga la excepción — el flujo del usuario sigue.
    """
    try:
        texto = construir_texto_busqueda(candidato)
        # Solo guardar si cambió, para no escribir innecesariamente
        if candidato.texto_busqueda != texto:
            candidato.texto_busqueda = texto
            candidato.save(update_fields=['texto_busqueda'])
        return True
    except Exception as e:
        logger.error(f'Error actualizando texto_busqueda candidato {candidato.pk}: {e}')
        return False