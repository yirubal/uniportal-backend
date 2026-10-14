"""Students API endpoints."""
from rest_framework.views import APIView
from rest_framework.response import Response
from ..serializers import StudentSerializer
from ..permissions import IsTelegramAuthenticated, IsPremium




class StudentProfileView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        return Response(StudentSerializer(request.student).data)

    def patch(self, request):
        student = request.student
        serializer = StudentSerializer(student, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class StudentWatermarkView(APIView):
    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        student  = request.student
        username = f'@{student.username}' if student.username else f'ID:{student.telegram_id}'
        watermark = f'{username} · {student.telegram_id} · Unity Uni'
        return Response({'watermark': watermark})


class PerformanceView(APIView):
    permission_classes = [IsTelegramAuthenticated, IsPremium]

    def get(self, request):
        from apps.quiz.engine import get_performance_summary
        return Response(get_performance_summary(request.student))
