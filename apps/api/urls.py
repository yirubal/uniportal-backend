from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path('auth/telegram/', views.TelegramAuthView.as_view(), name='auth-telegram'),
    path('telegram/webhook/', views.TelegramWebhookView.as_view(), name='telegram-webhook'),

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
    path('exams/lookup/', views.ExamLookupView.as_view(), name='exam-lookup'),
    path('exams/active-term/', views.ActiveExamTermView.as_view(), name='exam-active-term'),

    # Selective Practice
    path('quiz/courses/<int:course_id>/chapters/', views.CourseChaptersView.as_view(), name='course-chapters'),
    path('quiz/courses/<int:course_id>/topics/', views.CourseTopicsView.as_view(), name='course-topics'),
    path('quiz/selective-practice/', views.SelectivePracticeView.as_view(), name='selective-practice'),

    # Exit Exam Topics
    path('exit-exams/topics/', views.ExitExamTopicsView.as_view(), name='exit-exam-topics'),
    path('exit-exams/topics/questions/', views.TopicQuestionsView.as_view(), name='exit-exam-topic-questions'),

    # Quiz Attempts
    path('quiz/attempts/', views.QuizAttemptView.as_view(), name='quiz-attempts'),
    path('quiz/attempts/<int:attempt_id>/feedback/', views.QuizFeedbackView.as_view(), name='quiz-feedback'),

    # Subscription
    path('subscription/plans/', views.SubscriptionPlansView.as_view(), name='subscription-plans'),
    path('subscription/request/', views.SubscriptionRequestView.as_view(), name='subscription-request'),
]
