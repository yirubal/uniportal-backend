from uuid import UUID, uuid4

from django import forms
from django.core import signing

from .models import BroadcastMessage


class BroadcastForm(forms.Form):
    message = forms.CharField(max_length=4096)
    parse_mode = forms.ChoiceField(choices=BroadcastMessage.PARSE_CHOICES, required=False)
    submission_token = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial['submission_token'] = signing.dumps(
                {'user': user.pk, 'nonce': str(uuid4())}, salt='admin-broadcast',
            )

    def clean_submission_token(self):
        try:
            token = signing.loads(self.cleaned_data['submission_token'], salt='admin-broadcast', max_age=86400)
            if token['user'] != self.user.pk:
                raise signing.BadSignature
            return UUID(token['nonce'])
        except (signing.BadSignature, ValueError, KeyError, TypeError):
            raise forms.ValidationError('This send confirmation is invalid or expired. Reload the page before sending.') from None
