import logging
from .scoring import quiz_percentage
from .selection import filter_topic_tags, select_random_questions
from apps.quiz.models import Question, QuizAttempt, ExamPaper

logger = logging.getLogger(__name__)


def get_practice_questions(
    exam_paper_id: int,
    is_premium: bool,
    limit: int = None,
    topic: str = None,
) -> list:
    """
    Returns randomized practice questions from a given exam paper.
    Access is controlled by the exam paper's access_level.
    """
    try:
        exam = ExamPaper.objects.get(id=exam_paper_id, is_active=True)
    except ExamPaper.DoesNotExist:
        logger.warning(f'ExamPaper {exam_paper_id} not found')
        return []

    if exam.access_level == ExamPaper.ACCESS_PREMIUM and not is_premium:
        logger.warning(f'Premium exam {exam_paper_id} — access denied')
        return []

    questions = Question.objects.filter(
        exam_paper=exam,
        is_active=True,
    )

    if topic:
        questions = filter_topic_tags(questions, [topic])
    return select_random_questions(questions, limit)


def get_exit_exam_questions(
    department_id: int,
    is_premium: bool,
    exam_paper_id: int = None,
    topic: str = None,
    limit: int = None,
) -> list | None:
    """
    Returns exit exam questions for a department.
    Premium only. Optionally filter by exam paper or topic.
    """
    if not is_premium:
        return None

    questions = Question.objects.filter(
        is_active=True,
        exam_paper__department_id=department_id,
        exam_paper__exam_type__in=[
            ExamPaper.TYPE_EXIT_REAL,
            ExamPaper.TYPE_EXIT_MODEL,
        ],
        exam_paper__is_active=True,
    )

    if exam_paper_id:
        questions = questions.filter(exam_paper_id=exam_paper_id)

    if topic:
        questions = filter_topic_tags(questions, [topic])
    return select_random_questions(questions, limit)


def get_simulation_questions(
    exam_paper_id: int,
    is_premium: bool,
) -> list | None:
    """
    Returns all questions for a full exam simulation.
    Order is preserved (not shuffled) to match original paper order.
    """
    try:
        exam = ExamPaper.objects.get(id=exam_paper_id, is_active=True)
    except ExamPaper.DoesNotExist:
        logger.warning(f'ExamPaper {exam_paper_id} not found')
        return None

    if exam.access_level == ExamPaper.ACCESS_PREMIUM and not is_premium:
        logger.warning(f'Access denied to exam {exam_paper_id}')
        return None

    if not exam.is_ready:
        logger.warning(f'Exam {exam_paper_id} is not ready')
        return None

    return list(exam.questions.filter(is_active=True).select_related('chapter').order_by('id')[:501])


def get_topic_questions(
    department_id: int,
    topic: str,
    is_premium: bool,
    limit: int = 20,
) -> list:
    """
    Returns questions filtered by topic tag across all exit exam papers
    for a given department.
    """
    questions = Question.objects.filter(
        is_active=True,
        exam_paper__department_id=department_id,
        exam_paper__exam_type__in=[
            ExamPaper.TYPE_EXIT_REAL,
            ExamPaper.TYPE_EXIT_MODEL,
        ],
        exam_paper__is_active=True,
    ).distinct()

    return select_random_questions(filter_topic_tags(questions, [topic]), limit)


