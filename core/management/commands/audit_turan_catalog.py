import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.turan_catalog import audit_catalog, fill_web_prices


class Command(BaseCommand):
    help = "Проверяет WEBSITE TURAN и оптовые цены без изменения БД и отправки в маркеты."

    def add_arguments(self, parser):
        parser.add_argument("--stock", required=True)
        parser.add_argument("--prices", required=True)
        parser.add_argument("--sheet", default="Остатки на 04.09.2026")
        parser.add_argument("--output", required=True)
        parser.add_argument("--with-web-prices", action="store_true")

    def handle(self, *args, **options):
        try:
            result = audit_catalog(options["stock"], options["prices"], options["sheet"])
            if options["with_web_prices"]:
                result = fill_web_prices(result)
        except (OSError, ValueError, KeyError) as exc:
            raise CommandError(str(exc)) from exc
        Path(options["output"]).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.stdout.write(json.dumps(result["summary"], ensure_ascii=False))
