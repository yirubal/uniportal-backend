"""Paper-level review using local checks; no provider requests or student API changes."""
import json
import re
from hashlib import sha256
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.admin.models import CHANGE, LogEntry
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch, Q, prefetch_related_objects
from django.db.models.functions import Lower, Trim
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from unfold.widgets import UnfoldAdminSelectWidget

from apps.bot.models import QuestionExtraction
from .models import Chapter, ExamPaper, Question

SALT = 'paper-question-review'
REVIEW_FIELDS = ['text', 'question_type', 'correct_option', 'explanation', 'chapter_id',
                 'exam_paper_id', 'difficulty', 'topic_tags', 'is_active', 'source_extraction_id',
                 'source_quote', *[f'option_{letter}' for letter in 'abcdef']]


def question_fingerprint(question):
    paper = question.exam_paper
    values = [getattr(question, name) for name in REVIEW_FIELDS]
    values.append([paper.course_id, paper.department_id, paper.exam_type, paper.is_active])
    return sha256(json.dumps(values,
                             ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def duplicate_texts(paper, questions):
    # Match case and surrounding spaces only. This is not semantic deduplication.
    keys = [question.text.strip().lower() for question in questions]
    return set(paper.questions.order_by().annotate(key=Lower(Trim('text')))
        .filter(key__in=keys).values('key').annotate(total=Count('pk'))
        .filter(total__gt=1).values_list('key', flat=True))


def quality_flags(question, duplicates):
    errors, warnings = [], []
    options = [getattr(question, f'option_{letter}').strip() for letter in 'abcdef']
    kind, answer = question.question_type, question.correct_option.strip()
    if not question.text.strip():
        errors.append('Question text is empty.')
    if question.text.strip().lower() in duplicates:
        errors.append('Another question in this paper has the same text (ignoring case and surrounding spaces).')
    if kind not in dict(Question.TYPE_CHOICES):
        errors.append('Question type is unsupported.')
    if kind in ('mcq', 'true_false'):
        allowed = 'ab' if kind == 'true_false' else 'abcdef'
        if len(answer) != 1 or answer not in allowed or not options[ord(answer) - ord('a')]:
            errors.append('Choose a valid answer letter with a populated option.')
        populated = [value.casefold() for value in options if value]
        if len(populated) < 2 or len(populated) != len(set(populated)):
            errors.append('Provide at least two distinct options; remove repeated choices.')
    if kind == 'true_false' and (options[0].casefold() != 'true' or options[1].casefold() != 'false' or any(options[2:])):
        errors.append('True/false needs only A=True and B=False.')
    if kind == 'fill_blank' and not answer:
        errors.append('Fill-blank questions need an answer.')
    if kind in ('essay', 'fill_blank') and any(options):
        errors.append('Essay and fill-blank questions must not contain choice options.')
    if kind in ('essay', 'matching'):
        warnings.append('Student responses require manual marking.')
        if answer:
            errors.append('Essay and matching questions must not have a single correct-option value.')
    if kind == 'matching' and (sum(bool(value) for value in options) < 2 or any(
            '→' not in value or not all(part.strip() for part in value.split('→', 1)) for value in options if value)):
        errors.append('Matching needs at least two populated Term → Answer pairs.')
    if question.chapter_id:
        if question.chapter.course_id != question.exam_paper.course_id or not question.chapter.is_active:
            errors.append('Choose an active chapter belonging to this paper course, or remove the chapter.')
    elif question.exam_paper.course_id:
        warnings.append('No chapter assigned; chapter practice will not include this question.')
    generated = question.source_extraction_id and question.source_extraction.mode == 'generate'
    if not question.explanation.strip():
        (errors if generated else warnings).append('Add an explanation or model answer for review.')
    if generated:
        quote = ' '.join(question.source_quote.split())
        if not quote or quote not in ' '.join(question.source_extraction.source_text.split()):
            errors.append('The generated source excerpt is missing or no longer matches the saved source.')
        warnings.append('AI answer and difficulty are suggestions; verify against the source.')
    return errors, warnings


def suggest_chapter(question, chapters):
    """A transparent title-word match, not an AI classification or confidence score."""
    words = set(re.findall(r'\w{4,}', question.text.casefold()))
    scored = [(len(words & set(re.findall(r'\w{4,}', chapter.title.casefold()))), chapter) for chapter in chapters]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if scored and scored[0][0] and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    return None


class PaperReviewForm(forms.Form):
    selection = forms.CharField(widget=forms.HiddenInput)
    selected = forms.MultipleChoiceField(widget=forms.CheckboxSelectMultiple, choices=[])
    reviewed = forms.BooleanField(required=False, label='I checked the selected answers and source material.')
    action = forms.ChoiceField(choices=[('chapters', 'Save chapter choices'), ('activate', 'Activate reviewed questions')])

    def __init__(self, *args, questions, chapters, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['selected'].choices = [(str(question.pk), str(question.pk)) for question in questions]
        chapter_choices = [('', 'Keep current chapter'), *[(chapter.pk, f'{chapter.number}. {chapter.title}') for chapter in chapters]]
        for question in questions:
            self.fields[f'chapter_{question.pk}'] = forms.ModelChoiceField(
                queryset=chapters, required=False, empty_label='Keep current chapter', widget=UnfoldAdminSelectWidget)
            self.fields[f'chapter_{question.pk}'].choices = chapter_choices


def paper_review_view(model_admin, request, paper_id):
    paper = get_object_or_404(ExamPaper, pk=paper_id)
    if not (model_admin.has_view_or_change_permission(request, paper) and request.user.has_perm('quiz.change_question')):
        raise PermissionDenied
    can_chapters = request.user.has_perm('quiz.view_chapter') or request.user.has_perm('quiz.change_chapter')
    chapters = (Chapter.objects.filter(course_id=paper.course_id, is_active=True).order_by('order', 'number')
                if paper.course_id and can_chapters else Chapter.objects.none())
    sources = Prefetch('source_extraction', queryset=QuestionExtraction.objects.defer('chunks', 'questions'))
    queryset = paper.questions.select_related('exam_paper', 'chapter').prefetch_related(sources).order_by('pk')
    page = Paginator(queryset, 25).get_page(request.GET.get('page'))
    questions = list(page.object_list)
    errors = []
    if request.method == 'POST':
        # Only rows actually shown to this actor may be submitted. Lock questions,
        # not nullable joined relations (PostgreSQL rejects those outer-join locks).
        try:
            payload = signing.loads(request.POST.get('selection', ''), salt=SALT, max_age=3600)
            if payload['user'] != request.user.pk or payload['paper'] != paper.pk or not 1 <= len(payload['rows']) <= 25:
                raise signing.BadSignature
            ids = [int(key) for key in payload['rows']]
        except (signing.BadSignature, ValueError, TypeError, KeyError):
            messages.error(request, 'This review expired or is invalid. Reload the page; no changes were applied.')
            return redirect(request.path)
        with transaction.atomic():
            paper = ExamPaper.objects.select_for_update().get(pk=paper.pk)
            locked = list(paper.questions.filter(pk__in=ids).select_for_update().order_by('pk'))
            # Load related source/chapter objects only after locking the question rows.
            prefetch_related_objects(locked, 'exam_paper', 'chapter', sources)
            form = PaperReviewForm(request.POST, questions=locked, chapters=chapters)
            old_chapter_tags = {question.pk: f'Chapter {question.chapter.number}: {question.chapter.title}'
                                for question in locked if question.chapter_id}
            if form.is_valid():
                selected = [question for question in locked if str(question.pk) in form.cleaned_data['selected']]
                if len(locked) != len(ids) or any(question_fingerprint(question) != payload['rows'][str(question.pk)] for question in locked):
                    errors.append('Questions changed since this page was opened. Reload and review the latest content; no changes were applied.')
                if form.cleaned_data['action'] == 'activate' and not form.cleaned_data['reviewed']:
                    errors.append('Confirm that you checked the selected answers and source material before activation.')
                if form.cleaned_data['action'] == 'chapters':
                    selected = [question for question in selected if form.cleaned_data.get(f'chapter_{question.pk}')]
                    if not selected:
                        errors.append('Choose a chapter for at least one selected question.')
                duplicates = duplicate_texts(paper, selected)
                for question in selected:
                    chapter = form.cleaned_data.get(f'chapter_{question.pk}')
                    if chapter and not question.is_active:
                        question.chapter = chapter
                    if form.cleaned_data['action'] == 'chapters' and question.is_active:
                        errors.append(f'Question #{question.pk} is active. Deactivate it before changing its chapter here.')
                    if form.cleaned_data['action'] == 'activate':
                        if question.is_active:
                            errors.append(f'Question #{question.pk} is already active. Review inactive drafts only.')
                        blockers, _ = quality_flags(question, duplicates)
                        errors.extend(f'Question #{question.pk}: {message}' for message in blockers)
                if not errors:
                    for question in selected:
                        if form.cleaned_data.get(f'chapter_{question.pk}'):
                            tag = f'Chapter {question.chapter.number}: {question.chapter.title}'
                            tags = list(question.topic_tags) if isinstance(question.topic_tags, list) else []
                            # Preserve granular tags; replace the prior chapter label only.
                            tags = [value for value in tags if value != old_chapter_tags.get(question.pk)]
                            question.topic_tags = tags if tag in tags else [*tags, tag]
                        if form.cleaned_data['action'] == 'activate':
                            question.is_active = True
                        question.save(update_fields=['chapter', 'topic_tags', 'is_active'])
                    LogEntry.objects.log_actions(user_id=request.user.pk, queryset=selected, action_flag=CHANGE,
                        change_message='Applied explicit paper review: ' + form.cleaned_data['action'])
                    messages.success(request, f'Updated {len(selected)} reviewed question(s). Paper visibility was not changed.')
                    return redirect(request.get_full_path())
            else:
                errors.append('Select questions and valid chapter choices. No changes were applied.')
    form = PaperReviewForm(request.POST if request.method == 'POST' else None, questions=questions, chapters=chapters)
    # Always sign current displayed content after a failed submission; errors still
    # require an explicit fresh review before the admin can activate anything.
    form.initial['selection'] = signing.dumps({'user': request.user.pk, 'paper': paper.pk,
        'rows': {str(question.pk): question_fingerprint(question) for question in questions}}, salt=SALT, compress=True)
    if form.is_bound:
        data = form.data.copy()
        data['selection'] = form.initial['selection']
        data['reviewed'] = ''
        form.data = data
    duplicates = duplicate_texts(paper, questions)
    chapter_list = list(chapters)
    cards = []
    for question in questions:
        blockers, warnings = quality_flags(question, duplicates)
        cards.append({'question': question, 'errors': blockers, 'warnings': warnings,
            'chapter_field': form[f'chapter_{question.pk}'],
            'suggestion': suggest_chapter(question, chapter_list) if not question.chapter_id else None,
            'options': [(letter.upper(), getattr(question, f'option_{letter}')) for letter in 'abcdef'
                        if getattr(question, f'option_{letter}')],
            'selected': str(question.pk) in request.POST.getlist('selected')})
    counts = paper.questions.aggregate(total=Count('pk'), active=Count('pk', filter=Q(is_active=True)),
        unassigned=Count('pk', filter=Q(chapter__isnull=True)))
    # Aggregate this paper only, rather than joining every question in the course.
    chapter_counts = {row['chapter_id']: row for row in paper.questions.order_by().values('chapter_id').annotate(
        total=Count('pk'), active=Count('pk', filter=Q(is_active=True)))}
    coverage = list(chapters)
    for chapter in coverage:
        chapter.total = chapter_counts.get(chapter.pk, {}).get('total', 0)
        chapter.active = chapter_counts.get(chapter.pk, {}).get('active', 0)
    allowed_sources = Q(pk__in=[])
    if request.user.has_perm('content.view_resource') or request.user.has_perm('content.change_resource'):
        allowed_sources |= Q(resource__isnull=False)
    if request.user.has_perm('content.view_fileinbox') or request.user.has_perm('content.change_fileinbox'):
        allowed_sources |= Q(inbox__isnull=False)
    source = paper.ai_extractions.filter(allowed_sources).only('resource_id', 'inbox_id').order_by('-pk').first()
    can_generate = (model_admin.has_add_permission(request) and model_admin.has_change_permission(request)
                    and request.user.has_perm('quiz.add_question'))
    for chapter in coverage:
        chapter.revision_url = None
        if source and can_generate and (source.resource_id or source.inbox_id):
            values = {'title': f'{chapter.title} — revision'[:500], 'course': paper.course_id,
                      'exam_type': 'quiz', 'year': paper.year, 'chapter': chapter.pk, 'focus': chapter.title[:500],
                      'resource' if source.resource_id else 'inbox': source.resource_id or source.inbox_id}
            chapter.revision_url = reverse('admin:quiz_exampaper_generate_paper') + '?' + urlencode(values)
    return render(request, 'admin/quiz/paper_review.html', {**model_admin.admin_site.each_context(request),
        'opts': paper._meta, 'title': f'Review questions — {paper.title}', 'paper': paper, 'page': page,
        'cards': cards, 'form': form, 'errors': errors, 'counts': counts, 'coverage': coverage,
        'can_chapters': can_chapters, 'can_view_jobs': request.user.has_perm('bot.view_questionextraction')
            or request.user.has_perm('bot.change_questionextraction')})
