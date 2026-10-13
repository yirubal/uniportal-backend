from types import SimpleNamespace

from django.core.cache import caches
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from apps.accounts.models import Student
from apps.content.models import Course, Resource
from apps.quiz.models import Chapter, ExamPaper, Question, QuizAttempt
from apps.quiz.engine import get_performance_summary, get_practice_questions
from apps.quiz.selection import filter_topic_tags
from .serializers import ResourceSerializer
from .throttles import AuthRateThrottle, StudentRateThrottle, SubscriptionRateThrottle
from .views import _generate_jwt


class APIEfficiencyTests(APITestCase):
    def setUp(self):
        self.student = Student.objects.create(telegram_id=91001, first_name='Efficiency')
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + _generate_jwt(self.student))
        self.course = Course.objects.create(name='Efficiency course', code='EFF 101')
        self.paper = ExamPaper.objects.create(title='Efficiency paper', course=self.course, exam_type='quiz', year=2026, access_level='free', duration_minutes=30)
        self.chapter = Chapter.objects.create(course=self.course, number=1, title='Loops')

    def test_resource_course_serialization_uses_two_queries_at_different_list_sizes(self):
        for count in (3, 30):
            Resource.objects.all().delete()
            for index in range(count):
                resource = Resource.objects.create(title=str(index), status='published')
                resource.courses.add(self.course)
            with self.assertNumQueries(2):
                data = ResourceSerializer(Resource.objects.all().prefetch_related('courses'), many=True).data
            self.assertEqual(len(data), count)
            self.assertEqual(data[0]['course_codes'], ['EFF 101'])

    def test_papers_and_history_have_bounded_queries_with_nested_counts(self):
        for index in range(12):
            paper = ExamPaper.objects.create(title=str(index), exam_type='quiz', year=2000 + index, course=self.course, access_level='free')
            Question.objects.create(exam_paper=paper, chapter=self.chapter, text='Question')
            QuizAttempt.objects.create(student=self.student, exam_paper=paper, score=1, total_questions=1, gradable_total=1)
        with CaptureQueriesContext(connection) as queries:
            papers = self.client.get('/api/exams/')
        self.assertEqual(papers.status_code, 200)
        self.assertLessEqual(len(queries), 2)
        self.assertTrue(all(row['total_questions'] == 1 for row in papers.data if row['title'] != 'Efficiency paper'))
        with CaptureQueriesContext(connection) as queries:
            history = self.client.get('/api/quiz/attempts/')
        self.assertEqual(history.status_code, 200)
        self.assertLessEqual(len(queries), 2)
        self.assertNotIn('detailed_answers', queries[-1]['sql'])
        self.assertNotIn('selected_topics', queries[-1]['sql'])

    @override_settings(API_LEGACY_LIST_LIMIT=3)
    def test_opt_in_pagination_and_legacy_overflow_are_explicit(self):
        resources = [Resource.objects.create(title=str(index), status='published') for index in range(5)]
        for resource in resources:
            resource.courses.add(self.course)
        path = f'/api/courses/{self.course.pk}/resources/'
        self.assertEqual(self.client.get(path).status_code, 400)
        first = self.client.get(path, {'page': 1, 'page_size': 2})
        self.assertEqual(first.data['count'], 5)
        self.assertEqual(len(first.data['results']), 2)
        self.assertIsNotNone(first.data['next'])
        second = self.client.get(path, {'page': 2, 'page_size': 2})
        self.assertFalse({row['id'] for row in first.data['results']} & {row['id'] for row in second.data['results']})
        for size in ('abc', 0, 201):
            self.assertEqual(self.client.get(path, {'page_size': size}).status_code, 400)

    def test_legacy_history_remains_twenty_and_paged_history_can_go_further(self):
        QuizAttempt.objects.bulk_create([QuizAttempt(student=self.student, score=0, total_questions=1) for _ in range(25)])
        self.assertEqual(len(self.client.get('/api/quiz/attempts/').data), 20)
        response = self.client.get('/api/quiz/attempts/', {'page': 2, 'page_size': 20})
        self.assertEqual(response.data['count'], 25)
        self.assertEqual(len(response.data['results']), 5)

    def test_selection_filters_exact_tags_and_does_not_hydrate_unselected_questions(self):
        Question.objects.bulk_create([Question(exam_paper=self.paper, chapter=self.chapter, text=str(index),
                                              topic_tags=['Loops' if index % 2 else 'Nested Loops']) for index in range(600)])
        matched = filter_topic_tags(Question.objects.all(), ['Loops', 'Loops'])
        self.assertEqual(matched.count(), 300)
        with CaptureQueriesContext(connection) as queries:
            questions = get_practice_questions(self.paper.pk, is_premium=False, limit=20, topic='Loops')
        self.assertEqual(len(questions), 20)
        self.assertEqual(len({row.pk for row in questions}), 20)
        self.assertTrue(all(row.topic_tags == ['Loops'] for row in questions))
        self.assertEqual(len(queries), 3)
        self.assertIn('LIMIT 20', queries[1]['sql'])
        self.assertNotIn('"text"', queries[1]['sql'])
        with self.assertNumQueries(0):
            self.assertTrue(all(row.chapter.title == 'Loops' for row in questions))

    def test_performance_aggregates_all_attempts_but_fetches_bounded_history(self):
        QuizAttempt.objects.bulk_create([QuizAttempt(student=self.student, exam_paper=self.paper, score=1,
            total_questions=400, gradable_total=400, detailed_answers={'1': {'is_correct': False, 'topic_tags': ['Historical']}})
            for _ in range(100)])
        with CaptureQueriesContext(connection) as queries:
            summary = get_performance_summary(self.student)
        self.assertEqual(summary['total_attempts'], 100)
        self.assertEqual(summary['average_score'], 0.3)
        self.assertEqual(summary['best_score'], 0.3)
        self.assertEqual(summary['attempts_by_paper'][0]['average'], 0.3)
        self.assertEqual(summary['weak_topics'], ['Historical'])
        self.assertEqual(len(summary['score_over_time']), 30)
        self.assertEqual(len(queries), 4)
        self.assertIn('LIMIT 30', queries[1]['sql'])
        self.assertNotIn('detailed_answers', queries[1]['sql'])
        self.assertIn('LIMIT 20', queries[2]['sql'])
        self.assertEqual(QuizAttempt.objects.first().percentage, 0.3)

    def test_malformed_catalogue_filters_are_400(self):
        for path, params in [('/api/exams/', {'department': 'bad'}),
                             (f'/api/departments/1/courses/', {'year': 'bad'}),
                             (f'/api/courses/{self.course.pk}/resources/', {'search': 'a' * 201})]:
            self.assertEqual(self.client.get(path, params).status_code, 400)


