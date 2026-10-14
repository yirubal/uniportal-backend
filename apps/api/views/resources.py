"""Resources API endpoints."""
import mimetypes
import logging
from urllib.parse import unquote
from botocore.exceptions import ClientError
from django.core import signing
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from django.http import FileResponse, HttpResponseRedirect
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.conf import settings
from ..pagination import list_response
from apps.accounts.models import Student
from apps.content.delivery import resource_file_url, resource_filename
from apps.content.models import Resource
from ..serializers import ResourceSerializer, ResourceFilterInputSerializer
from ..permissions import IsTelegramAuthenticated

logger = logging.getLogger(__name__)
RESOURCE_DOWNLOAD_TOKEN_MAX_AGE = settings.RESOURCE_LINK_TTL_SECONDS
RESOURCE_DOWNLOAD_TOKEN_SALT = 'apps.api.resource-download'


class ResourceListView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request, course_id):
        inputs = ResourceFilterInputSerializer(data=request.query_params)
        inputs.is_valid(raise_exception=True)
        params = inputs.validated_data
        file_type, search = params.get('type'), params.get('search')

        resources = Resource.objects.filter(
            courses=course_id,
            status=Resource.STATUS_PUBLISHED,
        ).prefetch_related('courses').distinct()

        if file_type:
            resources = resources.filter(file_type=file_type)

        if search:
            from django.db.models import Q
            resources = resources.filter(
                Q(title__icontains=search) |
                Q(extracted_text__icontains=search)
            )

        return list_response(resources.order_by('-created_at', '-pk'), ResourceSerializer, request)


class ResourceDetailView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request, resource_id):
        try:
            resource = Resource.objects.prefetch_related('courses').get(
                id=resource_id,
                status=Resource.STATUS_PUBLISHED,
            )
        except Resource.DoesNotExist:
            return Response(
                {'error': 'NOT_FOUND', 'message': 'Resource not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            ResourceSerializer(resource, context={'request': request}).data
        )


class ResourceDownloadView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def post(self, request, resource_id):
        try:
            resource = Resource.objects.get(
                id=resource_id,
                status=Resource.STATUS_PUBLISHED,
            )
        except Resource.DoesNotExist:
            return Response(
                {'error': 'NOT_FOUND', 'message': 'Resource not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        student = request.student

        file_url = resource_file_url(resource, request)
        if file_url is None:
            return Response({'error': 'FILE_NOT_FOUND', 'message': 'Resource has no file.'}, status=404)
        with transaction.atomic():
            locked_student = Student.objects.select_for_update().get(pk=student.pk)
            today = timezone.localdate()
            if locked_student.last_download_reset < today:
                Student.objects.filter(pk=student.pk).update(downloads_today=0, last_download_reset=today)
            Student.objects.filter(pk=student.pk).update(downloads_today=F('downloads_today') + 1)
            Resource.objects.filter(pk=resource.pk).update(downloads_count=F('downloads_count') + 1)
        return Response({
            'url':      file_url,
            'filename': _resource_download_filename(resource),
            'expires_in': RESOURCE_DOWNLOAD_TOKEN_MAX_AGE,
        })


class ResourceDownloadFileView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, resource_id, token=None):
        token = unquote(token or request.query_params.get('token', ''))
        try:
            payload = signing.loads(
                token,
                salt=RESOURCE_DOWNLOAD_TOKEN_SALT,
                max_age=RESOURCE_DOWNLOAD_TOKEN_MAX_AGE,
            )
        except signing.SignatureExpired:
            return Response(
                {'error': 'DOWNLOAD_EXPIRED', 'message': 'Download link expired.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        except signing.BadSignature:
            return Response(
                {'error': 'INVALID_DOWNLOAD', 'message': 'Invalid download link.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if payload.get('resource_id') != resource_id:
            return Response(
                {'error': 'INVALID_DOWNLOAD', 'message': 'Invalid download link.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            resource = Resource.objects.get(
                id=resource_id,
                status=Resource.STATUS_PUBLISHED,
            )
        except Resource.DoesNotExist:
            return Response(
                {'error': 'NOT_FOUND', 'message': 'Resource not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if payload.get('file_name') != resource.file.name:
            return Response(
                {'error': 'INVALID_DOWNLOAD', 'message': 'Invalid download link.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        from storages.backends.s3 import S3Storage
        if isinstance(resource.file.storage, S3Storage):
            return HttpResponseRedirect(resource_file_url(resource, request,
                                        inline=bool(payload.get('inline')), method=request.method))

        try:
            file_handle = resource.file.open('rb')
        except (ClientError, FileNotFoundError, ValueError):
            logger.warning('Resource file missing for download: resource_id=%s', resource_id)
            return Response(
                {'error': 'FILE_NOT_FOUND', 'message': 'Resource file not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        filename = _resource_download_filename(resource)
        content_type, _ = mimetypes.guess_type(filename)
        response = FileResponse(
            file_handle,
            as_attachment=not bool(payload.get('inline')),
            filename=filename,
            content_type=content_type or 'application/octet-stream',
        )
        response['X-Content-Type-Options'] = 'nosniff'
        return response


def _resource_download_filename(resource):
    return resource_filename(resource)
