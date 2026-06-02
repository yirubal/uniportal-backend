from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.db import connections
from django.db.utils import OperationalError
from django.http import JsonResponse
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)


def health_check(request):
    try:
        with connections['default'].cursor():
            pass
    except OperationalError:
        return JsonResponse(
            {'status': 'unhealthy', 'database': 'disconnected'},
            status=503,
        )

    return JsonResponse({'status': 'healthy', 'database': 'connected'})


urlpatterns = [
    path('health/', health_check, name='health-check'),

    # Admin
    path('admin/', admin.site.urls),

    # API
    path('api/', include('apps.api.urls')),

    # API Docs — available in DEBUG mode only
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/',   SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/',  SpectacularRedocView.as_view(url_name='schema'),   name='redoc'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += [
        path('api-auth/', include('rest_framework.urls')),
    ]
