import logging
import mimetypes
from urllib.parse import urlencode

from django.contrib import admin
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.admin import SimpleListFilter
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.urls import path, reverse
from django.utils.html import format_html
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import redirect
from apps.bot.admin_filters import WorkAttentionFilter
from unfold.admin import ModelAdmin, TabularInline

from . import views_admin
from .models import (
    Department,
    Course,
    CoursePlacement,
    Resource,
    FileInbox,
)
from .services import clear_inbox_file, copy_inbox_file_to_resource
from .forms import ResourceReviewForm
from .delivery import resource_file_url, resource_filename

logger = logging.getLogger(__name__)


# ── Department ────────────────────────────────────────────────────────────────

@admin.register(Department)
class DepartmentAdmin(ModelAdmin):
    list_display  = ['name', 'level', 'is_active', 'created_at']
    list_filter   = ['level', 'is_active']
    search_fields = ['name']
    list_editable = ['is_active']


# ── Course ────────────────────────────────────────────────────────────────────

class CoursePlacementInline(TabularInline):
    model            = CoursePlacement
    extra            = 1
    can_delete       = True
    show_change_link = False
    fields           = ['department', 'program', 'year', 'period']
    autocomplete_fields = ['department']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('department')


@admin.register(Course)
class CourseAdmin(ModelAdmin):
    list_display  = ['name', 'code', 'display_departments', 'display_programs', 'display_years', 'resource_audit_link', 'is_active']
    search_fields = ['name', 'code']
    list_filter   = ['is_active', 'placements__department', 'placements__program', 'placements__year']
    list_editable = ['is_active']
    inlines       = [CoursePlacementInline]
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related(
            'placements__department'
        )

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'course-resource-audit/',
                self.admin_site.admin_view(self.audit_view),
                name='course_resource_audit',
            ),
            path(
                'course-resource-audit/<int:course_id>/',
                self.admin_site.admin_view(self.resource_detail_view),
                name='course_resource_detail',
            ),
            path(
                'course-resource-audit/<int:course_id>/delete-duplicates/',
                self.admin_site.admin_view(views_admin.delete_duplicate_resources),
                name='delete_duplicate_resources',
            ),
            path(
                'resource/<int:resource_id>/delete/',
                self.admin_site.admin_view(views_admin.delete_resource),
                name='delete_resource',
            ),
        ]
        return custom + urls

    def audit_view(self, request):
        """Wraps the audit logic so it gets full Unfold admin context (theme, sidebar, colors)."""
        from django.shortcuts import render
        if not (request.user.has_perm('content.view_course') and request.user.has_perm('content.view_resource')):
            raise PermissionDenied
        context = {
            **self.admin_site.each_context(request),
            **views_admin.course_resource_audit_context(request),
        }
        return render(request, 'admin/content/course_resource_audit.html', context)

    def resource_detail_view(self, request, course_id):
        """Wraps the course resource detail page in the same Unfold admin context."""
        from django.shortcuts import render
        if not (request.user.has_perm('content.view_course') and request.user.has_perm('content.view_resource')):
            raise PermissionDenied
        context = {
            **self.admin_site.each_context(request),
            **views_admin.course_resource_detail_context(course_id, request),
        }
        return render(request, 'admin/content/course_resource_detail.html', context)

    def get_search_results(self, request, queryset, search_term):
        queryset, duplicates = super().get_search_results(request, queryset, search_term)
        if (request.GET.get('app_label') == 'content'
                and request.GET.get('model_name') == 'resource'
                and request.GET.get('field_name') == 'courses'):
            queryset = queryset.filter(is_active=True)
        return queryset, duplicates

    @admin.display(description='Audit')
    def resource_audit_link(self, obj):
        url = reverse('admin:course_resource_detail', kwargs={'course_id': obj.id})
        return format_html('<a href="{}">📋 Resources</a>', url)

    @admin.display(description='Departments')
    def display_departments(self, obj):
        depts = sorted(set(
            p.department.name for p in obj.placements.all() if p.department
        ))
        return ', '.join(depts) if depts else '—'

    @admin.display(description='Programs')
    def display_programs(self, obj):
        programs = sorted(set(p.program for p in obj.placements.all()))
        return ', '.join(programs) if programs else '—'

    @admin.display(description='Years')
    def display_years(self, obj):
        years = sorted(set(p.year for p in obj.placements.all()))
        return ', '.join([f'Y{y}' for y in years]) if years else '—'


