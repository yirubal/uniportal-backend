from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse

from apps.content.models import Course, Resource
from apps.exams.models import ExamPDFUpload, ExamTerm
from apps.quiz.models import Chapter, ExamPaper, Question
from scripts.check_admin_performance import measure, seed_rows


@override_settings(ALLOWED_HOSTS=['testserver'])
class AdminUsabilityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('efficiency-admin')
        self.client.force_login(self.user)
        seed_rows(0, 1, self.user)

    def test_rendered_list_query_cost_does_not_grow_per_displayed_row(self):
        before = measure(self.client)
        seed_rows(1, 25, self.user)
        after = measure(self.client)
        for page in before:
            with self.subTest(page=page):
                self.assertEqual(after[page]['queries'], before[page]['queries'])
                self.assertLessEqual(after[page]['queries'], 14)

    def test_annotated_counts_preserve_active_question_and_distinct_import_totals(self):
        paper, chapter = ExamPaper.objects.get(), Chapter.objects.get()
        Question.objects.create(text='Inactive sample', exam_paper=paper, chapter=chapter, is_active=False)
        ExamPDFUpload.objects.create(original_name='Second sample.pdf', pdf_type='attendance', term=ExamTerm.objects.get())
        request = self.client.get('/admin/').wsgi_request
        paper = admin.site._registry[ExamPaper].get_queryset(request).get(pk=paper.pk)
        chapter = admin.site._registry[Chapter].get_queryset(request).get(pk=chapter.pk)
        term = admin.site._registry[ExamTerm].get_queryset(request).get()
        self.assertEqual(paper.total_questions, 1)
        self.assertEqual(chapter.question_count, 1)
        self.assertEqual(term.admin_student_count, 1)
        self.assertEqual(term.admin_pdf_count, 2)

    def test_resource_review_return_link_preserves_search_and_status_filters(self):
        resource = Resource.objects.get()
        response = self.client.get(reverse('admin:content_resource_change', args=[resource.pk]), {
            '_changelist_filters': 'q=Sample&status__exact=pending&next=https://example.invalid',
        })
        link = response.context['workflow_links'][0]
        self.assertEqual(parse_qs(urlsplit(link['url']).query), {'q': ['Sample'], 'status__exact': ['pending']})

    def test_course_detail_and_pagination_keep_coverage_scope_on_a_local_route(self):
        course = Course.objects.get()
        response = self.client.get(reverse('admin:course_resource_detail', args=[course.pk]), {
            'audit_filters': 'q=Sample&program=distance&tab=missing&page=2&next=https://example.invalid',
        })
        self.assertTrue(response.context['audit_url'].startswith(reverse('admin:course_resource_audit') + '?'))
        self.assertNotIn('next=', response.context['audit_url'])
        self.assertEqual(parse_qs(urlsplit(response.context['audit_url']).query)['program'], ['distance'])
        self.assertIn('audit_filters=', response.context['pagination_query'])

    def test_question_bulk_return_keeps_the_original_list_filters(self):
        question = Question.objects.get()
        url = reverse('admin:quiz_question_changelist') + '?q=Sample'
        response = self.client.post(url, {'action': 'bulk_set_metadata', '_selected_action': [question.pk], 'index': 0})
        self.assertEqual(response.context['bulk_return_url'], url)
        token = response.context['form']['selection'].value()
        response = self.client.post(reverse('admin:quiz_question_bulk_metadata'), {'selection': token, 'difficulty': 'hard'})
        self.assertEqual(response.url, url)
        # A next parameter is rejected by the standard changelist before actions;
        # also check that the action itself never carries one into a return URL.
        request = RequestFactory().post(url + '&next=https://example.invalid')
        request.user = self.user
        model_admin = admin.site._registry[Question]
        with patch.object(model_admin, 'render_bulk_edit') as render:
            model_admin.start_bulk_edit(request, Question.objects.filter(pk=question.pk))
        self.assertEqual(render.call_args.args[3], url)

    def test_related_filters_are_searchable_and_keep_existing_lookup_urls(self):
        course = Course.objects.get()
        response = self.client.get(reverse('admin:quiz_question_changelist'), {'chapter__course__id__exact': course.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cl'].result_count, 1)
        self.assertContains(response, 'unfold-filter-autocomplete')

    def test_custom_pages_include_control_labels_and_named_confirmation_dialog(self):
        response = self.client.get(reverse('admin:index'))
        self.assertContains(response, 'content/admin_accessibility.js')
        self.assertContains(response, 'aria-label="Toggle navigation"')
        self.assertContains(response, 'x-bind:aria-expanded="navigationOpen"')
        response = self.client.get(reverse('admin:accounts_broadcast'))
        self.assertContains(response, 'aria-labelledby="confirm-broadcast-title"')
        self.assertContains(response, 'id="confirm-broadcast-description"')