class StudentThrottleTests(APITestCase):
    def setUp(self):
        caches['default'].clear()
        caches['throttles'].clear()

    def request(self, student, ip='127.0.0.1', forwarded=''):
        return SimpleNamespace(student=student, user=SimpleNamespace(is_authenticated=False),
                               META={'REMOTE_ADDR': ip, 'HTTP_X_FORWARDED_FOR': forwarded})

    def test_students_behind_one_ip_have_distinct_keys(self):
        throttle = StudentRateThrottle()
        first = throttle.get_cache_key(self.request(SimpleNamespace(pk=1)), None)
        second = throttle.get_cache_key(self.request(SimpleNamespace(pk=2)), None)
        self.assertNotEqual(first, second)
        self.assertEqual(first, throttle.get_cache_key(self.request(SimpleNamespace(pk=1), ip='10.0.0.1'), None))

    def test_payment_histories_are_shared_between_cache_clients(self):
        from django.core.cache.backends.db import DatabaseCache
        throttle = SubscriptionRateThrottle()
        throttle.num_requests = 1
        request = self.request(SimpleNamespace(pk=3))
        self.assertTrue(throttle.allow_request(request, None))
        other = SubscriptionRateThrottle()
        other.num_requests = 1
        other.cache = DatabaseCache('api_throttle_cache', {'KEY_PREFIX': 'uniportal-throttle'})
        self.assertFalse(other.allow_request(request, None))
        self.assertTrue(other.allow_request(self.request(SimpleNamespace(pk=4)), None))

    def test_untrusted_forwarded_ip_cannot_change_auth_key(self):
        throttle = AuthRateThrottle()
        request = self.request(None, forwarded='1.2.3.4')
        key = throttle.get_cache_key(request, None)
        request.META['HTTP_X_FORWARDED_FOR'] = '5.6.7.8'
        self.assertEqual(key, throttle.get_cache_key(request, None))
