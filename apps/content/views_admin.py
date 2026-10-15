"""
apps/content/views_admin.py

Custom admin views: Course Resource Audit Dashboard
"""

from urllib.parse import urlencode, parse_qsl

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import permission_required
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib import messages
from django.db.models import Count, Q, Prefetch, Exists, OuterRef, Window
from django.db.models.functions import Lower, Trim
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST

from .models import Course, Resource, CoursePlacement, Department


def course_resource_audit_context(request) -> dict:
    """Count published coverage in one consistent course/placement scope."""
    search = request.GET.get('q', '').strip()
    program = request.GET.get('program', '')
    if program not in dict(CoursePlacement.PROGRAM_CHOICES):
        program = ''
    try:
        dept_filter = int(request.GET.get('department', '')) or None
    except (ValueError, TypeError):
        dept_filter = None
    active_tab = request.GET.get('tab', 'overview')
    if active_tab not in {'overview', 'missing', 'covered'}:
        active_tab = 'overview'

    courses = Course.objects.filter(is_active=True)
    placement_scope = CoursePlacement.objects.filter(course_id=OuterRef('pk'))
    if dept_filter:
        placement_scope = placement_scope.filter(department_id=dept_filter, department__is_active=True)
    if program:
        placement_scope = placement_scope.filter(program=program)
    if dept_filter or program:
        courses = courses.filter(Exists(placement_scope))
    if search:
        courses = courses.filter(Q(name__icontains=search) | Q(code__icontains=search))

    published = Resource.objects.filter(courses=OuterRef('pk'), status=Resource.STATUS_PUBLISHED)
    courses = courses.annotate(has_published=Exists(published))
    course_counts = courses.aggregate(
        total=Count('pk'), covered=Count('pk', filter=Q(has_published=True)),
    )
    total = course_counts['total']
    covered = course_counts['covered']
    resources = Resource.objects.filter(courses__in=courses)
    resource_counts = resources.aggregate(
        total=Count('pk', distinct=True),
        published=Count('pk', filter=Q(status=Resource.STATUS_PUBLISHED), distinct=True),
        pending=Count('pk', filter=Q(status=Resource.STATUS_PENDING), distinct=True),
    )
    # One grouped query for every department; repeated placements count once.
    department_scope = Q(course_placements__course__in=courses)
    if program:
        department_scope &= Q(course_placements__program=program)
    departments = Department.objects.filter(is_active=True)
    if dept_filter:
        departments = departments.filter(pk=dept_filter)
    department_counts = departments.annotate(
        total_courses=Count('course_placements__course', filter=department_scope, distinct=True),
        with_resources=Count('course_placements__course', filter=department_scope & Q(
            course_placements__course__resources__status=Resource.STATUS_PUBLISHED), distinct=True),
        resource_count=Count('course_placements__course__resources', filter=department_scope & Q(
            course_placements__course__resources__status=Resource.STATUS_PUBLISHED), distinct=True),
    ).filter(total_courses__gt=0).order_by('name', 'pk')

    params = {}
    if search:
        params['q'] = search
    if dept_filter:
        params['department'] = dept_filter
    if program:
        params['program'] = program
    tab_links = [{'key': key, 'label': label, 'url': '?' + urlencode({**params, 'tab': key})}
                 for key, label in [('overview', 'By department'), ('missing', f'Missing published material ({total - covered})'),
                                    ('covered', f'Published material ({covered})')]]
    params['tab'] = active_tab
    dept_stats, course_page = [], None
    if active_tab == 'overview':
        page = Paginator(department_counts, 24).get_page(request.GET.get('page'))
        for dept in page:
            dept_stats.append({'department': dept, 'total_courses': dept.total_courses,
                               'with_resources': dept.with_resources,
                               'without': dept.total_courses - dept.with_resources,
                               'resource_count': dept.resource_count,
                               'coverage_pct': round(100 * dept.with_resources / dept.total_courses)})
    else:
        placements = CoursePlacement.objects.select_related('department').filter(department__is_active=True)
        if program:
            placements = placements.filter(program=program)
        if dept_filter:
            placements = placements.filter(department_id=dept_filter)
        listed_courses = courses.filter(has_published=active_tab == 'covered').annotate(
            published_count=Count('resources', filter=Q(resources__status=Resource.STATUS_PUBLISHED), distinct=True),
            pending_count=Count('resources', filter=Q(resources__status=Resource.STATUS_PENDING), distinct=True),
        ).prefetch_related(Prefetch('placements', queryset=placements.order_by('department__name', 'program', 'year', 'period')))
        page = Paginator(listed_courses.order_by('name', 'pk'), 25).get_page(request.GET.get('page'))
        course_page = page

    return {
        'title': 'Resource coverage', 'opts': Course._meta,
        'total_courses': total, 'courses_with_resources': covered,
        'courses_without_resources': total - covered,
        'overall_coverage_pct': round(100 * covered / total) if total else 0,
        'total_resources': resource_counts['total'], 'published_resources': resource_counts['published'],
        'pending_resources': resource_counts['pending'],
        'metrics': [
            ('Active courses', total), ('With published material', covered),
            ('Missing published material', total - covered), ('Resources in scope', resource_counts['total']),
            ('Published resources', resource_counts['published']), ('Drafts to review', resource_counts['pending']),
        ],
        'dept_stats': dept_stats, 'courses': course_page, 'page_obj': page,
        'pagination_query': urlencode(params), 'return_query': urlencode({**params, 'page': page.number}), 'tab_links': tab_links,
        'departments': Department.objects.filter(is_active=True).order_by('name'),
        'program_choices': CoursePlacement.PROGRAM_CHOICES, 'program': program,
        'dept_filter': dept_filter, 'search': search, 'active_tab': active_tab,
    }


