from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from apps.accounts.models import Student
from apps.content.models import Course, Department
from .engine import calculate_score
from .models import ExamPaper, Question, QuizAttempt, QuizSimulation

SNAPSHOT_FIELDS = (
    'id', 'text', 'question_type', 'option_a', 'option_b', 'option_c', 'option_d',
    'option_e', 'correct_option', 'explanation', 'difficulty', 'topic_tags', 'year_source',
)


class SimulationCompleted(APIException):
    status_code = 409
    default_detail = 'This simulation is already completed. Open the paper to start another.'


def open_simulation(student, paper_id, questions):
    """Refreshes resume an issued paper; completed/expired papers start a new one."""
    with transaction.atomic():
        Student.objects.select_for_update().get(pk=student.pk)
        simulation = QuizSimulation.objects.filter(
            student=student, exam_paper_id=paper_id,
            completed_at__isnull=True, expires_at__gt=timezone.now(),
        ).order_by('-created_at').first()
        if simulation:
            return simulation
        snapshot = []
        for question in questions:
            row = {field: getattr(question, field) for field in SNAPSHOT_FIELDS}
            row.update({
                'available_options': question.available_options,
                'is_auto_gradable': question.is_auto_gradable,
                'chapter_id': question.chapter_id,
                'chapter': {'number': question.chapter.number, 'title': question.chapter.title}
                if question.chapter_id else None,
            })
            snapshot.append(row)
        return QuizSimulation.objects.create(
            student=student, exam_paper_id=paper_id, question_snapshot=snapshot,
            expires_at=timezone.now() + timedelta(days=1),
        )


def validate_quiz_context(data, questions):
    paper_id = data.get('exam_paper_id')
    course_id = data.get('course_id')
    department_id = data.get('department_id')
    if paper_id and not ExamPaper.objects.filter(pk=paper_id, is_active=True).exists():
        raise ValidationError({'exam_paper_id': 'Unknown or inactive exam paper.'})
    if course_id and not Course.objects.filter(pk=course_id, is_active=True).exists():
        raise ValidationError({'course_id': 'Unknown or inactive course.'})
    if department_id and not Department.objects.filter(pk=department_id, is_active=True).exists():
        raise ValidationError({'department_id': 'Unknown or inactive department.'})
    allowed_papers = ExamPaper.objects.filter(is_active=True)
    if paper_id:
        allowed_papers = allowed_papers.filter(pk=paper_id)
    if course_id:
        allowed_papers = allowed_papers.filter(course_id=course_id)
    if department_id:
        allowed_papers = allowed_papers.filter(
            Q(department_id=department_id) | Q(course__placements__department_id=department_id),
        )
    allowed_ids = set(allowed_papers.values_list('pk', flat=True))
    if any(question.exam_paper_id not in allowed_ids for question in questions):
        raise ValidationError({'answers': 'Questions do not belong to the supplied quiz context.'})
    if data['mode'] == QuizAttempt.MODE_SELECTIVE:
        selected = set(data['selected_topics'])
        if any(not selected.intersection(question.topic_tags or []) for question in questions):
            raise ValidationError({'selected_topics': 'Questions do not match the selected topics.'})
    question_map = {question.pk: question for question in questions}
    for answer in data['answers']:
        question = question_map[answer['question_id']]
        selected = answer['selected_option']
        if question.question_type in (Question.TYPE_MCQ, Question.TYPE_TRUE_FALSE) and selected:
            if selected.lower() not in question.available_options:
                raise ValidationError({'answers': f'Invalid option for question {question.pk}.'})


def save_quiz_attempt(student, data, questions):
    result = calculate_score(questions, data['answers'])
    question_map = {question.pk: question for question in questions}
    details = {}
    for scored in result['results']:
        question = question_map[scored['question_id']]
        details[str(question.pk)] = {
            'selected_option': scored['selected_option'],
            'correct_option': question.correct_option,
            'is_correct': scored['is_correct'],
            'is_pending': scored['is_pending'],
            'is_unanswered': not bool(scored['selected_option']),
            'question_text': question.text,
            'question_type': question.question_type,
            'options': question.available_options,
            'explanation': question.explanation or '',
            'topic_tags': question.topic_tags or [],
        }
    attempt = QuizAttempt.objects.create(
        student=student, exam_paper_id=data.get('exam_paper_id'),
        course_id=data.get('course_id'), department_id=data.get('department_id'),
        score=result['score'], total_questions=result['total'],
        gradable_total=result['gradable_total'], pending_count=result['pending_count'],
        answers={key: value['selected_option'] for key, value in details.items()},
        detailed_answers=details,
        selected_topics=data['selected_topics'] if data['mode'] == QuizAttempt.MODE_SELECTIVE else [],
        mode=data['mode'],
    )
    return {'attempt_id': attempt.pk, 'detailed_answers': details, **result}


def submit_quiz(student, data):
    ids = {answer['question_id'] for answer in data['answers']}
    if data['mode'] != QuizAttempt.MODE_SIMULATION:
        questions = list(Question.objects.filter(pk__in=ids, is_active=True).select_related('exam_paper'))
        if len(questions) != len(ids):
            raise ValidationError({'answers': 'Unknown or inactive question IDs.'})
        validate_quiz_context(data, questions)
        return save_quiz_attempt(student, data, questions)

    with transaction.atomic():
        simulations = QuizSimulation.objects.select_for_update().filter(
            student=student, exam_paper_id=data['exam_paper_id'],
        )
        if data.get('simulation_id'):
            simulations = simulations.filter(pk=data['simulation_id'])
        simulation = simulations.order_by('-created_at').first()
        if simulation is None:
            raise ValidationError({'simulation_id': 'Open this paper in simulation mode before submitting.'})
        if simulation.completed_at:
            raise SimulationCompleted()
        if simulation.expires_at <= timezone.now():
            raise ValidationError({'simulation_id': 'Simulation expired. Open the paper again.'})
        questions = [Question(**{field: row[field] for field in SNAPSHOT_FIELDS}, exam_paper_id=simulation.exam_paper_id)
                     for row in simulation.question_snapshot]
        if not ids.issubset({question.pk for question in questions}):
            raise ValidationError({'answers': 'Answers contain questions that were not issued.'})
        validate_quiz_context(data, questions)
        response = save_quiz_attempt(student, data, questions)
        simulation.attempt_id = response['attempt_id']
        simulation.completed_at = timezone.now()
        simulation.save(update_fields=['attempt', 'completed_at'])
        return response
