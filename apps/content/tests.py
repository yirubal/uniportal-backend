import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.content.models import Course, FileInbox, Resource
from apps.content.services import copy_inbox_file_to_resource


class ResourceFileStorageTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root)
        self.settings_override.enable()
        self.course = Course.objects.create(name='Global Trends', code='GT101')

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def create_inbox_item(self):
        return FileInbox.objects.create(
            file=SimpleUploadedFile(
                'global-trends.pdf',
                b'%PDF-1.4 source',
                content_type='application/pdf',
            ),
            original_filename='global-trends.pdf',
            telegram_message_id=1001,
            telegram_caption='',
            posted_date=timezone.now(),
            processing_status=FileInbox.STATUS_PROCESSED,
        )

    def test_copy_inbox_file_to_resource_saves_resource_storage_object(self):
        inbox_item = self.create_inbox_item()
        resource = Resource(
            title='Global Trends',
            file_type=Resource.TYPE_LECTURE_NOTE,
            access_level=Resource.ACCESS_PREMIUM,
            status=Resource.STATUS_PENDING,
            course=self.course,
        )

        copy_inbox_file_to_resource(inbox_item, resource)
        resource.save()

        self.assertTrue(resource.file.name.startswith('resources/'))
        self.assertNotEqual(resource.file.name, inbox_item.file.name)
        with resource.file.open('rb') as handle:
            self.assertEqual(handle.read(), b'%PDF-1.4 source')

    def test_repair_resource_files_copies_assigned_inbox_source(self):
        inbox_item = self.create_inbox_item()
        resource = Resource.objects.create(
            title='Broken Resource',
            file='resources/missing.pdf',
            file_type=Resource.TYPE_LECTURE_NOTE,
            access_level=Resource.ACCESS_PREMIUM,
            status=Resource.STATUS_PUBLISHED,
            course=self.course,
        )
        inbox_item.assigned_resource = resource
        inbox_item.save(update_fields=['assigned_resource'])

        call_command('repair_resource_files')

        resource.refresh_from_db()
        self.assertTrue(resource.file.name.startswith('resources/'))
        self.assertNotEqual(resource.file.name, 'resources/missing.pdf')
        with resource.file.open('rb') as handle:
            self.assertEqual(handle.read(), b'%PDF-1.4 source')
