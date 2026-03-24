from django.utils.cache import add_never_cache_headers


class NoCacheMiddleware:
    """
    Middleware para obligar a los navegadores a NUNCA guardar en caché las páginas.
    Evita que el usuario use el botón de "Atrás" de forma incorrecta.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Le aplicamos el candado a TODAS las respuestas de nuestro sistema
        add_never_cache_headers(response)

        return response