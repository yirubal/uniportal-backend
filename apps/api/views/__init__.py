"""Public view imports retained for existing URLs and callers."""

from .auth import (
    TelegramAuthView,
    TelegramWebhookView,
    _generate_jwt,
)

from .students import (
    StudentProfileView,
    StudentWatermarkView,
    PerformanceView,
)

from .catalog import (
    DepartmentListView,
    CourseListView,
)

from .resources import (
    ResourceListView,
    ResourceDetailView,
    ResourceDownloadView,
    ResourceDownloadFileView,
    RESOURCE_DOWNLOAD_TOKEN_MAX_AGE,
    RESOURCE_DOWNLOAD_TOKEN_SALT,
)

from .quiz import (
    ExamPaperListView,
    ExamPaperQuestionsView,
    CourseTopicsView,
    CourseChaptersView,
    SelectivePracticeView,
    ExitExamTopicsView,
    TopicQuestionsView,
    QuizAttemptView,
    QuizFeedbackView,
)

from .exams import (
    ActiveExamTermView,
    ExamLookupView,
)

from .subscriptions import (
    SubscriptionPlansView,
    SubscriptionRequestView,
)
