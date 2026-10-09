from django.core.management.base import BaseCommand
from apps.bot.worker import process_claimed_work


class Command(BaseCommand):
    help = 'Internal worker subprocess; requires a claimed record and its token.'

    def add_arguments(self, parser):
        parser.add_argument('kind', choices=['update', 'notification', 'inbox', 'exam', 'ai'])
        parser.add_argument('record_id', type=int)
        parser.add_argument('claim_token')

    def handle(self, *args, **options):
        process_claimed_work(options['kind'], options['record_id'], options['claim_token'])
