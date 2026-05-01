import mimetypes
import logging
from pathlib import Path
from urllib.parse import urlencode

from botocore.exceptions import ClientError
from django.core import signing
from django.http import FileResponse
from django.urls import reverse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.conf import settings
from .throttles import AuthRateThrottle, SubscriptionRateThrottle

from apps.accounts.models import Student
from apps.accounts.auth import validate_telegram_init_data
from apps.content.models import Department, Course, CoursePlacement, Resource
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

RESOURCE_DOWNLOAD_TOKEN_MAX_AGE = 300
RESOURCE_DOWNLOAD_TOKEN_SALT = 'apps.api.resource-download'


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
            course_id=course_id,
            status=Resource.STATUS_PUBLISHED,
        )

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
            resource = Resource.objects.get(
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
            kwargs={'resource_id': resource.id},
        )
        file_url = request.build_absolute_uri(
            f'{download_path}?{urlencode({"token": token})}'
        )
        return Response({
            'url':      file_url,
            'filename': _resource_download_filename(resource),
            'expires_in': RESOURCE_DOWNLOAD_TOKEN_MAX_AGE,
        })


class ResourceDownloadFileView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, resource_id):
        token = request.query_params.get('token', '')
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
            questions = get_practice_questions(
                exam_paper_id=exam_id,
                is_premium=student.is_premium,
                limit=int(request.query_params.get('limit', 10)),
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
            mode=mode,
        )

        return Response({
            'attempt_id': attempt.id,
            **result,
        }, status=status.HTTP_201_CREATED)

    def get(self, request):
        attempts = QuizAttempt.objects.filter(
            student=request.student
        ).select_related('exam_paper').order_by('-completed_at')[:20]

        return Response(QuizAttemptSerializer(attempts, many=True).data)


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
        from apps.accounts.models import SubscriptionPlan, SubscriptionRequest
        from apps.accounts.notifications import notify_subscription_request_created

        plan_id        = request.data.get('plan')
        payment_method = request.data.get('payment_method', 'telebirr')  # telebirr or cbe
        paid_from      = request.data.get('paid_from', '')  # phone or account number student paid from

        try:
            plan = SubscriptionPlan.objects.get(plan_id=plan_id, is_active=True)
        except SubscriptionPlan.DoesNotExist:
            return Response(
                {'error': 'INVALID_PLAN', 'message': 'Invalid plan selected.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing = SubscriptionRequest.objects.filter(
            student=request.student,
            status=SubscriptionRequest.STATUS_PENDING,
        ).select_related('plan').first()

        if existing:
            return _build_payment_response(existing, existing.plan)

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
                        paid_from=paid_from,
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
            transaction.on_commit(lambda: notify_subscription_request_created(sub_request))

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
            'payment_options': {
                'telebirr': {
                    'number': settings_obj.telebirr_number,
                    'name': settings_obj.telebirr_name,
                },
                'cbe': {
                    'account': settings_obj.cbe_account,
                    'name': settings_obj.cbe_name,
                } if settings_obj.cbe_account else None,
            },
        })


def _serialize_subscription_request(sub_request):
    if not sub_request:
        return None

    return {
        'reference': sub_request.reference,
        'plan': sub_request.plan.name,
        'amount': float(sub_request.amount),
        'status': sub_request.status,
        'requested_at': sub_request.requested_at,
        'updated_at': sub_request.updated_at,
    }


def _build_payment_response(sub_request, plan):
    from apps.accounts.models import SiteSettings
    from rest_framework.response import Response

    settings_obj = SiteSettings.get()

    payment_options = {
        'telebirr': {
            'number': settings_obj.telebirr_number,
            'name':   settings_obj.telebirr_name,
        },
    }
    if settings_obj.cbe_account:
        payment_options['cbe'] = {
            'account': settings_obj.cbe_account,
            'name':    settings_obj.cbe_name,
        }

    return Response({
        'reference':               sub_request.reference,
        'plan':                    plan.name,
        'amount':                  float(plan.price),
        'days':                    plan.days,
        'status':                  sub_request.status,
        'note':                    f'Include reference {sub_request.reference} in your payment note.',
        'additional_instructions': settings_obj.payment_instructions or '',
        'payment_options':         payment_options,
    })
