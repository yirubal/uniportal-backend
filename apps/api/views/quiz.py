"""Quiz API endpoints."""
import re
from django.db.models import Count, Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from ..pagination import list_response
from apps.content.models import Course
from apps.quiz.models import Chapter, ExamPaper, Question, QuizAttempt
from ..serializers import ChapterSerializer, QuestionSerializer, QuestionSimulationSerializer, ExamPaperSerializer, QuizAttemptSerializer, PaperQuestionInputSerializer, TopicQuestionInputSerializer, SelectivePracticeInputSerializer, QuizSubmissionInputSerializer, MAX_QUIZ_QUESTIONS, ExamFilterInputSerializer, TopicCountSerializer
from ..permissions import IsTelegramAuthenticated




class ExamPaperListView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        inputs = ExamFilterInputSerializer(data=request.query_params)
        inputs.is_valid(raise_exception=True)
        params = inputs.validated_data
        exam_type, department_id, course_id = params.get('type'), params.get('department'), params.get('course')

        exams = ExamPaper.objects.filter(is_active=True).select_related('course', 'department').annotate(
            active_question_count=Count('questions', filter=Q(questions__is_active=True)),
        )

        if exam_type:
            exams = exams.filter(exam_type=exam_type)
        if department_id:
            exams = exams.filter(department_id=department_id)
        if course_id:
            exams = exams.filter(course_id=course_id)

        return list_response(exams.order_by('-year', '-pk'), ExamPaperSerializer, request)


class ExamPaperQuestionsView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request, exam_id):
        from apps.quiz.engine import get_simulation_questions, get_practice_questions

        student = request.student
        inputs = PaperQuestionInputSerializer(data=request.query_params)
        inputs.is_valid(raise_exception=True)
        params = inputs.validated_data
        mode = params['mode']

        if mode == 'practice':
            questions = get_practice_questions(
                exam_paper_id=exam_id,
                is_premium=student.is_premium,
                limit=params.get('limit'),
                topic=params.get('topic'),
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

        if mode == 'simulation':
            from apps.quiz.services import open_simulation
            if len(questions) > MAX_QUIZ_QUESTIONS:
                return Response({'detail': 'Paper exceeds the 500-question simulation limit.'}, status=400)
            simulation = open_simulation(student, exam_id, questions)
            return Response(
                QuestionSimulationSerializer(simulation.question_snapshot, many=True).data,
                headers={'X-Quiz-Simulation-ID': str(simulation.pk)},
            )
        return Response(QuestionSerializer(questions, many=True).data)


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

        chapter_counts = {}
        other_topics = set()
        all_topics = set()
        for topic_list in questions.values_list('topic_tags', flat=True).iterator(chunk_size=500):
            if not isinstance(topic_list, list) or not topic_list:
                continue

            cleaned_topics = [str(topic).strip() for topic in topic_list if str(topic).strip()]
            if not cleaned_topics:
                continue

            chapter = cleaned_topics[0]
            chapter_counts[chapter] = chapter_counts.get(chapter, 0) + 1
            all_topics.update(cleaned_topics)
            other_topics.update(cleaned_topics[1:])

        chapters = sorted(
            chapter_counts,
            key=lambda chapter: (
                self._chapter_number(chapter),
                chapter.lower(),
            ),
        )
        chapters_with_count = [
            {
                'name': chapter,
                'question_count': chapter_counts[chapter],
            }
            for chapter in chapters
        ]

        return Response({
            'course_id': course.id,
            'course_name': course.name,
            'course_code': course.code,
            'total_chapters': len(chapters),
            'chapters': chapters,
            'chapters_with_count': chapters_with_count,
            'total_topics': len(all_topics),
            'topics': sorted(all_topics),
            'other_topics': sorted(other_topics),
        })

    @staticmethod
    def _chapter_number(chapter):
        match = re.search(r'\d+', chapter)
        return int(match.group()) if match else 999


class CourseChaptersView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request, course_id):
        try:
            course = Course.objects.get(id=course_id, is_active=True)
        except Course.DoesNotExist:
            return Response(
                {'detail': 'Course not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        chapters = Chapter.objects.filter(
            course=course,
            is_active=True,
        ).annotate(active_question_count=Count('questions', filter=Q(questions__is_active=True))).order_by('order', 'number', 'pk')

        page = list_response(chapters, ChapterSerializer, request)
        paginated = isinstance(page.data, dict)
        data = {
            'course_id': course.id, 'course_name': course.name, 'course_code': course.code,
            'total_chapters': page.data['count'] if paginated else len(page.data),
            'chapters': page.data['results'] if paginated else page.data,
        }
        if paginated:
            data.update(next=page.data['next'], previous=page.data['previous'])
        return Response(data)


class SelectivePracticeView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def post(self, request):
        inputs = SelectivePracticeInputSerializer(data=request.data)
        inputs.is_valid(raise_exception=True)
        params = inputs.validated_data
        course_id = params['course_id']
        selected_topics = params['selected_topics']
        limit = params['limit']

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

        from apps.quiz.selection import filter_topic_tags
        matching = filter_topic_tags(base_queryset, normalized_topics)
        total_filtered_count = matching.count()
        filtered_questions = list(matching.select_related('chapter')[:limit])

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


class ExitExamTopicsView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        inputs = ExamFilterInputSerializer(data=request.query_params)
        inputs.is_valid(raise_exception=True)
        department_id = inputs.validated_data.get('department')

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
        for tags in questions.exclude(topic_tags=[]).values_list('topic_tags', flat=True).iterator(chunk_size=500):
            for tag in (tags or []):
                topics[tag] = topics.get(tag, 0) + 1

        result = [
            {'topic': topic, 'count': count}
            for topic, count in sorted(topics.items())
        ]
        return list_response(result, TopicCountSerializer, request)


class TopicQuestionsView(APIView):
    """
    Returns questions filtered by topic tag.
    Used for topic-based practice mode.
    """
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        from apps.quiz.engine import get_topic_questions

        inputs = TopicQuestionInputSerializer(data=request.query_params)
        inputs.is_valid(raise_exception=True)
        params = inputs.validated_data

        questions = get_topic_questions(
            department_id=params['department'],
            topic=params['topic'],
            is_premium=request.student.is_premium,
            limit=params['limit'],
        )

        return Response(QuestionSerializer(questions, many=True).data)


class QuizAttemptView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def post(self, request):
        from apps.quiz.services import submit_quiz

        inputs = QuizSubmissionInputSerializer(data=request.data)
        inputs.is_valid(raise_exception=True)
        result = submit_quiz(request.student, inputs.validated_data)
        return Response(result, status=status.HTTP_201_CREATED)

    def get(self, request):
        attempts = QuizAttempt.objects.filter(student=request.student).defer(
            'answers', 'detailed_answers', 'selected_topics',
        ).select_related(
            'exam_paper__course', 'exam_paper__department',
        ).annotate(active_question_count=Count(
            'exam_paper__questions', filter=Q(exam_paper__questions__is_active=True),
        )).order_by('-completed_at', '-pk')
        if 'page' not in request.query_params and 'page_size' not in request.query_params:
            attempts = attempts[:20]  # Preserve the existing recent-history array.
        return list_response(attempts, QuizAttemptSerializer, request, legacy_limit=20)


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
            'gradable_total': attempt.gradable_total,
            'pending_count': attempt.pending_count,
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
                    if not answer.get('is_correct') and not answer.get('is_pending')
                ),
                'topics_missed': get_topics_with_low_score(detailed_answers),
            },
        })
