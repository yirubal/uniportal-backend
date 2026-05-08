import shutil
import tempfile

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.bot.tasks import (
    INBOX_DUPLICATE_CLEANUP_CACHE_KEY,
    _cleanup_assigned_inbox_duplicates_if_due,
)
from apps.content.models import Course, FileInbox, Resource
from apps.content.services import clear_inbox_file, copy_inbox_file_to_resource


class ResourceFileStorageTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root)
        self.settings_override.enable()
        self.course = Course.objects.create(name='Global Trends', code='GT101')

    def tearDown(self):
        cache.delete(INBOX_DUPLICATE_CLEANUP_CACHE_KEY)
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
        )

        copy_inbox_file_to_resource(inbox_item, resource)
        resource.save()
        resource.courses.add(self.course)

        self.assertTrue(resource.file.name.startswith('resources/'))
        self.assertNotEqual(resource.file.name, inbox_item.file.name)
        with resource.file.open('rb') as handle:
            self.assertEqual(handle.read(), b'%PDF-1.4 source')

    def test_clear_inbox_file_removes_duplicate_without_touching_resource(self):
        inbox_item = self.create_inbox_item()
        inbox_file_name = inbox_item.file.name
        resource = Resource(
            title='Global Trends',
            file_type=Resource.TYPE_LECTURE_NOTE,
            access_level=Resource.ACCESS_PREMIUM,
            status=Resource.STATUS_PENDING,
        )
        copy_inbox_file_to_resource(inbox_item, resource)
        resource.save()
        resource.courses.add(self.course)

        cleared = clear_inbox_file(
            inbox_item,
            protected_file_name=resource.file.name,
        )

        inbox_item.refresh_from_db()
        self.assertTrue(cleared)
        self.assertEqual(inbox_item.file.name, '')
        self.assertFalse(resource.file.storage.exists(inbox_file_name))
        self.assertTrue(resource.file.storage.exists(resource.file.name))
        with resource.file.open('rb') as handle:
            self.assertEqual(handle.read(), b'%PDF-1.4 source')

    def test_repair_resource_files_copies_assigned_inbox_source(self):
        inbox_item = self.create_inbox_item()
        inbox_file_name = inbox_item.file.name
        resource = Resource.objects.create(
            title='Broken Resource',
            file='resources/missing.pdf',
            file_type=Resource.TYPE_LECTURE_NOTE,
            access_level=Resource.ACCESS_PREMIUM,
            status=Resource.STATUS_PUBLISHED,
        )
        resource.courses.add(self.course)
        inbox_item.assigned_resource = resource
        inbox_item.save(update_fields=['assigned_resource'])

        call_command('repair_resource_files')

        resource.refresh_from_db()
        inbox_item.refresh_from_db()
        self.assertTrue(resource.file.name.startswith('resources/'))
        self.assertNotEqual(resource.file.name, 'resources/missing.pdf')
        self.assertEqual(inbox_item.file.name, '')
        self.assertFalse(resource.file.storage.exists(inbox_file_name))
        with resource.file.open('rb') as handle:
            self.assertEqual(handle.read(), b'%PDF-1.4 source')

    def test_cleanup_duplicate_inbox_files_removes_already_assigned_duplicates(self):
        inbox_item = self.create_inbox_item()
        inbox_file_name = inbox_item.file.name
        resource = Resource(
            title='Assigned Resource',
            file_type=Resource.TYPE_LECTURE_NOTE,
            access_level=Resource.ACCESS_PREMIUM,
            status=Resource.STATUS_PUBLISHED,
        )
        copy_inbox_file_to_resource(inbox_item, resource)
        resource.save()
        resource.courses.add(self.course)
        inbox_item.assigned_resource = resource
        inbox_item.save(update_fields=['assigned_resource'])

        call_command('cleanup_duplicate_inbox_files')

        inbox_item.refresh_from_db()
        resource.refresh_from_db()
        self.assertEqual(inbox_item.file.name, '')
        self.assertFalse(resource.file.storage.exists(inbox_file_name))
        self.assertTrue(resource.file.storage.exists(resource.file.name))

    def test_periodic_cleanup_helper_cleans_assigned_duplicates_once_due(self):
        assigned_inbox = self.create_inbox_item()
        assigned_file_name = assigned_inbox.file.name
        resource = Resource(
            title='Assigned Resource',
            file_type=Resource.TYPE_LECTURE_NOTE,
            access_level=Resource.ACCESS_PREMIUM,
            status=Resource.STATUS_PUBLISHED,
        )
        copy_inbox_file_to_resource(assigned_inbox, resource)
        resource.save()
        resource.courses.add(self.course)
        assigned_inbox.assigned_resource = resource
        assigned_inbox.save(update_fields=['assigned_resource'])

        _cleanup_assigned_inbox_duplicates_if_due()

        assigned_inbox.refresh_from_db()
        self.assertEqual(assigned_inbox.file.name, '')
        self.assertFalse(resource.file.storage.exists(assigned_file_name))
        self.assertTrue(cache.get(INBOX_DUPLICATE_CLEANUP_CACHE_KEY))
