from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path('auth/telegram/', views.TelegramAuthView.as_view(), name='auth-telegram'),

    # Student
    path('students/me/', views.StudentProfileView.as_view(), name='student-profile'),
    path('students/me/watermark/', views.StudentWatermarkView.as_view(), name='student-watermark'),
    path('students/me/performance/', views.PerformanceView.as_view(), name='student-performance'),

    # Departments
    path('departments/', views.DepartmentListView.as_view(), name='department-list'),

    # Courses
    path('departments/<int:department_id>/courses/', views.CourseListView.as_view(), name='course-list'),

    # Resources
    path('courses/<int:course_id>/resources/', views.ResourceListView.as_view(), name='resource-list'),
    path('resources/<int:resource_id>/', views.ResourceDetailView.as_view(), name='resource-detail'),
    path('resources/<int:resource_id>/download/', views.ResourceDownloadView.as_view(), name='resource-download'),

    # Quiz
    path('courses/<int:course_id>/questions/', views.QuestionListView.as_view(), name='question-list'),
    path('quiz/attempts/', views.QuizAttemptView.as_view(), name='quiz-attempts'),

    # Exams
    path('exams/', views.ExamPaperListView.as_view(), name='exam-list'),
    path('exams/<int:exam_id>/questions/', views.ExamPaperQuestionsView.as_view(), name='exam-questions'),
    path('exit-exams/topics/', views.ExitExamTopicsView.as_view(), name='exit-exam-topics'),

    # Subscription
    path('subscription/plans/', views.SubscriptionPlansView.as_view(), name='subscription-plans'),
    path('subscription/request/', views.SubscriptionRequestView.as_view(), name='subscription-request'),
]