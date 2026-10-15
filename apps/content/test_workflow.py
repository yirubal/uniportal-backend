from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.forms import modelform_factory
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from storages.backends.s3 import S3Storage

from apps.content.admin import ResourceAdmin
from apps.content.forms import ResourceReviewForm
from apps.content.models import Course, CoursePlacement, Department, FileInbox, Resource
from apps.content.views_admin import course_resource_audit_context


@override_settings(ALLOWED_HOSTS=['testserver'])
class ContentWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('content-editor')
        self.client.force_login(self.user)
        self.course = Course.objects.create(name='Active course', code='ACTIVE')
        self.media = TemporaryDirectory(prefix='uniportal-content-workflow-')
        self.addCleanup(self.media.cleanup)
        self.settings = override_settings(MEDIA_ROOT=self.media.name)
        self.settings.enable()
        self.addCleanup(self.settings.disable)

    def resource(self, title='Module', **values):
        # These tests exercise references without issuing storage requests.
        obj = Resource(title=title, file_type='module', file='resources/module.pdf', **values)
        Resource.objects.bulk_create([obj])
        return obj

    def form(self, instance, **values):
        form_class = modelform_factory(Resource, form=ResourceReviewForm,
                                       fields=['title', 'file', 'file_type', 'status', 'courses'])
        data = {'title': instance.title, 'file_type': 'module',
                'status': 'pending', 'courses': [], **values}
        return form_class(data, instance=instance)

    def inbox(self, message_id):
        return FileInbox.objects.create(
            original_filename='module.pdf', telegram_message_id=message_id,
            posted_date=timezone.now(), processing_status='processed',
            file=SimpleUploadedFile('module.pdf', b'%PDF-1.4 synthetic content', content_type='application/pdf'),
        )

    def create_drafts(self, *items):
        return self.client.post(reverse('admin:content_fileinbox_changelist'), {
            'action': 'publish_as_resource', '_selected_action': [item.pk for item in items], 'index': 0,
        })

    def test_single_draft_opens_review_and_preserves_the_file(self):
        inbox = self.inbox(1)
        original_name = inbox.file.name
        response = self.create_drafts(inbox)
        resource = Resource.objects.get()
        self.assertRedirects(response, reverse('admin:content_resource_change', args=[resource.pk]))
        self.assertEqual(resource.status, 'pending')
        self.assertFalse(resource.courses.exists())
        self.assertEqual(resource.file.name, original_name)
        self.assertTrue(resource.file.storage.exists(original_name))
        inbox.refresh_from_db()
        self.assertEqual(inbox.assigned_resource_id, resource.pk)
        self.assertEqual(inbox.file.name, '')
        response = self.client.get(reverse('admin:content_fileinbox_change', args=[inbox.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Open linked resource')

    def test_batch_drafts_redirect_to_only_created_drafts_and_repeat_is_safe(self):
        one, two = self.inbox(1), self.inbox(2)
        missing = FileInbox.objects.create(original_filename='missing.pdf', telegram_message_id=3,
                                           posted_date=timezone.now(), processing_status='processed')
        response = self.create_drafts(one, two, missing)
        self.assertEqual(response.status_code, 302)
        destination = self.client.get(response.url)
        self.assertEqual(destination.status_code, 200)
        self.assertEqual(destination.context['cl'].result_count, 2)
        self.create_drafts(one, two)
        self.assertEqual(Resource.objects.count(), 2)
        self.assertIsNone(FileInbox.objects.get(pk=missing.pk).assigned_resource_id)

    def test_bulk_publish_requires_pending_file_and_active_course_and_logs_changes(self):
        ready = self.resource('Ready')
        ready.courses.add(self.course)
        unassigned = self.resource('Needs courses')
        no_file = Resource.objects.create(title='No file', file_type='module')
        no_file.courses.add(self.course)
        rejected = self.resource('Rejected', status='rejected')
        rejected.courses.add(self.course)
        inactive = Course.objects.create(name='Inactive course', code='OLD', is_active=False)
        old = self.resource('Inactive only')
        old.courses.add(inactive)
        response = self.client.post(reverse('admin:content_resource_changelist') + '?status__exact=pending', {
            'action': 'publish_selected', '_selected_action': [ready.pk, unassigned.pk, no_file.pk, old.pk], 'index': 0,
        })
        self.assertEqual(response.status_code, 302)
        ready.refresh_from_db()
        self.assertEqual(ready.status, 'published')
        for obj in [unassigned, no_file, old, rejected]:
            obj.refresh_from_db()
            self.assertNotEqual(obj.status, 'published')
        self.assertTrue(LogEntry.objects.filter(object_id=str(ready.pk), action_flag=CHANGE).exists())

    def test_bulk_publish_with_related_course_search_locks_resources_without_distinct(self):
        resource = self.resource('Reviewed draft')
        resource.courses.add(self.course)
        response = self.client.post(reverse('admin:content_resource_changelist') + '?q=ACTIVE', {
            'action': 'publish_selected', '_selected_action': [resource.pk], 'index': 0,
        })
        self.assertEqual(response.status_code, 302)
        resource.refresh_from_db()
        self.assertEqual(resource.status, 'published')

    def test_form_allows_unassigned_draft_and_blocks_invalid_publication(self):
        resource = self.resource()
        self.assertTrue(self.form(resource).is_valid())
        form = self.form(resource, status='published')
        self.assertFalse(form.is_valid())
        self.assertIn('courses', form.errors)
        form = self.form(resource, status='published', courses=[self.course.pk])
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        resource.refresh_from_db()
        self.assertEqual(resource.status, 'published')

    def test_inactive_assignments_remain_visible_but_do_not_enable_publishing(self):
        inactive = Course.objects.create(name='Archived', code='OLD', is_active=False)
        resource = self.resource()
        resource.courses.add(inactive)
        self.assertTrue(self.form(resource, courses=[inactive.pk]).is_valid())
        self.assertFalse(self.form(resource, status='published', courses=[inactive.pk]).is_valid())

    def test_relation_search_returns_active_courses_only(self):
        Course.objects.create(name='Inactive course', code='OLD', is_active=False)
        response = self.client.get(reverse('admin:autocomplete'), {
            'app_label': 'content', 'model_name': 'resource', 'field_name': 'courses', 'term': 'course',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual([int(result['id']) for result in response.json()['results']], [self.course.pk])

    def test_review_filters_match_pending_assignment_and_file_state(self):
        ready = self.resource('Ready')
        ready.courses.add(self.course)
        unassigned = self.resource('Unassigned')
        for step, expected in [('ready', [ready]), ('needs_courses', [unassigned])]:
            response = self.client.get(reverse('admin:content_resource_changelist'), {'review_step': step})
            self.assertEqual(list(response.context['cl'].result_list), expected)

    def test_local_preview_is_staff_authorized_and_streams_the_file(self):
        resource = Resource.objects.create(title='Preview', file_type='module', file=SimpleUploadedFile(
            'preview.pdf', b'%PDF-1.4 test document', content_type='application/pdf'))
        url = reverse('admin:content_resource_preview', args=[resource.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 test document')
        staff = get_user_model().objects.create_user('no-resource-access', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_private_r2_preview_uses_existing_signed_delivery_without_reading_file(self):
        resource = self.resource()
        resource.file.storage = S3Storage(access_key='test', secret_key='test', bucket_name='test')
        with patch.object(ResourceAdmin, 'get_object', return_value=resource), patch(
            'apps.content.admin.resource_file_url', return_value='https://storage.example.test/signed-file',
        ) as signed, patch.object(resource.file.storage, 'open', side_effect=AssertionError('Unexpected read')):
            response = self.client.get(reverse('admin:content_resource_preview', args=[resource.pk]))
        self.assertEqual(response.status_code, 302)
        signed.assert_called_once()
        self.assertTrue(signed.call_args.kwargs['inline'])


@override_settings(ALLOWED_HOSTS=['testserver'])
class ResourceCoverageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('coverage-admin')
        self.client.force_login(self.user)
        self.department = Department.objects.create(name='Business')
        self.other = Department.objects.create(name='Computing')
        self.pending = Course.objects.create(name='Draft only', code='DRAFT')
        self.covered = Course.objects.create(name='Published course', code='PUB')
        self.inactive = Course.objects.create(name='Inactive', code='OLD', is_active=False)
        for course in [self.pending, self.covered, self.inactive]:
            CoursePlacement.objects.create(course=course, department=self.department, program='distance', year=1, period=1)
        CoursePlacement.objects.create(course=self.covered, department=self.department, program='distance', year=2, period=1)
        CoursePlacement.objects.create(course=self.pending, department=self.other, program='regular', year=1, period=1)
        draft = Resource(title='Draft', file_type='module', status='pending', file='draft.pdf')
        published = Resource(title='Published', file_type='module', status='published', file='published.pdf')
        Resource.objects.bulk_create([draft, published])
        draft.courses.add(self.pending)
        published.courses.add(self.covered, self.inactive)

    def context(self, **params):
        request = RequestFactory().get('/admin/content/course/course-resource-audit/', params)
        return course_resource_audit_context(request)

    def test_coverage_counts_only_published_resources_and_distinct_active_courses(self):
        context = self.context(program='distance')
        self.assertEqual(context['total_courses'], 2)
        self.assertEqual(context['courses_with_resources'], 1)
        self.assertEqual(context['overall_coverage_pct'], 50)
        self.assertEqual(context['dept_stats'][0]['total_courses'], 2)
        self.assertEqual(context['dept_stats'][0]['resource_count'], 1)
        self.assertEqual([course.pk for course in self.context(tab='missing')['courses']], [self.pending.pk])

    def test_department_and_program_must_match_the_same_placement(self):
        context = self.context(department=self.other.pk, program='distance')
        self.assertEqual(context['total_courses'], 0)
        self.assertEqual(context['total_resources'], 0)
        self.assertEqual(context['dept_stats'], [])

    def test_search_scopes_metrics_and_department_cards(self):
        context = self.context(q='Draft')
        self.assertEqual(context['total_courses'], 1)
        self.assertEqual(context['courses_with_resources'], 0)
        self.assertEqual(context['pending_resources'], 1)
        self.assertEqual(context['published_resources'], 0)
        self.assertTrue(all(stat['total_courses'] == 1 for stat in context['dept_stats']))

    def test_pagination_preserves_scope_and_invalid_tab_is_safe(self):
        Course.objects.bulk_create([Course(name=f'Course {i:02}', code=f'C{i}') for i in range(30)])
        context = self.context(tab='missing', page=2, q='Course')
        self.assertEqual(context['page_obj'].number, 2)
        self.assertEqual(context['page_obj'].paginator.count, 30)
        self.assertEqual(parse_qs(context['pagination_query']), {'tab': ['missing'], 'q': ['Course']})
        response = self.client.get(reverse('admin:course_resource_audit'), {'tab': "not-a-tab'"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_tab'], 'overview')
        self.assertNotContains(response, 'switchTab(')

    def test_course_detail_paginates_and_marks_title_matches_without_deleting(self):
        resources = [Resource(title='Repeated title', file_type='module') for _ in range(30)]
        Resource.objects.bulk_create(resources)
        for resource in resources:
            resource.courses.add(self.covered)
        response = self.client.get(reverse('admin:course_resource_detail', args=[self.covered.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['resources_with_flags']), 25)
        self.assertEqual(response.context['duplicate_count'], 1)
        self.assertEqual(response.context['page_obj'].paginator.count, 31)
        self.assertTrue(any(item['is_duplicate'] for item in response.context['resources_with_flags']))
        self.assertEqual(Resource.objects.count(), 32)

    def test_department_query_count_does_not_grow_per_department(self):
        def measure():
            with CaptureQueriesContext(connection) as queries:
                context = self.context()
                list(context['departments'])
            return len(queries)
        baseline = measure()
        for i in range(30):
            department = Department.objects.create(name=f'Department {i}')
            CoursePlacement.objects.create(course=self.pending, department=department,
                                           program='distance', year=1, period=1)
        self.assertEqual(measure(), baseline)
        self.assertLessEqual(baseline, 6)
