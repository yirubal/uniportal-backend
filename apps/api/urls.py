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
    path('resources/<int:resource_id>/download/file/<path:token>/', views.ResourceDownloadFileView.as_view(), name='resource-download-file'),
    path('resources/<int:resource_id>/download/file/', views.ResourceDownloadFileView.as_view(), name='resource-download-file-query'),

    # Exams
    path('exams/', views.ExamPaperListView.as_view(), name='exam-list'),
    path('exams/<int:exam_id>/questions/', views.ExamPaperQuestionsView.as_view(), name='exam-questions'),

    # Exit Exam Topics
    path('exit-exams/topics/', views.ExitExamTopicsView.as_view(), name='exit-exam-topics'),
    path('exit-exams/topics/questions/', views.TopicQuestionsView.as_view(), name='exit-exam-topic-questions'),

    # Quiz Attempts
    path('quiz/attempts/', views.QuizAttemptView.as_view(), name='quiz-attempts'),

    # Subscription
    path('subscription/plans/', views.SubscriptionPlansView.as_view(), name='subscription-plans'),
    path('subscription/request/', views.SubscriptionRequestView.as_view(), name='subscription-request'),
]
