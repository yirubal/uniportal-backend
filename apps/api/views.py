import asyncio
import mimetypes
import logging
import re
import threading
from pathlib import Path
from urllib.parse import quote, unquote

from botocore.exceptions import ClientError
from django.core import signing
from django.http import FileResponse
from django.urls import reverse
from django.utils.html import escape
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.conf import settings
from .throttles import AuthRateThrottle, SubscriptionRateThrottle

from apps.accounts.models import Student
from apps.accounts.auth import validate_telegram_init_data
from apps.content.models import Department, Course, CoursePlacement, Resource
from apps.exams.models import ExamTerm, StudentExam
from apps.quiz.models import ExamPaper, Question, QuizAttempt
from .serializers import (
    StudentSerializer,
    DepartmentSerializer,
    CourseSerializer,
    CoursePlacementSerializer,
    ResourceSerializer,
    QuestionSerializer,
    QuestionSimulationSerializer,
    ExamPaperSerializer,
    QuizAttemptSerializer,
)
from .permissions import IsTelegramAuthenticated, IsPremium, FreeQuotaNotExceeded

logger = logging.getLogger(__name__)

RESOURCE_DOWNLOAD_TOKEN_MAX_AGE = 900
RESOURCE_DOWNLOAD_TOKEN_SALT = 'apps.api.resource-download'
PAYMENT_REFERENCE_RE = re.compile(r'^[A-Z0-9]{6,50}$')
_telegram_webhook_loop = None
_telegram_webhook_thread = None
_telegram_webhook_loop_lock = threading.Lock()


def _run_telegram_webhook_loop(loop):
    asyncio.set_event_loop(loop)

    def keepalive():
        loop.call_later(0.25, keepalive)

    loop.call_soon(keepalive)
    loop.run_forever()


# ─── AUTH ─────────────────────────────────────────────────────────────────────

