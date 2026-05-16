import random
import logging
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
        questions = questions.filter(topic_tags__contains=topic)

    if limit and not is_premium:
        limit = min(limit, 5)

    questions = list(questions)
    random.shuffle(questions)
    if limit:
        return questions[:limit]

    return questions


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
        questions = questions.filter(topic_tags__contains=topic)

    questions = list(questions)
    random.shuffle(questions)

    if limit:
        questions = questions[:limit]

    return questions


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

    return list(exam.questions.filter(is_active=True).order_by('id'))


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
        topic_tags__contains=topic,
        exam_paper__department_id=department_id,
        exam_paper__exam_type__in=[
            ExamPaper.TYPE_EXIT_REAL,
            ExamPaper.TYPE_EXIT_MODEL,
        ],
        exam_paper__is_active=True,
    ).distinct()

    if not is_premium:
        limit = min(limit, 5)

    questions = list(questions)
    random.shuffle(questions)
    return questions[:limit]


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
        auto_gradable = question.is_auto_gradable  # False for essay

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
    percentage = round((score / gradable_total) * 100, 1) if gradable_total > 0 else 0

    pending_count = sum(1 for r in results if r['is_pending'])

    topic_breakdown = {
        tag: {
            'correct':    data['correct'],
            'total':      data['total'],
            'percentage': round(
                (data['correct'] / data['total']) * 100, 1
            ) if data['total'] > 0 else 0,
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
                'percentage': round(percentage, 1),
                'correct': scores['correct'],
                'total': scores['total'],
            })

    return sorted(weak_topics, key=lambda item: item['percentage'])


def get_performance_summary(student) -> dict:
    """
    Returns a student's overall performance summary across all attempts.
    """
    attempts = QuizAttempt.objects.filter(
        student=student,
    ).order_by('-completed_at')

    total_attempts = attempts.count()

    if total_attempts == 0:
        return {
            'total_attempts':    0,
            'average_score':     0,
            'best_score':        0,
            'weak_topics':       [],
            'score_over_time':   [],
            'attempts_by_paper': [],
        }

    percentages = [a.percentage for a in attempts]
    average_score = round(sum(percentages) / len(percentages), 1)
    best_score = max(percentages)

    score_over_time = [
        {
            'date':  a.completed_at.strftime('%Y-%m-%d'),
            'score': a.percentage,
            'mode':  a.mode,
        }
        for a in attempts[:30]
    ]

    # Weak topics — from recent attempts' wrong answers
    weak_topics = set()
    for attempt in attempts[:20]:
        if isinstance(attempt.answers, dict):
            for question_id, selected in attempt.answers.items():
                try:
                    q = Question.objects.get(id=question_id)
                    if (
                        q.is_auto_gradable and
                        q.correct_option and
                        selected != q.correct_option
                    ):
                        for tag in (q.topic_tags or []):
                            weak_topics.add(tag)
                except Question.DoesNotExist:
                    pass

    # Attempts breakdown by exam paper
    from django.db.models import Count, Avg
    by_paper = (
        attempts
        .filter(exam_paper__isnull=False)
        .values('exam_paper__title', 'exam_paper__exam_type')
        .annotate(total=Count('id'), average=Avg('score'))
        .order_by('-total')[:10]
    )

    attempts_by_paper = [
        {
            'paper_title': item['exam_paper__title'],
            'exam_type':   item['exam_paper__exam_type'],
            'attempts':    item['total'],
            'average':     round(float(item['average'] or 0), 1),
        }
        for item in by_paper
    ]

    return {
        'total_attempts':    total_attempts,
        'average_score':     average_score,
        'best_score':        best_score,
        'weak_topics':       list(weak_topics),
        'score_over_time':   score_over_time,
        'attempts_by_paper': attempts_by_paper,
    }
