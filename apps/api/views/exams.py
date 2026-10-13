"""Exams API endpoints."""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from apps.exams.models import ExamTerm, StudentExam
from ..permissions import IsTelegramAuthenticated




class ActiveExamTermView(APIView):
    """Returns whether an active exam term exists."""

    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        term = ExamTerm.objects.filter(is_active=True).first()
        if not term:
            return Response({'active': False})

        return Response({
            'active': True,
            'year': term.year,
            'term': term.term,
            'center': term.center,
        })


class ExamLookupView(APIView):
    """
    Looks up a student's exam schedule by student ID or name.
    Query params: ?query=93372 OR ?query=Abirham
    Legacy params ?student_id= and ?name= are still supported.
    Returns all exams for the active term.
    """

    permission_classes = [IsTelegramAuthenticated]

    def get(self, request):
        query = request.query_params.get('query', '').strip()

        if not query:
            query = request.query_params.get('student_id', '').strip()
        if not query:
            query = request.query_params.get('name', '').strip()

        if not query:
            return Response(
                {'error': 'Enter your student ID or name to search'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        term = ExamTerm.objects.filter(is_active=True).first()
        if not term:
            return Response(
                {'error': 'No active exam schedule available right now'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if query.isdigit():
            exams = StudentExam.objects.filter(
                term=term,
                student_id=query,
            ).select_related('session')

            if not exams.exists():
                return Response(
                    {'error': f'No exam found for ID {query}. Check your student ID.'},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            if len(query) < 3:
                return Response(
                    {'error': 'Enter at least 3 characters to search by name'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            exams = StudentExam.objects.filter(
                term=term,
                student_name__istartswith=query,
            ).select_related('session')

            if not exams.exists():
                first_word = query.split()[0]
                exams = StudentExam.objects.filter(
                    term=term,
                    student_name__istartswith=first_word + ' ',
                ).select_related('session')

            if not exams.exists():
                return Response(
                    {
                        'error': (
                            f'No exam found for "{query}". '
                            'Try your first name only or your student ID.'
                        )
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            if exams.count() > 20:
                return Response(
                    {
                        'error': (
                            f'Too many results for "{query}". '
                            'Please be more specific — try your full first name '
                            'or use your student ID instead.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        seen = set()
        results = []
        for exam in exams.order_by('session__date', 'session__start_time'):
            key = (exam.session.date, exam.course_code)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    'course_name': exam.course_name,
                    'course_code': exam.course_code,
                    'room_code': exam.room_code,
                    'department': exam.department,
                    'date': exam.session.date.strftime('%A, %B %d, %Y'),
                    'start_time': exam.session.start_time.strftime('%I:%M %p'),
                    'end_time': exam.session.end_time.strftime('%I:%M %p'),
                    'session': f'Session {exam.session.session_number}',
                }
            )

        first_exam = exams.first()
        return Response({
            'student_name': first_exam.student_name,
            'student_id': first_exam.student_id,
            'term': str(term),
            'exams': results,
        })