# ── Course Placement ──────────────────────────────────────────────────────────

@admin.register(CoursePlacement)
class CoursePlacementAdmin(ModelAdmin):
    autocomplete_fields = ['course', 'department']
    list_display  = ['course', 'department', 'program', 'year', 'period']
    list_filter   = ['department', 'program', 'year', 'period']
    search_fields = ['course__name', 'course__code', 'department__name']
    actions       = ['delete_selected']
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('course', 'department')


# ── Resource ──────────────────────────────────────────────────────────────────

class ResourceReviewFilter(SimpleListFilter):
    title = 'draft review step'
    parameter_name = 'review_step'

    def lookups(self, request, model_admin):
        return [('needs_courses', 'Needs an active course'), ('ready', 'Ready for file review')]

    def queryset(self, request, queryset):
        active_course = Exists(Course.objects.filter(resources=OuterRef('pk'), is_active=True))
        if self.value() == 'needs_courses':
            return queryset.filter(status=Resource.STATUS_PENDING).filter(~active_course)
        if self.value() == 'ready':
            return queryset.filter(status=Resource.STATUS_PENDING).exclude(file='').filter(active_course)
        return queryset


@admin.register(Resource)
class ResourceAdmin(ModelAdmin):
    form = ResourceReviewForm
    autocomplete_fields = ['courses']
    change_form_template = 'admin/content/resource/change_form.html'
    change_list_template = 'admin/content/resource/change_list.html'
    list_display  = ['title', 'display_courses', 'file_type', 'source', 'access_level', 'status', 'downloads_count', 'created_at']
    list_filter   = ['status', ResourceReviewFilter, 'file_type', 'source', 'access_level', 'courses']
    search_fields = ['title', 'extracted_text', 'original_caption', 'courses__name', 'courses__code']
    readonly_fields = [
        'extracted_text', 'downloads_count', 'telegram_message_id',
        'original_caption', 'created_at', 'updated_at', 'file_size', 'page_count', 'file_review',
    ]
    list_editable = ['source', 'access_level']
    list_per_page = 25
    actions       = ['publish_selected', 'reject_selected', 'mark_as_free', 'mark_as_premium']
    fieldsets = (
        ('Resource Info', {
            'fields': ('title', 'file', 'file_review', 'file_size', 'page_count', 'file_type', 'source', 'courses')
        }),
        ('Access & Status', {
            'fields': ('access_level', 'status')
        }),
        ('Extracted Content', {
            'fields': ('extracted_text',),
            'classes': ('collapse',),
        }),
        ('Telegram Source', {
            'fields': ('telegram_message_id', 'original_caption'),
            'classes': ('collapse',),
        }),
        ('Stats', {
            'fields': ('downloads_count', 'created_at', 'updated_at')
        }),
    )

    def changelist_view(self, request, extra_context=None):
        context = {
            'workflow_title': 'Draft → course assignment → review → publish',
            'workflow_help': 'Open a draft, assign its active courses and review its file. Publish from the detail form or select reviewed drafts and use Publish selected reviewed drafts.',
            'workflow_links': [
                {'label': 'Drafts needing courses', 'url': reverse('admin:content_resource_changelist') + '?review_step=needs_courses'},
                {'label': 'Ready for file review', 'url': reverse('admin:content_resource_changelist') + '?review_step=ready'},
            ],
            **(extra_context or {}),
        }
        return super().changelist_view(request, context)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('courses')

    @admin.display(description='Courses')
    def display_courses(self, obj):
        courses = obj.courses.all()
        if not courses:
            return '—'
        course_codes = [f'{course.code}' for course in courses[:3]]
        more_count = courses.count() - 3
        return ', '.join(course_codes) + (f' +{more_count} more' if more_count > 0 else '')

    def get_urls(self):
        return [path('<int:resource_id>/preview/', self.admin_site.admin_view(self.preview_file),
                     name='content_resource_preview')] + super().get_urls()

    def preview_file(self, request, resource_id):
        resource = self.get_object(request, str(resource_id))
        if resource is None:
            raise Http404
        if not self.has_view_or_change_permission(request, resource):
            raise PermissionDenied
        if not resource.file:
            raise Http404('No file is attached to this resource.')
        from storages.backends.s3 import S3Storage
        if isinstance(resource.file.storage, S3Storage):
            return redirect(resource_file_url(resource, request, inline=True))
        try:
            handle = resource.file.open('rb')
        except OSError:
            raise Http404('The stored file is unavailable.') from None
        return FileResponse(handle, filename=resource_filename(resource),
                            content_type=mimetypes.guess_type(resource.file.name)[0] or 'application/octet-stream')

    @admin.display(description='Review file')
    def file_review(self, obj):
        if not obj.pk or not obj.file:
            return 'Attach a file, then save the draft to preview it.'
        return format_html('<a href="{}" target="_blank" rel="noopener">Open file for review</a>',
                           reverse('admin:content_resource_preview', args=[obj.pk]))

    def render_change_form(self, request, context, *args, **kwargs):
        obj = context['adminform'].form.instance
        context['workflow_title'] = 'Review and publish'
        context['workflow_help'] = (
            '1. Check the title and file. 2. Assign active courses using search. '
            '3. Save as Pending to continue later, or choose Published after reviewing. '
            'Publishing requires an attached file and at least one active course.'
        )
        if obj.pk:
            context['workflow_links'] = [{
                'label': 'Back to draft resources',
                'url': reverse('admin:content_resource_changelist') + '?status__exact=pending',
            }]
        return super().render_change_form(request, context, *args, **kwargs)

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        course_id = request.GET.get('course')
        if course_id:
            initial['courses'] = [course_id]
        return initial

    @admin.action(permissions=['change'], description='Publish selected reviewed drafts')
    @transaction.atomic
    def publish_selected(self, request, queryset):
        selected = queryset.count()
        active_course = Course.objects.filter(resources=OuterRef('pk'), is_active=True)
        eligible = list(Resource.objects.select_for_update().filter(
            pk__in=queryset.values('pk'), status=Resource.STATUS_PENDING,
        ).exclude(file='').filter(Exists(active_course)))
        count = Resource.objects.filter(pk__in=[obj.pk for obj in eligible]).update(status=Resource.STATUS_PUBLISHED)
        LogEntry.objects.log_actions(
            user_id=request.user.pk, queryset=eligible, action_flag=CHANGE,
            change_message='Published reviewed draft with an attached file and active course.',
        )
        self.message_user(
            request,
            f'{count} draft resource(s) published; {selected - count} skipped. '
            'Only pending drafts with an attached file and an active course can be published.',
            messages.SUCCESS if count else messages.WARNING,
        )

    @admin.action(permissions=['change'], description='Reject selected resources')
    def reject_selected(self, request, queryset):
        count = queryset.update(status=Resource.STATUS_REJECTED)
        self.message_user(request, f'{count} resource(s) rejected.')

    @admin.action(permissions=['change'], description='Mark selected as Free')
    def mark_as_free(self, request, queryset):
        count = queryset.update(access_level=Resource.ACCESS_FREE)
        self.message_user(request, f'{count} resource(s) marked as free.')

    @admin.action(permissions=['change'], description='Mark selected as Premium')
    def mark_as_premium(self, request, queryset):
        count = queryset.update(access_level=Resource.ACCESS_PREMIUM)
        self.message_user(request, f'{count} resource(s) marked as premium.')


