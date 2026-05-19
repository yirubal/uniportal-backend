from django.contrib import admin, messages
from django.shortcuts import render, redirect
from django.urls import path
from django.http import HttpResponseRedirect
from unfold.admin import ModelAdmin
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import format_html
import os


from .models import Chapter, ExamPaper, Question, QuizAttempt


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
        'course',
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

    @admin.display(description='Total Questions')
    def total_questions_display(self, obj):
        return obj.questions.filter(is_active=True).count()

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
        )
        return super().change_view(request, object_id, form_url, extra_context)


# ─── Question Admin ────────────────────────────────────────────────────────────

@admin.register(Question)
class QuestionAdmin(ModelAdmin):
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
        'chapter__course',
        'chapter',
        'exam_paper__exam_type',
        'exam_paper__department',
        'exam_paper__course',
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

    @admin.action(description='Activate selected questions')
    def activate_questions(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f'{queryset.count()} question(s) activated.')

    @admin.action(description='Deactivate selected questions')
    def deactivate_questions(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f'{queryset.count()} question(s) deactivated.')

    @admin.action(description='Assign selected questions to an exam paper')
    def assign_to_exam_paper(self, request, queryset):
        if request.method == 'POST' and 'exam_paper' in request.POST:
            exam_paper_id = request.POST.get('exam_paper')
            try:
                exam_paper = ExamPaper.objects.get(id=exam_paper_id)
                queryset.update(exam_paper=exam_paper)
                self.message_user(request, f'{queryset.count()} question(s) assigned to {exam_paper.title}.')
                return redirect('/admin/quiz/question/')
            except ExamPaper.DoesNotExist:
                self.message_user(request, 'Exam paper not found.', level='error')

        exam_papers = ExamPaper.objects.filter(is_active=True).order_by('-year')
        return render(request, 'admin/quiz/assign_exam_paper.html', {
            'questions': queryset,
            'exam_papers': exam_papers,
            'question_count': queryset.count(),
        })

    # ── Bulk Metadata Action ──────────────────────────────────────────────────

    @admin.action(description='📋 Set metadata for selected questions')
    def bulk_set_metadata(self, request, queryset):
        selected_ids = list(queryset.values_list('id', flat=True))
        request.session['bulk_metadata_question_ids'] = selected_ids
        return HttpResponseRedirect('bulk-metadata/')

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
        question_ids = request.session.get('bulk_metadata_question_ids', [])

        if not question_ids:
            messages.warning(request, 'No questions selected. Please select questions first.')
            return redirect('..')

        # ── POST: apply ───────────────────────────────────────────────────────
        if request.method == 'POST':
            qs = Question.objects.filter(id__in=question_ids)
            updates = {}

            paper_id = request.POST.get('exam_paper')
            if paper_id:
                updates['exam_paper'] = ExamPaper.objects.get(id=paper_id)

            chapter_id = request.POST.get('chapter')
            if chapter_id:
                updates['chapter'] = Chapter.objects.get(id=chapter_id)

            year = request.POST.get('year_source')
            if year:
                updates['year_source'] = year.strip()

            difficulty = request.POST.get('difficulty')
            if difficulty:
                updates['difficulty'] = difficulty

            is_active = request.POST.get('is_active')
            if is_active == 'true':
                updates['is_active'] = True
            elif is_active == 'false':
                updates['is_active'] = False

            if updates:
                qs.update(**updates)
                del request.session['bulk_metadata_question_ids']
                messages.success(request, f'✅ Updated {len(question_ids)} question(s) successfully.')
            else:
                messages.info(request, 'No fields were changed — all fields were left blank.')

            return redirect('../')

        # ── GET: render form ──────────────────────────────────────────────────
        context = {
            **self.admin_site.each_context(request),
            'title': 'Set Question Metadata',
            'question_ids': question_ids,
            'exam_papers': ExamPaper.objects.filter(is_active=True).order_by('-year', 'title'),
            'chapters': Chapter.objects.filter(is_active=True).select_related('course').order_by('course__name', 'number'),
        }
        return render(request, 'admin/quiz/bulk_metadata.html', context)


# ─── QuizAttempt Admin ─────────────────────────────────────────────────────────

@admin.register(QuizAttempt)
class QuizAttemptAdmin(ModelAdmin):
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
        'answers',
        'mode',
        'completed_at',
    ]
