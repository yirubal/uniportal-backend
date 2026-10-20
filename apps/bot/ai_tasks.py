from hashlib import sha256

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from .extractor import EXTRACTION_VERSION, _extract_from_chunk, validate_questions
from .models import QuestionExtraction


def queue_question_extraction(inbox=None, *, resource=None, exam_paper=None, chapter=None, requested_by=None):
    if (inbox is None) == (resource is None):
        raise ValueError('Choose one inbox file or one resource.')
    source = inbox if inbox is not None else resource
    if inbox is not None and inbox.processing_status != inbox.STATUS_PROCESSED:
        raise ValueError('Wait until the inbox file has finished text extraction.')
    text = source.extracted_text.strip()
    if not 50 <= len(text) <= settings.AI_MAX_INPUT_CHARS:
        raise ValueError(f'AI extraction needs 50–{settings.AI_MAX_INPUT_CHARS} characters; select a suitable source.')
    if exam_paper:
        if not exam_paper.is_active:
            raise ValueError('Choose an active exam paper.')
        if exam_paper.is_exit_exam:
            if not exam_paper.department_id:
                raise ValueError('Assign a department to the exit exam paper first.')
        elif not exam_paper.course_id:
            raise ValueError('Assign a course to this paper before AI extraction.')
    if chapter and (not exam_paper or not chapter.is_active or chapter.course_id != exam_paper.course_id):
        raise ValueError('Choose an active chapter belonging to the paper course.')
    cooldown = (QuestionExtraction.objects.filter(next_attempt_at__gt=timezone.now(),
        error_message__startswith='Gemini quota reached;').order_by('-next_attempt_at')
        .values_list('next_attempt_at', flat=True).first())
    extraction, created = QuestionExtraction.objects.get_or_create(
        **({'inbox': inbox} if inbox is not None else {'resource': resource}),
        defaults={'source_text': text, 'source_hash': sha256(text.encode()).hexdigest(),
                  'version': f'{EXTRACTION_VERSION}:{settings.GEMINI_MODEL}',
                  'exam_paper': exam_paper, 'chapter': chapter, 'requested_by': requested_by,
                  'target_required': exam_paper is not None,
                  'next_attempt_at': cooldown or timezone.now(),
                  'source_label': inbox.original_filename if inbox is not None else resource.title},
    )
    if not created and (extraction.exam_paper_id != getattr(exam_paper, 'pk', None)
                        or extraction.chapter_id != getattr(chapter, 'pk', None)):
        raise ValueError(f'This source already has extraction #{extraction.pk}. Review its existing questions instead of extracting it again.')
    return extraction, created


def _check_extraction_target(extraction):
    if extraction.target_required and extraction.exam_paper_id is None:
        raise ValueError('The target paper was deleted. Review this extraction before retrying.')
    if extraction.exam_paper_id and not extraction.exam_paper.is_active:
        raise ValueError('The target paper is inactive. Review it before retrying.')
    if (extraction.target_required and not extraction.exam_paper.is_exit_exam
            and not extraction.exam_paper.course_id):
        raise ValueError('The target course was removed. Review before retrying.')
    if (extraction.target_required and extraction.exam_paper.is_exit_exam
            and not extraction.exam_paper.department_id):
        raise ValueError('The exit paper department was removed. Review before retrying.')
    if extraction.chapter_id and (not extraction.chapter.is_active or not extraction.exam_paper_id
                                 or extraction.chapter.course_id != extraction.exam_paper.course_id):
        raise ValueError('The chapter no longer belongs to the paper course.')


def process_question_extraction(extraction):
    from apps.quiz.models import Question
    _check_extraction_target(extraction)
    cached = QuestionExtraction.objects.filter(
        source_hash=extraction.source_hash, version=extraction.version, status='processed',
    ).exclude(pk=extraction.pk).first()
    if cached:
        questions = validate_questions(cached.questions)
    else:
        questions = []
        chunks = dict(extraction.chunks)
        for offset in range(0, len(extraction.source_text), 8000):
            key = str(offset)
            if key not in chunks:
                if extraction.version != f'{EXTRACTION_VERSION}:{settings.GEMINI_MODEL}':
                    raise ValueError('The AI model/version changed. Review this extraction before retrying.')
                counted = QuestionExtraction.objects.filter(pk=extraction.pk, claim_token=extraction.claim_token,
                    provider_calls__lt=settings.AI_MAX_CALLS_PER_JOB).update(provider_calls=F('provider_calls') + 1)
                if not counted:
                    raise ValueError('AI request limit reached or claim lost. Review this extraction before retrying.')
                chunks[key] = _extract_from_chunk(settings.GEMINI_API_KEY, extraction.source_text[offset:offset + 8000])
                # Persist each completed paid call before continuing/retrying.
                updated = QuestionExtraction.objects.filter(pk=extraction.pk, claim_token=extraction.claim_token).update(chunks=chunks)
                if not updated:
                    raise RuntimeError('Extraction claim was lost')
            questions.extend(chunks[key])
            if len(questions) > settings.AI_MAX_QUESTIONS:
                raise ValueError('Too many AI questions; split the input.')
        questions = validate_questions(questions)
    if not questions:
        raise ValueError('AI found no questions; manual review required.')
    with transaction.atomic():
        current = QuestionExtraction.objects.select_for_update().get(pk=extraction.pk)
        if current.claim_token != extraction.claim_token or current.status != 'processing':
            return
        if current.exam_paper_id != extraction.exam_paper_id or current.chapter_id != extraction.chapter_id:
            raise ValueError('The extraction target changed during processing. Review before retrying.')
        _check_extraction_target(current)
        tags = [f'Chapter {extraction.chapter.number}: {extraction.chapter.title}'] if extraction.chapter_id else []
        Question.objects.bulk_create([
            Question(text=row['question'], question_type=row['question_type'],
                     exam_paper_id=current.exam_paper_id, chapter_id=current.chapter_id,
                     source_extraction=current, topic_tags=tags,
                     correct_option=row['correct_option'], explanation=row['explanation'],
                     **{f'option_{letter}': row[f'option_{letter}'] for letter in 'abcdef'}, is_active=False)
            for row in questions
        ])
        current.questions = questions
        current.status = 'processed'
        current.claim_token = None
        current.claimed_at = None
        current.error_message = ''
        current.save(update_fields=['questions', 'status', 'claim_token', 'claimed_at', 'error_message'])
