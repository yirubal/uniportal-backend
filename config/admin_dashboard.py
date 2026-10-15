"""Task navigation and small database summaries for the existing Django admin."""
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group, User
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import BroadcastMessage, SiteSettings, Student, SubscriptionPlan, SubscriptionRequest
from apps.bot.admin_filters import work_attention_conditions
from apps.bot.models import NotificationDelivery, QuestionExtraction, TelegramUpdate
from apps.content.models import Course, CoursePlacement, Department, FileInbox, Resource
from apps.exams.models import ExamNotificationLog, ExamPDFUpload, ExamSession, ExamTerm, StudentExam
from apps.quiz.models import Chapter, ExamPaper, Question, QuizAttempt


def can_view(request, model):
    return admin.site._registry[model].has_view_or_change_permission(request)


def changelist(model):
    return reverse(f'admin:{model._meta.app_label}_{model._meta.model_name}_changelist')


def navigation(request):
    # Keep destinations explicit; standard model links inherit Django permissions.
    groups = [
        ('', [('Overview', 'dashboard', 'admin:index', None, ())]),
        ('Content', [
            ('File inbox', 'inbox', None, FileInbox, ()),
            ('Resources', 'folder', None, Resource, ()),
            ('Courses', 'menu_book', None, Course, ()),
            ('Resource coverage', 'fact_check', 'admin:course_resource_audit', Course,
             ('content.view_course', 'content.view_resource')),
            ('Departments', 'apartment', None, Department, ()),
            ('Course placements', 'account_tree', None, CoursePlacement, ()),
        ]),
        ('Exams & quizzes', [
            ('Exam terms', 'calendar_month', None, ExamTerm, ()),
            ('Exam sessions', 'schedule', None, ExamSession, ()),
            ('Student exam records', 'assignment', None, StudentExam, ()),
            ('Exam PDF imports', 'upload_file', None, ExamPDFUpload, ()),
            ('Exam papers', 'description', None, ExamPaper, ()),
            ('Questions', 'quiz', None, Question, ()),
            ('Chapters', 'menu_book', None, Chapter, ()),
            ('Quiz attempts', 'history_edu', None, QuizAttempt, ()),
        ]),
        ('Students & communication', [
            ('Find a student', 'people', None, Student, ()),
            ('Send broadcast', 'campaign', 'admin:accounts_broadcast', None, ('accounts.add_broadcastmessage',)),
            ('Broadcast history', 'history', None, BroadcastMessage, ()),
            ('Payment requests', 'payments', None, SubscriptionRequest, ()),
        ]),
        ('Operations', [
            ('Telegram updates', 'sync', None, TelegramUpdate, ()),
            ('File processing', 'manage_search', None, FileInbox, ()),
            ('Question extraction', 'psychology', None, QuestionExtraction, ()),
            ('Message delivery', 'outgoing_mail', None, NotificationDelivery, ()),
            ('Exam reminder history', 'notifications', None, ExamNotificationLog, ()),
        ]),
        ('Settings', [
            ('Site settings', 'settings', None, SiteSettings, ()),
            ('Subscription plans', 'card_membership', None, SubscriptionPlan, ()),
            ('Staff accounts', 'admin_panel_settings', None, User, ()),
            ('Staff groups', 'group', None, Group, ()),
        ]),
    ]
    result = []
    for title, destinations in groups:
        items = []
        for label, icon, route, model, permissions in destinations:
            if model is not None and not can_view(request, model):
                continue
            if not request.user.has_perms(permissions):
                continue
            item = {'title': label, 'icon': icon,
                    'link': reverse(route) if route else changelist(model)}
            if route == 'admin:index':
                item['active'] = request.path == reverse('admin:index')
            if label == 'File processing':
                item['link'] += '?assigned=all'
            items.append(item)
        if items:
            result.append({'title': title, 'separator': bool(title),
                           'collapsible': bool(title), 'items': items})
    return result


def dashboard(request, context):
    now = timezone.now()
    cards, queues, shortcuts = [], [], []
    for label, icon, route, allowed in [
        ('Review file inbox', 'inbox', 'admin:content_fileinbox_changelist', can_view(request, FileInbox)),
        ('Create a resource', 'add', 'admin:content_resource_add', request.user.has_perm('content.add_resource')),
        ('Upload exam PDFs', 'upload_file', 'admin:exams_examterm_upload_pdfs',
         request.user.has_perms(['exams.add_exampdfupload', 'exams.view_exampdfupload'])),
        ('Find a student', 'person_search', 'admin:accounts_student_changelist', can_view(request, Student)),
    ]:
        if allowed:
            shortcuts.append({'label': label, 'icon': icon, 'url': reverse(route)})

    for model, label, status_field in [
        (ExamPDFUpload, 'Exam PDF imports', 'status'),
        (FileInbox, 'File extraction', 'processing_status'),
        (QuestionExtraction, 'Question extraction', 'status'),
        (NotificationDelivery, 'Message delivery', 'status'),
        (TelegramUpdate, 'Telegram updates', 'status'),
    ]:
        if not can_view(request, model):
            continue
        conditions = work_attention_conditions(status_field, now)
        counts = model.objects.aggregate(**{
            key: Count('pk', filter=condition) for key, condition in conditions.items()
        })
        url = changelist(model)
        # The inbox normally hides assigned records. Operations must include them.
        url += '?assigned=all&' if model is FileInbox else '?'
        queues.append({'label': label, 'counts': [
            {'label': caption, 'value': counts[key], 'url': url + f'attention={key}'}
            for key, caption in [('failed', 'Failed'), ('overdue', 'Overdue'), ('stale', 'Stale')]
        ]})
        for key, caption in [('failed', 'failed'), ('overdue', 'pending over 15 minutes'), ('stale', 'stale claims')]:
            if counts[key]:
                cards.append({'label': f'{label}: {caption}', 'value': counts[key],
                              'url': url + f'attention={key}', 'urgent': True})

    for model, label, condition, query in [
        (Resource, 'Draft resources to review', Q(status='pending'), 'status__exact=pending'),
        (FileInbox, 'Extracted files to assign', Q(processing_status='processed', assigned_resource__isnull=True),
         'processing_status__exact=processed&assigned=unassigned'),
        (Question, 'Questions without an exam paper', Q(exam_paper__isnull=True), 'assignment_status=unassigned'),
    ]:
        if can_view(request, model):
            cards.append({'label': label, 'value': model.objects.filter(condition).count(),
                          'url': changelist(model) + '?' + query, 'urgent': False})

    active_term = None
    if can_view(request, ExamTerm):
        term = ExamTerm.objects.filter(is_active=True).first()
        if term:
            active_term = {'label': str(term), 'start_date': term.exam_start_date,
                           'url': reverse('admin:exams_examterm_change', args=[term.pk])}

    visible_models = Q(pk__in=[])
    for model in admin.site._registry:
        if can_view(request, model):
            visible_models |= Q(content_type__app_label=model._meta.app_label,
                                content_type__model=model._meta.model_name)
    activity = []
    for entry in LogEntry.objects.filter(visible_models).select_related('content_type', 'user').order_by('-action_time', '-pk')[:6]:
        activity.append({'label': entry.object_repr, 'action': entry.get_action_flag_display(),
                         'at': entry.action_time, 'by': entry.user.get_username(),
                         'url': entry.get_admin_url() if not entry.is_deletion() else None})

    context.update(title='Overview', attention_cards=cards, work_queues=queues,
                   task_shortcuts=shortcuts, active_exam_term=active_term,
                   can_view_exam_terms=can_view(request, ExamTerm), recent_activity=activity,
                   observed_at=now)
    return context