class TelegramAuthView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        init_data = request.data.get('init_data', '')

        if settings.DEBUG and request.data.get('dev_mode'):
            student, _ = Student.objects.get_or_create(
                telegram_id=request.data.get('telegram_id', 999999),
                defaults={
                    'first_name': request.data.get('first_name', 'Dev'),
                    'username': request.data.get('username', 'devuser'),
                }
            )
            token = _generate_jwt(student)
            return Response({
                'token': token,
                'student': StudentSerializer(student).data,
            })

        try:
            user_data = validate_telegram_init_data(init_data)
        except ValueError as e:
            return Response(
                {'error': 'AUTH_FAILED', 'message': str(e)},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # ── Channel membership gate ───────────────────────────────────────────
        # This runs for BOTH /start and the "Open App" menu button (which opens
        # the mini app directly, bypassing all bot handlers).
        channel_id = getattr(settings, 'TELEGRAM_OFFICIAL_CHANNEL_ID', '')
        if channel_id:
            from apps.accounts.notifications import check_channel_membership_sync
            if not check_channel_membership_sync(user_data['id']):
                return Response(
                    {
                        'error':       'CHANNEL_REQUIRED',
                        'message':     'You must join our official channel before using the app.',
                        'channel_url': getattr(
                            settings,
                            'TELEGRAM_CHANNEL_LINK',
                            'https://t.me/unityuniversityportal',
                        ),
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        student, created = Student.objects.update_or_create(
            telegram_id=user_data['id'],
            defaults={
                'first_name': user_data.get('first_name', ''),
                'last_name':  user_data.get('last_name', ''),
                'username':   user_data.get('username', ''),
            }
        )

        token = _generate_jwt(student)
        return Response({
            'token': token,
            'student': StudentSerializer(student).data,
        })


class TelegramWebhookView(APIView):
    """
    Receives Telegram updates via webhook POST requests.
    Telegram authenticates with the secret-token header configured on webhook setup.
    """
    permission_classes = []
    authentication_classes = []

    @staticmethod
    def get_event_loop():
        global _telegram_webhook_loop, _telegram_webhook_thread

        with _telegram_webhook_loop_lock:
            thread_dead = (
                _telegram_webhook_thread is None
                or not _telegram_webhook_thread.is_alive()
            )
            if (
                _telegram_webhook_loop is None
                or _telegram_webhook_loop.is_closed()
                or thread_dead
            ):
                _telegram_webhook_loop = asyncio.new_event_loop()
                _telegram_webhook_thread = threading.Thread(
                    target=_run_telegram_webhook_loop,
                    args=(_telegram_webhook_loop,),
                    daemon=True,
                )
                _telegram_webhook_thread.start()
            return _telegram_webhook_loop

    def post(self, request):
        secret = settings.TELEGRAM_WEBHOOK_SECRET
        if secret:
            token_header = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
            if token_header != secret:
                logger.warning('Webhook request with invalid secret token')
                return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

        if not settings.TELEGRAM_BOT_TOKEN:
            return Response({'error': 'Bot not configured'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            from apps.bot.application import process_telegram_update

            loop = self.get_event_loop()
            future = asyncio.run_coroutine_threadsafe(
                process_telegram_update(request.data),
                loop,
            )
            future.result(timeout=30)
            return Response({'ok': True})
        except Exception:
            logger.exception('Webhook processing error')
            # Telegram retries non-200 responses aggressively. Processing errors are
            # logged, but the request is acknowledged to avoid retry storms.
            return Response({'ok': True})



def _generate_jwt(student: Student) -> str:
    from rest_framework_simplejwt.tokens import RefreshToken
    refresh = RefreshToken()
    refresh['student_id']  = student.id
    refresh['telegram_id'] = student.telegram_id
    return str(refresh.access_token)


# ─── STUDENT ──────────────────────────────────────────────────────────────────

class StudentProfileView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        return Response(StudentSerializer(request.student).data)

    def patch(self, request):
        student = request.student
        serializer = StudentSerializer(student, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class StudentWatermarkView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        student  = request.student
        username = f'@{student.username}' if student.username else f'ID:{student.telegram_id}'
        watermark = f'{username} · {student.telegram_id} · Unity Uni'
        return Response({'watermark': watermark})


# ─── DEPARTMENTS ──────────────────────────────────────────────────────────────

class DepartmentListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        level       = request.query_params.get('level')
        departments = Department.objects.filter(is_active=True)
        if level:
            departments = departments.filter(level=level)
        return Response(DepartmentSerializer(departments, many=True).data)


# ─── COURSES ──────────────────────────────────────────────────────────────────

class CourseListView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request, department_id):
        program = request.query_params.get('program')
        year    = request.query_params.get('year')
        period  = request.query_params.get('period')

        placements = CoursePlacement.objects.filter(
            department_id=department_id,
        ).select_related('course')

        if program:
            placements = placements.filter(program=program)
        if year:
            placements = placements.filter(year=year)
        if period:
            placements = placements.filter(period=period)

        return Response(CoursePlacementSerializer(placements, many=True).data)


# ─── RESOURCES ────────────────────────────────────────────────────────────────

class ResourceListView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request, course_id):
        file_type = request.query_params.get('type')
        search    = request.query_params.get('search')

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

        return Response(
            ResourceSerializer(resources, many=True, context={'request': request}).data
        )


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

        if resource.access_level == Resource.ACCESS_PREMIUM and not student.is_premium:
            return Response(
                {
                    'error':            'INSUFFICIENT_ACCESS',
                    'message':          'Upgrade to premium to download this resource.',
                    'upgrade_required': True,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        student.reset_daily_quota()

        resource.downloads_count += 1
        resource.save(update_fields=['downloads_count'])

        student.downloads_today += 1
        student.save(update_fields=['downloads_today'])

        token = signing.dumps(
            {
                'resource_id': resource.id,
                'student_id': student.id,
                'file_name': resource.file.name,
            },
            salt=RESOURCE_DOWNLOAD_TOKEN_SALT,
        )
        download_path = reverse(
            'resource-download-file',
            kwargs={
                'resource_id': resource.id,
                'token': quote(token, safe=''),
            },
        )
        file_url = request.build_absolute_uri(download_path)
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
            as_attachment=True,
            filename=filename,
            content_type=content_type or 'application/octet-stream',
        )
        response['X-Content-Type-Options'] = 'nosniff'
        return response


def _resource_download_filename(resource):
    return Path(resource.file.name).name or f'resource-{resource.id}'


# ─── EXAM PAPERS ──────────────────────────────────────────────────────────────

class ExamPaperListView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        exam_type     = request.query_params.get('type')
        department_id = request.query_params.get('department')
        course_id     = request.query_params.get('course')

        exams = ExamPaper.objects.filter(is_active=True)

        if exam_type:
            exams = exams.filter(exam_type=exam_type)
        if department_id:
            exams = exams.filter(department_id=department_id)
        if course_id:
            exams = exams.filter(course_id=course_id)

        return Response(
            ExamPaperSerializer(exams, many=True, context={'request': request}).data
        )


class ExamPaperQuestionsView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request, exam_id):
        from apps.quiz.engine import get_simulation_questions, get_practice_questions

        student = request.student
        mode    = request.query_params.get('mode', 'simulation')

        if mode == 'practice':
            requested_limit = request.query_params.get('limit')
            questions = get_practice_questions(
                exam_paper_id=exam_id,
                is_premium=student.is_premium,
                limit=int(requested_limit) if requested_limit else None,
                topic=request.query_params.get('topic'),
            )
        else:
            questions = get_simulation_questions(
                exam_paper_id=exam_id,
                is_premium=student.is_premium,
            )

        if questions is None:
            try:
                exam = ExamPaper.objects.get(id=exam_id)
                if exam.access_level == ExamPaper.ACCESS_PREMIUM and not student.is_premium:
                    return Response(
                        {
                            'error':            'INSUFFICIENT_ACCESS',
                            'message':          'Upgrade to premium to access this exam.',
                            'upgrade_required': True,
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )
            except ExamPaper.DoesNotExist:
                pass
            return Response(
                {'error': 'NOT_FOUND', 'message': 'Exam not found or not ready.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer_class = (
            QuestionSerializer if mode == 'practice'
            else QuestionSimulationSerializer
        )
        return Response(serializer_class(questions, many=True).data)


class CourseTopicsView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request, course_id):
        try:
            course = Course.objects.get(id=course_id, is_active=True)
        except Course.DoesNotExist:
            return Response(
                {'detail': 'Course not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        questions = Question.objects.filter(
            exam_paper__course=course,
            exam_paper__is_active=True,
            is_active=True,
        )
        if not request.student.is_premium:
            questions = questions.filter(
                exam_paper__access_level=ExamPaper.ACCESS_FREE,
            )

        topics = set()
        for topic_list in questions.values_list('topic_tags', flat=True):
            if isinstance(topic_list, list):
                topics.update(topic for topic in topic_list if topic)

        sorted_topics = sorted(topics)
        return Response({
            'course_id': course.id,
            'course_name': course.name,
            'course_code': course.code,
            'total_topics': len(sorted_topics),
            'topics': sorted_topics,
        })


class SelectivePracticeView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def post(self, request):
        course_id = request.data.get('course_id')
        selected_topics = request.data.get('selected_topics', [])
        limit = request.data.get('limit', 50)

        if not course_id:
            return Response(
                {'detail': 'course_id is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(selected_topics, list) or not selected_topics:
            return Response(
                {'detail': 'selected_topics must be a non-empty list'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            limit = int(limit)
        except (TypeError, ValueError):
            return Response(
                {'detail': 'limit must be a number'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        limit = max(1, min(limit, 100))

        try:
            course = Course.objects.get(id=course_id, is_active=True)
        except Course.DoesNotExist:
            return Response(
                {'detail': 'Course not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        normalized_topics = [
            str(topic).strip()
            for topic in selected_topics
            if str(topic).strip()
        ]
        if not normalized_topics:
            return Response(
                {'detail': 'selected_topics must be a non-empty list'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        base_queryset = Question.objects.filter(
            exam_paper__course=course,
            exam_paper__is_active=True,
            is_active=True,
        ).select_related('exam_paper').order_by('id')

        if not request.student.is_premium:
            base_queryset = base_queryset.filter(
                exam_paper__access_level=ExamPaper.ACCESS_FREE,
            )

        filtered_questions = []
        for question in base_queryset:
            question_topics = question.topic_tags or []
            if any(topic in question_topics for topic in normalized_topics):
                filtered_questions.append(question)

        total_filtered_count = len(filtered_questions)
        filtered_questions = filtered_questions[:limit]

        if not filtered_questions:
            return Response(
                {
                    'detail': 'No questions found for selected topics',
                    'course_id': course.id,
                    'selected_topics': normalized_topics,
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({
            'course_id': course.id,
            'course_name': course.name,
            'course_code': course.code,
            'selected_topics': normalized_topics,
            'questions': QuestionSerializer(filtered_questions, many=True).data,
            'total_questions_in_course': base_queryset.count(),
            'filtered_count': total_filtered_count,
            'returned_count': len(filtered_questions),
            'can_start': True,
        })


class ActiveExamTermView(APIView):
    """Returns whether an active exam term exists."""

    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        term = ExamTerm.objects.filter(is_active=True).first()
        if not term:
            return Response({'active': False})

        return Response({
            'active': True,
            'year': term.year,
            'term': term.term,
            'center': term.center,
        })


class ExamLookupView(APIView):
    """
    Looks up a student's exam schedule by student ID or name.
    Query params: ?query=93372 OR ?query=Abirham
    Legacy params ?student_id= and ?name= are still supported.
    Returns all exams for the active term.
    """

    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        query = request.query_params.get('query', '').strip()

        if not query:
            query = request.query_params.get('student_id', '').strip()
        if not query:
            query = request.query_params.get('name', '').strip()

        if not query:
            return Response(
                {'error': 'Enter your student ID or name to search'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        term = ExamTerm.objects.filter(is_active=True).first()
        if not term:
            return Response(
                {'error': 'No active exam schedule available right now'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if query.isdigit():
            exams = StudentExam.objects.filter(
                term=term,
                student_id=query,
            ).select_related('session')

            if not exams.exists():
                return Response(
                    {'error': f'No exam found for ID {query}. Check your student ID.'},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            if len(query) < 3:
                return Response(
                    {'error': 'Enter at least 3 characters to search by name'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            exams = StudentExam.objects.filter(
                term=term,
                student_name__istartswith=query,
            ).select_related('session')

            if not exams.exists():
                first_word = query.split()[0]
                exams = StudentExam.objects.filter(
                    term=term,
                    student_name__istartswith=first_word + ' ',
                ).select_related('session')

            if not exams.exists():
                return Response(
                    {
                        'error': (
                            f'No exam found for "{query}". '
                            'Try your first name only or your student ID.'
                        )
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            if exams.count() > 20:
                return Response(
                    {
                        'error': (
                            f'Too many results for "{query}". '
                            'Please be more specific — try your full first name '
                            'or use your student ID instead.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        seen = set()
        results = []
        for exam in exams.order_by('session__date', 'session__start_time'):
            key = (exam.session.date, exam.course_code)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    'course_name': exam.course_name,
                    'course_code': exam.course_code,
                    'room_code': exam.room_code,
                    'department': exam.department,
                    'date': exam.session.date.strftime('%A, %B %d, %Y'),
                    'start_time': exam.session.start_time.strftime('%I:%M %p'),
                    'end_time': exam.session.end_time.strftime('%I:%M %p'),
                    'session': f'Session {exam.session.session_number}',
                }
            )

        first_exam = exams.first()
        return Response({
            'student_name': first_exam.student_name,
            'student_id': first_exam.student_id,
            'term': str(term),
            'exams': results,
        })


# ─── QUESTIONS ────────────────────────────────────────────────────────────────

class ExitExamTopicsView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        department_id = request.query_params.get('department')

        questions = Question.objects.filter(
            is_active=True,
            exam_paper__exam_type__in=[
                ExamPaper.TYPE_EXIT_REAL,
                ExamPaper.TYPE_EXIT_MODEL,
            ],
            exam_paper__is_active=True,
        )

        if department_id:
            # Filter through exam_paper since department is no longer on Question
            questions = questions.filter(
                exam_paper__department_id=department_id
            )

        topics = {}
        for q in questions.exclude(topic_tags=[]):
            for tag in (q.topic_tags or []):
                topics[tag] = topics.get(tag, 0) + 1

        result = [
            {'topic': topic, 'count': count}
            for topic, count in sorted(topics.items())
        ]
        return Response(result)


class TopicQuestionsView(APIView):
    """
    Returns questions filtered by topic tag.
    Used for topic-based practice mode.
    """
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        from apps.quiz.engine import get_topic_questions

        department_id = request.query_params.get('department')
        topic         = request.query_params.get('topic')
        limit         = int(request.query_params.get('limit', 20))

        if not department_id or not topic:
            return Response(
                {'error': 'INVALID', 'message': 'department and topic are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        questions = get_topic_questions(
            department_id=int(department_id),
            topic=topic,
            is_premium=request.student.is_premium,
            limit=limit,
        )

        return Response(QuestionSerializer(questions, many=True).data)


# ─── QUIZ ATTEMPTS ────────────────────────────────────────────────────────────

class QuizAttemptView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def post(self, request):
        from apps.quiz.engine import calculate_score

        student       = request.student
        answers       = request.data.get('answers', [])
        mode          = request.data.get('mode', 'practice')
        exam_paper_id = request.data.get('exam_paper_id')
        course_id     = request.data.get('course_id')
        department_id = request.data.get('department_id')
        selected_topics = request.data.get('selected_topics', [])

        if not answers:
            return Response(
                {'error': 'INVALID', 'message': 'No answers provided.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        question_ids = [a.get('question_id') for a in answers]
        questions    = list(Question.objects.filter(
            id__in=question_ids,
            is_active=True,
        ))

        if not questions:
            return Response(
                {'error': 'INVALID', 'message': 'No valid questions found.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = calculate_score(questions=questions, answers=answers)
        questions_map = {str(question.id): question for question in questions}
        result_map = {
            str(item['question_id']): item
            for item in result.get('results', [])
        }
        detailed_answers = {}

        for answer in answers:
            question_id = str(answer.get('question_id'))
            question = questions_map.get(question_id)
            scored = result_map.get(question_id, {})
            if not question:
                continue

            detailed_answers[question_id] = {
                'selected_option': answer.get('selected_option', ''),
                'correct_option': question.correct_option,
                'is_correct': scored.get('is_correct', False),
                'is_pending': scored.get('is_pending', False),
                'question_text': question.text,
                'question_type': question.question_type,
                'options': question.available_options,
                'explanation': question.explanation or '',
                'topic_tags': question.topic_tags or [],
            }

        attempt = QuizAttempt.objects.create(
            student=student,
            exam_paper_id=exam_paper_id,
            course_id=course_id,
            department_id=department_id,
            score=result['score'],
            total_questions=result['total'],
            answers={
                str(a['question_id']): a.get('selected_option', '')
                for a in answers
            },
            detailed_answers=detailed_answers,
            selected_topics=(
                selected_topics
                if mode == QuizAttempt.MODE_SELECTIVE and isinstance(selected_topics, list)
                else []
            ),
            mode=mode,
        )

        return Response({
            'attempt_id': attempt.id,
            'detailed_answers': detailed_answers,
            **result,
        }, status=status.HTTP_201_CREATED)

    def get(self, request):
        attempts = QuizAttempt.objects.filter(
            student=request.student
        ).select_related('exam_paper').order_by('-completed_at')[:20]

        return Response(QuizAttemptSerializer(attempts, many=True).data)


class QuizFeedbackView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request, attempt_id):
        from apps.quiz.engine import get_topics_with_low_score

        try:
            attempt = QuizAttempt.objects.get(
                id=attempt_id,
                student=request.student,
            )
        except QuizAttempt.DoesNotExist:
            return Response(
                {'detail': 'Attempt not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        detailed_answers = attempt.detailed_answers or {}

        return Response({
            'attempt_id': attempt.id,
            'score': attempt.score,
            'total_questions': attempt.total_questions,
            'percentage': attempt.percentage,
            'mode': attempt.mode,
            'completed_at': attempt.completed_at,
            'detailed_answers': detailed_answers,
            'summary': {
                'correct': sum(
                    1 for answer in detailed_answers.values()
                    if answer.get('is_correct')
                ),
                'incorrect': sum(
                    1 for answer in detailed_answers.values()
                    if not answer.get('is_correct')
                ),
                'topics_missed': get_topics_with_low_score(detailed_answers),
            },
        })


# ─── PERFORMANCE ──────────────────────────────────────────────────────────────

class PerformanceView(APIView):
    permission_classes = [IsTelegramAuthenticated, IsPremium]

    def get(self, request):
        from apps.quiz.engine import get_performance_summary
        return Response(get_performance_summary(request.student))


# ─── SUBSCRIPTION ─────────────────────────────────────────────────────────────

class SubscriptionPlansView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        from apps.accounts.models import SubscriptionPlan
        plans = SubscriptionPlan.objects.filter(is_active=True)
        data  = [
            {
                'id':          p.plan_id,
                'name':        p.name,
                'price':       float(p.price),
                'days':        p.days,
                'description': p.description,
                'badge':       p.badge,
            }
            for p in plans
        ]
        return Response(data)


class SubscriptionRequestView(APIView):
    permission_classes = [IsTelegramAuthenticated]
    throttle_classes = [SubscriptionRateThrottle]

    def post(self, request):
        import random
        import string
        from django.db import IntegrityError, transaction
        from apps.accounts.models import SiteSettings, SubscriptionPlan, SubscriptionRequest

        plan_id           = request.data.get('plan')
        payment_method    = (request.data.get('payment_method') or 'telebirr').strip().lower()
        payment_reference = _normalize_payment_reference(
            request.data.get('payment_reference', request.data.get('paid_from', ''))
        )

        try:
            plan = SubscriptionPlan.objects.get(plan_id=plan_id, is_active=True)
        except SubscriptionPlan.DoesNotExist:
            return Response(
                {'error': 'INVALID_PLAN', 'message': 'Invalid plan selected.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if payment_method not in dict(SubscriptionRequest.PAYMENT_CHOICES):
            return Response(
                {
                    'error': 'INVALID_PAYMENT_METHOD',
                    'message': 'Choose either Telebirr or CBE as the payment method.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing = SubscriptionRequest.objects.filter(
            student=request.student,
            status=SubscriptionRequest.STATUS_PENDING,
        ).select_related('plan').first()

        if existing:
            return _build_payment_response(existing, existing.plan)

        settings_obj = SiteSettings.get()
        if payment_method == SubscriptionRequest.PAYMENT_CBE and not settings_obj.cbe_account:
            return Response(
                {
                    'error': 'PAYMENT_METHOD_UNAVAILABLE',
                    'message': 'CBE payment is not available right now. Please use Telebirr.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        reference_error = _validate_payment_reference(payment_reference, payment_method)
        if reference_error:
            return Response(
                {
                    'error': 'INVALID_PAYMENT_REFERENCE',
                    'message': reference_error,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        created = False
        try:
            with transaction.atomic():
                existing = SubscriptionRequest.objects.select_for_update().filter(
                    student=request.student,
                    status=SubscriptionRequest.STATUS_PENDING,
                ).select_related('plan').first()

                if existing:
                    sub_request = existing
                else:
                    # Generate unique reference
                    while True:
                        reference = 'UNI-' + ''.join(random.choices(string.digits, k=5))
                        if not SubscriptionRequest.objects.filter(reference=reference).exists():
                            break

                    sub_request = SubscriptionRequest.objects.create(
                        student=request.student,
                        plan=plan,
                        reference=reference,
                        payment_method=payment_method,
                        paid_from=payment_reference,
                        payment_reference=payment_reference,
                        amount=plan.price,
                        status=SubscriptionRequest.STATUS_PENDING,
                    )
                    created = True
        except IntegrityError:
            sub_request = SubscriptionRequest.objects.filter(
                student=request.student,
                status=SubscriptionRequest.STATUS_PENDING,
            ).select_related('plan').first()
            if sub_request is None:
                raise

        if created:
            transaction.on_commit(lambda: _notify_subscription_request_created(sub_request))

        return _build_payment_response(sub_request, sub_request.plan)

    def get(self, request):
        from apps.accounts.models import SubscriptionRequest, SiteSettings

        active_request = SubscriptionRequest.objects.filter(
            student=request.student,
            status__in=[
                SubscriptionRequest.STATUS_PENDING,
                SubscriptionRequest.STATUS_APPROVED,
                SubscriptionRequest.STATUS_REJECTED,
            ],
        ).select_related('plan').first()

        settings_obj = SiteSettings.get()

        return Response({
            'has_pending_request': (
                active_request is not None
                and active_request.status == SubscriptionRequest.STATUS_PENDING
            ),
            'pending_request': _serialize_subscription_request(active_request)
            if active_request and active_request.status == SubscriptionRequest.STATUS_PENDING
            else None,
            'current_request': _serialize_subscription_request(active_request),
            'active_request': _serialize_subscription_request(active_request),
            'payment_options': _build_payment_options(settings_obj),
            'additional_instructions': settings_obj.payment_instructions or '',
        })


def _serialize_subscription_request(sub_request):
    if not sub_request:
        return None

    return {
        'reference': sub_request.reference,
        'plan': sub_request.plan.name,
        'amount': float(sub_request.amount),
        'status': sub_request.status,
        'payment_method': sub_request.payment_method,
        'payment_reference': sub_request.payment_reference or sub_request.paid_from,
        'requested_at': sub_request.requested_at,
        'updated_at': sub_request.updated_at,
    }


def _notify_subscription_request_created(sub_request):
    from apps.accounts.notifications import notify_subscription_request_created
    from apps.bot.notifications import send_admin_notification

    notify_subscription_request_created(sub_request)

    try:
        send_admin_notification(_build_admin_subscription_request_message(sub_request))
    except Exception as exc:
        logger.warning(
            'Admin subscription notification failed for request %s: %s',
            sub_request.reference,
            exc,
        )


def _build_admin_subscription_request_message(sub_request):
    student = sub_request.student
    full_name = f'{student.first_name} {student.last_name}'.strip() or 'Student'
    username = f'@{student.username}' if student.username else 'No username'
    payment_reference = sub_request.payment_reference or sub_request.paid_from or 'Not provided'

    return (
        '💰 New Subscription Request\n\n'
        f'Student: {escape(full_name)} ({escape(username)})\n'
        f'Plan: {escape(sub_request.plan.name)} — ETB {sub_request.plan.price}\n'
        f'Payment: {escape(sub_request.payment_method)} from {escape(payment_reference)}\n'
        f'Reference: {escape(sub_request.reference)}\n'
        f'Amount: ETB {sub_request.amount}\n\n'
        '👉 Review: https://web-production-312b.up.railway.app/admin/accounts/subscriptionrequest/'
    )


def _build_payment_response(sub_request, plan):
    from apps.accounts.models import SiteSettings
    from rest_framework.response import Response

    settings_obj = SiteSettings.get()

    payment_options = _build_payment_options(settings_obj)

    return Response({
        'reference':               sub_request.reference,
        'plan':                    plan.name,
        'amount':                  float(plan.price),
        'days':                    plan.days,
        'status':                  sub_request.status,
        'payment_method':          sub_request.payment_method,
        'payment_reference':       sub_request.payment_reference or sub_request.paid_from,
        'payment_destination':     _build_payment_destination(sub_request.payment_method, payment_options),
        'note':                    f'Include reference {sub_request.reference} in your payment note.',
        'additional_instructions': settings_obj.payment_instructions or '',
        'payment_options':         payment_options,
    })


def _normalize_payment_reference(raw_reference):
    return str(raw_reference or '').strip().upper()


def _build_payment_options(settings_obj):
    return {
        'telebirr': {
            'number': settings_obj.telebirr_number,
            'name': settings_obj.telebirr_name,
        },
        'cbe': {
            'account': settings_obj.cbe_account,
            'name': settings_obj.cbe_name,
        } if settings_obj.cbe_account else None,
    }


def _validate_payment_reference(payment_reference, payment_method):
    if not payment_reference:
        if payment_method == 'cbe':
            return 'Enter the CBE transaction ID from your receipt.'
        return 'Enter the Telebirr transaction number from your receipt.'

    if not PAYMENT_REFERENCE_RE.fullmatch(payment_reference):
        return 'Use 6-50 characters with capital letters and numbers only.'

    if not any(char.isalpha() for char in payment_reference):
        return 'The transaction reference must include at least one capital letter.'

    if not any(char.isdigit() for char in payment_reference):
        return 'The transaction reference must include at least one number.'

    return None


def _build_payment_destination(payment_method, payment_options):
    destination = payment_options.get(payment_method)
    if not destination:
        return None

    if payment_method == 'cbe':
        return {
            'method': 'cbe',
            'label': 'CBE account number',
            'value': destination['account'],
            'name': destination['name'],
        }

    return {
        'method': 'telebirr',
        'label': 'Telebirr number',
        'value': destination['number'],
        'name': destination['name'],
    }
