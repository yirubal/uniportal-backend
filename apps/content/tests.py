import shutil
import tempfile
from unittest.mock import patch
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory

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
from apps.content.admin import FileInboxAdmin
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

    def test_publish_reuses_stored_inbox_file_without_copying(self):
        inbox_item = self.create_inbox_item()
        resource = Resource(
            title='Global Trends',
            file_type=Resource.TYPE_LECTURE_NOTE,
            access_level=Resource.ACCESS_PREMIUM,
            status=Resource.STATUS_PENDING,
        )

        with patch.object(resource.file.storage, 'save') as save_file:
            copy_inbox_file_to_resource(inbox_item, resource)
        save_file.assert_not_called()
        resource.save()
        resource.courses.add(self.course)

        self.assertEqual(resource.file.name, inbox_item.file.name)
        with resource.file.open('rb') as handle:
            self.assertEqual(handle.read(), b'%PDF-1.4 source')

    def test_clear_inbox_reference_preserves_shared_resource_file(self):
        inbox_item = self.create_inbox_item()
        inbox_file_name = inbox_item.file.name
        resource = Resource(
            title='Global Trends',
            file_type=Resource.TYPE_LECTURE_NOTE,
            access_level=Resource.ACCESS_PREMIUM,
            status=Resource.STATUS_PUBLISHED,
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
        self.assertTrue(resource.file.storage.exists(inbox_file_name))
        self.assertTrue(resource.file.storage.exists(resource.file.name))
        with resource.file.open('rb') as handle:
            self.assertEqual(handle.read(), b'%PDF-1.4 source')

    def test_repair_resource_files_reuses_assigned_inbox_source(self):
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
        self.assertEqual(resource.file.name, inbox_file_name)
        self.assertNotEqual(resource.file.name, 'resources/missing.pdf')
        self.assertEqual(inbox_item.file.name, '')
        self.assertTrue(resource.file.storage.exists(inbox_file_name))
        with resource.file.open('rb') as handle:
            self.assertEqual(handle.read(), b'%PDF-1.4 source')

    def test_cleanup_clears_shared_reference_without_deleting_resource_file(self):
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
        self.assertTrue(resource.file.storage.exists(inbox_file_name))
        self.assertTrue(resource.file.storage.exists(resource.file.name))

    def test_periodic_cleanup_preserves_shared_file_and_runs_once_when_due(self):
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
        self.assertTrue(resource.file.storage.exists(assigned_file_name))
        self.assertTrue(cache.get(INBOX_DUPLICATE_CLEANUP_CACHE_KEY))
        with patch('apps.content.services.cleanup_assigned_inbox_duplicates') as cleanup:
            _cleanup_assigned_inbox_duplicates_if_due()
        cleanup.assert_not_called()

    def create_separate_resource_file(self, inbox_item):
        resource = Resource.objects.create(
            title='Published Resource',
            file=SimpleUploadedFile('published.pdf', b'%PDF-1.4 source'),
            status=Resource.STATUS_PUBLISHED,
        )
        resource.courses.add(self.course)
        inbox_item.assigned_resource = resource
        inbox_item.save(update_fields=['assigned_resource'])
        return resource

    def test_cleanup_deletes_unreferenced_legacy_duplicate(self):
        inbox_item = self.create_inbox_item()
        inbox_file_name = inbox_item.file.name
        resource = self.create_separate_resource_file(inbox_item)

        call_command('cleanup_duplicate_inbox_files')

        inbox_item.refresh_from_db()
        self.assertEqual(inbox_item.file.name, '')
        self.assertFalse(resource.file.storage.exists(inbox_file_name))
        with resource.file.open('rb') as handle:
            self.assertEqual(handle.read(), b'%PDF-1.4 source')

    def test_cleanup_preserves_duplicate_used_by_another_resource(self):
        inbox_item = self.create_inbox_item()
        inbox_file_name = inbox_item.file.name
        self.create_separate_resource_file(inbox_item)
        other_resource = Resource.objects.create(
            title='Another Published Resource',
            file=inbox_file_name,
            status=Resource.STATUS_PUBLISHED,
        )

        call_command('cleanup_duplicate_inbox_files')

        inbox_item.refresh_from_db()
        self.assertEqual(inbox_item.file.name, '')
        with other_resource.file.open('rb') as handle:
            self.assertEqual(handle.read(), b'%PDF-1.4 source')

    def test_clear_preserves_file_used_by_another_inbox(self):
        inbox_item = self.create_inbox_item()
        other_inbox = FileInbox.objects.create(
            file=inbox_item.file.name,
            original_filename='same-file.pdf',
            telegram_message_id=1002,
            posted_date=timezone.now(),
        )

        clear_inbox_file(inbox_item)

        inbox_item.refresh_from_db()
        self.assertEqual(inbox_item.file.name, '')
        with other_inbox.file.open('rb') as handle:
            self.assertEqual(handle.read(), b'%PDF-1.4 source')

    def test_cleanup_preserves_inbox_source_when_resource_file_is_missing(self):
        inbox_item = self.create_inbox_item()
        inbox_file_name = inbox_item.file.name
        resource = Resource.objects.create(title='Missing File', file='resources/missing.pdf')
        inbox_item.assigned_resource = resource
        inbox_item.save(update_fields=['assigned_resource'])

        call_command('cleanup_duplicate_inbox_files')

        inbox_item.refresh_from_db()
        self.assertEqual(inbox_item.file.name, inbox_file_name)
        self.assertTrue(inbox_item.file.storage.exists(inbox_file_name))

    def test_cleanup_dry_run_preserves_files_and_references(self):
        inbox_item = self.create_inbox_item()
        inbox_file_name = inbox_item.file.name
        resource = self.create_separate_resource_file(inbox_item)

        call_command('cleanup_duplicate_inbox_files', dry_run=True)

        inbox_item.refresh_from_db()
        self.assertEqual(inbox_item.file.name, inbox_file_name)
        self.assertTrue(resource.file.storage.exists(inbox_file_name))
        self.assertTrue(resource.file.storage.exists(resource.file.name))

    def test_admin_creates_pending_resource_without_placeholder_course(self):
        self.course.delete()
        inbox_item = self.create_inbox_item()
        original_key = inbox_item.file.name
        request = RequestFactory().post('/admin/content/fileinbox/')
        request.user = get_user_model().objects.create_superuser(username='content-admin')
        model_admin = FileInboxAdmin(FileInbox, admin.site)
        with patch.object(model_admin, 'message_user'):
            model_admin.publish_as_resource(request, FileInbox.objects.filter(pk=inbox_item.pk))
            model_admin.publish_as_resource(request, FileInbox.objects.filter(pk=inbox_item.pk))
        resource = Resource.objects.get()
        inbox_item.refresh_from_db()
        self.assertEqual(resource.status, Resource.STATUS_PENDING)
        self.assertFalse(resource.courses.exists())
        self.assertEqual(resource.file.name, original_key)
        self.assertEqual(inbox_item.assigned_resource_id, resource.pk)
        self.assertEqual(inbox_item.file.name, '')
        with resource.file.open('rb') as handle:
            self.assertEqual(handle.read(), b'%PDF-1.4 source')
