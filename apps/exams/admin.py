from hashlib import sha256

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme
from apps.bot.admin_filters import WorkAttentionFilter
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
    list_display = [
        '__str__',
        'active_status',
        'exam_start_date',
        'student_count',
        'pdf_count',
        'activation_controls',
    ]
    readonly_fields = ['exam_start_date']
    inlines = [ExamSessionInline]
    actions = ['activate_selected_term', 'deactivate_selected_terms']

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
            path(
                '<int:term_id>/upload-status/',
                self.admin_site.admin_view(self.upload_status_view),
                name='exam_upload_status',
            ),
            path(
                '<int:term_id>/activate/',
                self.admin_site.admin_view(self.activate_term_view),
                name='exams_examterm_activate',
            ),
            path(
                '<int:term_id>/deactivate/',
                self.admin_site.admin_view(self.deactivate_term_view),
                name='exams_examterm_deactivate',
            ),
        ]
        return custom + urls

    def activate_term_view(self, request, term_id):
        term = get_object_or_404(ExamTerm, pk=term_id)
        if not self.has_change_permission(request, term):
            raise PermissionDenied
        if request.method != 'POST':
            messages.warning(request, 'Use the Activate button to change the active exam term.')
            return self._redirect_back(request)

        term.activate()
        messages.success(request, f'{term} is now the active exam term.')
        return self._redirect_back(request)

    def deactivate_term_view(self, request, term_id):
        term = get_object_or_404(ExamTerm, pk=term_id)
        if not self.has_change_permission(request, term):
            raise PermissionDenied
        if request.method != 'POST':
            messages.warning(request, 'Use the Deactivate button to change the active exam term.')
            return self._redirect_back(request)

        term.deactivate()
        messages.success(request, f'{term} has been deactivated.')
        return self._redirect_back(request)

    def _redirect_back(self, request):
        fallback = reverse('admin:exams_examterm_changelist')
        referer = request.META.get('HTTP_REFERER')
        if referer and url_has_allowed_host_and_scheme(
            referer,
            allowed_hosts={request.get_host()},
        ):
            return redirect(referer)
        return redirect(fallback)

    def upload_status_view(self, request, term_id):
        from django.http import JsonResponse

        if not request.user.has_perm('exams.view_exampdfupload'):
            raise PermissionDenied
        uploads = ExamPDFUpload.objects.filter(term_id=term_id)
        return JsonResponse({
            'pending': uploads.filter(status=ExamPDFUpload.STATUS_PENDING).count(),
            'processing': uploads.filter(status=ExamPDFUpload.STATUS_PROCESSING).count(),
            'processed': uploads.filter(status=ExamPDFUpload.STATUS_PROCESSED).count(),
            'failed': uploads.filter(status=ExamPDFUpload.STATUS_FAILED).count(),
        })

    def upload_pdfs_view(self, request, term_id=None):
        if not request.user.has_perms(['exams.add_exampdfupload', 'exams.view_exampdfupload']):
            raise PermissionDenied
        term = None
        if term_id is not None:
            term = get_object_or_404(ExamTerm, pk=term_id)

        if request.method == 'POST':
            action = request.POST.get('action', 'upload')

            if action == 'process':
                has_pending = ExamPDFUpload.objects.filter(
                    status=ExamPDFUpload.STATUS_PENDING,
                ).exists()
                has_processing = ExamPDFUpload.objects.filter(
                    status=ExamPDFUpload.STATUS_PROCESSING,
                ).exists()

                if has_pending:
                    messages.success(request, 'Pending PDFs are queued for the worker.')
                elif has_processing:
                    messages.warning(request, 'PDF processing is already running.')
                else:
                    messages.warning(request, 'No pending PDF files to process.')

                return redirect(request.path)

            schedule_files = request.FILES.getlist('schedule_pdf')
            attendance_files = request.FILES.getlist('attendance_pdfs')
            from django.core.exceptions import ValidationError
            from apps.content.validators import validate_exam_pdf
            try:
                for upload_file in schedule_files + attendance_files:
                    validate_exam_pdf(upload_file)
            except ValidationError as exc:
                messages.error(request, '; '.join(exc.messages))
                return redirect(request.path)
            queued_count = 0
            skipped_count = 0

            for upload_file in schedule_files:
                content_hash = self._uploaded_file_hash(upload_file)
                if self._is_duplicate_pdf_upload(content_hash):
                    skipped_count += 1
                    messages.warning(request, f'{upload_file.name} was already uploaded, so it was skipped.')
                    continue

                upload = ExamPDFUpload(
                    original_name=upload_file.name,
                    pdf_type=ExamPDFUpload.TYPE_SCHEDULE,
                    term=term,
                    content_hash=content_hash,
                    status=ExamPDFUpload.STATUS_PENDING,
                )
                upload.file.save(upload_file.name, upload_file, save=True)
                queued_count += 1

            for upload_file in attendance_files:
                content_hash = self._uploaded_file_hash(upload_file)
                if self._is_duplicate_pdf_upload(content_hash):
                    skipped_count += 1
                    messages.warning(request, f'{upload_file.name} was already uploaded, so it was skipped.')
                    continue

                upload = ExamPDFUpload(
                    original_name=upload_file.name,
                    pdf_type=ExamPDFUpload.TYPE_ATTENDANCE,
                    term=term,
                    content_hash=content_hash,
                    status=ExamPDFUpload.STATUS_PENDING,
                )
                upload.file.save(upload_file.name, upload_file, save=True)

                queued_count += 1

            if queued_count:
                messages.success(
                    request,
                    f'{queued_count} PDF file(s) uploaded and queued for background processing.',
                )
            elif skipped_count:
                messages.warning(request, 'No new PDF files were queued because all selected files were duplicates.')
            else:
                messages.warning(request, 'No PDF files were selected.')

            return redirect(request.path)

        upload_qs = ExamPDFUpload.objects.filter(term=term) if term else ExamPDFUpload.objects.all()
        status_counts = upload_qs.aggregate(
            pending=Count('id', filter=Q(status=ExamPDFUpload.STATUS_PENDING)),
            processing=Count('id', filter=Q(status=ExamPDFUpload.STATUS_PROCESSING)),
            processed=Count('id', filter=Q(status=ExamPDFUpload.STATUS_PROCESSED)),
            failed=Count('id', filter=Q(status=ExamPDFUpload.STATUS_FAILED)),
        )
        pending_count = status_counts['pending'] or 0
        processing_count = status_counts['processing'] or 0
        processed_count = status_counts['processed'] or 0
        failed_count = status_counts['failed'] or 0
        uploads = upload_qs.order_by('-uploaded_at')[:50]
        context = {
            **self.admin_site.each_context(request),
            'title': f'Upload PDFs — {term or "New Term"}',
            'term': term,
            'term_id': term_id,
            'uploads': uploads,
            'status_counts': status_counts,
            'pending_count': pending_count,
            'processing_count': processing_count,
            'processed_count': processed_count,
            'failed_count': failed_count,
            'opts': ExamTerm._meta,
        }
        return render(request, 'admin/exams/upload_pdfs.html', context)

    @staticmethod
    def _uploaded_file_hash(upload_file):
        digest = sha256()
        for chunk in upload_file.chunks():
            digest.update(chunk)
        upload_file.seek(0)
        return digest.hexdigest()

    @staticmethod
    def _is_duplicate_pdf_upload(content_hash):
        return ExamPDFUpload.objects.filter(
            content_hash=content_hash,
            status__in=[
                ExamPDFUpload.STATUS_PENDING,
                ExamPDFUpload.STATUS_PROCESSING,
                ExamPDFUpload.STATUS_PROCESSED,
            ],
        ).exists()

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['upload_pdfs_url'] = (
            reverse('admin:exam_upload_pdfs', args=[object_id])
            if request.user.has_perms(['exams.add_exampdfupload', 'exams.view_exampdfupload']) else None
        )
        return super().change_view(request, object_id, form_url, extra_context)

    def get_list_display(self, request):
        columns = super().get_list_display(request)
        if not self.has_change_permission(request):
            return [column for column in columns if column != 'activation_controls']
        return columns

    @admin.display(description='Active')
    def active_status(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="font-weight: 600; color: var(--color-primary-600, #7c3aed);">'
                '{}</span>',
                'Active',
            )
        return format_html(
            '<span style="color: var(--color-base-500, #6b7280);">{}</span>',
            'Inactive',
        )

    @admin.display(description='Term state')
    def activation_controls(self, obj):
        if obj.is_active:
            url = reverse('admin:exams_examterm_deactivate', args=[obj.pk])
            label = 'Deactivate'
            color = 'var(--color-danger-600, #dc2626)'
        else:
            url = reverse('admin:exams_examterm_activate', args=[obj.pk])
            label = 'Activate'
            color = 'var(--color-primary-600, #7c3aed)'

        return format_html(
            '<button type="submit" form="changelist-form" formmethod="post" formaction="{}" '
            'style="border: 0; border-radius: var(--border-radius, 6px); color: #fff; '
            'cursor: pointer; font-size: 0.75rem; font-weight: 600; padding: 0.35rem 0.75rem; '
            'background: {};">{}</button>',
            url,
            color,
            label,
        )

    @admin.action(permissions=['change'], description='Activate selected term')
    def activate_selected_term(self, request, queryset):
        terms = list(queryset)
        if len(terms) != 1:
            messages.error(request, 'Select exactly one exam term to activate.')
            return

        terms[0].activate()
        messages.success(request, f'{terms[0]} is now the active exam term.')

    @admin.action(permissions=['change'], description='Deactivate selected term(s)')
    def deactivate_selected_terms(self, request, queryset):
        count = 0
        for term in queryset:
            term.deactivate()
            count += 1

        messages.success(request, f'{count} exam term(s) deactivated.')

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
    list_display = ['original_name', 'pdf_type', 'term', 'status', 'records_created', 'records_updated', 'uploaded_at']
    list_filter = [WorkAttentionFilter, 'term', 'status', 'pdf_type']
    change_list_template = 'admin/exams/exampdfupload/change_list.html'
    readonly_fields = [
        'original_name',
        'pdf_type',
        'term',
        'file',
        'content_hash',
        'status',
        'records_created', 'records_updated',
        'error_message',
        'uploaded_at', 'attempt_count', 'claimed_at', 'next_attempt_at',
    ]
    actions = ['retry_failed_uploads']

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(permissions=['change'], description='Retry failed PDF imports after review')
    def retry_failed_uploads(self, request, queryset):
        from django.utils import timezone
        selected = queryset.count()
        count = queryset.filter(status='failed').update(status='pending', attempt_count=0, next_attempt_at=timezone.now(), claimed_at=None, claim_token=None, error_message='')
        self.message_user(request, f'Queued {count} failed PDF(s) for retry; {selected - count} non-failed PDF(s) skipped.')

    def add_view(self, request, form_url='', extra_context=None):
        return redirect('admin:exams_examterm_upload_pdfs')


@admin.register(ExamNotificationLog)
class ExamNotificationLogAdmin(ModelAdmin):
    list_display = ['term', 'days_before', 'sent_count', 'failed_count', 'sent_at']
    list_filter = ['term']
    readonly_fields = ['term', 'days_before', 'sent_count', 'failed_count', 'sent_at']
