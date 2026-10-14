"""Catalog API endpoints."""
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from ..pagination import list_response
from apps.content.models import Department, CoursePlacement
from ..serializers import DepartmentSerializer, CoursePlacementSerializer, CourseFilterInputSerializer
from ..permissions import IsTelegramAuthenticated




class DepartmentListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        level       = request.query_params.get('level')
        departments = Department.objects.filter(is_active=True)
        if level:
            departments = departments.filter(level=level)
        return list_response(departments.order_by('name', 'pk'), DepartmentSerializer, request)


class CourseListView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request, department_id):
        inputs = CourseFilterInputSerializer(data=request.query_params)
        inputs.is_valid(raise_exception=True)
        params = inputs.validated_data
        program, year, period = params.get('program'), params.get('year'), params.get('period')

        placements = CoursePlacement.objects.filter(
            department_id=department_id,
        ).select_related('course')

        if program:
            placements = placements.filter(program=program)
        if year:
            placements = placements.filter(year=year)
        if period:
            placements = placements.filter(period=period)

        return list_response(placements.order_by('year', 'period', 'course__name', 'pk'), CoursePlacementSerializer, request)
