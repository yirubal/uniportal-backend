from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    ExamNotificationLog,
    ExamPDFUpload,
    ExamScheduleEntry,
    ExamSession,
    ExamTerm,
    StudentExam,
)


class ExamSessionInline(TabularInline):
    model = ExamSession
    extra = 0
    readonly_fields = ['session_number', 'date', 'start_time', 'end_time']
    can_delete = False


class ExamScheduleEntryInline(TabularInline):
    model = ExamScheduleEntry
    extra = 0
    readonly_fields = ['course_name', 'course_code', 'total_students', 'rooms']
    can_delete = False


@admin.register(ExamTerm)
class ExamTermAdmin(ModelAdmin):
    list_display = ['__str__', 'is_active', 'exam_start_date', 'student_count', 'pdf_count']
    list_editable = ['is_active']
    readonly_fields = ['exam_start_date']
    inlines = [ExamSessionInline]

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'upload-pdfs/',
                self.admin_site.admin_view(self.upload_pdfs_view),
                name='exams_examterm_upload_pdfs',
            ),
            path(
                '<int:term_id>/upload-pdfs/',
                self.admin_site.admin_view(self.upload_pdfs_view),
                name='exam_upload_pdfs',
            ),
        ]
        return custom + urls

    def upload_pdfs_view(self, request, term_id=None):
        from .services import process_attendance_pdf, process_schedule_pdf

        term = None
        if term_id is not None:
            term = ExamTerm.objects.filter(pk=term_id).first()

        if request.method == 'POST':
            schedule_files = request.FILES.getlist('schedule_pdf')
            attendance_files = request.FILES.getlist('attendance_pdfs')
            total_created = 0
            failed = 0

            for upload_file in schedule_files:
                upload = ExamPDFUpload(
                    original_name=upload_file.name,
                    pdf_type=ExamPDFUpload.TYPE_SCHEDULE,
                    term=term,
                )
                upload.file.save(upload_file.name, upload_file, save=True)
                success, created, error = process_schedule_pdf(upload)
                if success:
                    total_created += created
                    if upload.term and term is None:
                        term = upload.term
                        term_id = term.id
                else:
                    failed += 1
                    messages.error(request, f'Schedule PDF failed: {error}')

            for upload_file in attendance_files:
                upload = ExamPDFUpload(
                    original_name=upload_file.name,
                    pdf_type=ExamPDFUpload.TYPE_ATTENDANCE,
                    term=term,
                )
                upload.file.save(upload_file.name, upload_file, save=True)
                success, created, error = process_attendance_pdf(upload)
                if success:
                    total_created += created
                    if upload.term and term is None:
                        term = upload.term
                        term_id = term.id
                else:
                    failed += 1
                    messages.error(request, f'Failed: {upload_file.name} — {error}')

            processed_count = len(schedule_files) + len(attendance_files) - failed
            if total_created or processed_count:
                messages.success(
                    request,
                    f'Processed {processed_count} PDFs. {total_created} records created.',
                )

            if term_id:
                return redirect(f'/admin/exams/examterm/{term_id}/change/')
            return redirect('/admin/exams/examterm/')

        uploads = (
            ExamPDFUpload.objects.filter(term=term).order_by('-uploaded_at')
            if term
            else ExamPDFUpload.objects.order_by('-uploaded_at')[:50]
        )
        context = {
            **self.admin_site.each_context(request),
            'title': f'Upload PDFs — {term or "New Term"}',
            'term': term,
            'term_id': term_id,
            'uploads': uploads,
            'opts': ExamTerm._meta,
        }
        return render(request, 'admin/exams/upload_pdfs.html', context)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['upload_pdfs_url'] = f'/admin/exams/examterm/{object_id}/upload-pdfs/'
        return super().change_view(request, object_id, form_url, extra_context)

    @admin.display(description='Students')
    def student_count(self, obj):
        return obj.student_exams.count()

    @admin.display(description='PDFs')
    def pdf_count(self, obj):
        return obj.pdf_uploads.count()


@admin.register(ExamSession)
class ExamSessionAdmin(ModelAdmin):
    list_display = ['__str__', 'term', 'date', 'start_time', 'end_time']
    list_filter = ['term']
    inlines = [ExamScheduleEntryInline]


@admin.register(StudentExam)
class StudentExamAdmin(ModelAdmin):
    list_display = ['student_name', 'student_id', 'department', 'course_code', 'room_code', 'session']
    list_filter = ['term', 'department', 'session__date']
    search_fields = ['student_name', 'student_id', 'course_code']
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('term', 'session')


@admin.register(ExamPDFUpload)
class ExamPDFUploadAdmin(ModelAdmin):
    list_display = ['original_name', 'pdf_type', 'term', 'status', 'records_created', 'uploaded_at']
    list_filter = ['term', 'status', 'pdf_type']
    change_list_template = 'admin/exams/exampdfupload/change_list.html'
    readonly_fields = [
        'original_name',
        'pdf_type',
        'term',
        'file',
        'status',
        'records_created',
        'error_message',
        'uploaded_at',
    ]

    def add_view(self, request, form_url='', extra_context=None):
        return redirect('admin:exams_examterm_upload_pdfs')


@admin.register(ExamNotificationLog)
class ExamNotificationLogAdmin(ModelAdmin):
    list_display = ['term', 'days_before', 'sent_count', 'failed_count', 'sent_at']
    list_filter = ['term']
    readonly_fields = ['term', 'days_before', 'sent_count', 'failed_count', 'sent_at']
