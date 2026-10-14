from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.db import connections
from django.db.utils import DatabaseError
from django.http import JsonResponse
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)


def health_check(request):
    try:
        with connections['default'].cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse(
            {'status': 'unhealthy', 'database': 'disconnected'},
            status=503,
        )

    return JsonResponse({'status': 'healthy', 'database': 'connected'})


def liveness_check(request):
    return JsonResponse({'status': 'alive'})


urlpatterns = [
    path('health/', health_check, name='health-check'),
    path('live/', liveness_check, name='liveness-check'),

    # Admin
    path('admin/', admin.site.urls),

    # API
    path('api/', include('apps.api.urls')),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += [
        path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
        path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
        path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
        path('api-auth/', include('rest_framework.urls')),
    ]