# ── File Inbox ────────────────────────────────────────────────────────────────

class AssignmentFilter(SimpleListFilter):
    title          = 'assignment status'
    parameter_name = 'assigned'

    def lookups(self, request, model_admin):
        return [
            ('unassigned', 'Unassigned (pending)'),
            ('assigned',   'Assigned'),
            ('all',        'All'),
        ]

    def queryset(self, request, queryset):
        if self.value() == 'assigned':
            return queryset.filter(assigned_resource__isnull=False)
        if self.value() == 'all':
            return queryset
        return queryset.filter(assigned_resource__isnull=True)


@admin.register(FileInbox)
class FileInboxAdmin(ModelAdmin):
    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.has_perm('content.add_resource'):
            actions.pop('publish_as_resource', None)
        if not request.user.has_perm('quiz.add_question'):
            actions.pop('extract_questions', None)
        return actions

    change_form_template = 'admin/content/fileinbox/change_form.html'
    change_list_template = 'admin/content/fileinbox/change_list.html'
    list_display  = ['original_filename', 'telegram_caption_preview', 'posted_date', 'processing_status', 'is_assigned']
    list_filter   = [WorkAttentionFilter, AssignmentFilter, 'processing_status']
    search_fields = ['original_filename', 'telegram_caption', 'extracted_text']
    readonly_fields = [
        'original_filename', 'telegram_message_id', 'telegram_caption',
        'posted_date', 'processing_status', 'extracted_text',
        'processing_error', 'extraction_outcome', 'attempt_count', 'claimed_at', 'next_attempt_at', 'telegram_chat_id', 'created_at', 'assigned_resource',
    ]
    actions       = ['retry_failed_extraction', 'mark_as_processed', 'publish_as_resource', 'extract_questions']
    list_per_page = 25
    fieldsets = (
        ('File Info', {
            'fields': ('file', 'original_filename', 'telegram_chat_id', 'telegram_message_id', 'telegram_caption', 'posted_date')
        }),
        ('Processing', {
            'fields': ('processing_status', 'processing_error', 'extraction_outcome', 'attempt_count', 'claimed_at', 'next_attempt_at')
        }),
        ('Extracted Text', {
            'fields': ('extracted_text',),
            'classes': ('collapse',),
        }),
        ('Assignment', {
            'fields': ('assigned_resource',)
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('assigned_resource')

    def render_change_form(self, request, context, *args, **kwargs):
        obj = context['adminform'].form.instance
        context['workflow_title'] = 'Inbox → draft → review → publish'
        links = []
        if obj.assigned_resource_id:
            help_text = 'A resource draft has already been created from this file. Open it to assign courses, review and publish.'
            resource_admin = self.admin_site._registry[Resource]
            if resource_admin.has_view_or_change_permission(request):
                links.append({'label': 'Open linked resource', 'url': reverse(
                    'admin:content_resource_change', args=[obj.assigned_resource_id])})
        elif obj.processing_status == FileInbox.STATUS_PROCESSED and obj.file:
            help_text = 'Text extraction is complete. Select this file in the inbox and use Create draft resources. Then assign courses, review the file and publish.'
        elif obj.processing_status == FileInbox.STATUS_FAILED:
            help_text = 'Extraction failed. Review the processing error, then select Retry failed text extraction from the inbox after fixing the cause.'
        else:
            help_text = 'The worker must finish processing this file before you can create a draft. Pending work is not published to students.'
        links.append({'label': 'Back to file inbox', 'url': reverse('admin:content_fileinbox_changelist')})
        context.update(workflow_help=help_text, workflow_links=links)
        return super().render_change_form(request, context, *args, **kwargs)

    def changelist_view(self, request, extra_context=None):
        context = {
            'workflow_title': 'Start with extracted, unassigned files',
            'workflow_help': 'Select processed files and use Create draft resources in Actions. A single draft opens directly; a batch opens its draft review list. Assigned files are hidden by default; use the assignment filter to revisit them.',
            'workflow_links': [{'label': 'Extracted files ready for drafts', 'url': reverse('admin:content_fileinbox_changelist') + '?processing_status__exact=processed&assigned=unassigned'}],
            **(extra_context or {}),
        }
        return super().changelist_view(request, context)

    @admin.display(description='Assigned', boolean=True)
    def is_assigned(self, obj):
        return obj.assigned_resource is not None

    @admin.display(description='Caption')
    def telegram_caption_preview(self, obj):
        if obj.telegram_caption:
            return obj.telegram_caption[:60] + ('...' if len(obj.telegram_caption) > 60 else '')
        return '—'

    @admin.action(permissions=['change'], description='Retry failed text extraction after review')
    def retry_failed_extraction(self, request, queryset):
        from django.utils import timezone
        selected = queryset.count()
        count = queryset.filter(processing_status='failed', assigned_resource__isnull=True).exclude(file='').update(
            processing_status='unprocessed', attempt_count=0, next_attempt_at=timezone.now(),
            claimed_at=None, claim_token=None, processing_error='',
        )
        self.message_user(request, f'Queued {count} file(s) for extraction; {selected - count} ineligible file(s) skipped.')

    @admin.action(permissions=['change'], description='Manually mark selected as processed (does not extract text)')
    def mark_as_processed(self, request, queryset):
        selected = queryset.count()
        count = queryset.exclude(processing_status='processing').update(processing_status=FileInbox.STATUS_PROCESSED)
        self.message_user(request, f'{count} item(s) manually marked as processed; {selected - count} processing item(s) skipped. Text extraction was not run.')

    @admin.action(permissions=['change'], description='Create draft resources — assign courses and review next')
    def publish_as_resource(self, request, queryset):
        if not request.user.has_perm('content.add_resource'):
            raise PermissionDenied
        selected = queryset.count()
        created_ids = []
        failed = 0
        for item in queryset.filter(
            processing_status=FileInbox.STATUS_PROCESSED, assigned_resource__isnull=True,
        ).exclude(file=''):
            try:
                with transaction.atomic():
                    item = FileInbox.objects.select_for_update().get(pk=item.pk)
                    if item.assigned_resource_id or item.processing_status != FileInbox.STATUS_PROCESSED or not item.file:
                        continue
                    title = item.telegram_caption.strip() or item.original_filename
                    resource = Resource(
                        title=title[:500], file_type=Resource.TYPE_LECTURE_NOTE,
                        source=Resource.SOURCE_OTHER, extracted_text=item.extracted_text,
                        access_level=Resource.ACCESS_PREMIUM, status=Resource.STATUS_PENDING,
                        telegram_message_id=item.telegram_message_id, original_caption=item.telegram_caption,
                    )
                    copy_inbox_file_to_resource(item, resource)
                    resource.save()
                    item.assigned_resource = resource
                    item.save(update_fields=['assigned_resource'])
                    clear_inbox_file(item, protected_file_name=resource.file.name)
                    self.admin_site._registry[Resource].log_addition(request, resource, 'Created draft from file inbox.')
                    self.log_change(request, item, 'Linked to a resource draft.')
                created_ids.append(resource.pk)
            except Exception as exc:
                failed += 1
                logger.warning('Draft creation failed inbox_id=%s error_type=%s', item.pk, type(exc).__name__)
                self.message_user(request, f'Could not create a draft for {item.original_filename}. Check file availability and try again.', messages.ERROR)

        self.message_user(
            request,
            f'{len(created_ids)} draft resource(s) created; {failed} failed; '
            f'{selected - len(created_ids) - failed} ineligible or already assigned file(s) skipped. '
            'Assign courses, review the file, then publish.',
            messages.WARNING if failed else messages.SUCCESS,
        )
        resource_admin = self.admin_site._registry[Resource]
        if created_ids and resource_admin.has_view_or_change_permission(request):
            if len(created_ids) == 1:
                return HttpResponseRedirect(reverse('admin:content_resource_change', args=created_ids))
            return HttpResponseRedirect(reverse('admin:content_resource_changelist') + '?' + urlencode({
                'id__in': ','.join(map(str, created_ids)), 'status__exact': Resource.STATUS_PENDING,
            }))

    @admin.action(permissions=['change'], description='Extract questions from selected files using AI')
    def extract_questions(self, request, queryset):
        if not request.user.has_perm('quiz.add_question'):
            raise PermissionDenied
        from apps.bot.ai_tasks import queue_question_extraction
        queued = 0
        for item in queryset.filter(processing_status=FileInbox.STATUS_PROCESSED).exclude(extracted_text=''):
            try:
                _, created = queue_question_extraction(item)
                queued += int(created)
            except ValueError as exc:
                self.message_user(request, f'{item.original_filename}: {exc}', messages.WARNING)
        self.message_user(request, f'Queued {queued} extraction(s). Review progress at /admin/bot/questionextraction/ and generated questions under Quiz.', messages.SUCCESS)
