from hashlib import sha256

from django.conf import settings
from django.db import transaction
from .extractor import EXTRACTION_VERSION, _extract_from_chunk, validate_questions
from .models import QuestionExtraction


def queue_question_extraction(inbox):
    text = inbox.extracted_text.strip()
    if not 50 <= len(text) <= settings.AI_MAX_INPUT_CHARS:
        raise ValueError('AI extraction needs 50–40000 characters; split larger documents.')
    return QuestionExtraction.objects.get_or_create(
        inbox=inbox,
        defaults={'source_text': text, 'source_hash': sha256(text.encode()).hexdigest(),
                  'version': f'{EXTRACTION_VERSION}:{settings.GEMINI_MODEL}'},
    )


def process_question_extraction(extraction):
    from apps.quiz.models import Question
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
        Question.objects.bulk_create([
            Question(text=row['question'], question_type=row['question_type'],
                     correct_option=row['correct_option'], explanation=row['explanation'],
                     **{f'option_{letter}': row[f'option_{letter}'] for letter in 'abcde'}, is_active=False)
            for row in questions
        ])
        current.questions = questions
        current.status = 'processed'
        current.claim_token = None
        current.claimed_at = None
        current.error_message = ''
        current.save(update_fields=['questions', 'status', 'claim_token', 'claimed_at', 'error_message'])
