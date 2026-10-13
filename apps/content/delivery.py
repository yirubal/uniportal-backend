"""Issue expiring file links without transferring R2 bytes through Django."""
import mimetypes
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils.http import content_disposition_header
from storages.backends.s3 import S3Storage
from storages.utils import clean_name

DOWNLOAD_SALT = 'apps.api.resource-download'


def resource_filename(resource):
    return Path(resource.file.name).name.replace('\r', '').replace('\n', '') or f'resource-{resource.pk}'


def resource_file_url(resource, request, *, inline=False, method='GET'):
    if not resource.file:
        return None
    storage = resource.file.storage
    if isinstance(storage, S3Storage):
        # Use the signed connection directly: storage.url() can use a permanent
        # custom-domain URL even when query-string authentication is enabled.
        params = {'Bucket': storage.bucket_name,
                  'Key': storage._normalize_name(clean_name(resource.file.name))}
        if method != 'HEAD':
            params.update({
                'ResponseContentDisposition': content_disposition_header(not inline, resource_filename(resource)),
                'ResponseContentType': mimetypes.guess_type(resource_filename(resource))[0] or 'application/octet-stream',
            })
        return storage.connection.meta.client.generate_presigned_url(
            'head_object' if method == 'HEAD' else 'get_object', Params=params,
            ExpiresIn=settings.RESOURCE_LINK_TTL_SECONDS, HttpMethod=method,
        )
    token = signing.dumps({'resource_id': resource.pk, 'student_id': request.student.pk,
                           'file_name': resource.file.name, 'inline': inline}, salt=DOWNLOAD_SALT)
    path = reverse('resource-download-file', kwargs={'resource_id': resource.pk, 'token': quote(token, safe='')})
    return request.build_absolute_uri(path)
