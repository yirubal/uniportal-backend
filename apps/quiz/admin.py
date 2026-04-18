from django.contrib import admin
from django.shortcuts import render, redirect
from unfold.admin import ModelAdmin
from .models import ExamPaper, Question, QuizAttempt


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


@admin.register(Question)
class QuestionAdmin(ModelAdmin):
    list_display = [
        'short_text',
        'exam_paper',
        'department',
        'course',
        'difficulty',
        'year_source',
        'access_level',
        'is_active',
    ]
    list_filter = [
        'difficulty',
        'access_level',
        'is_active',
        'exam_paper__exam_type',
        'department',
    ]
    search_fields = [
        'text',
        'department__name',
        'course__name',
    ]
    list_editable = ['access_level', 'is_active']
    fieldsets = (
        ('Question', {
            'fields': (
                'text',
                'exam_paper',
            )
        }),
        ('Belongs To', {
            'description': 'For exit exam questions fill Department only. For course questions fill Course only.',
            'fields': (
                'department',
                'course',
            )
        }),
        ('Options', {
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
        ('Access', {
            'fields': (
                'access_level',
                'is_active',
            )
        }),
    )
    actions = [
        'activate_questions',
        'deactivate_questions',
        'assign_to_department',
        'assign_to_exam_paper',
    ]

    @admin.display(description='Question')
    def short_text(self, obj):
        return obj.text[:80] + '...' if len(obj.text) > 80 else obj.text

    @admin.action(description='Activate selected questions')
    def activate_questions(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f'{queryset.count()} question(s) activated.')

    @admin.action(description='Deactivate selected questions')
    def deactivate_questions(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f'{queryset.count()} question(s) deactivated.')

    @admin.action(description='Assign selected questions to a department')
    def assign_to_department(self, request, queryset):
        from apps.content.models import Department

        if request.method == 'POST' and 'department' in request.POST:
            department_id = request.POST.get('department')
            try:
                department = Department.objects.get(id=department_id)
                queryset.update(department=department, course=None)
                self.message_user(
                    request,
                    f'{queryset.count()} question(s) assigned to {department.name}.',
                )
                return redirect('/admin/quiz/question/')
            except Department.DoesNotExist:
                self.message_user(request, 'Department not found.', level='error')

        departments = Department.objects.filter(is_active=True).order_by('name')
        return render(
            request,
            'admin/quiz/assign_department.html',
            {
                'questions': queryset,
                'departments': departments,
                'question_count': queryset.count(),
            }
        )

    @admin.action(description='Assign selected questions to an exam paper')
    def assign_to_exam_paper(self, request, queryset):
        if request.method == 'POST' and 'exam_paper' in request.POST:
            exam_paper_id = request.POST.get('exam_paper')
            try:
                exam_paper = ExamPaper.objects.get(id=exam_paper_id)
                queryset.update(exam_paper=exam_paper)
                self.message_user(
                    request,
                    f'{queryset.count()} question(s) assigned to {exam_paper.title}.',
                )
                return redirect('/admin/quiz/question/')
            except ExamPaper.DoesNotExist:
                self.message_user(request, 'Exam paper not found.', level='error')

        exam_papers = ExamPaper.objects.filter(is_active=True).order_by('-year')
        return render(
            request,
            'admin/quiz/assign_exam_paper.html',
            {
                'questions': queryset,
                'exam_papers': exam_papers,
                'question_count': queryset.count(),
            }
        )


@admin.register(QuizAttempt)
class QuizAttemptAdmin(ModelAdmin):
    list_display = [
        'student',
        'exam_paper',
        'department',
        'course',
        'score',
        'total_questions',
        'percentage',
        'mode',
        'completed_at',
    ]
    list_filter = [
        'mode',
        'department',
    ]
    search_fields = [
        'student__username',
        'student__first_name',
    ]
    readonly_fields = [
        'student',
        'course',
        'department',
        'exam_paper',
        'score',
        'total_questions',
        'answers',
        'mode',
        'completed_at',
        'percentage',
        'passed',
    ]