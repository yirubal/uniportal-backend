import os

from django.contrib import admin, messages
from django.contrib.admin.models import CHANGE, LogEntry
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, redirect
from django.urls import path, reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import AutocompleteSelectFilter

from .models import Chapter, ExamPaper, Question, QuizAttempt
from .forms import QuestionBulkEditForm


# ─── Filters ──────────────────────────────────────────────────────────────────

class AssignmentStatusFilter(admin.SimpleListFilter):
    title = 'Assignment Status'
    parameter_name = 'assignment_status'

    def lookups(self, request, model_admin):
        return [
            ('unassigned',     '🔴 Unassigned (no exam paper)'),
            ('assigned',       '🟢 Assigned to exam paper'),
        ]

    def queryset(self, request, queryset):
        if self.value() == 'unassigned':
            return queryset.filter(exam_paper__isnull=True)
        if self.value() == 'assigned':
            return queryset.filter(exam_paper__isnull=False)
        return queryset


# ─── Chapter Admin ────────────────────────────────────────────────────────────

@admin.register(Chapter)
class ChapterAdmin(ModelAdmin):
    list_display = [
        'chapter_display',
        'course',
        'title',
        'question_count_display',
        'is_active',
        'created_at',
    ]
    list_filter = [
        ('course', AutocompleteSelectFilter),
        'is_active',
        'created_at',
    ]
    search_fields = [
        'title',
        'description',
        'course__name',
        'course__code',
    ]
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['course', 'number']
    list_editable = ['is_active']
    fieldsets = (
        ('Chapter Info', {
            'fields': (
                'course',
                'number',
                'title',
                'description',
            )
        }),
        ('Display Settings', {
            'fields': (
                'icon',
                'order',
                'is_active',
            )
        }),
        ('Metadata', {
            'classes': ('collapse',),
            'fields': (
                'created_at',
                'updated_at',
            )
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('course').annotate(
            active_question_count=Count('questions', filter=Q(questions__is_active=True)),
        )

    @admin.display(description='Chapter')
    def chapter_display(self, obj):
        label = f'{obj.icon} Chapter {obj.number}' if obj.icon else f'Chapter {obj.number}'
        return format_html('<strong>{}</strong>', label)

    @admin.display(description='Questions')
    def question_count_display(self, obj):
        return format_html(
            '<span style="background-color:#E8F4F8;padding:3px 8px;'
            'border-radius:3px;font-weight:bold">{} Q</span>',
            obj.question_count,
        )


# ─── ExamPaper Admin ───────────────────────────────────────────────────────────"

@admin.register(ExamPaper)
class ExamPaperAdmin(ModelAdmin):
    list_display = [
        'title',
        'exam_type',
        'year',
        'department',
        'course',
        'duration_minutes',
        'total_questions_display',
        'access_level',
        'is_active',
    ]
    list_filter = [
        'exam_type',
        'access_level',
        'is_active',
        'department',
    ]
    search_fields = [
        'title',
        'department__name',
        'course__name',
    ]
    readonly_fields = [
        'total_questions_display',
        'is_ready',
        'created_at',
        'updated_at',
    ]
    list_editable = ['access_level', 'is_active']
    fieldsets = (
        ('Exam Info', {
            'fields': (
                'title',
                'exam_type',
                'year',
            )
        }),
        ('Belongs To', {
            'description': 'For Exit Exams fill Department only. For Final Exam and Team Quiz fill Course only.',
            'fields': (
                'department',
                'course',
            )
        }),
        ('Configuration', {
            'fields': (
                'duration_minutes',
                'instructions',
                'access_level',
                'is_active',
            )
        }),
        ('Source', {
            'fields': (
                'source_resource',
            )
        }),
        ('Stats', {
            'fields': (
                'total_questions_display',
                'is_ready',
                'created_at',
                'updated_at',
            )
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('course', 'department').annotate(
            active_question_count=Count('questions', filter=Q(questions__is_active=True)),
        )

    @admin.display(description='Total Questions')
    def total_questions_display(self, obj):
        return obj.total_questions

    # ── Extra URLs ────────────────────────────────────────────────────────────

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                '<int:paper_id>/import-questions/',
                self.admin_site.admin_view(self.import_questions_view),
                name='quiz_exampaper_import_questions',
            ),
            path(
                'download-template/',
                self.admin_site.admin_view(self.download_template_view),
                name='quiz_exampaper_download_template',
            ),
            path(
                '<int:paper_id>/download-template/',
                self.admin_site.admin_view(self.download_template_view),
                name='quiz_exampaper_download_template_for_paper',
            ),
        ]
        return custom + urls

    # ── Download template ─────────────────────────────────────────────────────

    def _import_template_context(self, exam_paper=None):
        is_exit_exam = bool(exam_paper and exam_paper.is_exit_exam)
        filename = (
            'exit_exam_import_template.xlsx'
            if is_exit_exam
            else 'quiz_import_template.xlsx'
        )
        label = 'Exit exam import template' if is_exit_exam else 'Quiz import template'
        return {
            'filename': filename,
            'label': label,
            'path': os.path.join(os.path.dirname(__file__), 'static', 'quiz', filename),
        }

    def download_template_view(self, request, paper_id=None):
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        exam_paper = None
        if paper_id is not None:
            try:
                exam_paper = ExamPaper.objects.get(pk=paper_id)
            except ExamPaper.DoesNotExist:
                messages.error(request, 'Exam paper not found.')
                return HttpResponseRedirect(reverse('admin:quiz_exampaper_changelist'))

        template = self._import_template_context(exam_paper)
        template_path = os.path.join(
            os.path.dirname(__file__), 'static', 'quiz', template['filename']
        )
        if not os.path.exists(template_path):
            messages.error(request, 'Template file not found. Contact the developer.')
            return HttpResponseRedirect(reverse('admin:quiz_exampaper_changelist'))

        with open(template_path, 'rb') as f:
            response = HttpResponse(
                f.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="{template["filename"]}"'
            return response

    # ── Import questions view ─────────────────────────────────────────────────

    def import_questions_view(self, request, paper_id):
        if not (self.has_change_permission(request) and request.user.has_perm('quiz.add_question')):
            raise PermissionDenied
        from apps.quiz.models import ExamPaper
        from apps.quiz.importers import import_exit_questions_from_excel, import_questions_from_excel

        try:
            exam_paper = ExamPaper.objects.get(pk=paper_id)
        except ExamPaper.DoesNotExist:
            messages.error(request, 'Exam paper not found.')
            return HttpResponseRedirect(reverse('admin:quiz_exampaper_changelist'))

        if request.method == 'POST':
            excel_file = request.FILES.get('excel_file')
            if not excel_file:
                messages.error(request, 'No file uploaded.')
            else:
                if exam_paper.is_exit_exam:
                    result = import_exit_questions_from_excel(excel_file, exam_paper)
                else:
                    result = import_questions_from_excel(excel_file, exam_paper)

                if result.created:
                    messages.success(
                        request,
                        f'✅ {result.created} question(s) imported successfully. '
                        f'They are inactive — review and activate them in the Questions table.'
                    )
                if result.skipped:
                    messages.warning(request, f'⚠️ {result.skipped} row(s) were skipped.')
                for error in result.errors:
                    messages.warning(request, error)

                if result.created:
                    return HttpResponseRedirect(
                        reverse('admin:quiz_question_changelist') +
                        f'?exam_paper__id__exact={paper_id}'
                    )

        template = self._import_template_context(exam_paper)
        context = {
            **self.admin_site.each_context(request),
            'title': f'Import Questions — {exam_paper.title}',
            'exam_paper': exam_paper,
            'template_url': reverse(
                'admin:quiz_exampaper_download_template_for_paper',
                args=[paper_id],
            ),
            'template_filename': template['filename'],
            'template_label': template['label'],
        }
        return render(request, 'admin/quiz/exampaper/import_questions.html', context)


    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['import_url'] = reverse(
            'admin:quiz_exampaper_import_questions',
            args=[object_id]
        ) if self.has_change_permission(request) and request.user.has_perm('quiz.add_question') else None
        return super().change_view(request, object_id, form_url, extra_context)


# ─── Question Admin ────────────────────────────────────────────────────────────

@admin.register(Question)
class QuestionAdmin(ModelAdmin):
    list_select_related = ['chapter__course', 'exam_paper__course', 'exam_paper__department']
    ordering = ['-id']
    list_per_page = 50

    list_display = [
        'short_text',
        'question_type',
        'chapter',
        'exam_paper',
        'difficulty',
        'year_source',
        'is_active',
    ]
    list_filter = [
        AssignmentStatusFilter,
        'question_type',
        'difficulty',
        'is_active',
        ('chapter__course', AutocompleteSelectFilter),
        ('chapter', AutocompleteSelectFilter),
        'exam_paper__exam_type',
        ('exam_paper__department', AutocompleteSelectFilter),
        ('exam_paper__course', AutocompleteSelectFilter),
    ]
    search_fields = [
        'text',
        'explanation',
        'chapter__title',
        'exam_paper__title',
        'exam_paper__department__name',
        'exam_paper__course__name',
    ]
    list_editable = ['is_active']
    fieldsets = (
        ('Question', {
            'fields': (
                'text',
                'question_type',
                'exam_paper',
                'chapter',
            )
        }),
        ('Options', {
            'description': (
                'MCQ: fill A–D (and E if needed). '
                'True/False: A=True, B=False only. '
                'Fill blank: put answer in Correct Option, leave A–E blank. '
                'Matching: each option is "Term → Answer". '
                'Essay: leave all blank.'
            ),
            'fields': (
                'option_a',
                'option_b',
                'option_c',
                'option_d',
                'option_e',
                'correct_option',
            )
        }),
        ('Explanation & Tags', {
            'fields': (
                'explanation',
                'topic_tags',
                'year_source',
                'difficulty',
            )
        }),
        ('Visibility', {
            'fields': (
                'is_active',
            )
        }),
    )
    actions = [
        'activate_questions',
        'deactivate_questions',
        'assign_to_exam_paper',
        'bulk_set_metadata',
    ]

    # ── Display ───────────────────────────────────────────────────────────────

    @admin.display(description='Question')
    def short_text(self, obj):
        return obj.text[:80] + '...' if len(obj.text) > 80 else obj.text

    # ── Simple Actions ────────────────────────────────────────────────────────

    @admin.action(permissions=['change'], description='Activate selected questions')
    def activate_questions(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f'{count} question(s) activated.')

    @admin.action(permissions=['change'], description='Deactivate selected questions')
    def deactivate_questions(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f'{count} question(s) deactivated.')

    @admin.action(permissions=['change'], description='Assign selected questions to an exam paper')
    def assign_to_exam_paper(self, request, queryset):
        return self.start_bulk_edit(request, queryset, assignment_only=True)

    @admin.action(permissions=['change'], description='Set metadata for selected questions')
    def bulk_set_metadata(self, request, queryset):
        return self.start_bulk_edit(request, queryset)

    def start_bulk_edit(self, request, queryset, assignment_only=False):
        filters = request.GET.copy()
        filters.pop('next', None)
        selection = signing.dumps({
            'user': request.user.pk, 'ids': list(queryset.values_list('pk', flat=True)),
            'assignment_only': assignment_only, 'filters': filters.urlencode(),
        }, salt='quiz-admin-bulk-edit', compress=True)
        form = QuestionBulkEditForm(initial={'selection': selection}, user=request.user, assignment_only=assignment_only)
        return self.render_bulk_edit(request, form, queryset, reverse('admin:quiz_question_changelist') + ('?' + filters.urlencode() if filters else ''))

    def render_bulk_edit(self, request, form, queryset, return_url):
        return render(request, 'admin/quiz/bulk_metadata.html', {
            **self.admin_site.each_context(request), 'opts': Question._meta,
            'title': 'Review question changes', 'form': form, 'bulk_return_url': return_url, 'question_count': queryset.count(),
            'question_preview': list(queryset.order_by('pk').values_list('text', flat=True)[:5]),
        })

    # ── Extra URL ─────────────────────────────────────────────────────────────

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'bulk-metadata/',
                self.admin_site.admin_view(self.bulk_metadata_view),
                name='quiz_question_bulk_metadata',
            )
        ]
        return custom + urls

    def bulk_metadata_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied
        try:
            selection = signing.loads(request.POST.get('selection', ''), salt='quiz-admin-bulk-edit', max_age=3600)
            if selection['user'] != request.user.pk or not selection['ids']:
                raise signing.BadSignature
        except (signing.BadSignature, KeyError, TypeError):
            messages.warning(request, 'This selection is invalid or expired. Select the questions again; no changes were applied.')
            return redirect('admin:quiz_question_changelist')
        return_url = reverse('admin:quiz_question_changelist') + ('?' + selection['filters'] if selection.get('filters') else '')
        form = QuestionBulkEditForm(request.POST, user=request.user, assignment_only=selection.get('assignment_only', False))
        queryset = self.get_queryset(request).filter(pk__in=selection['ids'])
        if form.is_valid():
            with transaction.atomic():
                # Lock questions only; optional paper/chapter relations are prefetched
                # separately so PostgreSQL never locks the nullable side of a join.
                questions = list(queryset.select_related(None).select_for_update().prefetch_related('chapter', 'exam_paper'))
                if len(questions) != len(selection['ids']):
                    form.add_error(None, 'Some selected questions no longer exist or are unavailable. Select again; no changes were applied.')
                else:
                    data = form.cleaned_data
                    for question in questions:
                        paper = data.get('exam_paper') or question.exam_paper
                        chapter = None if data.get('clear_chapter') else data.get('chapter') or question.chapter
                        if paper and chapter and paper.course_id != chapter.course_id:
                            form.add_error(None, 'The resulting chapter and exam paper must belong to the same course. Choose a matching chapter or remove the chapter assignment. No changes were applied.')
                            break
                if not form.errors:
                    updates = {key: form.cleaned_data[key] for key in ('exam_paper', 'chapter', 'year_source', 'difficulty')
                               if form.cleaned_data.get(key)}
                    if form.cleaned_data.get('clear_chapter'):
                        updates['chapter'] = None
                    if form.cleaned_data.get('is_active'):
                        updates['is_active'] = form.cleaned_data['is_active'] == 'true'
                    if updates:
                        count = Question.objects.filter(pk__in=[question.pk for question in questions]).update(**updates)
                        LogEntry.objects.log_actions(user_id=request.user.pk, queryset=questions, action_flag=CHANGE,
                                                     change_message='Applied reviewed bulk question metadata.')
                        messages.success(request, f'Applied metadata to {count} selected question(s).')
                    else:
                        messages.info(request, 'All fields were left unchanged; no updates were applied.')
                    return redirect(return_url)
        return self.render_bulk_edit(request, form, queryset, return_url)


# ─── QuizAttempt Admin ─────────────────────────────────────────────────────────

@admin.register(QuizAttempt)
class QuizAttemptAdmin(ModelAdmin):
    list_select_related = ['student', 'exam_paper__course', 'exam_paper__department']
    list_display = [
        'student',
        'exam_paper',
        'score',
        'total_questions',
        'percentage',
        'mode',
        'completed_at',
    ]
    list_filter = [
        'mode',
        'exam_paper__department',
    ]
    search_fields = [
        'student__username',
        'student__first_name',
    ]
    readonly_fields = [
        'student',
        'exam_paper',
        'score',
        'total_questions',
        'gradable_total',
        'pending_count',
        'detailed_answers',
        'answers',
        'mode',
        'completed_at',
    ]