def calculate_score(
    questions: list,
    answers: list[dict],
) -> dict:
    """
    Scores a quiz attempt. Handles all question types:
    - mcq, true_false, fill_blank: auto-graded
    - matching, essay: not auto-graded, marked as pending

    answers format: [{'question_id': 1, 'selected_option': 'a'}, ...]
    """
    answers_map = {
        str(a['question_id']): a.get('selected_option', '')
        for a in answers
    }

    score = 0
    gradable_total = 0  # only auto-gradable questions count toward score
    results = []
    topic_scores = {}
    questions_map = {str(q.id): q for q in questions}

    for question_id, question in questions_map.items():
        selected = answers_map.get(question_id, '')
        q_type = question.question_type

        is_correct = False
        is_pending = False  # True for essay/matching — needs manual review

        if q_type == Question.TYPE_ESSAY:
            # Cannot auto-grade — mark as pending
            is_pending = True

        elif q_type == Question.TYPE_MATCHING:
            # Cannot auto-grade — mark as pending
            is_pending = True

        elif q_type in (Question.TYPE_MCQ, Question.TYPE_TRUE_FALSE):
            # Must match the correct letter
            is_correct = (
                bool(selected) and
                bool(question.correct_option) and
                selected.lower() == question.correct_option.lower()
            )
            gradable_total += 1
            if is_correct:
                score += 1

        elif q_type == Question.TYPE_FILL_BLANK:
            # Case-insensitive answer match
            is_correct = (
                bool(selected) and
                bool(question.correct_option) and
                selected.strip().lower() == question.correct_option.strip().lower()
            )
            gradable_total += 1
            if is_correct:
                score += 1

        results.append({
            'question_id':    int(question_id),
            'question':       question.text,
            'question_type':  q_type,
            'selected_option': selected,
            'correct_option': question.correct_option,
            'is_correct':     is_correct,
            'is_pending':     is_pending,
            'explanation':    question.explanation,
            'options':        question.available_options,
        })

        # Topic breakdown — only for auto-gradable questions
        if not is_pending:
            for tag in (question.topic_tags or []):
                if tag not in topic_scores:
                    topic_scores[tag] = {'correct': 0, 'total': 0}
                topic_scores[tag]['total'] += 1
                if is_correct:
                    topic_scores[tag]['correct'] += 1

    # Score is out of auto-gradable questions only
    percentage = quiz_percentage(score, gradable_total)

    pending_count = sum(1 for r in results if r['is_pending'])

    topic_breakdown = {
        tag: {
            'correct':    data['correct'],
            'total':      data['total'],
            'percentage': quiz_percentage(data['correct'], data['total']),
        }
        for tag, data in topic_scores.items()
    }

    weak_topics = [
        tag for tag, data in topic_breakdown.items()
        if data['percentage'] < 50
    ]

    return {
        'score':           score,
        'total':           len(questions_map),
        'gradable_total':  gradable_total,
        'pending_count':   pending_count,
        'percentage':      percentage,
        'passed':          percentage >= 50,
        'results':         results,
        'topic_breakdown': topic_breakdown,
        'weak_topics':     weak_topics,
    }


def get_topics_with_low_score(detailed_answers: dict) -> list[dict]:
    """
    From detailed answer feedback, return topics where the student scored below 50%.
    """
    topic_scores = {}

    for answer_data in detailed_answers.values():
        if answer_data.get('is_pending') or answer_data.get('question_type') in (Question.TYPE_ESSAY, Question.TYPE_MATCHING):
            continue
        is_correct = answer_data.get('is_correct', False)
        topics = answer_data.get('topic_tags', [])

        for topic in topics:
            if topic not in topic_scores:
                topic_scores[topic] = {'correct': 0, 'total': 0}

            topic_scores[topic]['total'] += 1
            if is_correct:
                topic_scores[topic]['correct'] += 1

    weak_topics = []
    for topic, scores in topic_scores.items():
        percentage = (
            scores['correct'] / scores['total'] * 100
            if scores['total'] > 0 else 0
        )
        if percentage < 50:
            weak_topics.append({
                'topic': topic,
                'percentage': quiz_percentage(scores['correct'], scores['total']),
                'correct': scores['correct'],
                'total': scores['total'],
            })

    return sorted(weak_topics, key=lambda item: item['percentage'])


def get_performance_summary(student) -> dict:
    from django.db.models import Avg, Case, Count, F, FloatField, Max, Value, When
    from django.db.models.functions import Coalesce, Round

    attempts = QuizAttempt.objects.filter(student=student).order_by().annotate(
        denominator=Coalesce('gradable_total', 'total_questions'),
    ).annotate(percent=Case(
        When(denominator__gt=0, then=Round(100.0 * F('score') / F('denominator'), 1)),
        default=Value(0.0), output_field=FloatField(),
    ))
    totals = attempts.aggregate(total=Count('pk'), average=Avg('percent'), best=Max('percent'))
    recent = list(attempts.order_by('-completed_at', '-pk').values('completed_at', 'mode', 'percent')[:30])
    weak_topics = set()
    snapshots = attempts.order_by('-completed_at', '-pk').values_list('detailed_answers', flat=True)[:20]
    for details in snapshots.iterator(chunk_size=1):
        for topic in get_topics_with_low_score(details or {}):
            weak_topics.add(topic['topic'])
    papers = attempts.filter(exam_paper__isnull=False).values(
        'exam_paper__title', 'exam_paper__exam_type', 'exam_paper_id',
    ).annotate(attempts=Count('pk'), average=Avg('percent')).order_by('-attempts', 'exam_paper_id')[:10]
    return {
        'total_attempts': totals['total'],
        'average_score': round(totals['average'] or 0, 1),
        'best_score': totals['best'] or 0,
        'weak_topics': sorted(weak_topics),
        'score_over_time': [{'date': row['completed_at'].strftime('%Y-%m-%d'), 'score': row['percent'], 'mode': row['mode']}
                            for row in recent],
        'attempts_by_paper': [{'paper_title': row['exam_paper__title'], 'exam_type': row['exam_paper__exam_type'],
                               'attempts': row['attempts'], 'average': round(row['average'], 1)} for row in papers],
    }
