import json

from django.core.management.base import BaseCommand

from core.marketplace.sync import sync_shat_marketplaces


class Command(BaseCommand):
    help = "Отправляет актуальные SHAT товары в M-Market, O!Market и Bakai Market."

    def add_arguments(self, parser):
        parser.add_argument("--channel-id", action="append", type=int, default=[], help="ID канала, можно несколько раз.")
        parser.add_argument("--dry-run", action="store_true", help="Собрать payload без отправки в маркетплейсы.")

    def handle(self, *args, **options):
        result = sync_shat_marketplaces(
            channel_ids=options["channel_id"] or None,
            dry_run=options["dry_run"],
        )
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if result["errors"]:
            self.stderr.write(self.style.ERROR(f"Ошибки синка: {len(result['errors'])}"))
        else:
            self.stdout.write(self.style.SUCCESS("SHAT marketplace sync завершен."))
