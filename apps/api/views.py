from django.shortcuts import render

# Create your views here.
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.utils import timezone
from django.conf import settings

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


# ─── AUTH ────────────────────────────────────────────────────────────────────

class TelegramAuthView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        init_data = request.data.get('init_data', '')

        # Dev mode — allow mock login
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

        # Create or update student
        student, created = Student.objects.update_or_create(
            telegram_id=user_data['id'],
            defaults={
                'first_name': user_data.get('first_name', ''),
                'last_name': user_data.get('last_name', ''),
                'username': user_data.get('username', ''),
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
    refresh['student_id'] = student.id
    refresh['telegram_id'] = student.telegram_id
    return str(refresh.access_token)


# ─── STUDENT ─────────────────────────────────────────────────────────────────

class StudentProfileView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        return Response(StudentSerializer(request.student).data)

    def patch(self, request):
        student = request.student
        allowed_fields = [
            'preferred_department',
            'preferred_program',
            'preferred_year',
            'preferred_period',
            'onboarding_complete',
        ]
        for field in allowed_fields:
            if field in request.data:
                setattr(student, field, request.data[field])
        student.save()
        return Response(StudentSerializer(student).data)


class StudentWatermarkView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        student = request.student
        username = f'@{student.username}' if student.username else f'ID:{student.telegram_id}'
        watermark = f'{username} · {student.telegram_id} · Unity Uni'
        return Response({'watermark': watermark})


# ─── DEPARTMENTS ─────────────────────────────────────────────────────────────

class DepartmentListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        level = request.query_params.get('level')
        departments = Department.objects.filter(is_active=True)
        if level:
            departments = departments.filter(level=level)
        return Response(DepartmentSerializer(departments, many=True).data)


# ─── COURSES ─────────────────────────────────────────────────────────────────

class CourseListView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request, department_id):
        program = request.query_params.get('program')
        year = request.query_params.get('year')
        period = request.query_params.get('period')

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


# ─── RESOURCES ───────────────────────────────────────────────────────────────

class ResourceListView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request, course_id):
        file_type = request.query_params.get('type')
        search = request.query_params.get('search')

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
            ResourceSerializer(
                resources,
                many=True,
                context={'request': request}
            ).data
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

        # Check access
        if resource.access_level == Resource.ACCESS_PREMIUM and not student.is_premium:
            return Response(
                {
                    'error': 'INSUFFICIENT_ACCESS',
                    'message': 'Upgrade to premium to download this resource.',
                    'upgrade_required': True,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Reset quota if needed
        student.reset_daily_quota()

        # Log download
        resource.downloads_count += 1
        resource.save(update_fields=['downloads_count'])

        student.downloads_today += 1
        student.save(update_fields=['downloads_today'])

        # Return download URL
        file_url = request.build_absolute_uri(resource.file.url)
        return Response({
            'url': file_url,
            'filename': resource.file.name.split('/')[-1],
        })


# ─── QUIZ ─────────────────────────────────────────────────────────────────────

class QuestionListView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request, course_id):
        import random

        student = request.student
        mode = request.query_params.get('mode', 'practice')
        limit = int(request.query_params.get('limit', 10))
        topic = request.query_params.get('topic')

        questions = Question.objects.filter(
            course_id=course_id,
            is_active=True,
        )

        # Free users only get free questions
        if not student.is_premium:
            questions = questions.filter(access_level=Question.ACCESS_FREE)
            limit = min(limit, 5)

        if topic:
            questions = questions.filter(topic_tags__contains=topic)

        questions = list(questions)
        random.shuffle(questions)
        questions = questions[:limit]

        serializer = QuestionSerializer if mode == 'practice' else QuestionSimulationSerializer
        return Response(serializer(questions, many=True).data)


class ExamPaperListView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        exam_type = request.query_params.get('type')
        department_id = request.query_params.get('department')

        exams = ExamPaper.objects.filter(is_active=True)

        if exam_type:
            exams = exams.filter(exam_type=exam_type)

        if department_id:
            exams = exams.filter(
                course__placements__department_id=department_id
            ).distinct()

        return Response(
            ExamPaperSerializer(
                exams,
                many=True,
                context={'request': request}
            ).data
        )


class ExamPaperQuestionsView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request, exam_id):
        try:
            exam = ExamPaper.objects.get(id=exam_id, is_active=True)
        except ExamPaper.DoesNotExist:
            return Response(
                {'error': 'NOT_FOUND', 'message': 'Exam not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check access
        if exam.access_level == ExamPaper.ACCESS_PREMIUM and not request.student.is_premium:
            return Response(
                {
                    'error': 'INSUFFICIENT_ACCESS',
                    'message': 'Upgrade to premium to access this exam.',
                    'upgrade_required': True,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        questions = exam.questions.filter(is_active=True)
        mode = request.query_params.get('mode', 'simulation')
        serializer = QuestionSerializer if mode == 'practice' else QuestionSimulationSerializer

        return Response(serializer(questions, many=True).data)


class ExitExamTopicsView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        department_id = request.query_params.get('department')

        questions = Question.objects.filter(
            is_active=True,
            exam_paper__exam_type=ExamPaper.TYPE_EXIT,
        )

        if department_id:
            questions = questions.filter(
                course__placements__department_id=department_id
            )

        # Collect all topic tags
        topics = {}
        for q in questions.exclude(topic_tags=[]):
            for tag in q.topic_tags:
                topics[tag] = topics.get(tag, 0) + 1

        result = [
            {'topic': topic, 'count': count}
            for topic, count in sorted(topics.items())
        ]
        return Response(result)


class QuizAttemptView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def post(self, request):
        student = request.student
        answers = request.data.get('answers', [])
        mode = request.data.get('mode', 'practice')
        course_id = request.data.get('course_id')
        exam_paper_id = request.data.get('exam_paper_id')

        if not answers:
            return Response(
                {'error': 'INVALID', 'message': 'No answers provided.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Calculate score
        score = 0
        total = len(answers)
        results = []

        for answer in answers:
            question_id = answer.get('question_id')
            selected = answer.get('selected_option')

            try:
                question = Question.objects.get(id=question_id, is_active=True)
                is_correct = question.correct_option == selected
                if is_correct:
                    score += 1
                results.append({
                    'question_id': question_id,
                    'question': question.text,
                    'selected_option': selected,
                    'correct_option': question.correct_option,
                    'is_correct': is_correct,
                    'explanation': question.explanation,
                    'options': question.available_options,
                })
            except Question.DoesNotExist:
                pass

        percentage = round((score / total) * 100, 1) if total > 0 else 0

        # Save attempt
        attempt = QuizAttempt.objects.create(
            student=student,
            course_id=course_id,
            exam_paper_id=exam_paper_id,
            score=score,
            total_questions=total,
            answers={a['question_id']: a['selected_option'] for a in answers},
            mode=mode,
        )

        return Response({
            'attempt_id': attempt.id,
            'score': score,
            'total': total,
            'percentage': percentage,
            'passed': percentage >= 50,
            'results': results,
        })

    def get(self, request):
        attempts = QuizAttempt.objects.filter(
            student=request.student
        ).order_by('-completed_at')[:20]
        return Response(QuizAttemptSerializer(attempts, many=True).data)


# ─── PERFORMANCE ─────────────────────────────────────────────────────────────

class PerformanceView(APIView):
    permission_classes = [IsTelegramAuthenticated, IsPremium]

    def get(self, request):
        student = request.student
        attempts = QuizAttempt.objects.filter(student=student)

        total_attempts = attempts.count()
        if total_attempts == 0:
            return Response({
                'total_attempts': 0,
                'average_score': 0,
                'best_score': 0,
                'weak_topics': [],
                'score_over_time': [],
                'attempts_by_course': [],
            })

        scores = [a.percentage for a in attempts]
        average_score = round(sum(scores) / len(scores), 1)
        best_score = max(scores)

        # Score over time
        score_over_time = [
            {
                'date': a.completed_at.strftime('%Y-%m-%d'),
                'score': a.percentage,
            }
            for a in attempts.order_by('completed_at')[:30]
        ]

        return Response({
            'total_attempts': total_attempts,
            'average_score': average_score,
            'best_score': best_score,
            'weak_topics': [],
            'score_over_time': score_over_time,
            'attempts_by_course': [],
        })


# ─── SUBSCRIPTION ─────────────────────────────────────────────────────────────

class SubscriptionPlansView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        from apps.accounts.models import SubscriptionPlan
        plans = SubscriptionPlan.objects.filter(is_active=True)
        data = [
            {
                'id': p.plan_id,
                'name': p.name,
                'price': float(p.price),
                'days': p.days,
                'description': p.description,
                'badge': p.badge,
            }
            for p in plans
        ]
        return Response(data)


class SubscriptionRequestView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def post(self, request):
        import random
        import string
        from apps.accounts.models import SubscriptionPlan, SiteSettings

        plan_id = request.data.get('plan')

        try:
            plan = SubscriptionPlan.objects.get(
                plan_id=plan_id,
                is_active=True,
            )
        except SubscriptionPlan.DoesNotExist:
            return Response(
                {'error': 'INVALID_PLAN', 'message': 'Invalid plan selected.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        settings_obj = SiteSettings.get()
        reference = 'UNI-' + ''.join(random.choices(string.digits, k=5))

        # Build payment instructions
        instructions = f'Send ETB {plan.price} to Telebirr: {settings_obj.telebirr_number}'
        if settings_obj.telebirr_name:
            instructions += f' ({settings_obj.telebirr_name})'

        additional = settings_obj.payment_instructions or ''

        return Response({
            'reference': reference,
            'plan': plan.name,
            'amount': float(plan.price),
            'instructions': instructions,
            'note': f'Include reference {reference} in your payment note.',
            'additional_instructions': additional,
            'days': plan.days,
            'payment_options': {
                'telebirr': {
                    'number': settings_obj.telebirr_number,
                    'name': settings_obj.telebirr_name,
                },
                'cbe': {
                    'account': settings_obj.cbe_account,
                    'name': settings_obj.cbe_name,
                } if settings_obj.cbe_account else None,
            }
        })