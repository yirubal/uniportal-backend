from datetime import timedelta

from django.contrib.admin.models import CHANGE, DELETION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.bot.models import NotificationDelivery, QuestionExtraction, TelegramUpdate
from apps.content.models import FileInbox, Resource
from apps.exams.models import ExamPDFUpload, ExamTerm
from apps.quiz.models import Question
from config.admin_dashboard import dashboard, navigation


@override_settings(ALLOWED_HOSTS=['testserver'])
class AdminDashboardTests(TestCase):
    def setUp(self):
        self.root = get_user_model().objects.create_superuser('dashboard-root')
        self.client.force_login(self.root)

    def overview(self):
        response = self.client.get(reverse('admin:index'))
        self.assertEqual(response.status_code, 200)
        return response

    def test_attention_links_show_exact_records_including_assigned_inbox_items(self):
        now = timezone.now()
        resource = Resource.objects.create(title='Draft', file_type='module')
        FileInbox.objects.create(original_filename='assigned.pdf', telegram_message_id=90,
                                 posted_date=now, assigned_resource=resource, processing_status='failed')
        FileInbox.objects.create(original_filename='ready.pdf', telegram_message_id=91,
                                 posted_date=now, processing_status='processed')
        Question.objects.create(text='Unassigned?', question_type='mcq')
        for model, values in [
            (ExamPDFUpload, {'original_name': 'failed.pdf', 'pdf_type': 'schedule'}),
            (NotificationDelivery, {'deduplication_key': 'failed', 'chat_id': 1, 'text': 'Hello'}),
            (TelegramUpdate, {'update_id': 1, 'payload': {}}),
        ]:
            model.objects.create(status='failed', **values)
        overdue = ExamPDFUpload.objects.create(original_name='overdue.pdf', pdf_type='schedule',
                                               next_attempt_at=now - timedelta(hours=1))
        ExamPDFUpload.objects.create(original_name='future.pdf', pdf_type='schedule',
                                     next_attempt_at=now + timedelta(hours=1))
        ExamPDFUpload.objects.create(original_name='stale.pdf', pdf_type='schedule', status='processing',
                                     claimed_at=now - timedelta(hours=1))
        response = self.overview()
        cards = response.context['attention_cards']
        self.assertTrue(any('over 15 minutes' in card['label'] for card in cards))
        for card in cards:
            with self.subTest(label=card['label']):
                destination = self.client.get(card['url'])
                self.assertEqual(destination.status_code, 200)
                self.assertEqual(destination.context['cl'].result_count, card['value'])
        queue = next(queue for queue in response.context['work_queues'] if queue['label'] == 'Exam PDF imports')
        destination = self.client.get(queue['counts'][1]['url'])
        self.assertEqual(list(destination.context['cl'].result_list), [overdue])

    def test_restricted_staff_does_not_receive_counts_or_links_for_other_models(self):
        user = get_user_model().objects.create_user('resource-reviewer', is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename='view_resource'))
        Resource.objects.create(title='Visible draft', file_type='module')
        self.client.force_login(user)
        response = self.overview()
        self.assertEqual([card['label'] for card in response.context['attention_cards']], ['Draft resources to review'])
        self.assertEqual(response.context['work_queues'], [])
        self.assertEqual(response.context['task_shortcuts'], [])
        self.assertFalse(response.context['can_view_exam_terms'])
        self.assertNotContains(response, 'Message delivery')
        self.assertNotContains(response, 'Send broadcast')
        self.assertNotContains(response, 'Staff accounts')

    def test_sidebar_exposes_every_allowed_destination_and_hides_empty_groups(self):
        request = RequestFactory().get('/admin/')
        request.user = self.root
        groups = navigation(request)
        self.assertEqual([group['title'] for group in groups], [
            '', 'Content', 'Exams & quizzes', 'Students & communication', 'Operations', 'Settings',
        ])
        for group in groups:
            for item in group['items']:
                with self.subTest(destination=item['title']):
                    self.assertEqual(self.client.get(item['link']).status_code, 200)
        user = get_user_model().objects.create_user('no-permissions', is_staff=True)
        request.user = user
        self.assertEqual([group['title'] for group in navigation(request)], [''])

    def test_overview_link_is_active_only_on_homepage(self):
        request = RequestFactory().get('/admin/content/resource/')
        request.user = self.root
        self.assertFalse(navigation(request)[0]['items'][0]['active'])

    def test_recent_activity_is_permission_filtered_and_deleted_records_are_not_linked(self):
        user = get_user_model().objects.create_user('activity-reviewer', is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename='view_resource'))
        for label, model, flag in [('Visible resource', Resource, CHANGE),
                                   ('Deleted resource', Resource, DELETION),
                                   ('Hidden delivery', NotificationDelivery, CHANGE)]:
            LogEntry.objects.create(user=self.root, content_type=ContentType.objects.get_for_model(model),
                                    object_id='123', object_repr=label, action_flag=flag)
        self.client.force_login(user)
        response = self.overview()
        self.assertNotContains(response, 'Hidden delivery')
        activity = response.context['recent_activity']
        self.assertEqual(len(activity), 2)
        self.assertIsNone(next(item['url'] for item in activity if item['label'] == 'Deleted resource'))

    def test_active_term_and_empty_states_render_without_health_claims(self):
        response = self.overview()
        self.assertContains(response, 'No exam term is active')
        self.assertContains(response, 'Queue counts do not confirm that the worker is running')
        term = ExamTerm.objects.create(year=2018, term=1, is_active=True)
        self.assertEqual(self.overview().context['active_exam_term']['label'], str(term))

    def test_dashboard_queries_are_bounded_as_records_grow(self):
        request = RequestFactory().get('/admin/')
        request.user = self.root
        with self.assertNumQueries(10):
            dashboard(request, {})
        TelegramUpdate.objects.bulk_create([
            TelegramUpdate(update_id=i, payload={}, status='failed') for i in range(1, 101)
        ])
        with self.assertNumQueries(10):
            result = dashboard(request, {})
        self.assertEqual(next(card['value'] for card in result['attention_cards']
                              if card['label'] == 'Telegram updates: failed'), 100)

    def test_stale_missing_claim_and_ai_queue_filters_match_overview(self):
        inbox = FileInbox.objects.create(original_filename='ai.pdf', telegram_message_id=20,
                                        posted_date=timezone.now())
        QuestionExtraction.objects.create(inbox=inbox, source_hash='x', version='v1', source_text='text',
                                          status='processing', claimed_at=None)
        response = self.overview()
        queue = next(queue for queue in response.context['work_queues'] if queue['label'] == 'Question extraction')
        stale = queue['counts'][2]
        self.assertEqual(stale['value'], 1)
        destination = self.client.get(stale['url'])
        self.assertEqual(destination.context['cl'].result_count, 1)