def course_resource_detail_context(course_id, request=None) -> dict:
    course = get_object_or_404(Course, id=course_id)
    resources = Resource.objects.filter(courses=course)
    counts = resources.aggregate(
        total=Count('pk'), published=Count('pk', filter=Q(status=Resource.STATUS_PUBLISHED)),
        pending=Count('pk', filter=Q(status=Resource.STATUS_PENDING)),
    )
    matching_titles = resources.annotate(normalized_title=Lower(Trim('title'))).values(
        'normalized_title').annotate(matches=Count('pk')).filter(matches__gt=1).order_by()
    listed = resources.annotate(title_matches=Window(
        expression=Count('pk'), partition_by=[Lower(Trim('title'))],
    )).prefetch_related('courses').order_by('file_type', 'title', 'pk')
    page = Paginator(listed, 25).get_page(request.GET.get('page') if request else None)
    audit_filters = request.GET.get('audit_filters', '') if request else ''
    # Only carry filter values back to a fixed local admin route.
    allowed_filters = {key: value for key, value in parse_qsl(audit_filters)
                       if key in {'q', 'department', 'program', 'tab', 'page'}}
    audit_query = urlencode(allowed_filters)
    return {
        'title': f'Resources — {course.name}', 'course': course, 'opts': Course._meta,
        'resources_with_flags': [{'resource': resource, 'is_duplicate': resource.title_matches > 1} for resource in page],
        'placements': CoursePlacement.objects.filter(course=course).select_related('department').order_by('department__name', 'year', 'period'),
        'total': counts['total'], 'published_count': counts['published'], 'pending_count': counts['pending'],
        'duplicate_count': matching_titles.count(), 'page_obj': page,
        'audit_url': reverse('admin:course_resource_audit') + ('?' + audit_query if audit_query else ''),
        'pagination_query': urlencode({'audit_filters': audit_query}) if audit_query else '',
    }


@staff_member_required
@permission_required(('content.view_course', 'content.view_resource'), raise_exception=True)
def course_resource_detail(request, course_id):
    context = course_resource_detail_context(course_id, request)
    return render(request, 'admin/content/course_resource_detail.html', context)


@staff_member_required
@permission_required('content.delete_resource', raise_exception=True)
@require_POST
def delete_resource(request, resource_id):
    # Old links must go through Django's permission checks, related-object review
    # and explicit deletion confirmation before any record can be removed.
    get_object_or_404(Resource, id=resource_id)
    return redirect('admin:content_resource_delete', object_id=resource_id)


@staff_member_required
@permission_required(('content.view_course', 'content.view_resource'), raise_exception=True)
@require_POST
def delete_duplicate_resources(request, course_id):
    get_object_or_404(Course, id=course_id)
    messages.warning(
        request,
        'Matching titles are only possible duplicates. Compare the files and '
        'course associations, then use Review deletion for an individual resource.',
    )
    return redirect('admin:course_resource_detail', course_id=course_id)
